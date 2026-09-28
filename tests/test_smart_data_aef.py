import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

try:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    SPATIAL_AVAILABLE = True
except ImportError:
    SPATIAL_AVAILABLE = False

from gep.geo.alphaearth import dequantize_int8
from gep.smart_data.aef_pipeline import (
    AEF_ATTRIBUTION,
    AefSubsetPlan,
    build_aef_subset,
    plan_aef_subset,
)


FIXTURES = Path(__file__).parent / "fixtures" / "smart_data" / "aef"


def write_tile(path: Path, *, west: float, north: float, value: int, nodata_pixel=False):
    values = np.full((64, 4, 4), value, dtype="int8")
    if nodata_pixel:
        values[:, 0, 0] = -128
    with rasterio.open(
        path, "w", driver="GTiff", width=4, height=4, count=64, dtype="int8",
        crs="EPSG:32650", transform=from_origin(west, north, 10, 10), nodata=-128,
    ) as dataset:
        dataset.write(values)
        for band in range(1, 65):
            dataset.set_band_description(band, f"A{band - 1:02d}")


def projected_boundary(west=10, south=0, east=60, north=40):
    return {
        "status": "unconfirmed_osm_demo_boundary", "sha256": "b" * 64, "crs": "EPSG:32650",
        "bbox": [west, south, east, north],
        "geometry": {"type": "Polygon", "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south],
        ]]},
    }


