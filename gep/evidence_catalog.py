"""Read narrowly scoped evidence from one admitted release package."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


NODE_METRICS = {
    "P1.maize.quantity": "玉米产量",
    "P4.harvest_quantity": "水产品产量",
}


class EvidenceCatalog:
    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)

    @staticmethod
    def _release_name(data_version: Any) -> str:
        version = str(data_version or "").strip()
        if not version or Path(version).name != version or version in {".", ".."}:
            raise ValueError("data_version must be one release directory name")
        return version

    @staticmethod
    def _json_list(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise ValueError(f"{path.name} must contain a JSON record list")
        return payload

    @staticmethod
    def _locator(record: dict[str, Any]) -> str:
        pieces = []
        if record.get("table_id"):
            pieces.append(f"表 {record['table_id']}")
        if record.get("printed_page"):
            pieces.append(f"印刷页 {record['printed_page']}")
        return "，".join(pieces) or str(record.get("locator") or "准入记录")

    @classmethod
    def _normalize_record(cls, record: dict[str, Any]) -> dict[str, Any]:
        source_hash = str(record.get("source_sha256") or record.get("sha256") or "").lower()
        metric = str(record.get("metric") or "")
        value = record.get("value")
        unit = str(record.get("unit") or "")
        fragment = f"{metric}：{'' if value is None else value} {unit}".strip()
        if record.get("note"):
            fragment = f"{fragment}；{record['note']}"
        return {
            "source_id": str(record.get("source_id") or ""),
            "source_type": str(record.get("source_type") or record.get("raw_status") or "admitted_record"),
            "source_file": str(record.get("source_file") or ""),
            "locator": cls._locator(record),
            "source_sha256": source_hash,
            "license_or_access": str(record.get("license_or_access") or "admitted-reference-review"),
            "tool_run_id": f"catalog:{hashlib.sha256(fragment.encode()).hexdigest()[:16]}",
            "extracted_fragment": fragment,
            "metric": metric,
            "value": value,
            "unit": unit,
            "raw_status": str(record.get("raw_status") or record.get("source_type") or record.get("status") or ""),
        }

    def for_work_order(self, work_order: dict[str, Any]) -> list[dict[str, Any]]:
        version = self._release_name(work_order.get("data_version"))
        release_root = (self.data_root / "05_release" / version).resolve()
        releases_root = (self.data_root / "05_release").resolve()
        if not release_root.is_relative_to(releases_root):
            raise ValueError("data_version escapes the admitted release root")
        if not release_root.is_dir():
            return []

        node_kind = work_order.get("node_kind")
        if node_kind == "indicator":
            path = release_root / "missing_inputs.csv"
            if not path.is_file():
                return []
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    if row.get("indicator_id") == work_order.get("indicator_id"):
                        return [{
                            "source_id": f"gap-register:{row['indicator_id']}",
                            "source_type": "gap_register",
                            "source_file": f"05_release/{version}/missing_inputs.csv",
                            "locator": f"missing_inputs.csv，指标 {row['indicator_id']}",
                            "source_sha256": file_hash,
                            "license_or_access": "admitted-reference-review",
                            "tool_run_id": f"catalog:{file_hash[:16]}",
                            "extracted_fragment": str(row.get("missing_inputs") or ""),
                            "metric": str(row.get("indicator_name") or ""),
                            "value": None,
                            "unit": "",
                            "raw_status": str(row.get("status") or ""),
                        }]
            return []

        metric = NODE_METRICS.get(str(work_order.get("node_key") or ""))
        if not metric:
            return []
        region_code = str(work_order.get("region_code") or "")
        year = str(work_order.get("year") or "")
        matches = []
        for filename in ("observations.json", "pending.json"):
            for record in self._json_list(release_root / filename):
                if (str(record.get("region_code") or "") == region_code
                        and str(record.get("year") or "") == year
                        and str(record.get("metric") or "") == metric):
                    matches.append(self._normalize_record(record))
        return matches
