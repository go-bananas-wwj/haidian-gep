import tempfile
import unittest
from pathlib import Path

from gep.smart_data import AssetRecord, ObservationRecord
from gep.smart_data.workflow import SmartDataWorkflow
from gep.task_service import GepStore


class SmartDataWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = GepStore(Path(self.directory.name) / "smart.sqlite3")
        self.store.smart_data.register_asset(AssetRecord.from_dict({
            "asset_id":"climate", "asset_version":"v1", "asset_type":"climate", "title":"climate",
            "publisher":"NASA", "source_url":"https://example.test/climate", "license_or_access":"public",
            "period_start":"2024-01-01", "period_end":"2024-12-31", "region_code":"110108",
            "bbox":None, "crs":None, "local_path":None, "sha256":"a"*64, "quality_status":"proxy", "quality":{},
        }))
        self.store.smart_data.register_observation(ObservationRecord.from_dict({
            "observation_id":"precip-2024", "metric":"precipitation", "value":855.17, "unit":"mm/a",
            "region_code":"110108", "year":2024, "spatial_grain":"proxy", "method_id":"monthly_sum",
            "method_version":"v1", "input_asset_ids":["climate"], "confidence":.65,
            "uncertainty":{"limitation":"single point"}, "evidence_class":"model_estimate",
        }))

    def tearDown(self):
        self.store.close(); self.directory.cleanup()

    def test_workflow_reuses_observation_as_auto_demo_candidate(self):
        result = SmartDataWorkflow(self.store.smart_data).run({
            "task_id":"task", "node_id":"node", "node_key":"R1.precipitation", "node_label":"precipitation",
            "node_kind":"input", "indicator_id":"R1", "region_code":"110108", "year":2024,
            "data_version":"smart-data-2024-v1",
        })
        self.assertEqual(result["value"], 855.17)
        self.assertEqual(result["unit"], "mm/a")
        self.assertEqual(result["result_class"], "model_estimate")
        self.assertTrue(result["auto_adopt"])
        self.assertEqual(result["evidence"]["source_id"], "precip-2024")

    def test_workflow_uses_explicit_safe_proxy_aliases(self):
        self.store.smart_data.register_observation(ObservationRecord.from_dict({
            "observation_id":"npp-2024","metric":"npp","value":.38,"unit":"kgC/m2/a","region_code":"110108",
            "year":2024,"spatial_grain":"district","method_id":"modis.npp","method_version":"v1",
            "input_asset_ids":["climate"],"confidence":.75,"uncertainty":{"not_nep":True},"evidence_class":"public_calculation"}))
        result=SmartDataWorkflow(self.store.smart_data).run({"data_version":"smart-data-2024-v1","node_label":"npp_or_nep",
            "node_key":"R6.npp_or_nep","node_kind":"input","indicator_id":"R6","year":2024,"region_code":"110108"})
        self.assertEqual(result["value"],.38)
        self.assertEqual(result["unit"],"kgC/m2/a")
        self.assertEqual(result["result_class"],"public_calculation")
        self.assertIn("代理",result["explanation"])

    def test_smart_task_schedules_only_inputs_and_indicators_get_progress(self):
        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "smart.sqlite3", auto_enqueue_on_create=True, smart_data_enabled=True)
        task = self.store.create_task("110108", 2024, "demo", "GB/T 46869-2025", "smart-data-2024-v1")
        jobs = self.store.connection.execute("SELECT node_id FROM supplement_jobs WHERE task_id=?", (task["task_id"],)).fetchall()
        kinds = {self.store._node_by_id(row["node_id"])["kind"] for row in jobs}
        progress = self.store.indicator_progress(task["task_id"])
        self.assertEqual(kinds, {"input"})
        self.assertEqual(len(progress), 22)
        self.assertTrue(all(item["total"] > 0 for item in progress.values()))
        self.assertNotIn("research_complete", {item["status"] for item in progress.values()})

    def test_missing_records_are_consolidated_as_department_or_decision_work(self):
        workflow = SmartDataWorkflow(self.store.smart_data)
        department = workflow.run({"data_version":"smart-data-2024-v1", "node_label":"visitor_count",
            "node_key":"C1.visitor_count", "node_kind":"input", "indicator_id":"C1", "year":2024, "region_code":"110108"})
        decision = workflow.run({"data_version":"smart-data-2024-v1", "node_label":"deduplication_choice",
            "node_key":"C2.deduplication_choice", "node_kind":"input", "indicator_id":"C2", "year":2024, "region_code":"110108"})
        self.assertEqual(department["reason_code"], "department_data_required")
        self.assertEqual(department["result_class"], "needs_department_data")
        self.assertEqual(decision["reason_code"], "business_decision_required")
        self.assertEqual(decision["result_class"], "needs_business_decision")

    def test_r4_inland_evidence_becomes_a_not_applicable_demo_candidate(self):
        result = SmartDataWorkflow(self.store.smart_data).run({
            "data_version":"smart-data-2024-v1", "node_label":"inland_boundary_evidence",
            "node_key":"R4.inland_boundary_evidence", "node_kind":"input", "indicator_id":"R4",
            "year":2024, "region_code":"110108",
        })
        self.assertEqual(result["value"], 1)
        self.assertEqual(result["unit"], "boolean")
        self.assertEqual(result["result_class"], "not_applicable_candidate")
        self.assertTrue(result["auto_adopt"])

    def test_smart_candidate_persists_demo_class_and_request_is_idempotent(self):
        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "persist.sqlite3", smart_data_enabled=True)
        self.store.smart_data.register_asset(AssetRecord.from_dict({
            "asset_id":"climate", "asset_version":"v1", "asset_type":"climate", "title":"climate",
            "publisher":"NASA", "source_url":"https://example.test/climate", "license_or_access":"public",
            "period_start":"2024-01-01", "period_end":"2024-12-31", "region_code":"110108",
            "bbox":None, "crs":None, "local_path":None, "sha256":"a"*64, "quality_status":"proxy", "quality":{},
        }))
        self.store.smart_data.register_observation(ObservationRecord.from_dict({
            "observation_id":"precip-2024", "metric":"precipitation", "value":855.17, "unit":"mm/a",
            "region_code":"110108", "year":2024, "spatial_grain":"proxy", "method_id":"monthly_sum",
            "method_version":"v1", "input_asset_ids":["climate"], "confidence":.65,
            "uncertainty":{}, "evidence_class":"model_estimate",
        }))
        task = self.store.create_task("110108", 2024, "demo", "GB/T 46869-2025", "smart-data-2024-v1")
        node = self.store.node(task["task_id"], "R1.precipitation")
        first = self.store.request_supplement(task["task_id"], node["node_id"], "same-key")
        repeated = self.store.request_supplement(task["task_id"], node["node_id"], "same-key")
        self.store.process_next_supplement()
        current = self.store.node(task["task_id"], "R1.precipitation")
        self.assertEqual(repeated["job_id"], first["job_id"])
        self.assertEqual(current["value"], 855.17)
        self.assertEqual(current["evidence"]["current"]["result_class"], "model_estimate")
        self.assertTrue(current["evidence"]["current"]["demo_auto_adopt"])
        chain=self.store.calculation_chain(node["node_id"])
        self.assertEqual(chain["plan"]["method_id"],"monthly_sum")
        self.assertEqual(chain["observations"][0]["observation_id"],"precip-2024")
        self.assertEqual(chain["run"]["result"],{"value":855.17,"unit":"mm/a"})

    def test_feature_flag_off_preserves_legacy_indicator_scheduling(self):
        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "legacy.sqlite3", auto_enqueue_on_create=True, smart_data_enabled=False)
        task = self.store.create_task("110108", 2024, "demo", "GB/T 46869-2025", "reference-2024-v0.1")
        jobs = self.store.connection.execute("SELECT node_id FROM supplement_jobs WHERE task_id=?", (task["task_id"],)).fetchall()
        kinds = {self.store._node_by_id(row["node_id"])["kind"] for row in jobs}
        self.assertEqual(kinds, {"indicator", "input"})


if __name__ == "__main__": unittest.main()
