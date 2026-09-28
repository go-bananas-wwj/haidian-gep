import tempfile
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from gep.task_service import GepStore


class SupplementWorkerTests(unittest.TestCase):
    def test_worker_loads_the_selected_runtime_provider(self):
        """Break caught: the worker could ignore SUPPLEMENT_PROVIDER and always use Dify."""
        from gep.worker import SupplementWorker

        sentinel = object()
        worker = SupplementWorker("unused.sqlite3")
        with patch("gep.worker.workflow_from_environment", return_value=sentinel) as factory, \
                patch("gep.worker.GepStore") as store_class:
            store_class.return_value.process_next_supplement.return_value = None
            worker.run_once()

        factory.assert_called_once_with()
        store_class.assert_called_once_with(worker.database_path, supplement_workflow=sentinel)

    def test_worker_claims_a_persisted_queue_after_the_request_connection_is_closed(self):
        """Break caught: queued work could disappear when the API process or browser disconnects."""
        class Workflow:
            def run(self, _work_order):
                return {
                    "value": 2100, "unit": "yuan/t", "explanation": "已从归档台账提取。",
                    "evidence": {"source_id": "price-register-2024", "source_type": "official_register",
                                 "locator": "row=2024", "source_sha256": "a" * 64,
                                 "license_or_access": "internal-review-required", "tool_run_id": "dify-run-001",
                                 "extracted_fragment": "玉米，2100 元/吨"},
                }

        from gep.worker import SupplementWorker

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "tasks.sqlite3"
            request_store = GepStore(database)
            try:
                task = request_store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
                node = request_store.node(task["task_id"], "P1.maize.producer_price")
                queued = request_store.request_supplement(task["task_id"], node["node_id"], "price-request-1")
                self.assertEqual(queued["status"], "queued")
            finally:
                request_store.close()

            result = SupplementWorker(database, supplement_workflow=Workflow()).run_once()

            verification_store = GepStore(database)
            try:
                current = verification_store.node(task["task_id"], "P1.maize.producer_price")
                self.assertEqual(result["status"], "completed_pending_review")
                self.assertEqual(current["value"], 2100)
                self.assertEqual(current["review_status"], "pending_review")
            finally:
                verification_store.close()

    def test_worker_cli_processes_one_persisted_job_without_an_http_server(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "tasks.sqlite3"
            store = GepStore(database)
            try:
                task = store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
                node = store.node(task["task_id"], "P1.maize.producer_price")
                store.request_supplement(task["task_id"], node["node_id"], "price-request-1")
            finally:
                store.close()

            completed = subprocess.run(
                [sys.executable, "-m", "gep", "worker", "--database", str(database), "--once"],
                cwd=Path(__file__).parents[1], capture_output=True, text=True, check=True,
            )

            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("not configured", result["reason"])

    def test_worker_recovers_an_interrupted_running_job(self):
        """Break caught: a worker crash could leave a supplement permanently running."""
        class Workflow:
            def run(self, _work_order):
                return {
                    "value": 2100, "unit": "yuan/t", "explanation": "已从归档台账提取。",
                    "evidence": {"source_id": "price-register-2024", "source_type": "official_register",
                                 "locator": "row=2024", "source_sha256": "b" * 64,
                                 "license_or_access": "internal-review-required", "tool_run_id": "dify-run-002",
                                 "extracted_fragment": "玉米，2100 元/吨"},
                }

        from gep.worker import SupplementWorker

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "tasks.sqlite3"
            store = GepStore(database)
            try:
                task = store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
                node = store.node(task["task_id"], "P1.maize.producer_price")
                queued = store.request_supplement(task["task_id"], node["node_id"], "recover-request-1")
                store.connection.execute(
                    "UPDATE supplement_jobs SET status='running',updated_utc='2000-01-01T00:00:00+00:00' WHERE job_id=?",
                    (queued["job_id"],),
                )
                store.connection.commit()
            finally:
                store.close()

            result = SupplementWorker(database, supplement_workflow=Workflow()).run_once()

            verification_store = GepStore(database)
            try:
                job = verification_store.supplement_job(queued["job_id"])
                self.assertEqual(result["status"], "completed_pending_review")
                self.assertEqual(job["attempt_count"], 1)
                self.assertIn("supplement.requeued", [event["type"] for event in verification_store.events(task["task_id"])])
            finally:
                verification_store.close()
