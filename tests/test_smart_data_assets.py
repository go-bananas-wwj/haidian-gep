import json
import tempfile
import unittest
from pathlib import Path

from gep.smart_data.assets import scan_known_assets


class SmartDataAssetScanTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "data"
        (self.root / "catalog").mkdir(parents=True)
        (self.root / "derived").mkdir()
        (self.root / "raw" / "public").mkdir(parents=True)

    def tearDown(self):
        self.directory.cleanup()

    def write_receipts(self):
        (self.root / "derived" / "nasa.csv").write_text("month,precipitation\n202401,1\n", encoding="utf-8")
        (self.root / "catalog" / "climate_receipt.json").write_text(json.dumps({
            "source": "https://power.larc.nasa.gov/api/temporal/monthly/point",
            "derived_path": "data/derived/nasa.csv", "sha256": "a" * 64,
            "valid_months": [f"2024{month:02d}" for month in range(1, 13)],
            "limitation": "single point",
        }), encoding="utf-8")
        (self.root / "catalog" / "modis_2024_reference_receipt.json").write_text(json.dumps([
            {"local_path": "data/derived/npp_2024.tif", "sha256": "b" * 64,
             "units": "kg C m-2 year-1", "description": "Not NEP."},
        ]), encoding="utf-8")
        (self.root / "raw" / "public" / "worldcover.tif").write_bytes(b"worldcover-fixture")
        (self.root / "catalog" / "public_raster_receipt.json").write_text(json.dumps({"files": [{
            "collection": "esa-worldcover", "item_id": "worldcover-2021", "asset": "map",
            "source_href": "https://example.test/worldcover.tif",
            "properties": {"start_datetime": "2021-01-01T00:00:00Z", "end_datetime": "2021-12-31T23:59:59Z"},
            "bbox_wgs84": [116.0, 39.8, 116.4, 40.2], "local_path": "data/raw/public/worldcover.tif",
            "crs": "EPSG:4326", "sha256": "c" * 64,
        }]}), encoding="utf-8")

    def test_data_asset_scan_registers_present_and_missing_assets_in_stable_order(self):
        self.write_receipts()

        assets = scan_known_assets(self.root)

        self.assertEqual([asset.asset_id for asset in assets], [
            "esa-worldcover-worldcover-2021", "modis-npp-2024", "nasa-power-monthly-point",
        ])
        by_id = {asset.asset_id: asset for asset in assets}
        self.assertEqual(by_id["nasa-power-monthly-point"].quality_status, "proxy")
        self.assertEqual(by_id["nasa-power-monthly-point"].period_start, "2024-01-01")
        self.assertEqual(by_id["modis-npp-2024"].quality_status, "missing")
        self.assertEqual(by_id["esa-worldcover-worldcover-2021"].quality_status, "available")
        self.assertEqual(by_id["esa-worldcover-worldcover-2021"].local_path, "raw/public/worldcover.tif")

    def test_data_asset_scan_rejects_a_symlink_that_escapes_the_data_root(self):
        outside = Path(self.directory.name) / "outside.tif"
        outside.write_bytes(b"outside")
        evil = self.root / "raw" / "public" / "evil.tif"
        evil.symlink_to(outside)
        (self.root / "catalog" / "public_raster_receipt.json").write_text(json.dumps({"files": [{
            "collection": "cop-dem-glo-30", "item_id": "evil", "asset": "data",
            "source_href": "https://example.test/evil.tif", "properties": {"datetime": "2021-01-01T00:00:00Z"},
            "bbox_wgs84": [116.0, 39.8, 116.4, 40.2], "local_path": "data/raw/public/evil.tif",
            "crs": "EPSG:4326", "sha256": "d" * 64,
        }]}), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "escapes the approved data root"):
            scan_known_assets(self.root)

    def test_xuannv_comparison_asset_never_claims_2024_coverage(self):
        (self.root / "catalog" / "xuannv_window_202512_202605.json").write_text(json.dumps({
            "window": {"start": "2025-12-01", "end_exclusive": "2026-06-01"},
            "embedding_manifest_sha256_verified": False,
        }), encoding="utf-8")

        assets = scan_known_assets(self.root)

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].asset_type, "comparison_embedding")
        self.assertEqual(assets[0].period_start, "2025-12-01")
        self.assertEqual(assets[0].period_end, "2026-05-31")
        self.assertEqual(assets[0].quality_status, "review_required")

    def test_scan_exposes_built_aef_subset_and_downgraded_classification(self):
        subset = self.root / "haidian_gep_2024" / "03_features" / "alphaearth_2024"
        classified = self.root / "haidian_gep_2024" / "03_features" / "aef_classification_2024" / "classification"
        subset.mkdir(parents=True); classified.mkdir(parents=True)
        (subset / "aef_2024_haidian_int8.tif").write_bytes(b"subset")
        (subset / "aef_2024_haidian_int8.manifest.json").write_text(json.dumps({
            "year":2024,"output_file":"aef_2024_haidian_int8.tif","output_sha256":"e"*64,
            "quality_status":"demo_ready","coverage_fraction":1.0,"band_count":64,"pixel_size_m":10.0,"crs":"EPSG:32650",
        }))
        (classified / "aef_ecosystem_class_2024.tif").write_bytes(b"classified")
        (classified / "aef_ecosystem_class_2024.report.json").write_text(json.dumps({
            "output_sha256":"f"*64,"macro_f1":0.43,"auto_usable":False,"gate_reasons":["macro_f1_below_0.70"]
        }))
        assets = scan_known_assets(self.root)
        by_id={a.asset_id:a for a in assets}
        self.assertEqual(by_id["alphaearth-2024-subset"].quality_status,"demo_ready")
        self.assertEqual(by_id["alphaearth-2024-classification"].quality_status,"review_required")


if __name__ == "__main__":
    unittest.main()
