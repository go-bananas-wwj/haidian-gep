"""Coverage QA for selected AlphaEarth assets before feature admission."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CoverageReport:
    ready: bool
    boundary_area: float
    valid_area: float
    hole_area: float
    overlap_area: float
    issues: tuple[str, ...]


def _rect(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ValueError("bbox must contain west, south, east, north")
    west, south, east, north = (float(item) for item in value)
    if not all(math.isfinite(item) for item in (west, south, east, north)) or west >= east or south >= north:
        raise ValueError("bbox must have finite increasing coordinates")
    return west, south, east, north


def _clip(rectangle: tuple[float, float, float, float], boundary: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
    west, south = max(rectangle[0], boundary[0]), max(rectangle[1], boundary[1])
    east, north = min(rectangle[2], boundary[2]), min(rectangle[3], boundary[3])
    return (west, south, east, north) if west < east and south < north else None


def _union_area(rectangles: list[tuple[float, float, float, float]]) -> float:
    if not rectangles:
        return 0.0
    xs = sorted({coordinate for rectangle in rectangles for coordinate in (rectangle[0], rectangle[2])})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((rectangle[1], rectangle[3]) for rectangle in rectangles if rectangle[0] <= left and rectangle[2] >= right)
        covered = 0.0
        cursor_start = cursor_end = None
        for start, end in spans:
            if cursor_start is None:
                cursor_start, cursor_end = start, end
            elif start > cursor_end:
                covered += cursor_end - cursor_start
                cursor_start, cursor_end = start, end
            else:
                cursor_end = max(cursor_end, end)
        if cursor_start is not None:
            covered += cursor_end - cursor_start
        total += (right - left) * covered
    return total


def _sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text.lower())


def coverage_report(boundary_bbox: list[float] | tuple[float, float, float, float], assets: Iterable[Mapping[str, Any]]) -> CoverageReport:
    """Calculate union, hole and overlap area in the supplied native planar CRS."""
    boundary = _rect(boundary_bbox)
    boundary_area = (boundary[2] - boundary[0]) * (boundary[3] - boundary[1])
    valid_rectangles: list[tuple[float, float, float, float]] = []
    issues: list[str] = []
    crs_values: set[str] = set()
    for asset in assets:
        asset_id = str(asset.get("asset_id", "unknown"))
        if asset.get("band_count") != 64:
            issues.append(f"{asset_id}:band_count")
            continue
        if not asset.get("valid"):
            issues.append(f"{asset_id}:invalid_pixels")
            continue
        if not _sha256(asset.get("sha256", "")):
            issues.append(f"{asset_id}:sha256")
            continue
        if not str(asset.get("crs", "")).strip() or not str(asset.get("affine", "")).strip():
            issues.append(f"{asset_id}:georeferencing")
            continue
        try:
            clipped = _clip(_rect(asset.get("bbox")), boundary)
        except (TypeError, ValueError):
            issues.append(f"{asset_id}:bbox")
            continue
        if clipped is not None:
            valid_rectangles.append(clipped)
            crs_values.add(str(asset["crs"]))
    if len(crs_values) > 1:
        issues.append("mixed_crs")
    valid_area = _union_area(valid_rectangles)
    raw_area = sum((rectangle[2] - rectangle[0]) * (rectangle[3] - rectangle[1]) for rectangle in valid_rectangles)
    hole_area = max(0.0, boundary_area - valid_area)
    overlap_area = max(0.0, raw_area - valid_area)
    if hole_area / boundary_area > 0.005:
        issues.append("coverage_hole_exceeds_0.5_percent")
    return CoverageReport(not issues, boundary_area, valid_area, hole_area, overlap_area, tuple(sorted(issues)))
