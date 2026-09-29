import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


class AgentStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "tasks.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _old_database(self):
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE tasks (task_id TEXT PRIMARY KEY, region_code TEXT NOT NULL, year INTEGER NOT NULL);
            CREATE TABLE nodes (node_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, node_key TEXT NOT NULL);
            INSERT INTO tasks VALUES ('task-1','110108',2024);
            INSERT INTO nodes VALUES ('node-1','task-1','R1.ecosystem_area');
            """
        )
        connection.commit()
        connection.close()

    @staticmethod
    def _run():
        return {
            "run_id": "run-1", "task_id": "task-1", "node_id": "node-1",
            "status": "running", "model": "deepseek-flash", "created_utc": "2026-09-29T00:00:00Z",
        }

    @staticmethod
    def _evidence():
        return {
            "evidence_id": "evidence-1", "run_id": "run-1", "node_id": "node-1",
            "source_id": "source-1", "source_type": "official_web", "risk_tier": "B",
            "locator": "表 2", "content_sha256": "a" * 64,
            "created_utc": "2026-09-29T00:01:00Z",
        }

    def test_existing_task_database_is_migrated_without_data_loss(self):
        """Break caught: adding agent tables could recreate or erase an existing task database."""
        from gep.agent.store import AgentStore

        self._old_database()
        store = AgentStore(self.database)
        try:
            task = store.connection.execute("SELECT * FROM tasks WHERE task_id='task-1'").fetchone()
            self.assertEqual(dict(task), {"task_id": "task-1", "region_code": "110108", "year": 2024})
            tables = {row[0] for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"agent_runs", "tool_runs", "evidence_items", "calculation_steps", "agent_decisions"} <= tables)
        finally:
            store.close()

    def test_same_run_and_evidence_are_idempotent(self):
        """Break caught: retrying the same supplement job could duplicate audit records."""
        from gep.agent.store import AgentStore

        self._old_database()
        store = AgentStore(self.database)
        try:
            first_run = store.start_run(self._run())
            second_run = store.start_run(self._run())
            first_evidence = store.record_evidence(self._evidence())
            second_evidence = store.record_evidence(self._evidence())
            self.assertEqual(first_run, second_run)
            self.assertEqual(first_evidence, second_evidence)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0], 1)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0], 1)
            payload = json.loads(store.connection.execute("SELECT payload_json FROM evidence_items").fetchone()[0])
            self.assertEqual(payload["source_id"], "source-1")
        finally:
            store.close()

    def test_different_payload_for_same_identity_is_rejected(self):
        """Break caught: a retry could silently overwrite provenance under the same evidence ID."""
        from gep.agent.store import AgentStore, AgentStoreConflictError

        self._old_database()
        store = AgentStore(self.database)
        try:
            store.start_run(self._run())
            store.record_evidence(self._evidence())
            changed = {**self._evidence(), "locator": "表 9"}
            with self.assertRaisesRegex(AgentStoreConflictError, "immutable"):
                store.record_evidence(changed)
            stored = store.connection.execute("SELECT payload_json FROM evidence_items").fetchone()[0]
            self.assertEqual(json.loads(stored)["locator"], "表 2")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