@unittest.skipUnless(SPATIAL_AVAILABLE, "spatial build dependencies are optional")
class SmartDataAefPipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_plan_selects_three_2024_tiles_and_uses_companion_vrts(self):
        boundary = json.loads((FIXTURES / "boundary_demo.geojson").read_text())

        plan = plan_aef_subset(FIXTURES / "index.json", boundary)

        self.assertEqual([asset["asset_id"] for asset in plan.assets], ["east", "middle", "west"])
        self.assertTrue(all(asset["vrt_url"].endswith(".vrt") for asset in plan.assets))
        self.assertTrue(all(asset["tiff_url"].startswith("https://data.source.coop/") for asset in plan.assets))
        self.assertTrue(plan.demo_boundary)
        self.assertEqual(plan.year, 2024)

    def test_build_uses_vrt_sources_deduplicates_overlap_and_preserves_nodata(self):
        west = self.root / "west.tif"; east = self.root / "east.tif"
        write_tile(west, west=0, north=40, value=1)
        write_tile(east, west=30, north=40, value=2)
        plan = AefSubsetPlan(
            year=2024, boundary=projected_boundary(), assets=(
                {"asset_id": "west", "vrt_url": str(west), "tiff_url": "invalid://must-not-open"},
                {"asset_id": "east", "vrt_url": str(east), "tiff_url": "invalid://must-not-open"},
            ), output_name="aef_2024_haidian.tif", demo_boundary=True,
        )

        result = build_aef_subset(plan, self.root / "output")

        self.assertEqual(result.band_count, 64)
        self.assertEqual(result.pixel_size_m, 10.0)
        self.assertEqual(result.crs, "EPSG:32650")
        self.assertEqual(result.boundary_pixel_count, 20)
        self.assertEqual(result.valid_pixel_count, 20)
        self.assertEqual(result.coverage_fraction, 1.0)
        self.assertEqual(result.quality_status, "demo_ready")
        self.assertEqual(result.attribution, AEF_ATTRIBUTION)
        self.assertTrue(result.output_path.is_file())
        self.assertTrue(result.manifest_path.is_file())
        self.assertEqual(len(result.output_sha256), 64)
        with rasterio.open(result.output_path) as dataset:
            self.assertEqual(dataset.count, 64)
            self.assertEqual(dataset.nodata, -128)
            self.assertEqual(dataset.descriptions, tuple(f"A{index:02d}" for index in range(64)))

    def test_nodata_is_preserved_and_reduces_valid_coverage(self):
        tile = self.root / "nodata.tif"
        write_tile(tile, west=0, north=40, value=1, nodata_pixel=True)
        plan = AefSubsetPlan(
            year=2024, boundary=projected_boundary(west=0, east=40),
            assets=({"asset_id": "nodata", "vrt_url": str(tile), "tiff_url": str(tile)},),
            output_name="nodata-output.tif", demo_boundary=True,
        )

        result = build_aef_subset(plan, self.root / "output")

        self.assertEqual(result.boundary_pixel_count, 16)
        self.assertEqual(result.valid_pixel_count, 15)
        self.assertEqual(result.coverage_fraction, 15 / 16)
        with rasterio.open(result.output_path) as dataset:
            self.assertEqual(dataset.read(1)[0, 0], -128)

    def test_partial_coverage_is_retained_but_not_demo_ready(self):
        west = self.root / "west.tif"
        write_tile(west, west=0, north=40, value=1)
        plan = AefSubsetPlan(
            year=2024, boundary=projected_boundary(west=0, east=80),
            assets=({"asset_id": "west", "vrt_url": str(west), "tiff_url": str(west)},),
            output_name="partial.tif", demo_boundary=True,
        )

        result = build_aef_subset(plan, self.root / "output")

        self.assertEqual(result.coverage_fraction, 0.5)
        self.assertEqual(result.quality_status, "partial_coverage")
        self.assertEqual(result.valid_pixel_count, 16)
        self.assertEqual(result.boundary_pixel_count, 32)

    def test_failed_remote_read_leaves_no_final_output_or_manifest(self):
        broken_vrt = self.root / "missing-source.vrt"
        bands = "".join(
            f'<VRTRasterBand dataType="Int8" band="{band}"><Description>A{band - 1:02d}</Description><NoDataValue>-128</NoDataValue>'
            f'<SimpleSource><SourceFilename>/missing/source.tif</SourceFilename><SourceBand>{band}</SourceBand></SimpleSource></VRTRasterBand>'
            for band in range(1, 65)
        )
        broken_vrt.write_text(
            '<VRTDataset rasterXSize="4" rasterYSize="4"><SRS>EPSG:32650</SRS>'
            '<GeoTransform>0,10,0,40,0,-10</GeoTransform>' + bands + '</VRTDataset>'
        )
        plan = AefSubsetPlan(
            year=2024, boundary=projected_boundary(),
            assets=({"asset_id": "broken", "vrt_url": str(broken_vrt), "tiff_url": "https://example.test/missing.tiff"},),
            output_name="failed.tif", demo_boundary=True,
        )
        output = self.root / "output"

        with self.assertRaises((OSError, rasterio.errors.RasterioError)):
            build_aef_subset(plan, output)

        self.assertFalse((output / "failed.tif").exists())
        self.assertFalse((output / "failed.manifest.json").exists())

    def test_output_name_cannot_escape_destination_and_dequantization_is_once_only(self):
        plan = AefSubsetPlan(
            year=2024, boundary=projected_boundary(), assets=(), output_name="../escape.tif", demo_boundary=True,
        )
        with self.assertRaisesRegex(ValueError, "output_name"):
            build_aef_subset(plan, self.root / "output")
        with self.assertRaisesRegex(ValueError, "already dequantized"):
            dequantize_int8([0], already_dequantized=True)

    def test_build_cli_reports_a_missing_index_without_writing_outputs(self):
        boundary = self.root / "boundary.geojson"
        boundary.write_text(json.dumps(projected_boundary()), encoding="utf-8")

        completed = subprocess.run([
            sys.executable, "scripts/build_smart_data.py", "aef", "--data-root", str(self.root),
            "--boundary", str(boundary),
        ], cwd=Path(__file__).parents[1], capture_output=True, text=True)

        self.assertEqual(completed.returncode, 2)
        self.assertIn("exactly one AEF index is required", completed.stderr)
        self.assertFalse((self.root / "03_features" / "alphaearth_2024").exists())

    def test_package_cli_exposes_the_same_safe_aef_build_entrypoint(self):
        boundary = self.root / "boundary.geojson"
        boundary.write_text(json.dumps(projected_boundary()), encoding="utf-8")

        completed = subprocess.run([
            sys.executable, "-m", "gep", "smart-data-build", "aef", "--data-root", str(self.root),
            "--boundary", str(boundary),
        ], cwd=Path(__file__).parents[1], capture_output=True, text=True)

        self.assertEqual(completed.returncode, 2)
        self.assertIn("exactly one AEF index is required", completed.stderr)


if __name__ == "__main__":
    unittest.main()
