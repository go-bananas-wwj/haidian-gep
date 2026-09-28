"""Versioned official-source research for the Haidian 2024 demo."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class OfficialSourceRegistry:
    def __init__(self, path: Path | None = None, *, timeout_seconds: int = 12):
        self.path = path or Path(__file__).with_name("official_sources.json")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.allowed_domains = frozenset(payload["allowed_domains"])
        self.sources = tuple(payload["sources"])
        self.timeout_seconds = timeout_seconds
        self._verification_cache: dict[str, dict[str, Any]] = {}

    def _official_url(self, url: str) -> str:
        parsed = urlparse(str(url))
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_domains:
            raise ValueError("official source URL must use an allowlisted Beijing government domain")
        return url

    def search(self, work_order: dict[str, Any]) -> list[dict[str, Any]]:
        node_key = str(work_order.get("node_key") or "")
        region_code = str(work_order.get("region_code") or "")
        try:
            year = int(work_order.get("year"))
        except (TypeError, ValueError):
            return []
        matches = []
        for source in self.sources:
            if str(source.get("region_code")) != region_code or int(source.get("year")) != year:
                continue
            self._official_url(source["url"])
            for fact in source.get("facts", []):
                if fact.get("node_key") != node_key:
                    continue
                matches.append({
                    **copy.deepcopy(fact),
                    "source_id": source["source_id"],
                    "source_type": "official_government",
                    "source_file": source["url"],
                    "url": source["url"],
                    "title": source["title"],
                    "publisher": source["publisher"],
                    "region_code": source["region_code"],
                    "year": source["year"],
                    "license_or_access": source["license_or_access"],
                    "tool_run_id": f"official-registry:{source['source_id']}",
                    "extracted_fragment": f"{fact['metric']}：{fact['value']} {fact['unit']}",
                })
        return matches

    def verify(self, record: dict[str, Any]) -> dict[str, Any]:
        url = self._official_url(str(record.get("url") or ""))
        if url in self._verification_cache:
            return {**record, **self._verification_cache[url]}
        request = Request(url, headers={"User-Agent": "Haidian-GEP-Evidence-Checker/1.0"}, method="HEAD")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                final_url = self._official_url(response.geturl())
                metadata = {
                    "online_status": "verified",
                    "checked_utc": datetime.now(timezone.utc).isoformat(),
                    "final_url": final_url,
                    "http_status": int(getattr(response, "status", 200)),
                    "content_type": str(response.headers.get("Content-Type", "")).split(";", 1)[0],
                    "etag": str(response.headers.get("ETag", "")),
                    "last_modified": str(response.headers.get("Last-Modified", "")),
                }
        except HTTPError as error:
            raise RuntimeError(f"official source HTTP {error.code}; verification failed") from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError("official source is unavailable; verification failed") from error
        self._verification_cache[url] = metadata
        return {**record, **metadata}
