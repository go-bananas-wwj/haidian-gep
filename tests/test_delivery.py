import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gep.delivery import export_incomplete_task_delivery
from gep.task_service import GepStore


class IncompleteTaskDeliveryTests(unittest.TestCase):
    """Break caught: a blocked task could be exported without its 22-item evidence or be mislabeled as a formal total."""

    def test_export_keeps_formal_gep_null_and_hashes_every_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GepStore(Path(directory) / "tasks.sqlite3")
            try:
                task = store.create_task("110108", 2024, "pending-confirmation", "GB/T 46869-2025", "reference-2024-v0.1")
                output = Path(directory) / "delivery"

                manifest = export_incomplete_task_delivery(store, task["task_id"], output)

                self.assertEqual(manifest["formal_gep_value"], None)
                self.assertEqual(manifest["appendix_e_row_count"], 22)
                appendix = json.loads((output / "appendix_e.json").read_text(encoding="utf-8"))
                self.assertEqual(appendix["formal_gep_value"], None)
                self.assertIn("incomplete", (output / "README.md").read_text(encoding="utf-8"))
                checksums = (output / "checksums.sha256").read_text(encoding="utf-8").splitlines()
                for line in checksums:
                    digest, filename = line.split("  ")
                    self.assertEqual(digest, hashlib.sha256((output / filename).read_bytes()).hexdigest())
            finally:
                store.close()

    def test_export_refuses_to_overwrite_an_existing_delivery_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GepStore(Path(directory) / "tasks.sqlite3")
            try:
                task = store.create_task("110108", 2024, "pending-confirmation", "GB/T 46869-2025", "reference-2024-v0.1")
                output = Path(directory) / "delivery"
                export_incomplete_task_delivery(store, task["task_id"], output)

                with self.assertRaises(FileExistsError):
                    export_incomplete_task_delivery(store, task["task_id"], output)
            finally:
                store.close()

    def test_export_includes_agent_candidate_records_with_evidence_and_explanation(self):
        """Break caught: a delivery could expose a candidate value but lose its source and tool provenance."""
        class Workflow:
            def run(self, _work_order):
                return {
                    "value": 2100, "unit": "yuan/t", "explanation": "从价格表定位并提取。",
                    "evidence": {"source_id": "price-register-2024", "source_type": "official_register",
                                 "locator": "table=maize;row=2024", "source_sha256": "a" * 64,
                                 "license_or_access": "internal-review-required", "tool_run_id": "dify-run-001",
                                 "extracted_fragment": "玉米，2100 元/吨"},
                }

        with tempfile.TemporaryDirectory() as directory:
            store = GepStore(Path(directory) / "tasks.sqlite3", supplement_workflow=Workflow())
            try:
                task = store.create_task("110108", 2024, "pending-confirmation", "GB/T 46869-2025", "reference-2024-v0.1")
                node = store.node(task["task_id"], "P1.maize.producer_price")
                store.request_supplement(task["task_id"], node["node_id"], "price-request-1")
                output = Path(directory) / "delivery"

                manifest = export_incomplete_task_delivery(store, task["task_id"], output)

                records = [json.loads(line) for line in (output / "supplement_records.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["value"], 2100)
                self.assertEqual(records[0]["evidence"]["source_id"], "price-register-2024")
                self.assertEqual(records[0]["evidence"]["tool_run_id"], "dify-run-001")
                self.assertIn("supplement_records.jsonl", manifest["artifact_sha256"])
            finally:
                store.close()

    def test_cli_exports_a_new_truthful_delivery_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "tasks.sqlite3"
            store = GepStore(database)
            try:
                task = store.create_task("110108", 2024, "pending-confirmation", "GB/T 46869-2025", "reference-2024-v0.1")
            finally:
                store.close()
            output = Path(directory) / "cli-delivery"

            completed = subprocess.run(
                [sys.executable, "scripts/export_delivery.py", "--database", str(database), "--task", task["task_id"], "--out", str(output)],
                cwd=Path(__file__).parents[1], capture_output=True, text=True, check=True,
            )

            self.assertIn("formal_gep_value=null", completed.stdout)
            self.assertTrue((output / "checksums.sha256").is_file())


if __name__ == "__main__":
    unittest.main()
