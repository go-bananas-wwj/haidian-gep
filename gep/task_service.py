"""Persistent, evidence-first task graph for the Haidian 2024 GEP demo.

This module intentionally does not estimate missing values.  It stores the
task graph and enforces that only reviewed, complete inputs may be frozen.
"""
from __future__ import annotations

import json
import hashlib
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INDICATORS = (
    ("P1", "农产品", "material"), ("P2", "林产品", "material"),
    ("P3", "牧产品", "material"), ("P4", "渔产品", "material"),
    ("P5", "淡水资源", "material"), ("P6", "生态能源", "material"),
    ("P7", "其他物质产品", "material"),
    ("R1", "水源涵养", "regulating"), ("R2", "土壤保持", "regulating"),
    ("R3", "防风固沙", "regulating"), ("R4", "海岸防护", "regulating"),
    ("R5", "洪水调蓄", "regulating"), ("R6", "固碳", "regulating"),
    ("R7", "氧气提供", "regulating"), ("R8", "空气净化", "regulating"),
    ("R9", "水净化", "regulating"), ("R10", "局部气候调节", "regulating"),
    ("R11", "噪声消减", "regulating"), ("R12", "作物授粉", "regulating"),
    ("C1", "旅游康养", "cultural"), ("C2", "休闲游憩", "cultural"),
    ("C3", "景观增值", "cultural"),
)


class ConflictError(ValueError):
    """The caller tried to review or revise an out-of-date node version."""


