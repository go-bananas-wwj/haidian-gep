import tempfile
import unittest
from pathlib import Path

from gep.task_service import ConflictError, GepStore, SnapshotBlocked


class TaskServiceTests(unittest.TestCase):
    """Break caught: removing the formal-review gate could turn reference data into GEP."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = GepStore(Path(self.directory.name) / "tasks.sqlite3")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_new_task_creates_all_22_indicators_and_real_maize_evidence(self):
        task = self.store.create_task(
            region_code="110108",
            year=2024,
            boundary_version="pending-confirmation",
            standard_version="GB/T 46869-2025",
            data_version="reference-2024-v0.1",
        )

        graph = self.store.graph(task["task_id"])
        indicators = [node for node in graph["nodes"] if node["kind"] == "indicator"]
        maize = next(node for node in graph["nodes"] if node["node_key"] == "P1.maize.quantity")

        self.assertEqual(len(indicators), 22)
        self.assertEqual(maize["value"], 2935.1)
        self.assertEqual(maize["unit"], "t/a")
        self.assertEqual(maize["evidence"]["table_id"], "5-11")
        self.assertEqual(maize["evidence"]["printed_page"], 71)
        self.assertNotIn("synthetic", str(maize).lower())

    def test_snapshot_is_blocked_by_unreviewed_and_missing_inputs(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")

        with self.assertRaises(SnapshotBlocked) as raised:
            self.store.create_snapshot(task["task_id"])

        blocking = raised.exception.blocking
        self.assertIn("P1.maize.quantity", blocking)
        self.assertIn("R4", blocking)
        self.assertGreaterEqual(len(blocking), 22)

    def test_review_requires_current_node_version(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        maize = self.store.node(task["task_id"], "P1.maize.quantity")

        reviewed = self.store.review_node(maize["node_id"], maize["version"], "approved", "reviewer", "matches table")

        self.assertEqual(reviewed["review_status"], "approved")
        with self.assertRaises(ConflictError):
            self.store.review_node(maize["node_id"], maize["version"], "approved", "other", "stale")

    def test_correction_invalidates_only_edited_node_review_and_emits_event(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        maize = self.store.node(task["task_id"], "P1.maize.quantity")
        self.store.review_node(maize["node_id"], maize["version"], "approved", "reviewer", "verified")

        corrected = self.store.revise_node(
            maize["node_id"], maize["version"], 2936.0, "t/a", "operator", "corrected ledger",
        )
        events = self.store.events(task["task_id"], after=0)

        self.assertEqual(corrected["review_status"], "pending_review")
        self.assertEqual(corrected["version"], 2)
        self.assertTrue(any(event["type"] == "node.revised" for event in events))


if __name__ == "__main__":
    unittest.main()
