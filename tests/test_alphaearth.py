import tempfile
import unittest
from pathlib import Path
import json
import subprocess
import sys

from gep.geo.alphaearth import (
    dequantize_int8,
    rewrite_vrt_source,
    select_2024_assets,
    validate_boundary,
)
from gep.geo.coverage import coverage_report


class AlphaEarthTests(unittest.TestCase):
    def test_dequantize_masks_nodata_and_uses_float_formula_once(self):
        values = dequantize_int8([-128, -127, 0, 127])

        self.assertEqual(values[0], None)
        self.assertEqual(values[1], -(127 / 127.5) ** 2)
        self.assertEqual(values[2], 0.0)
        self.assertEqual(values[3], (127 / 127.5) ** 2)
        self.assertTrue(all(value is None or isinstance(value, float) for value in values))
        with self.assertRaises(ValueError):
            dequantize_int8(values, already_dequantized=True)

    def test_selection_requires_approved_boundary_and_returns_all_intersections(self):
        boundary = {
            "status": "approved", "sha256": "b" * 64, "crs": "EPSG:4326",
            "bbox": [116.0, 39.8, 116.4, 40.2],
        }
        assets = [
            {"asset_id": "west", "year": 2024, "wgs84_west": 115.9, "wgs84_south": 39.8, "wgs84_east": 116.1, "wgs84_north": 40.0},
            {"asset_id": "east", "year": 2024, "wgs84_west": 116.1, "wgs84_south": 40.0, "wgs84_east": 116.5, "wgs84_north": 40.3},
            {"asset_id": "old", "year": 2023, "wgs84_west": 116.0, "wgs84_south": 39.8, "wgs84_east": 116.4, "wgs84_north": 40.2},
        ]

        self.assertEqual(validate_boundary(boundary)["sha256"], "b" * 64)
        self.assertEqual([asset["asset_id"] for asset in select_2024_assets(assets, boundary)], ["east", "west"])
        with self.assertRaises(ValueError):
            select_2024_assets(assets, {**boundary, "status": "unconfirmed_osm_demo_boundary"})

    def test_vrt_rewrite_removes_remote_source_and_preserves_local_path(self):
        xml = """<VRTDataset><VRTRasterBand><SimpleSource><SourceDataset>https://data.source.coop/tile.tiff</SourceDataset></SimpleSource></VRTRasterBand></VRTDataset>"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "remote.vrt")
            destination = Path(directory, "local.vrt")
            source.write_text(xml, encoding="utf-8")

            rewrite_vrt_source(source, destination, Path(directory, "tile.tiff"))

            rewritten = destination.read_text(encoding="utf-8")
            self.assertIn(str(Path(directory, "tile.tiff")), rewritten)
            self.assertNotIn("https://", rewritten)

    def test_coverage_requires_64_bands_and_limits_holes_to_half_percent(self):
        boundary = [0, 0, 10, 10]
        assets = [
            {"asset_id": "west", "bbox": [0, 0, 5, 10], "band_count": 64, "valid": True, "sha256": "a" * 64, "crs": "EPSG:32650", "affine": "x"},
            {"asset_id": "east", "bbox": [5, 0, 10, 10], "band_count": 64, "valid": True, "sha256": "b" * 64, "crs": "EPSG:32650", "affine": "x"},
        ]

        report = coverage_report(boundary, assets)

        self.assertTrue(report.ready)
        self.assertEqual(report.valid_area, 100.0)
        self.assertEqual(report.hole_area, 0.0)
        incomplete = coverage_report(boundary, [{**assets[0], "band_count": 63}])
        self.assertFalse(incomplete.ready)
        self.assertIn("west:band_count", incomplete.issues)

    def test_acquisition_script_selects_assets_without_downloading_them(self):
        boundary = {"status": "approved", "sha256": "b" * 64, "crs": "EPSG:4326", "bbox": [0, 0, 2, 2]}
        assets = [{"asset_id": "tile", "year": 2024, "wgs84_west": 0, "wgs84_south": 0, "wgs84_east": 2, "wgs84_north": 2}]
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory, "index.json")
            boundary_path = Path(directory, "boundary.json")
            output_path = Path(directory, "selected.json")
            index_path.write_text(json.dumps(assets), encoding="utf-8")
            boundary_path.write_text(json.dumps(boundary), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "scripts/acquire_alphaearth.py", "--index", str(index_path), "--boundary", str(boundary_path), "--out", str(output_path)],
                cwd=Path(__file__).parents[1], capture_output=True, text=True, check=True,
            )

            self.assertIn("selected=1", completed.stdout)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["assets"][0]["asset_id"], "tile")


if __name__ == "__main__":
    unittest.main()
