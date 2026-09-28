import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from gep.smart_data import (
    AssetRecord,
    CalculationPlan,
    CalculationResult,
    ObservationRecord,
    SmartDataConflictError,
)
from gep.task_service import GepStore


def asset_payload(asset_id="nasa-power-2024", sha256="a" * 64):
    return {
        "asset_id": asset_id,
        "asset_version": "v1",
        "asset_type": "climate",
        "title": "NASA POWER monthly point",
        "publisher": "NASA",
        "source_url": "https://power.larc.nasa.gov/",
        "license_or_access": "public",
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "region_code": "110108",
        "bbox": [116.23, 40.03, 116.23, 40.03],
        "crs": "EPSG:4326",
        "local_path": "data/derived/nasa_power_monthly_point.csv",
        "sha256": sha256,
        "quality_status": "proxy",
        "quality": {"limitation": "single coarse grid point"},
    }


def observation_payload(observation_id="precip-2024", asset_ids=None):
    return {
        "observation_id": observation_id,
        "metric": "precipitation",
        "value": 855.17,
        "unit": "mm/a",
        "region_code": "110108",
        "year": 2024,
        "spatial_grain": "district_proxy",
        "method_id": "nasa_power.monthly_sum",
        "method_version": "v1",
        "input_asset_ids": asset_ids or ["nasa-power-2024"],
        "confidence": 0.65,
        "uncertainty": {"reason": "single point"},
        "evidence_class": "model_estimate",
    }


class SmartDataStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "tasks.sqlite3"
        self.store = GepStore(self.database)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_asset_rejects_non_sha256_and_non_https_remote_source(self):
        with self.assertRaisesRegex(ValueError, "64-character SHA-256"):
            AssetRecord.from_dict(asset_payload(sha256="not-a-hash"))

        insecure = asset_payload()
        insecure["source_url"] = "http://power.larc.nasa.gov/data"
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            AssetRecord.from_dict(insecure)

    def test_observation_requires_finite_value_matching_year_region_and_unit(self):
        self.store.smart_data.register_asset(AssetRecord.from_dict(asset_payload()))
        invalid = observation_payload()
        invalid["value"] = math.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            ObservationRecord.from_dict(invalid)

        invalid = observation_payload()
        invalid["unit"] = ""
        with self.assertRaisesRegex(ValueError, "unit"):
            ObservationRecord.from_dict(invalid)

        observation = ObservationRecord.from_dict(observation_payload())
        self.store.smart_data.register_observation(observation)
        self.assertEqual(
            [item["observation_id"] for item in self.store.smart_data.find_observations(
                metric="precipitation", year=2024, region_code="110108", unit="mm/a"
            )],
            ["precip-2024"],
        )
        self.assertEqual(self.store.smart_data.find_observations(
            metric="precipitation", year=2025, region_code="110108", unit="mm/a"
        ), [])
        self.assertEqual(self.store.smart_data.find_observations(
            metric="precipitation", year=2024, region_code="110105", unit="mm/a"
        ), [])

    def test_registering_same_version_is_idempotent_but_changed_hash_conflicts(self):
        asset = AssetRecord.from_dict(asset_payload())
        first = self.store.smart_data.register_asset(asset)
        repeated = self.store.smart_data.register_asset(asset)
        self.assertEqual(repeated, first)
        self.assertEqual(len(self.store.smart_data.list_assets()), 1)

        changed = AssetRecord.from_dict(asset_payload(sha256="b" * 64))
        with self.assertRaisesRegex(SmartDataConflictError, "asset version is immutable"):
            self.store.smart_data.register_asset(changed)

    def test_old_database_migrates_without_losing_tasks(self):
        self.store.close()
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP TABLE tasks")
            connection.execute(
                "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, region_code TEXT NOT NULL, year INTEGER NOT NULL, "
                "boundary_version TEXT NOT NULL, standard_version TEXT NOT NULL, data_version TEXT NOT NULL, created_utc TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?,?)",
                ("legacy-task", "110108", 2024, "legacy-boundary", "GB/T 46869-2025", "reference-2024-v0.1", "2024-01-01T00:00:00+00:00"),
            )
        self.store = GepStore(self.database)

        task = self.store.connection.execute("SELECT task_id,graph_version FROM tasks").fetchone()
        smart_tables = {row[0] for row in self.store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertEqual(dict(task), {"task_id": "legacy-task", "graph_version": 1})
        self.assertTrue({"data_assets", "derived_observations", "calculation_plans", "calculation_runs"} <= smart_tables)

    def test_calculation_chain_preserves_asset_observation_plan_and_run_lineage(self):
        task = self.store.create_task(
            "110108", 2024, "demo-boundary", "GB/T 46869-2025", "smart-data-2024-v1"
        )
        node = self.store.node(task["task_id"], "R1.precipitation")
        asset = AssetRecord.from_dict(asset_payload())
        observation = ObservationRecord.from_dict(observation_payload())
        self.store.smart_data.register_asset(asset)
        self.store.smart_data.register_observation(observation)
        plan = CalculationPlan.from_dict({
            "plan_id": "plan-r1-precip",
            "task_id": task["task_id"],
            "node_id": node["node_id"],
            "target_metric": "precipitation",
            "method_id": "R1.precipitation.demo",
            "method_version": "v1",
            "input_bindings": {"monthly_precipitation": observation.observation_id},
            "operations": [{"op": "identity", "input": "monthly_precipitation"}],
            "planner": "deterministic",
            "planner_model": "none",
            "explanation": "Use the admitted 2024 annual precipitation observation.",
            "schema_version": "1",
            "status": "ready",
        })
        result = CalculationResult.from_dict({
            "calculation_run_id": "run-r1-precip",
            "plan_id": plan.plan_id,
            "code_version": "test-code-v1",
            "input_manifest_sha256": "c" * 64,
            "parameter_manifest_sha256": "d" * 64,
            "result": {"value": 855.17, "unit": "mm/a"},
            "result_sha256": "e" * 64,
            "quality": {"status": "proxy"},
            "status": "succeeded",
            "error_code": None,
        })
        self.store.smart_data.register_plan(plan)
        self.store.smart_data.register_run(result)

        chain = self.store.smart_data.calculation_chain(node["node_id"])
        self.assertEqual(chain["plan"]["plan_id"], "plan-r1-precip")
        self.assertEqual(chain["observations"][0]["observation_id"], "precip-2024")
        self.assertEqual(chain["assets"][0]["asset_id"], "nasa-power-2024")
        self.assertEqual(chain["run"]["calculation_run_id"], "run-r1-precip")
        self.assertEqual(chain["run"]["result"], {"value": 855.17, "unit": "mm/a"})


if __name__ == "__main__":
    unittest.main()
