"""Truthful inspection of AlphaEarth Foundation spatial research assets."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


SPATIAL_NODE_KEYS = {
    "R1.ecosystem_area", "R2.area", "R5.ecosystem_area", "R6.ecosystem_area", "R8.ecosystem_area",
}
AEF_SOURCE_PREFIX = "/vsis3/us-west-2.opendata.source.coop/tge-labs/aef/v1/annual/2024/50N/"


class AefSpatialTool:
    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)

    def inspect(self, work_order: dict[str, Any]) -> dict[str, Any]:
        if work_order.get("node_key") not in SPATIAL_NODE_KEYS:
            return {"status": "not_applicable"}
        if int(work_order.get("year") or 0) != 2024:
            return {"status": "research_gap", "missing_prerequisites": ["aef_year_2024"]}
        vrt_files = sorted((self.data_root / "01_raw" / "remote_sensing" / "alphaearth_2024").glob("*.vrt"))
        if not vrt_files:
            return {"status": "research_gap", "year": 2024, "missing_prerequisites": ["aef_vrt"]}
        vrt = vrt_files[0]
        root = ElementTree.fromstring(vrt.read_text(encoding="utf-8"))
        bands = root.findall("VRTRasterBand")
        if len(bands) != 64:
            raise ValueError("AEF VRT must expose exactly 64 embedding bands")
        descriptions = [band.findtext("Description", "") for band in bands]
        if descriptions != [f"A{index:02d}" for index in range(64)]:
            raise ValueError("AEF VRT band descriptions must be A00 through A63")
        transform = [float(value.strip()) for value in root.findtext("GeoTransform", "").split(",")]
        if len(transform) != 6 or transform[1] != 10.0 or transform[5] != -10.0:
            raise ValueError("AEF VRT must use a 10 metre pixel grid")
        srs = root.findtext("SRS", "")
        if "32650" not in srs or "UTM zone 50N" not in srs:
            raise ValueError("AEF VRT must use WGS 84 / UTM zone 50N")
        source = root.findtext("./GDALWarpOptions/SourceDataset", "")
        if not source.startswith(AEF_SOURCE_PREFIX) or not source.endswith((".tif", ".tiff")):
            raise ValueError("AEF VRT source must use the approved Source Cooperative 2024 50N bucket")

        base = {
            "status": "research_gap", "year": 2024, "band_count": 64, "pixel_size_m": 10.0,
            "crs": "EPSG:32650", "source_scheme": "source-cooperative-vsis3", "source_dataset": source,
            "vrt_file": str(vrt.relative_to(self.data_root)),
            "vrt_sha256": hashlib.sha256(vrt.read_bytes()).hexdigest(),
        }
        boundary = self.data_root / "00_catalog" / "confirmed_boundary.geojson"
        labels = self.data_root / "03_features" / "aef_green_labels.geojson"
        validation_file = self.data_root / "03_features" / "aef_green_validation.json"
        missing = []
        if not boundary.is_file(): missing.append("confirmed_boundary")
        if not labels.is_file(): missing.append("training_labels")

        validated = None
        if validation_file.is_file():
            payload = json.loads(validation_file.read_text(encoding="utf-8"))
            output = validation_file.parent / str(payload.get("output_file") or "aef_green_2024.tif")
            if payload.get("validated") is True and output.is_file():
                actual_hash = hashlib.sha256(output.read_bytes()).hexdigest()
                accuracy = payload.get("overall_accuracy")
                if (actual_hash == payload.get("output_sha256") and isinstance(accuracy, (int, float))
                        and 0 <= accuracy <= 1 and isinstance(payload.get("green_area_hm2"), (int, float))):
                    validated = {**payload, "output_file": str(output.relative_to(self.data_root))}
        if validated is None:
            missing.append("validated_green_product")
            if importlib.util.find_spec("rasterio") is None:
                missing.append("raster_runtime")
        if missing:
            return {**base, "missing_prerequisites": missing}
        return {
            **base, **validated, "status": "ready", "missing_prerequisites": [],
        }
