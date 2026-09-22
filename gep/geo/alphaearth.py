"""AlphaEarth asset selection and safe local VRT preparation."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


NODATA_INT8 = -128


def _sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text.lower())


def validate_boundary(boundary: Mapping[str, Any]) -> dict[str, Any]:
    """Return a checked formal boundary descriptor; candidates are rejected."""
    if boundary.get("status") != "approved":
        raise ValueError("formal AlphaEarth processing requires an approved boundary")
    if not _sha256(boundary.get("sha256", "")):
        raise ValueError("approved boundary needs a SHA-256 hash")
    if not str(boundary.get("crs", "")).strip():
        raise ValueError("approved boundary needs a CRS")
    bbox = boundary.get("bbox")
    if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
        raise ValueError("approved boundary needs a four-value bbox")
    west, south, east, north = bbox
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in bbox) or west >= east or south >= north:
        raise ValueError("boundary bbox must have finite west/south/east/north coordinates")
    return {**dict(boundary), "bbox": [float(value) for value in bbox]}


def _intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def select_2024_assets(index_records: Iterable[Mapping[str, Any]], boundary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Select every 2024 index asset intersecting the approved WGS84 bbox."""
    checked = validate_boundary(boundary)
    bbox = tuple(checked["bbox"])
    selected: list[dict[str, Any]] = []
    for raw in index_records:
        if raw.get("year") != 2024:
            continue
        try:
            asset_bbox = tuple(float(raw[key]) for key in ("wgs84_west", "wgs84_south", "wgs84_east", "wgs84_north"))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("AlphaEarth index asset lacks a valid WGS84 bbox") from error
        if _intersects(asset_bbox, bbox):
            selected.append(dict(raw))
    if not selected:
        raise ValueError("no 2024 AlphaEarth assets intersect the approved boundary")
    return sorted(selected, key=lambda asset: str(asset.get("asset_id", asset.get("path", ""))))


def dequantize_int8(values: Iterable[int], already_dequantized: bool = False) -> list[float | None]:
    """Mask signed-Int8 NoData and apply the documented AlphaEarth transform once."""
    if already_dequantized:
        raise ValueError("AlphaEarth features are already dequantized; refusing a second conversion")
    result: list[float | None] = []
    for raw in values:
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < -128 or raw > 127:
            raise ValueError("AlphaEarth quantized input must contain signed Int8 values")
        if raw == NODATA_INT8:
            result.append(None)
            continue
        quotient = float(raw) / 127.5
        result.append(math.copysign(quotient * quotient, raw))
    return result


def rewrite_vrt_source(source_vrt: str | Path, destination_vrt: str | Path, local_cog: str | Path) -> Path:
    """Replace the sole VRT source with a local COG, rejecting multi-source ambiguity."""
    source = Path(source_vrt)
    destination = Path(destination_vrt)
    local = Path(local_cog).resolve()
    tree = ET.parse(source)
    nodes = tree.findall(".//SourceDataset")
    if len(nodes) != 1:
        raise ValueError("expected exactly one SourceDataset in the VRT")
    nodes[0].text = str(local)
    nodes[0].set("relativeToVRT", "0")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination, encoding="UTF-8", xml_declaration=True)
    return destination
