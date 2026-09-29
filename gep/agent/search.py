"""Pluggable web-search discovery providers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol, Sequence
from urllib.parse import parse_qs, urlencode, urlsplit

from .http import SafeHttpClient


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    provider: str
    rank: int
    discovery_only: bool = True


class SearchProvider(Protocol):
    def search(
        self,
        query: str,
        *,
        domains: Sequence[str] | None = None,
        limit: int = 5,
        language: str = "zh-CN",
    ) -> list[SearchHit]: ...


class _DuckDuckGoParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[tuple[str, str, str]] = []
        self._href = ""
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._capture_title = False
        self._capture_snippet = False

    @staticmethod
    def _class(attributes) -> set[str]:
        return set(dict(attributes).get("class", "").split())

    def handle_starttag(self, tag, attributes):
        classes = self._class(attributes)
        attrs = dict(attributes)
        if tag == "a" and "result__a" in classes:
            if self._href and self._title:
                self.results.append((self._href, " ".join(self._title).strip(), " ".join(self._snippet).strip()))
            self._href = attrs.get("href", "")
            self._title = []
            self._snippet = []
            self._capture_title = True
        elif "result__snippet" in classes and self._href:
            self._capture_snippet = True

    def handle_endtag(self, tag):
        if tag == "a":
            self._capture_title = False
            self._capture_snippet = False

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self._capture_title:
            self._title.append(value)
        elif self._capture_snippet:
            self._snippet.append(value)

    def close(self):
        super().close()
        if self._href and self._title:
            self.results.append((self._href, " ".join(self._title).strip(), " ".join(self._snippet).strip()))
            self._href = ""


def _source_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlsplit(href)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        redirected = parse_qs(parsed.query).get("uddg")
        if redirected:
            return redirected[0]
    return href


def _validate_search(query: str, limit: int) -> None:
    if not query.strip():
        raise ValueError("search query is required")
    if limit <= 0 or limit > 20:
        raise ValueError("search limit must be between 1 and 20")


class DuckDuckGoHtmlSearchProvider:
    def __init__(self, client: SafeHttpClient):
        self.client = client

    def search(self, query: str, *, domains=None, limit: int = 5, language: str = "zh-CN") -> list[SearchHit]:
        _validate_search(query, limit)
        scoped = query.strip()
        for domain in domains or ():
            scoped += f" site:{domain}"
        url = "https://html.duckduckgo.com/html/?" + urlencode({"q": scoped, "kl": language})
        document = self.client.fetch(url, accepted_types=("text/html",), max_bytes=2 * 1024 * 1024)
        parser = _DuckDuckGoParser()
        parser.feed(document.body.decode("utf-8", errors="replace"))
        parser.close()
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for href, title, snippet in parser.results:
            source = _source_url(href)
            if not source.startswith(("http://", "https://")) or source in seen:
                continue
            seen.add(source)
            hits.append(SearchHit(title=title, url=source, snippet=snippet, provider="duckduckgo", rank=len(hits) + 1))
            if len(hits) >= limit:
                break
        return hits


class SearxngSearchProvider:
    def __init__(self, client: SafeHttpClient, base_url: str):
        self.client = client
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("SearXNG base URL must use HTTP(S)")

    def search(self, query: str, *, domains=None, limit: int = 5, language: str = "zh-CN") -> list[SearchHit]:
        _validate_search(query, limit)
        scoped = query.strip()
        for domain in domains or ():
            scoped += f" site:{domain}"
        url = self.base_url + "/search?" + urlencode({"q": scoped, "format": "json", "language": language})
        document = self.client.fetch(url, accepted_types=("application/json",), max_bytes=2 * 1024 * 1024)
        try:
            payload = json.loads(document.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("SearXNG returned invalid JSON") from error
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for item in payload.get("results", []):
            source = str(item.get("url", ""))
            if not source.startswith(("http://", "https://")) or source in seen:
                continue
            seen.add(source)
            engine = str(item.get("engine") or "unknown")
            hits.append(SearchHit(
                title=str(item.get("title") or source),
                url=source,
                snippet=str(item.get("content") or ""),
                provider=f"searxng:{engine}",
                rank=len(hits) + 1,
            ))
            if len(hits) >= limit:
                break
        return hits
