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
from gep.smart_data.aef_classifier import (
    align_worldcover_labels,
    build_area_observations,
    classification_quality_gate,
    classify_aef,
    register_area_observations,
    spatial_block_split,
    train_aef_classifier,
)
from gep.smart_data import AssetRecord
from gep.task_service import GepStore


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


@unittest.skipUnless(SPATIAL_AVAILABLE, "spatial build dependencies are optional")
class SmartDataAefClassifierTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write_training_fixture(self):
        aef = self.root / "aef.tif"; labels = self.root / "labels.tif"
        height = width = 12
        label_values = np.zeros((height, width), dtype="uint8")
        for row in range(height):
            for column in range(width):
                label_values[row, column] = 10 if ((row // 2) + (column // 2)) % 2 == 0 else 50
        features = np.zeros((64, height, width), dtype="int8")
        features[0] = np.where(label_values == 10, -100, 100).astype("int8")
        features[1] = np.where(label_values == 10, -50, 50).astype("int8")
        transform = from_origin(0, 120, 10, 10)
        with rasterio.open(aef, "w", driver="GTiff", width=width, height=height, count=64, dtype="int8",
                           crs="EPSG:32650", transform=transform, nodata=-128) as dataset:
            dataset.write(features)
            for band in range(1, 65): dataset.set_band_description(band, f"A{band - 1:02d}")
        with rasterio.open(labels, "w", driver="GTiff", width=width, height=height, count=1, dtype="uint8",
                           crs="EPSG:32650", transform=transform, nodata=0) as dataset:
            dataset.write(label_values, 1)
        return aef, labels

    def test_classifier_spatial_holdout_is_disjoint_and_quality_gate_boundaries(self):
        rows, columns = np.indices((12, 12))
        split = spatial_block_split(rows.ravel(), columns.ravel(), block_size=2, holdout_fraction=0.25, random_seed=20240928)

        self.assertTrue(set(split.train_block_ids).isdisjoint(split.holdout_block_ids))
        self.assertGreater(len(split.train_indices), 0)
        self.assertGreater(len(split.holdout_indices), 0)
        accepted = classification_quality_gate(0.70, {10: 0.50, 50: 0.80}, 100.0, 100.0)
        low_f1 = classification_quality_gate(0.699, {10: 0.90, 50: 0.90}, 100.0, 100.0)
        low_recall = classification_quality_gate(0.90, {10: 0.499, 50: 0.90}, 100.0, 100.0)
        area_mismatch = classification_quality_gate(0.90, {10: 0.90, 50: 0.90}, 121.0, 100.0)
        self.assertTrue(accepted.auto_usable)
        self.assertEqual(accepted.reasons, ())
        self.assertFalse(low_f1.auto_usable)
        self.assertIn("macro_f1_below_0.70", low_f1.reasons)
        self.assertFalse(low_recall.auto_usable)
        self.assertIn("class_recall_below_0.50", low_recall.reasons)
        self.assertFalse(area_mismatch.auto_usable)
        self.assertIn("official_area_difference_above_20_percent", area_mismatch.reasons)

    def test_classifier_rejects_labels_with_misaligned_grid(self):
        aef, labels = self.write_training_fixture()
        misaligned = self.root / "misaligned.tif"
        with rasterio.open(labels) as source:
            values = source.read(1)
        with rasterio.open(misaligned, "w", driver="GTiff", width=12, height=12, count=1, dtype="uint8",
                           crs="EPSG:4326", transform=from_origin(116, 40, .001, .001), nodata=0) as output:
            output.write(values, 1)

        with self.assertRaisesRegex(ValueError, "aligned to the AEF grid"):
            train_aef_classifier(aef, misaligned, FIXTURES / "boundary_demo.geojson", self.root / "model")

    def test_classifier_trains_classifies_and_emits_area_observations(self):
        aef, labels = self.write_training_fixture()
        model = train_aef_classifier(
            aef, labels, FIXTURES / "boundary_demo.geojson", self.root / "model", random_seed=20240928,
        )
        classified = classify_aef(model, aef, self.root / "classification", official_green_area_hm2=None)
        observations = build_area_observations(
            classified, input_asset_ids=("alphaearth-2024-subset", "esa-worldcover-2021"), region_code="110108", year=2024,
        )

        self.assertTrue(set(model.train_block_ids).isdisjoint(model.holdout_block_ids))
        self.assertGreaterEqual(model.macro_f1, 0.70)
        self.assertTrue(classified.auto_usable)
        self.assertEqual(classified.area_hm2, {10: 0.72, 50: 0.72})
        self.assertEqual(classified.output_sha256, observations[0].artifact_sha256)
        self.assertEqual([item.metric for item in observations], ["ecosystem_area", "ecosystem_area"])
        self.assertEqual([item.unit for item in observations], ["hm2", "hm2"])
        self.assertEqual({item.evidence_class for item in observations}, {"model_estimate"})
        self.assertTrue(all(item.year == 2024 and item.region_code == "110108" for item in observations))

        store = GepStore(self.root / "smart.sqlite3")
        try:
            for asset_id in ("alphaearth-2024-subset", "esa-worldcover-2021"):
                store.smart_data.register_asset(AssetRecord.from_dict({
                    "asset_id": asset_id, "asset_version": "v1", "asset_type": "fixture",
                    "title": asset_id, "publisher": "fixture", "source_url": None,
                    "license_or_access": "test", "period_start": "2024-01-01", "period_end": "2024-12-31",
                    "region_code": "110108", "bbox": None, "crs": "EPSG:32650", "local_path": None,
                    "sha256": ("a" if asset_id.startswith("alphaearth") else "b") * 64,
                    "quality_status": "available", "quality": {},
                }))
            registered = register_area_observations(
                store.smart_data, classified,
                input_asset_ids=("alphaearth-2024-subset", "esa-worldcover-2021"),
                region_code="110108", year=2024,
            )
            found = store.smart_data.find_observations(metric="ecosystem_area", year=2024, region_code="110108")
        finally:
            store.close()
        self.assertEqual(len(registered), 2)
        self.assertEqual([item["observation_id"] for item in found], [
            "aef-2024-ecosystem-area-10", "aef-2024-ecosystem-area-50",
        ])

    def test_worldcover_alignment_writes_the_exact_aef_grid(self):
        aef, labels = self.write_training_fixture()
        shifted = self.root / "shifted-labels.tif"
        with rasterio.open(labels) as source:
            values = source.read(1)
        with rasterio.open(shifted, "w", driver="GTiff", width=6, height=6, count=1, dtype="uint8",
                           crs="EPSG:32650", transform=from_origin(0, 120, 20, 20), nodata=0) as output:
            output.write(values[::2, ::2], 1)

        aligned = align_worldcover_labels(aef, shifted, self.root / "aligned.tif")

        with rasterio.open(aef) as feature_grid, rasterio.open(aligned) as label_grid:
            self.assertEqual(label_grid.crs, feature_grid.crs)
            self.assertEqual(label_grid.transform, feature_grid.transform)
            self.assertEqual((label_grid.height, label_grid.width), (feature_grid.height, feature_grid.width))

    def test_classify_cli_emits_validation_and_area_observations(self):
        aef, labels = self.write_training_fixture()
        output = self.root / "cli-output"

        completed = subprocess.run([
            sys.executable, "scripts/build_smart_data.py", "classify", "--aef", str(aef),
            "--worldcover", str(labels), "--boundary", str(FIXTURES / "boundary_demo.geojson"),
            "--output-dir", str(output),
        ], cwd=Path(__file__).parents[1], capture_output=True, text=True)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["auto_usable"])
        self.assertEqual(payload["observation_count"], 2)
        self.assertTrue((output / "observations.json").is_file())
        observations = json.loads((output / "observations.json").read_text())
        self.assertEqual([item["metric"] for item in observations], ["ecosystem_area", "ecosystem_area"])


if __name__ == "__main__":
    unittest.main()
