"""Safe planning and construction of a cropped 2024 AlphaEarth subset."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from gep.geo.alphaearth import select_2024_assets, validate_boundary


AEF_HTTPS_PREFIX = "https://data.source.coop/tge-labs/aef/v1/annual/2024/"
AEF_S3_PREFIX = "s3://us-west-2.opendata.source.coop/tge-labs/aef/v1/annual/2024/"
AEF_ATTRIBUTION = "The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind."


@dataclass(frozen=True)
class AefSubsetPlan:
    year: int
    boundary: dict[str, Any]
    assets: tuple[dict[str, Any], ...]
    output_name: str
    demo_boundary: bool


@dataclass(frozen=True)
class AefSubsetResult:
    output_path: Path
    vrt_path: Path
    manifest_path: Path
    output_sha256: str
    band_count: int
    pixel_size_m: float
    crs: str
    boundary_pixel_count: int
    valid_pixel_count: int
    coverage_fraction: float
    quality_status: str
    attribution: str
    source_asset_ids: tuple[str, ...]
    demo_boundary: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path), "vrt_path": str(self.vrt_path),
            "manifest_path": str(self.manifest_path), "output_sha256": self.output_sha256,
            "band_count": self.band_count, "pixel_size_m": self.pixel_size_m, "crs": self.crs,
            "boundary_pixel_count": self.boundary_pixel_count, "valid_pixel_count": self.valid_pixel_count,
            "coverage_fraction": self.coverage_fraction, "quality_status": self.quality_status,
            "attribution": self.attribution, "source_asset_ids": list(self.source_asset_ids),
            "demo_boundary": self.demo_boundary,
        }


def _read_index(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        loaded = json.loads(path.read_text(encoding="utf-8"))
        records = loaded.get("assets", loaded) if isinstance(loaded, dict) else loaded
        if not isinstance(records, list):
            raise ValueError("AEF JSON index must contain a list")
        return [dict(record) for record in records if isinstance(record, dict)]
    if path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as parquet
        except ImportError as error:
            raise RuntimeError("pyarrow is required to read the AEF parquet index") from error
        table = parquet.read_table(path, columns=[
            "year", "path", "crs", "utm_zone", "wgs84_west", "wgs84_south", "wgs84_east", "wgs84_north",
        ])
        return table.to_pylist()
    raise ValueError("AEF index must be JSON or Parquet")


def _checked_boundary(boundary: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    status = boundary.get("status")
    demo = status == "unconfirmed_osm_demo_boundary"
    checked = validate_boundary({**dict(boundary), "status": "approved"} if demo else boundary)
    geometry = boundary.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("AlphaEarth boundary requires Polygon or MultiPolygon geometry")
    return {**checked, "status": status, "geometry": geometry}, demo


def _urls(record: Mapping[str, Any]) -> tuple[str, str]:
    raw = str(record.get("url") or record.get("path") or "")
    if raw.startswith(AEF_S3_PREFIX):
        tiff_url = AEF_HTTPS_PREFIX + raw.removeprefix(AEF_S3_PREFIX)
    elif raw.startswith(AEF_HTTPS_PREFIX):
        tiff_url = raw
    else:
        raise ValueError("AEF candidate must come from the approved Source Cooperative 2024 prefix")
    if not tiff_url.endswith((".tif", ".tiff")):
        raise ValueError("AEF candidate must be a TIFF")
    vrt_url = tiff_url.rsplit(".", 1)[0] + ".vrt"
    return tiff_url, vrt_url


def plan_aef_subset(index_path: Path, boundary: Mapping[str, Any], year: int = 2024) -> AefSubsetPlan:
    if year != 2024:
        raise ValueError("the first smart-data release requires the 2024 AEF layer")
    checked, demo = _checked_boundary(boundary)
    selected = select_2024_assets(_read_index(Path(index_path)), {**checked, "status": "approved"})
    assets = []
    for number, record in enumerate(selected):
        tiff_url, vrt_url = _urls(record)
        assets.append({**record, "asset_id": str(record.get("asset_id") or f"aef-2024-{number:03d}"),
                       "tiff_url": tiff_url, "vrt_url": vrt_url})
    return AefSubsetPlan(
        year=year, boundary=checked, assets=tuple(assets), output_name="aef_2024_haidian_int8.tif", demo_boundary=demo,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_source(source: str) -> str:
    if source.startswith(("http://", "https://")):
        if not source.startswith(AEF_HTTPS_PREFIX) or not source.endswith(".vrt"):
            raise ValueError("remote AEF VRT is outside the approved Source Cooperative 2024 prefix")
        return source
    path = Path(source)
    if not path.is_file():
        raise OSError(f"local AEF VRT does not exist: {path}")
    return str(path)


def _write_vrt(path: Path, source: Path, *, width: int, height: int, transform: Any, crs_wkt: str) -> None:
    bands = []
    for band in range(1, 65):
        bands.append(
            f'<VRTRasterBand dataType="Int8" band="{band}"><Description>A{band - 1:02d}</Description>'
            f'<NoDataValue>-128</NoDataValue><SimpleSource><SourceFilename relativeToVRT="0">{source}</SourceFilename>'
            f'<SourceBand>{band}</SourceBand></SimpleSource></VRTRasterBand>'
        )
    geotransform = ",".join(str(value) for value in (transform.c, transform.a, transform.b, transform.f, transform.d, transform.e))
    path.write_text(
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}"><SRS>{crs_wkt}</SRS>'
        f'<GeoTransform>{geotransform}</GeoTransform>{"".join(bands)}</VRTDataset>', encoding="utf-8",
    )


def build_aef_subset(plan: AefSubsetPlan, output_dir: Path) -> AefSubsetResult:
    """Build one masked Int8 subset atomically; remote data is read only through companion VRTs."""
    output_name = Path(plan.output_name)
    if output_name.name != plan.output_name or output_name.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("output_name must be one TIFF filename inside output_dir")
    if not plan.assets:
        raise ValueError("AEF subset plan has no source assets")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    final_output = output_dir / output_name.name
    final_vrt = output_dir / f"{output_name.stem}.vrt"
    final_manifest = output_dir / f"{output_name.stem}.manifest.json"
    if not all(path.resolve(strict=False).is_relative_to(output_dir.resolve()) for path in (final_output, final_vrt, final_manifest)):
        raise ValueError("output_name escapes output_dir")

    try:
        import numpy as np
        import rasterio
        from rasterio.features import bounds as geometry_bounds, geometry_mask
        from rasterio.merge import merge
        from rasterio.shutil import copy as raster_copy
        from rasterio.warp import transform_geom
    except ImportError as error:
        raise RuntimeError("numpy and rasterio are required to build the AEF subset") from error

    sources = []
    try:
        for asset in plan.assets:
            dataset = rasterio.open(_safe_source(str(asset["vrt_url"])))
            sources.append(dataset)
            if dataset.count != 64 or any(dtype != "int8" for dtype in dataset.dtypes):
                raise ValueError("AEF source must expose 64 signed Int8 bands")
            if dataset.nodata != -128:
                raise ValueError("AEF source NoData must be -128")
            if dataset.crs is None or dataset.crs.to_epsg() != 32650:
                raise ValueError("AEF source must use EPSG:32650")
            if not math.isclose(abs(dataset.transform.a), 10.0) or not math.isclose(abs(dataset.transform.e), 10.0):
                raise ValueError("AEF source must use a 10 metre grid")
            if dataset.descriptions != tuple(f"A{index:02d}" for index in range(64)):
                raise ValueError("AEF band descriptions must be A00 through A63")
        geometry = transform_geom(plan.boundary["crs"], sources[0].crs, plan.boundary["geometry"], precision=7)
        mosaic, transform = merge(sources, bounds=geometry_bounds(geometry), nodata=-128, method="first", dtype="int8")
        inside = geometry_mask([geometry], out_shape=mosaic.shape[1:], transform=transform, invert=True)
        mosaic[:, ~inside] = -128
        valid = inside & (mosaic[0] != -128)
        boundary_pixels = int(inside.sum()); valid_pixels = int(valid.sum())
        coverage = valid_pixels / boundary_pixels if boundary_pixels else 0.0
        quality = "demo_ready" if math.isclose(coverage, 1.0) else "partial_coverage"

        with tempfile.TemporaryDirectory(prefix="aef-build-", dir=output_dir) as temporary:
            temporary_dir = Path(temporary)
            raw_path = temporary_dir / "subset.tif"
            cog_path = temporary_dir / output_name.name
            vrt_path = temporary_dir / final_vrt.name
            manifest_path = temporary_dir / final_manifest.name
            with rasterio.open(
                raw_path, "w", driver="GTiff", width=mosaic.shape[2], height=mosaic.shape[1], count=64,
                dtype="int8", crs=sources[0].crs, transform=transform, nodata=-128, compress="DEFLATE",
            ) as output:
                output.write(mosaic)
                for band in range(1, 65): output.set_band_description(band, f"A{band - 1:02d}")
            raster_copy(raw_path, cog_path, driver="COG", compress="DEFLATE", blocksize=512)
            output_hash = _sha256(cog_path)
            with rasterio.open(cog_path) as output:
                _write_vrt(vrt_path, final_output.resolve(), width=output.width, height=output.height,
                           transform=output.transform, crs_wkt=output.crs.to_wkt())
            manifest = {
                "year": plan.year, "output_file": final_output.name, "output_sha256": output_hash,
                "band_count": 64, "pixel_size_m": 10.0, "crs": "EPSG:32650",
                "boundary_pixel_count": boundary_pixels, "valid_pixel_count": valid_pixels,
                "coverage_fraction": coverage, "quality_status": quality,
                "source_asset_ids": [str(asset["asset_id"]) for asset in plan.assets],
                "demo_boundary": plan.demo_boundary, "boundary_sha256": plan.boundary["sha256"],
                "attribution": AEF_ATTRIBUTION,
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(cog_path, final_output); os.replace(vrt_path, final_vrt); os.replace(manifest_path, final_manifest)
        return AefSubsetResult(
            output_path=final_output, vrt_path=final_vrt, manifest_path=final_manifest,
            output_sha256=output_hash, band_count=64, pixel_size_m=10.0, crs="EPSG:32650",
            boundary_pixel_count=boundary_pixels, valid_pixel_count=valid_pixels,
            coverage_fraction=coverage, quality_status=quality, attribution=AEF_ATTRIBUTION,
            source_asset_ids=tuple(str(asset["asset_id"]) for asset in plan.assets),
            demo_boundary=plan.demo_boundary,
        )
    finally:
        for source in sources:
            source.close()
