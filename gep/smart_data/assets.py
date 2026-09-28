"""Receipt-driven discovery of known Haidian smart-data assets."""
from __future__ import annotations

import calendar
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .types import AssetRecord


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _candidate_root(receipt: Path, recorded: str, data_root: Path) -> Path:
    relative = Path(recorded)
    if relative.is_absolute():
        return relative
    parts = relative.parts[1:] if relative.parts and relative.parts[0] == "data" else relative.parts
    normalized = Path(*parts)
    candidates = [data_root / normalized]
    for parent in receipt.parents:
        if parent == data_root.parent:
            break
        candidates.append(parent / normalized)
    return next((candidate for candidate in candidates if candidate.exists() or candidate.is_symlink()), candidates[0])


def _safe_path(receipt: Path, recorded: str, data_root: Path) -> tuple[Path, str]:
    candidate = _candidate_root(receipt, recorded, data_root)
    root = data_root.resolve()
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError(f"asset path escapes the approved data root: {recorded}")
    return candidate, candidate.relative_to(data_root).as_posix()


def _period_from_months(months: Iterable[str]) -> tuple[str, str]:
    ordered = sorted(str(month) for month in months if re.fullmatch(r"\d{6}", str(month)))
    if not ordered:
        raise ValueError("receipt has no valid YYYYMM period")
    first, last = ordered[0], ordered[-1]
    end_day = calendar.monthrange(int(last[:4]), int(last[4:]))[1]
    return f"{first[:4]}-{first[4:]}-01", f"{last[:4]}-{last[4:]}-{end_day:02d}"


def _status(path: Path, available: str = "available") -> str:
    return available if path.is_file() else "missing"


def _climate_assets(root: Path, version: str) -> list[AssetRecord]:
    receipt = root / "catalog" / "climate_receipt.json"
    data = _read_json(receipt)
    if not isinstance(data, dict):
        return []
    recorded = str(data.get("derived_path") or data.get("local_path") or "")
    path, local = _safe_path(receipt, recorded, root)
    start, end = _period_from_months(data.get("valid_months", []))
    return [AssetRecord.from_dict({
        "asset_id": "nasa-power-monthly-point", "asset_version": version, "asset_type": "climate",
        "title": "NASA POWER monthly point", "publisher": "NASA POWER",
        "source_url": data.get("source"), "license_or_access": "NASA open data terms",
        "period_start": start, "period_end": end, "region_code": "110108", "bbox": None,
        "crs": "EPSG:4326", "local_path": local, "sha256": data.get("sha256"),
        "quality_status": _status(path, "proxy"),
        "quality": {"limitation": data.get("limitation", ""), "data_version": version},
    })]


def _modis_asset_id(path: str) -> str:
    name = Path(path).stem.lower()
    year = re.search(r"20\d{2}", name)
    year_text = year.group(0) if year else "unknown"
    if name.startswith("npp"):
        suffix = "-qc" if "qc" in name else ""
        return f"modis-npp{suffix}-{year_text}"
    if name.startswith("et"):
        if "valid_period" in name: return f"modis-et-valid-periods-{year_text}"
        if "qa" in name: return f"modis-et-qa-{year_text}"
        return f"modis-et-{year_text}"
    return f"modis-{_slug(name)}"


def _modis_assets(root: Path, version: str) -> list[AssetRecord]:
    receipt = root / "catalog" / "modis_2024_reference_receipt.json"
    records = _read_json(receipt)
    if not isinstance(records, list):
        return []
    result = []
    for record in records:
        if not isinstance(record, dict) or not record.get("local_path"):
            continue
        path, local = _safe_path(receipt, str(record["local_path"]), root)
        match = re.search(r"20\d{2}", local)
        year = int(match.group(0)) if match else 2024
        result.append(AssetRecord.from_dict({
            "asset_id": _modis_asset_id(local), "asset_version": version,
            "asset_type": "npp" if "npp" in local.lower() else "et",
            "title": Path(local).name, "publisher": "NASA MODIS",
            "source_url": "https://modis.ornl.gov/", "license_or_access": "NASA open data terms",
            "period_start": f"{year}-01-01", "period_end": f"{year}-12-31", "region_code": "110108",
            "bbox": None, "crs": None, "local_path": local, "sha256": record.get("sha256"),
            "quality_status": _status(path),
            "quality": {"units": record.get("units"), "description": record.get("description", ""), "data_version": version},
        }))
    return result


def _date_only(value: Any, fallback: str) -> str:
    text = str(value or fallback)
    return text[:10]


