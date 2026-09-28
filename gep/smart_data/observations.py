"""Builders that turn admitted climate and raster assets into small observations."""
from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from typing import Iterable

from .types import ObservationRecord


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_2024(year: int) -> None:
    if year != 2024:
        raise ValueError("unsupported_year: smart-data v1 only derives 2024 observations")


def _require_file(path: Path) -> Path:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing_source_asset: {path}")
    return path


def _observation(
    *, observation_id: str, metric: str, value: float, unit: str, region_code: str, year: int,
    spatial_grain: str, method_id: str, asset_ids: Iterable[str], confidence: float,
    uncertainty: dict, evidence_class: str, artifact: Path | None = None,
) -> ObservationRecord:
    return ObservationRecord.from_dict({
        "observation_id": observation_id, "metric": metric, "value": value, "unit": unit,
        "region_code": region_code, "year": year, "spatial_grain": spatial_grain,
        "method_id": method_id, "method_version": "v1", "input_asset_ids": list(asset_ids),
        "confidence": confidence, "uncertainty": uncertainty, "evidence_class": evidence_class,
        "artifact_path": str(artifact) if artifact else None,
        "artifact_sha256": _sha256(artifact) if artifact else None,
    })


def build_nasa_power_observations(
    csv_path: Path, *, asset_id: str, year: int = 2024, region_code: str = "110108",
) -> list[ObservationRecord]:
    _require_2024(year); path = _require_file(csv_path)
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if str(row.get("month", "")).startswith("2024")]
    expected = {f"2024{month:02d}" for month in range(1, 13)}
    if {row.get("month") for row in rows if row.get("valid") == "True"} != expected:
        raise ValueError("incomplete_2024_months")
    try:
        precipitation = [float(row["precipitation_mm_month"]) for row in rows]
        temperatures = [float(row["temperature_C"]) for row in rows]
        shortwave = [float(row["shortwave_MJ_m2_month"]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid_climate_value") from error
    if not all(math.isfinite(value) for value in (*precipitation, *temperatures, *shortwave)):
        raise ValueError("invalid_climate_value")
    common = dict(
        region_code=region_code, year=year, spatial_grain="single_point_district_proxy",
        asset_ids=(asset_id,), confidence=0.65,
        uncertainty={"limitation": "single coarse grid point; not district spatial forcing", "month_count": 12},
        evidence_class="model_estimate", artifact=path,
    )
    return [
        _observation(observation_id="nasa-power-2024-precipitation", metric="precipitation",
                     value=sum(precipitation), unit="mm/a", method_id="nasa_power.monthly_sum", **common),
        _observation(observation_id="nasa-power-2024-temperature", metric="temperature",
                     value=sum(temperatures) / 12, unit="degC", method_id="nasa_power.monthly_mean", **common),
        _observation(observation_id="nasa-power-2024-shortwave", metric="shortwave_radiation",
                     value=sum(shortwave), unit="MJ/m2/a", method_id="nasa_power.monthly_sum", **common),
    ]


def build_modis_observations(
    npp_path: Path, npp_qc_path: Path, et_path: Path, et_period_count_path: Path,
    *, asset_ids: dict[str, str], year: int = 2024, region_code: str = "110108",
) -> list[ObservationRecord]:
    _require_2024(year)
    npp = _require_file(npp_path)
    if not Path(npp_qc_path).is_file():
        raise ValueError("missing_npp_qc")
    npp_qc = _require_file(npp_qc_path); et = _require_file(et_path); periods = _require_file(et_period_count_path)
    required = {"npp", "npp_qc", "et", "et_periods"}
    if not required <= set(asset_ids) or any(not asset_ids[key] for key in required):
        raise ValueError("missing_source_asset_id")
    try:
        import numpy as np
        import rasterio
    except ImportError as error:
        raise RuntimeError("numpy and rasterio are required") from error
    with rasterio.open(npp) as source, rasterio.open(npp_qc) as quality:
        if (source.crs, source.transform, source.shape) != (quality.crs, quality.transform, quality.shape):
            raise ValueError("npp_qc_grid_mismatch")
        values = source.read(1).astype("float64"); qc = quality.read(1)
        valid_npp = np.isfinite(values) & (values != source.nodata) & (qc != quality.nodata) & (qc <= 100)
    if not valid_npp.any(): raise ValueError("no_finite_raster_values:npp")
    with rasterio.open(et) as source, rasterio.open(periods) as period_source:
        if (source.crs, source.transform, source.shape) != (period_source.crs, period_source.transform, period_source.shape):
            raise ValueError("et_period_grid_mismatch")
        et_values = source.read(1).astype("float64"); period_values = period_source.read(1)
        valid_et = np.isfinite(et_values) & (et_values != source.nodata) & (period_values == 46)
    if not valid_et.any(): raise ValueError("no_complete_46_period_et_pixels")
    return [
        _observation(
            observation_id="modis-2024-npp-mean", metric="npp", value=float(values[valid_npp].mean()),
            unit="kgC/m2/a", region_code=region_code, year=year, spatial_grain="valid_district_pixels",
            method_id="modis.npp.qc_mean", asset_ids=(asset_ids["npp"], asset_ids["npp_qc"]),
            confidence=0.75, uncertainty={"valid_pixel_count": int(valid_npp.sum()), "not_nep": True},
            evidence_class="public_calculation", artifact=npp,
        ),
        _observation(
            observation_id="modis-2024-et-mean", metric="actual_et", value=float(et_values[valid_et].mean()),
            unit="mm/a", region_code=region_code, year=year, spatial_grain="complete_46_period_pixels",
            method_id="modis.et.complete_period_mean", asset_ids=(asset_ids["et"], asset_ids["et_periods"]),
            confidence=0.75, uncertainty={"complete_pixel_count": int(valid_et.sum()), "required_periods": 46},
            evidence_class="public_calculation", artifact=et,
        ),
    ]


def build_terrain_observations(
    dem_paths: Iterable[Path], *, asset_ids: Iterable[str], year: int = 2024, region_code: str = "110108",
) -> list[ObservationRecord]:
    _require_2024(year); paths = [_require_file(path) for path in dem_paths]; ids = tuple(asset_ids)
    if not paths or len(paths) != len(ids) or not all(ids): raise ValueError("missing_source_asset")
    try:
        import numpy as np
        import rasterio
        from rasterio.merge import merge
    except ImportError as error:
        raise RuntimeError("numpy and rasterio are required") from error
    sources = [rasterio.open(path) for path in paths]
    try:
        mosaic, transform = merge(sources, method="first", nodata=np.nan, dtype="float64")
    finally:
        for source in sources: source.close()
    values = mosaic[0]; valid = np.isfinite(values)
    if not valid.any(): raise ValueError("no_finite_raster_values:dem")
    filled = np.where(valid, values, np.nanmean(values[valid]))
    y_gradient, x_gradient = np.gradient(filled, abs(transform.e), abs(transform.a))
    slope = np.degrees(np.arctan(np.sqrt(x_gradient ** 2 + y_gradient ** 2)))
    uncertainty = {"unique_pixel_count": int(valid.sum()), "overlap_rule": "first_valid_pixel"}
    return [
        _observation(observation_id="dem-2024-elevation-mean", metric="elevation_mean",
                     value=float(values[valid].mean()), unit="m", region_code=region_code, year=year,
                     spatial_grain="deduplicated_mosaic", method_id="dem.mosaic_mean", asset_ids=ids,
                     confidence=0.85, uncertainty=uncertainty, evidence_class="public_calculation"),
        _observation(observation_id="dem-2024-slope-mean", metric="slope_mean",
                     value=float(slope[valid].mean()), unit="degree", region_code=region_code, year=year,
                     spatial_grain="deduplicated_mosaic", method_id="dem.gradient_slope", asset_ids=ids,
                     confidence=0.80, uncertainty=uncertainty, evidence_class="public_calculation"),
    ]


def build_cover_observations(
    cover_path: Path, *, asset_id: str, year: int = 2024, region_code: str = "110108",
) -> list[ObservationRecord]:
    _require_2024(year); path = _require_file(cover_path)
    try:
        import numpy as np
        import rasterio
    except ImportError as error:
        raise RuntimeError("numpy and rasterio are required") from error
    with rasterio.open(path) as source:
        values = source.read(1)
        valid = np.isfinite(values) & (values != source.nodata) & (values > 0)
        if not valid.any(): raise ValueError("no_finite_raster_values:cover")
        pixel_area = abs(source.transform.a * source.transform.e) / 10000.0
    result = []
    codes, counts = np.unique(values[valid].astype("int32"), return_counts=True)
    for code, count in zip(codes, counts):
        result.append(_observation(
            observation_id=f"worldcover-{year}-area-{int(code)}", metric="ecosystem_area",
            value=round(float(count) * pixel_area, 10), unit="hm2", region_code=region_code, year=year,
            spatial_grain=f"worldcover_class_{int(code)}", method_id="worldcover.pixel_area",
            asset_ids=(asset_id,), confidence=0.65,
            uncertainty={"class_code": int(code), "pixel_count": int(count), "source_year": 2021,
                         "boundary_status": "unconfirmed_osm_demo_boundary"},
            evidence_class="model_estimate", artifact=path,
        ))
    return result
