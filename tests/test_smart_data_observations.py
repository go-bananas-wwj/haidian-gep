import csv
import math
import tempfile
import unittest
from pathlib import Path
import json
import subprocess
import sys

try:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    SPATIAL_AVAILABLE = True
except ImportError:
    SPATIAL_AVAILABLE = False

from gep.smart_data.observations import (
    build_cover_observations,
    build_modis_observations,
    build_nasa_power_observations,
    build_terrain_observations,
    load_observation_manifest,
)


@unittest.skipUnless(SPATIAL_AVAILABLE, "spatial build dependencies are optional")
class SmartDataObservationBuilderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write_raster(self, name, values, *, transform=None, dtype="float32", nodata=-9999):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        array = np.asarray(values, dtype=dtype)
        transform = transform or from_origin(0, array.shape[0] * 10, 10, 10)
        with rasterio.open(path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
                           count=1, dtype=dtype, crs="EPSG:32650", transform=transform, nodata=nodata) as output:
            output.write(array, 1)
        return path

    def write_climate(self, months=12):
        path = self.root / "climate.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "month", "days", "valid", "temperature_C", "precipitation_mm_month", "shortwave_MJ_m2_month",
            ])
            writer.writeheader()
            for month in range(1, months + 1):
                writer.writerow({"month": f"2024{month:02d}", "days": 30, "valid": "True",
                                 "temperature_C": month, "precipitation_mm_month": month,
                                 "shortwave_MJ_m2_month": month * 10})
        return path

    def test_nasa_power_sums_exactly_twelve_2024_months(self):
        observations = build_nasa_power_observations(
            self.write_climate(), asset_id="nasa-climate", year=2024, region_code="110108",
        )
        by_metric = {item.metric: item for item in observations}
        self.assertEqual(by_metric["precipitation"].value, 78.0)
        self.assertEqual(by_metric["precipitation"].unit, "mm/a")
        self.assertEqual(by_metric["temperature"].value, 6.5)
        self.assertEqual(by_metric["shortwave_radiation"].value, 780.0)
        self.assertEqual({item.evidence_class for item in observations}, {"model_estimate"})

        with self.assertRaisesRegex(ValueError, "incomplete_2024_months"):
            build_nasa_power_observations(self.write_climate(11), asset_id="nasa-climate")

    def test_modis_keeps_npp_identity_and_et_uses_only_46_period_pixels(self):
        npp = self.write_raster("npp.tif", [[1, 2], [np.nan, 3]])
        npp_qc = self.write_raster("npp-qc.tif", [[10, 20], [30, 40]], dtype="uint8", nodata=255)
        et = self.write_raster("et.tif", [[100, 200], [300, 400]])
        periods = self.write_raster("periods.tif", [[46, 46], [45, 46]], dtype="uint8", nodata=0)

        observations = build_modis_observations(
            npp, npp_qc, et, periods,
            asset_ids={"npp": "npp", "npp_qc": "npp-qc", "et": "et", "et_periods": "et-periods"},
            year=2024, region_code="110108",
        )
        by_metric = {item.metric: item for item in observations}
        self.assertEqual(set(by_metric), {"npp", "actual_et"})
        self.assertNotIn("nep", by_metric)
        self.assertEqual(by_metric["npp"].value, 2.0)
        self.assertAlmostEqual(by_metric["actual_et"].value, 700 / 3)
        self.assertEqual(by_metric["actual_et"].uncertainty["complete_pixel_count"], 3)
        self.assertEqual({item.evidence_class for item in observations}, {"public_calculation"})

        with self.assertRaisesRegex(ValueError, "missing_npp_qc"):
            build_modis_observations(npp, self.root / "missing.tif", et, periods, asset_ids={"npp": "npp"})

    def test_dem_overlap_is_mosaicked_once_before_mean_elevation(self):
        west = self.write_raster("west.tif", np.full((2, 4), 10), transform=from_origin(0, 20, 10, 10))
        east = self.write_raster("east.tif", np.full((2, 4), 20), transform=from_origin(30, 20, 10, 10))

        observations = build_terrain_observations(
            [west, east], asset_ids=["dem-west", "dem-east"], year=2024, region_code="110108",
        )
        by_metric = {item.metric: item for item in observations}
        self.assertAlmostEqual(by_metric["elevation_mean"].value, 100 / 7)
        self.assertEqual(by_metric["elevation_mean"].uncertainty["unique_pixel_count"], 14)
        self.assertEqual(by_metric["slope_mean"].unit, "degree")

    def test_cover_areas_sum_to_valid_mask_within_one_pixel(self):
        cover = self.write_raster("cover.tif", [[10, 10, 50], [10, 80, 0]], dtype="uint8", nodata=0)

        observations = build_cover_observations(
            cover, asset_id="worldcover", year=2024, region_code="110108",
        )

        self.assertEqual([item.spatial_grain for item in observations], [
            "worldcover_class_10", "worldcover_class_50", "worldcover_class_80",
        ])
        self.assertEqual([item.value for item in observations], [0.03, 0.01, 0.01])
        self.assertAlmostEqual(sum(item.value for item in observations), 5 * 0.01, delta=0.01)
        self.assertEqual({item.evidence_class for item in observations}, {"model_estimate"})

    def test_wrong_year_missing_sources_and_nonfinite_rasters_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported_year"):
            build_nasa_power_observations(self.write_climate(), asset_id="nasa", year=2025)
        with self.assertRaisesRegex(ValueError, "missing_source_asset"):
            build_cover_observations(self.root / "missing.tif", asset_id="worldcover")
        invalid = self.write_raster("invalid.tif", [[np.nan, np.nan], [np.nan, np.nan]])
        with self.assertRaisesRegex(ValueError, "no_finite_raster_values"):
            build_cover_observations(invalid, asset_id="worldcover")

    def test_observations_cli_builds_one_reusable_manifest(self):
        derived = self.root / "derived"; public = self.root / "raw" / "public"
        derived.mkdir(); public.mkdir(parents=True)
        self.write_climate().replace(derived / "nasa_power_monthly_point.csv")
        self.write_raster("derived/npp_2024_kgC_m2.tif", [[1, 2], [2, 3]])
        self.write_raster("derived/npp_2024_qc.tif", [[10, 20], [30, 40]], dtype="uint8", nodata=255)
        self.write_raster("derived/et_2024_mm.tif", [[100, 200], [300, 400]])
        self.write_raster("derived/et_2024_valid_period_count.tif", [[46, 46], [46, 46]], dtype="uint8", nodata=0)
        self.write_raster("raw/public/dem-west.tif", np.full((2, 2), 10), transform=from_origin(0, 20, 10, 10))
        self.write_raster("raw/public/dem-east.tif", np.full((2, 2), 20), transform=from_origin(20, 20, 10, 10))
        self.write_raster("raw/public/worldcover.tif", [[10, 50], [80, 10]], dtype="uint8", nodata=0)
        output = self.root / "observations.json"

        completed = subprocess.run([
            sys.executable, "scripts/build_smart_data.py", "observations", "--data-root", str(self.root),
            "--output", str(output),
        ], cwd=Path(__file__).parents[1], capture_output=True, text=True)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["observation_count"], 10)
        observations = json.loads(output.read_text())
        self.assertIn("precipitation", {item["metric"] for item in observations})
        self.assertIn("actual_et", {item["metric"] for item in observations})
        self.assertIn("slope_mean", {item["metric"] for item in observations})

        loaded = load_observation_manifest(output)
        self.assertEqual(len(loaded), 10)
        self.assertEqual(loaded[0].year, 2024)


if __name__ == "__main__":
    unittest.main()