def _public_raster_assets(root: Path, version: str) -> list[AssetRecord]:
    receipt = root / "catalog" / "public_raster_receipt.json"
    document = _read_json(receipt)
    records = document.get("files", []) if isinstance(document, dict) else []
    result = []
    for record in records:
        if not isinstance(record, dict) or not record.get("local_path"):
            continue
        path, local = _safe_path(receipt, str(record["local_path"]), root)
        properties = record.get("properties") if isinstance(record.get("properties"), dict) else {}
        timestamp = properties.get("datetime")
        start = _date_only(properties.get("start_datetime") or timestamp, "2021-01-01")
        end = _date_only(properties.get("end_datetime") or timestamp, start)
        collection = str(record.get("collection") or "public-raster")
        publisher = "ESA" if collection == "esa-worldcover" else "Copernicus"
        result.append(AssetRecord.from_dict({
            "asset_id": f"{_slug(collection)}-{_slug(str(record.get('item_id') or Path(local).stem))}",
            "asset_version": version, "asset_type": "land_cover" if collection == "esa-worldcover" else "terrain",
            "title": str(record.get("item_id") or Path(local).name), "publisher": publisher,
            "source_url": record.get("source_href"), "license_or_access": "public source terms retained in receipt",
            "period_start": start, "period_end": end, "region_code": "110108",
            "bbox": record.get("bbox_wgs84"), "crs": record.get("crs"), "local_path": local,
            "sha256": record.get("sha256"), "quality_status": _status(path),
            "quality": {"collection": collection, "crop_scope": record.get("crop_scope", ""), "data_version": version},
        }))
    return result


def _aef_index_assets(root: Path, version: str) -> list[AssetRecord]:
    result = []
    for receipt in sorted(root.glob("**/aef_index.parquet.receipt.json")):
        data = _read_json(receipt)
        if not isinstance(data, dict) or not data.get("path"):
            continue
        path, local = _safe_path(receipt, str(data["path"]), root)
        result.append(AssetRecord.from_dict({
            "asset_id": "alphaearth-annual-index", "asset_version": version, "asset_type": "aef_index",
            "title": "AlphaEarth annual embedding index", "publisher": "Google and Google DeepMind",
            "source_url": data.get("url"), "license_or_access": "CC-BY 4.0",
            "period_start": "2017-01-01", "period_end": "2025-12-31", "region_code": "110108",
            "bbox": None, "crs": "EPSG:4326", "local_path": local, "sha256": data.get("sha256"),
            "quality_status": _status(path), "quality": {"data_version": version, "contains_2024": True},
        }))
    return result


def _xuannv_assets(root: Path, version: str) -> list[AssetRecord]:
    manifest = root / "catalog" / "xuannv_window_202512_202605.json"
    data = _read_json(manifest)
    if not isinstance(data, dict):
        return []
    window = data.get("window", {})
    start = str(window.get("start") or "2025-12-01")
    end_exclusive = str(window.get("end_exclusive") or "2026-06-01")
    end = "2026-05-31" if end_exclusive == "2026-06-01" else end_exclusive
    return [AssetRecord.from_dict({
        "asset_id": "xuannv-embedding-window-202512-202605", "asset_version": version,
        "asset_type": "comparison_embedding", "title": "Xuannv Haidian embedding window",
        "publisher": "ModelScope release", "source_url": "https://modelscope.cn/",
        "license_or_access": "publisher terms require review", "period_start": start,
        "period_end": end, "region_code": "110108", "bbox": None, "crs": None,
        "local_path": manifest.relative_to(root).as_posix(), "sha256": _hash(manifest),
        "quality_status": "available" if data.get("embedding_manifest_sha256_verified") is True else "review_required",
        "quality": {"data_version": version, "not_2024_input": True,
                    "embedding_manifest_sha256_verified": bool(data.get("embedding_manifest_sha256_verified"))},
    })]


def _official_fact_assets(root: Path, version: str) -> list[AssetRecord]:
    matches = sorted(root.glob("**/05_release/reference-2024-v0.1/observations.json"))
    if not matches:
        return []
    path = matches[0]
    return [AssetRecord.from_dict({
        "asset_id": "haidian-yearbook-2024-observations", "asset_version": version,
        "asset_type": "official_facts", "title": "Haidian yearbook 2024 selected observations",
        "publisher": "Haidian District Bureau of Statistics", "source_url": None,
        "license_or_access": "local original only", "period_start": "2024-01-01", "period_end": "2024-12-31",
        "region_code": "110108", "bbox": None, "crs": None,
        "local_path": path.relative_to(root).as_posix(), "sha256": _hash(path), "quality_status": "available",
        "quality": {"data_version": version, "source": "sealed reference release"},
    })]


def scan_known_assets(data_root: Path, data_version: str = "smart-data-2024-v1") -> list[AssetRecord]:
    """Discover only versioned, known receipt formats under an approved root."""
    root = Path(data_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("approved data root must be a real directory")
    assets = [
        *_climate_assets(root, data_version), *_modis_assets(root, data_version),
        *_public_raster_assets(root, data_version), *_aef_index_assets(root, data_version),
        *_xuannv_assets(root, data_version), *_official_fact_assets(root, data_version),
    ]
    by_id: dict[str, AssetRecord] = {}
    for asset in assets:
        if asset.asset_id in by_id and by_id[asset.asset_id] != asset:
            raise ValueError(f"duplicate smart-data asset id: {asset.asset_id}")
        by_id[asset.asset_id] = asset
    return [by_id[key] for key in sorted(by_id)]
