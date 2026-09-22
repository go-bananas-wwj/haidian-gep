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

    def test_task_expands_method_cards_into_required_input_nodes_without_inventing_values(self):
        """Break caught: the graph could show 22 headings while omitting their actual data requirements."""
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        graph = self.store.graph(task["task_id"])
        nodes = {node["node_key"]: node for node in graph["nodes"]}

        self.assertEqual(nodes["P1"]["evidence"]["method_id"], "material.residual_value.v1")
        self.assertEqual(nodes["R6"]["evidence"]["standard_clause"], "A.34--A.54")
        self.assertEqual(nodes["P1.maize.producer_price"]["value"], None)
        self.assertEqual(nodes["P1.maize.producer_price"]["acquisition_status"], "awaiting_agent")
        self.assertEqual(nodes["R4.inland_boundary_evidence"]["parent_key"], "R4")
        self.assertEqual(nodes["C2.hourly_wage"]["parent_key"], "C2")

    def test_snapshot_is_blocked_by_unreviewed_and_missing_inputs(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")

        with self.assertRaises(SnapshotBlocked) as raised:
            self.store.create_snapshot(task["task_id"])

        blocking = raised.exception.blocking
        self.assertIn("P1.maize.quantity", blocking)
        self.assertIn("R4", blocking)
        self.assertGreaterEqual(len(blocking), 22)

    def test_snapshot_stays_blocked_when_data_version_has_not_passed_admission(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        self.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.store.connection.commit()

        with self.assertRaises(SnapshotBlocked) as raised:
            self.store.create_snapshot(task["task_id"])

        self.assertIn("data_version:reference-2024-v0.1", raised.exception.blocking)

    def test_admitted_data_version_allows_a_complete_reviewed_graph_to_freeze(self):
        self.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.store.connection.commit()

        snapshot = self.store.create_snapshot(task["task_id"])

        self.assertTrue(snapshot["snapshot_id"])

    def test_run_rejects_an_unknown_snapshot(self):
        """Break caught: a caller could launch a calculation without frozen reviewed inputs."""
        with self.assertRaises(KeyError):
            self.store.create_run("missing-snapshot", "request-1")

    def test_not_applicable_indicator_does_not_require_its_valuation_inputs_in_snapshot(self):
        """Break caught: an approved inland non-applicability conclusion still demanded impossible coastal values."""
        self.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.store.connection.execute(
            "UPDATE nodes SET value_json=NULL, review_status='unsubmitted', applicability_status='pending' WHERE task_id=? AND node_key='R4.inland_boundary_evidence'",
            (task["task_id"],),
        )
        self.store.connection.execute(
            "UPDATE nodes SET value_json=NULL, review_status='approved', applicability_status='not_applicable' WHERE task_id=? AND node_key='R4'",
            (task["task_id"],),
        )
        self.store.connection.commit()

        snapshot = self.store.create_snapshot(task["task_id"])

        self.assertTrue(snapshot["snapshot_id"])

    def test_run_request_is_idempotent_for_a_frozen_snapshot(self):
        """Break caught: reconnecting clients could create duplicate calculation runs."""
        self.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.store.connection.commit()
        snapshot = self.store.create_snapshot(task["task_id"])

        first = self.store.create_run(snapshot["snapshot_id"], "run-request-1")
        retried = self.store.create_run(snapshot["snapshot_id"], "run-request-1")
        events = [event for event in self.store.events(task["task_id"]) if event["type"] == "run.blocked"]

        self.assertEqual(first["run_id"], retried["run_id"])
        self.assertEqual(first["status"], "blocked")
        self.assertEqual(len(events), 1)

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
            {"source_id": "corrected-ledger", "source_type": "manual_correction", "locator": "ledger row 8"},
        )
        events = self.store.events(task["task_id"], after=0)

        self.assertEqual(corrected["review_status"], "pending_review")
        self.assertEqual(corrected["version"], 2)
        self.assertTrue(any(event["type"] == "node.revised" for event in events))

    def test_revision_requires_new_evidence_and_preserves_observed_source(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        maize = self.store.node(task["task_id"], "P1.maize.quantity")

        with self.assertRaises(ValueError):
            self.store.revise_node(maize["node_id"], 1, 2936.0, "t/a", "operator", "correction", {})
        corrected = self.store.revise_node(
            maize["node_id"], 1, 2936.0, "t/a", "operator", "correction",
            {"source_id": "corrected-ledger", "source_type": "manual_correction", "locator": "ledger row 8"},
        )

        self.assertEqual(corrected["evidence"]["original"]["table_id"], "5-11")
        self.assertEqual(corrected["evidence"]["current"]["source_id"], "corrected-ledger")
        event = next(event for event in self.store.events(task["task_id"]) if event["type"] == "node.revised")
        self.assertEqual(event["payload"]["previous_value"], 2935.1)
        self.assertEqual(event["payload"]["value"], 2936.0)

    def test_second_database_connection_cannot_overwrite_same_node_version(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        maize = self.store.node(task["task_id"], "P1.maize.quantity")
        other = GepStore(Path(self.directory.name) / "tasks.sqlite3")
        evidence = {"source_id": "ledger", "source_type": "manual_correction", "locator": "row 8"}
        try:
            self.store.revise_node(maize["node_id"], 1, 2936.0, "t/a", "first", "first correction", evidence)
            with self.assertRaises(ConflictError):
                other.revise_node(maize["node_id"], 1, 2937.0, "t/a", "second", "second correction", evidence)
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
