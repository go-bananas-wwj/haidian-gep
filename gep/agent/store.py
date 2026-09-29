"""SQLite evidence ledger for auditable native-agent runs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


class AgentStoreConflictError(ValueError):
    """An immutable ledger identity was reused with different content."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, payload: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    identity = {key: payload.get(key) for key in keys}
    return f"{prefix}-{hashlib.sha256(_json(identity).encode()).hexdigest()[:24]}"


class AgentStore:
    def __init__(self, database_path: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(database_path, sqlite3.Connection)
        self.connection = (
            sqlite3.connect(database_path) if self._owns_connection else database_path
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, node_id TEXT NOT NULL,
                status TEXT NOT NULL, created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_runs (
                tool_run_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, node_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, tool_id TEXT NOT NULL, status TEXT NOT NULL,
                elapsed_ms INTEGER NOT NULL, created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence_items (
                evidence_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, node_id TEXT NOT NULL,
                source_id TEXT NOT NULL, risk_tier TEXT NOT NULL,
                created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calculation_steps (
                step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, node_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_decisions (
                decision_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, node_id TEXT NOT NULL,
                decision TEXT NOT NULL, created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                document_id TEXT PRIMARY KEY, title TEXT NOT NULL, publisher TEXT NOT NULL,
                source_url TEXT, license_or_access TEXT NOT NULL, locator TEXT NOT NULL,
                content_sha256 TEXT NOT NULL, region_code TEXT, year_start INTEGER, year_end INTEGER,
                review_state TEXT NOT NULL, created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, text TEXT NOT NULL, locator TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS agent_runs_node_created
                ON agent_runs(task_id,node_id,created_utc);
            CREATE INDEX IF NOT EXISTS tool_runs_run_sequence
                ON tool_runs(run_id,sequence);
            CREATE INDEX IF NOT EXISTS evidence_items_run_source
                ON evidence_items(run_id,source_id);
            CREATE INDEX IF NOT EXISTS calculation_steps_run_sequence
                ON calculation_steps(run_id,sequence);
            CREATE INDEX IF NOT EXISTS agent_decisions_run_created
                ON agent_decisions(run_id,created_utc);
            CREATE INDEX IF NOT EXISTS knowledge_documents_filters
                ON knowledge_documents(region_code,year_start,year_end,review_state);
            CREATE INDEX IF NOT EXISTS knowledge_chunks_document_sequence
                ON knowledge_chunks(document_id,sequence);
            """
        )
        self.connection.commit()

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def _insert_immutable(
        self,
        table: str,
        identity_field: str,
        payload: Mapping[str, Any],
        columns: tuple[str, ...],
    ) -> dict[str, Any]:
        normalized = dict(payload)
        encoded = _json(normalized)
        identity = str(normalized[identity_field])
        row = self.connection.execute(
            f"SELECT payload_json FROM {table} WHERE {identity_field}=?", (identity,)
        ).fetchone()
        if row is not None:
            if row["payload_json"] != encoded:
                raise AgentStoreConflictError(f"{table} identity is immutable")
            return json.loads(row["payload_json"])
        values = [normalized[column] for column in columns]
        placeholders = ",".join("?" for _ in range(len(columns) + 1))
        with self.connection:
            self.connection.execute(
                f"INSERT INTO {table} ({','.join(columns)},payload_json) VALUES ({placeholders})",
                (*values, encoded),
            )
        return normalized

    def start_run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(payload)
        item.setdefault("created_utc", _utcnow())
        item.setdefault("status", "running")
        item.setdefault("run_id", _stable_id("run", item, ("task_id", "node_id", "idempotency_key")))
        for key in ("task_id", "node_id"):
            if not str(item.get(key, "")).strip():
                raise ValueError(f"{key} is required")
        return self._insert_immutable(
            "agent_runs", "run_id", item,
            ("run_id", "task_id", "node_id", "status", "created_utc"),
        )

    def record_tool_run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(payload)
        item.setdefault("created_utc", _utcnow())
        item.setdefault("node_id", "")
        item.setdefault("status", "ok")
        item.setdefault("elapsed_ms", 0)
        item.setdefault("tool_run_id", _stable_id("tool", item, ("run_id", "sequence", "tool_id")))
        return self._insert_immutable(
            "tool_runs", "tool_run_id", item,
            ("tool_run_id", "run_id", "node_id", "sequence", "tool_id", "status", "elapsed_ms", "created_utc"),
        )

    def record_evidence(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(payload)
        item.setdefault("created_utc", _utcnow())
        item.setdefault("risk_tier", "unclassified")
        item.setdefault("evidence_id", _stable_id("evidence", item, ("run_id", "source_id", "locator", "content_sha256")))
        return self._insert_immutable(
            "evidence_items", "evidence_id", item,
            ("evidence_id", "run_id", "node_id", "source_id", "risk_tier", "created_utc"),
        )

    def record_calculation_step(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(payload)
        item.setdefault("created_utc", _utcnow())
        item.setdefault("step_id", _stable_id("step", item, ("run_id", "sequence")))
        return self._insert_immutable(
            "calculation_steps", "step_id", item,
            ("step_id", "run_id", "node_id", "sequence", "created_utc"),
        )

    def record_decision(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(payload)
        item.setdefault("created_utc", _utcnow())
        item.setdefault("decision_id", _stable_id("decision", item, ("run_id", "node_id", "decision")))
        return self._insert_immutable(
            "agent_decisions", "decision_id", item,
            ("decision_id", "run_id", "node_id", "decision", "created_utc"),
        )

    def latest_node_detail(self, task_id: str, node_id: str) -> dict[str, Any] | None:
        run_row = self.connection.execute(
            "SELECT * FROM agent_runs WHERE task_id=? AND node_id=? "
            "ORDER BY created_utc DESC,run_id DESC LIMIT 1",
            (task_id, node_id),
        ).fetchone()
        if run_row is None:
            return None
        run = json.loads(run_row["payload_json"])
        run_id = run_row["run_id"]

        def payloads(table: str, order: str) -> list[dict[str, Any]]:
            rows = self.connection.execute(
                f"SELECT payload_json FROM {table} WHERE run_id=? ORDER BY {order}", (run_id,)
            ).fetchall()
            return [json.loads(row["payload_json"]) for row in rows]

        return {
            "run": run,
            "tool_runs": payloads("tool_runs", "sequence,tool_run_id"),
            "evidence": payloads("evidence_items", "created_utc,evidence_id"),
            "calculation_steps": payloads("calculation_steps", "sequence,step_id"),
            "decisions": payloads("agent_decisions", "created_utc,decision_id"),
        }
