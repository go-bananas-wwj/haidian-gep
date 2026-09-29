"""SSRF-resistant HTTP client used by all native-agent network tools."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit


class SafeHttpError(ValueError):
    """A URL or response violated the agent's network safety policy."""


@dataclass(frozen=True)
class HttpDocument:
    original_url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    content_type: str
    body: bytes
    sha256: str
    fetched_utc: str


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, address: str, port: int, timeout: float):
        super().__init__(host, port=port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout, self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, port: int, timeout: float):
        super().__init__(host, port=port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _TransportResponse:
    def __init__(self, response: http.client.HTTPResponse, connection: http.client.HTTPConnection):
        self._response = response
        self._connection = connection
        self.status = response.status
        self.headers = dict(response.getheaders())

    def read(self, size: int = -1) -> bytes:
        return self._response.read(size)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()


class _PinnedTransport:
    """Transport that connects to an already validated IP while preserving Host/SNI."""

    def __call__(
        self,
        url: str,
        *,
        timeout: float,
        headers: Mapping[str, str],
        addresses: Iterable[str],
    ):
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        last_error: Exception | None = None
        for address in addresses:
            connection_class = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
            connection = connection_class(host, address, port, timeout)
            try:
                connection.request("GET", path, headers=dict(headers))
                return _TransportResponse(connection.getresponse(), connection)
            except (OSError, TimeoutError, http.client.HTTPException) as error:
                last_error = error
                connection.close()
        raise SafeHttpError("HTTP request failed") from last_error


def _resolve(host: str, port: int) -> list[str]:
    return sorted({item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def _header(headers: Any, name: str) -> str | None:
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is not None:
            return str(value)
    target = name.lower()
    for key, value in dict(headers).items():
        if str(key).lower() == target:
            return str(value)
    return None


class SafeHttpClient:
    def __init__(
        self,
        *,
        resolver: Callable[[str, int], Iterable[str]] = _resolve,
        transport: Callable[..., Any] | None = None,
        timeout_seconds: float = 10.0,
        max_redirects: int = 3,
        user_agent: str = "HaidianGEP-Agent/1.0",
    ):
        if timeout_seconds <= 0 or max_redirects < 0:
            raise ValueError("timeout must be positive and max_redirects non-negative")
        self.resolver = resolver
        self.transport = transport or _PinnedTransport()
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.user_agent = user_agent

    def _validate_target(self, url: str) -> tuple[str, ...]:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise SafeHttpError("only HTTP(S) URLs are allowed")
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise SafeHttpError("URL host is invalid")
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith(".localhost"):
            raise SafeHttpError("local addresses are not allowed")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            try:
                addresses = list(self.resolver(host, port))
            except (OSError, socket.gaierror) as error:
                raise SafeHttpError("URL host could not be resolved") from error
        if not addresses:
            raise SafeHttpError("URL host has no address")
        for address in addresses:
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError as error:
                raise SafeHttpError("resolver returned an invalid address") from error
            if not parsed_address.is_global:
                raise SafeHttpError("private, local, reserved, and metadata addresses are not allowed")
        return tuple(addresses)

    def fetch(
        self,
        url: str,
        *,
        accepted_types: tuple[str, ...] = ("text/html", "text/plain", "application/json", "application/pdf"),
        max_bytes: int = 5 * 1024 * 1024,
    ) -> HttpDocument:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        original_url = url
        current_url = url
        redirects = 0
        while True:
            addresses = self._validate_target(current_url)
            response = self.transport(
                current_url,
                timeout=self.timeout_seconds,
                headers={"User-Agent": self.user_agent, "Accept": ", ".join(accepted_types)},
                addresses=addresses,
            )
            try:
                status = int(getattr(response, "status", getattr(response, "code", 200)))
                if 300 <= status < 400:
                    location = _header(response.headers, "Location")
                    if not location:
                        raise SafeHttpError("redirect response has no location")
                    if redirects >= self.max_redirects:
                        raise SafeHttpError("too many redirects")
                    current_url = urljoin(current_url, location)
                    redirects += 1
                    continue
                if status < 200 or status >= 300:
                    raise SafeHttpError(f"HTTP request failed with status {status}")
                raw_content_type = _header(response.headers, "Content-Type") or ""
                content_type = raw_content_type.split(";", 1)[0].strip().lower()
                if accepted_types and content_type not in {value.lower() for value in accepted_types}:
                    raise SafeHttpError(f"unaccepted content type: {content_type or 'missing'}")
                content_length = _header(response.headers, "Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise SafeHttpError("response is too large")
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(min(65536, max_bytes + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > max_bytes:
                        raise SafeHttpError("response is too large")
                body = b"".join(chunks)
                headers = {str(key): str(value) for key, value in dict(response.headers).items()}
                return HttpDocument(
                    original_url=original_url,
                    final_url=current_url,
                    status=status,
                    headers=headers,
                    content_type=content_type,
                    body=body,
                    sha256=hashlib.sha256(body).hexdigest(),
                    fetched_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                )
            finally:
                response.close()