class SnapshotBlocked(ValueError):
    def __init__(self, blocking: list[str]):
        super().__init__("formal GEP snapshot is blocked by incomplete or unreviewed inputs")
        self.blocking = blocking


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GepStore:
    def __init__(self, database_path: str | Path):
        self.connection = sqlite3.connect(str(database_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, region_code TEXT NOT NULL, year INTEGER NOT NULL,
                boundary_version TEXT NOT NULL, standard_version TEXT NOT NULL,
                data_version TEXT NOT NULL, created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                node_key TEXT NOT NULL, parent_key TEXT, kind TEXT NOT NULL, label TEXT NOT NULL,
                category TEXT, required INTEGER NOT NULL DEFAULT 0, value_json TEXT,
                unit TEXT, evidence_json TEXT NOT NULL DEFAULT '{}', acquisition_status TEXT NOT NULL,
                review_status TEXT NOT NULL, applicability_status TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1, UNIQUE(task_id, node_key)
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                node_id TEXT, type TEXT NOT NULL, created_utc TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(node_id),
                version INTEGER NOT NULL, decision TEXT NOT NULL, reviewer TEXT NOT NULL,
                note TEXT NOT NULL, created_utc TEXT NOT NULL, UNIQUE(node_id, version)
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                graph_json TEXT NOT NULL, created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS supplement_jobs (
                job_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                node_id TEXT NOT NULL REFERENCES nodes(node_id), idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL, reason TEXT NOT NULL, created_utc TEXT NOT NULL,
                UNIQUE(task_id, node_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS data_admissions (
                data_version TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL,
                accepted INTEGER NOT NULL, registered_utc TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def register_data_admission(self, data_version: str, manifest_sha256: str, accepted: bool) -> None:
        """Persist one immutable data-version admission decision."""
        if not data_version.strip():
            raise ValueError("data version is required")
        if len(manifest_sha256) != 64 or any(character not in "0123456789abcdef" for character in manifest_sha256.lower()):
            raise ValueError("admission manifest must have a SHA-256 hash")
        existing = self.connection.execute(
            "SELECT manifest_sha256,accepted FROM data_admissions WHERE data_version=?", (data_version,)
        ).fetchone()
        if existing is not None:
            if existing["manifest_sha256"] != manifest_sha256 or bool(existing["accepted"]) != accepted:
                raise ConflictError("data admission is immutable; use a new data version")
            return
        with self.connection:
            self.connection.execute(
                "INSERT INTO data_admissions VALUES (?,?,?,?)",
                (data_version, manifest_sha256, int(accepted), _utc_now()),
            )

    def _event(self, task_id: str, node_id: str | None, event_type: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO events(task_id,node_id,type,created_utc,payload_json) VALUES (?,?,?,?,?)",
            (task_id, node_id, event_type, _utc_now(), json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )

    def create_task(
        self, region_code: str, year: int, boundary_version: str, standard_version: str, data_version: str,
    ) -> dict[str, str]:
        if region_code != "110108" or year != 2024:
            raise ValueError("this demo only accepts Haidian 110108 for year 2024")
        if not all(str(value).strip() for value in (boundary_version, standard_version, data_version)):
            raise ValueError("boundary, standard, and data versions are required")
        task_id = uuid.uuid4().hex
        self.connection.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?)",
            (task_id, region_code, year, boundary_version, standard_version, data_version, _utc_now()),
        )
        categories = (("material", "物质产品"), ("regulating", "调节服务"), ("cultural", "文化服务"))
        for key, label in categories:
            self._insert_node(task_id, key, None, "category", label, key, False, None, None, {}, "ready", "unsubmitted", "pending")
        for key, label, category in INDICATORS:
            self._insert_node(task_id, key, category, "indicator", label, category, True, None, None, {}, "awaiting_agent", "unsubmitted", "pending")
        self._insert_node(
            task_id, "P1.maize.quantity", "P1", "input", "玉米产量", "material", True, 2935.1, "t/a",
            {
                "source_id": "haidian_yearbook_2025", "source_file": "01_raw/statistics/yearbook_2025_bulletin_chapters_1_9.pdf",
                "table_id": "5-11", "printed_page": 71, "region_code": "110108", "year": 2024,
                "metric": "玉米产量", "source_type": "observed",
            },
            "acquired", "pending_review", "applicable",
        )
        self._event(task_id, None, "task.created", {"indicator_count": len(INDICATORS), "data_version": data_version})
        self.connection.commit()
        return {"task_id": task_id}

    def _insert_node(
        self, task_id: str, node_key: str, parent_key: str | None, kind: str, label: str, category: str,
        required: bool, value: Any, unit: str | None, evidence: dict[str, Any], acquisition_status: str,
        review_status: str, applicability_status: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (uuid.uuid4().hex, task_id, node_key, parent_key, kind, label, category, int(required),
             json.dumps(value, ensure_ascii=False) if value is not None else None, unit,
             json.dumps(evidence, ensure_ascii=False, sort_keys=True), acquisition_status, review_status,
             applicability_status),
        )

    @staticmethod
    def _node_dict(row: sqlite3.Row) -> dict[str, Any]:
        node = dict(row)
        node["required"] = bool(node["required"])
        node["value"] = json.loads(node.pop("value_json")) if node["value_json"] is not None else None
        node.pop("value_json", None)
        node["evidence"] = json.loads(node.pop("evidence_json"))
        node.pop("evidence_json", None)
        return node

    def graph(self, task_id: str) -> dict[str, Any]:
        task = self.connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if task is None:
            raise KeyError("task not found")
        rows = self.connection.execute("SELECT * FROM nodes WHERE task_id=? ORDER BY kind,node_key", (task_id,)).fetchall()
        return {"task": dict(task), "nodes": [self._node_dict(row) for row in rows]}

    def node(self, task_id: str, node_key: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM nodes WHERE task_id=? AND node_key=?", (task_id, node_key)).fetchone()
        if row is None:
            raise KeyError("node not found")
        return self._node_dict(row)

    def _node_by_id(self, node_id: str) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        if row is None:
            raise KeyError("node not found")
        return row

    def evidence(self, node_id: str) -> dict[str, Any]:
        row = self._node_by_id(node_id)
        return self._node_dict(row)

    def review_node(self, node_id: str, expected_version: int, decision: str, reviewer: str, note: str) -> dict[str, Any]:
        if decision not in {"approved", "returned"} or not reviewer.strip() or not note.strip():
            raise ValueError("decision, reviewer, and note are required")
        row = self._node_by_id(node_id)
        if row["version"] != expected_version or row["review_status"] != "pending_review":
            raise ConflictError("node version is stale or not awaiting review")
        status = "approved" if decision == "approved" else "returned"
        with self.connection:
            updated = self.connection.execute(
                "UPDATE nodes SET review_status=? WHERE node_id=? AND version=? AND review_status='pending_review'",
                (status, node_id, expected_version),
            )
            if updated.rowcount != 1:
                raise ConflictError("node version is stale or not awaiting review")
            self.connection.execute(
                "INSERT INTO reviews VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, node_id, expected_version, decision, reviewer, note, _utc_now()),
            )
            self._event(row["task_id"], node_id, f"node.{decision}", {"version": expected_version, "reviewer": reviewer})
        return self.node(row["task_id"], row["node_key"])

    def revise_node(
        self, node_id: str, expected_version: int, value: Any, unit: str, operator: str, reason: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError("corrected value must be a finite numeric measurement")
        if not unit.strip() or not operator.strip() or not reason.strip():
            raise ValueError("unit, operator, and reason are required")
        if not isinstance(evidence, dict) or not all(str(evidence.get(key, "")).strip() for key in ("source_id", "source_type", "locator")):
            raise ValueError("correction evidence needs source_id, source_type, and locator")
        row = self._node_by_id(node_id)
        if row["version"] != expected_version:
            raise ConflictError("node version is stale")
        next_version = expected_version + 1
        previous_value = json.loads(row["value_json"]) if row["value_json"] is not None else None
        previous_evidence = json.loads(row["evidence_json"])
        original = previous_evidence.get("original", previous_evidence)
        corrections = list(previous_evidence.get("corrections", []))
        correction = {**evidence, "operator": operator, "reason": reason, "version": next_version, "created_utc": _utc_now()}
        corrections.append(correction)
        combined_evidence = {"original": original, "current": evidence, "corrections": corrections}
        evidence_json = json.dumps(combined_evidence, ensure_ascii=False, sort_keys=True)
        with self.connection:
            updated = self.connection.execute(
                "UPDATE nodes SET value_json=?,unit=?,evidence_json=?,review_status='pending_review',version=? WHERE node_id=? AND version=?",
                (json.dumps(value, ensure_ascii=False, allow_nan=False), unit, evidence_json, next_version, node_id, expected_version),
            )
            if updated.rowcount != 1:
                raise ConflictError("node version is stale")
            self._event(row["task_id"], node_id, "node.revised", {
                "version": next_version, "operator": operator, "reason": reason,
                "previous_value": previous_value, "value": value, "unit": unit,
                "previous_evidence_sha256": hashlib.sha256(row["evidence_json"].encode()).hexdigest(),
                "evidence_sha256": hashlib.sha256(evidence_json.encode()).hexdigest(),
            })
        return self.node(row["task_id"], row["node_key"])

    def events(self, task_id: str, after: int = 0) -> list[dict[str, Any]]:
        if self.connection.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone() is None:
            raise KeyError("task not found")
        rows = self.connection.execute(
            "SELECT * FROM events WHERE task_id=? AND sequence>? ORDER BY sequence", (task_id, after)
        ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"]), "payload_json": None} for row in rows]

    def request_supplement(self, task_id: str, node_id: str, idempotency_key: str) -> dict[str, str]:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        node = self._node_by_id(node_id)
        if node["task_id"] != task_id:
            raise ValueError("node does not belong to task")
        existing = self.connection.execute(
            "SELECT * FROM supplement_jobs WHERE task_id=? AND node_id=? AND idempotency_key=?",
            (task_id, node_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            return {key: existing[key] for key in ("job_id", "status", "reason")}
        reason = "Dify workflow is not configured; no supplement candidate was generated"
        job_id = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO supplement_jobs VALUES (?,?,?,?,?,?,?)",
                (job_id, task_id, node_id, idempotency_key, "blocked", reason, _utc_now()),
            )
            self._event(task_id, node_id, "supplement.blocked", {"job_id": job_id, "reason": reason})
        return {"job_id": job_id, "status": "blocked", "reason": reason}

    def create_snapshot(self, task_id: str) -> dict[str, str]:
        graph = self.graph(task_id)
        nodes = graph["nodes"]
        blocking = [node["node_key"] for node in nodes if node["required"] and (
            node["applicability_status"] == "pending" or node["review_status"] != "approved" or node["value"] is None
        )]
        admission = self.connection.execute(
            "SELECT accepted FROM data_admissions WHERE data_version=?", (graph["task"]["data_version"],)
        ).fetchone()
        if admission is None or not bool(admission["accepted"]):
            blocking.append(f"data_version:{graph['task']['data_version']}")
        if blocking:
            raise SnapshotBlocked(blocking)
        snapshot_id = uuid.uuid4().hex
        graph_json = json.dumps(graph, ensure_ascii=False, sort_keys=True)
        with self.connection:
            self.connection.execute("INSERT INTO snapshots VALUES (?,?,?,?)", (snapshot_id, task_id, graph_json, _utc_now()))
            self._event(task_id, None, "snapshot.created", {"snapshot_id": snapshot_id})
        return {"snapshot_id": snapshot_id}
