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
from typing import Any, Protocol

from .methods import method_cards
from .runs import evaluate_frozen_graph


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
METHOD_CARDS = {card.indicator_id: card for card in method_cards()}


class ConflictError(ValueError):
    """The caller tried to review or revise an out-of-date node version."""


class SnapshotBlocked(ValueError):
    def __init__(self, blocking: list[str]):
        super().__init__("formal GEP snapshot is blocked by incomplete or unreviewed inputs")
        self.blocking = blocking


class SupplementWorkflow(Protocol):
    """A configured agent workflow that returns one structured candidate."""

    def run(self, work_order: dict[str, Any]) -> dict[str, Any]: ...


class UnconfiguredSupplementWorkflow:
    """Safe default: never invent a candidate when no real workflow is configured."""

    def run(self, work_order: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Dify workflow is not configured; no supplement candidate was generated")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GepStore:
    def __init__(self, database_path: str | Path, supplement_workflow: SupplementWorkflow | None = None):
        self.connection = sqlite3.connect(str(database_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.supplement_workflow = supplement_workflow or UnconfiguredSupplementWorkflow()
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, region_code TEXT NOT NULL, year INTEGER NOT NULL,
                boundary_version TEXT NOT NULL, standard_version TEXT NOT NULL,
                data_version TEXT NOT NULL, created_utc TEXT NOT NULL,
                graph_version INTEGER NOT NULL DEFAULT 1
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
                accepted INTEGER NOT NULL, registered_utc TEXT NOT NULL,
                registered_by TEXT NOT NULL DEFAULT 'legacy_unknown'
            );
            CREATE TABLE IF NOT EXISTS boundary_admissions (
                boundary_version TEXT PRIMARY KEY, geometry_sha256 TEXT NOT NULL,
                area_km2 REAL NOT NULL, crs TEXT NOT NULL, accepted INTEGER NOT NULL,
                registered_utc TEXT NOT NULL, registered_by TEXT NOT NULL DEFAULT 'legacy_unknown'
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
                parent_run_id TEXT REFERENCES runs(run_id), idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL, reason TEXT NOT NULL, chain_json TEXT NOT NULL,
                created_utc TEXT NOT NULL, UNIQUE(snapshot_id, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS formula_versions (
                formula_version_id TEXT PRIMARY KEY, indicator_id TEXT NOT NULL, data_version TEXT NOT NULL,
                method_id TEXT NOT NULL, standard_clause TEXT NOT NULL, card_sha256 TEXT NOT NULL,
                parameter_manifest_sha256 TEXT NOT NULL, source_id TEXT NOT NULL,
                source_sha256 TEXT NOT NULL, proposer TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL, review_version INTEGER NOT NULL, created_utc TEXT NOT NULL,
                UNIQUE(indicator_id, data_version, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS formula_reviews (
                formula_review_id TEXT PRIMARY KEY,
                formula_version_id TEXT NOT NULL REFERENCES formula_versions(formula_version_id),
                review_version INTEGER NOT NULL, decision TEXT NOT NULL, reviewer TEXT NOT NULL,
                note TEXT NOT NULL, created_utc TEXT NOT NULL,
                UNIQUE(formula_version_id, review_version)
            );
            """
        )
        task_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(tasks)")}
        if "graph_version" not in task_columns:
            self.connection.execute("ALTER TABLE tasks ADD COLUMN graph_version INTEGER NOT NULL DEFAULT 1")
        admission_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(data_admissions)")}
        if "registered_by" not in admission_columns:
            self.connection.execute("ALTER TABLE data_admissions ADD COLUMN registered_by TEXT NOT NULL DEFAULT 'legacy_unknown'")
        boundary_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(boundary_admissions)")}
        if "registered_by" not in boundary_columns:
            self.connection.execute("ALTER TABLE boundary_admissions ADD COLUMN registered_by TEXT NOT NULL DEFAULT 'legacy_unknown'")
        self.connection.commit()

    def register_data_admission(self, data_version: str, manifest_sha256: str, accepted: bool, registered_by: str = "system") -> dict[str, Any]:
        """Persist one immutable data-version admission decision."""
        if not data_version.strip() or not registered_by.strip():
            raise ValueError("data version is required")
        if len(manifest_sha256) != 64 or any(character not in "0123456789abcdef" for character in manifest_sha256.lower()):
            raise ValueError("admission manifest must have a SHA-256 hash")
        existing = self.connection.execute(
            "SELECT manifest_sha256,accepted,registered_by FROM data_admissions WHERE data_version=?", (data_version,)
        ).fetchone()
        if existing is not None:
            if existing["manifest_sha256"] != manifest_sha256 or bool(existing["accepted"]) != accepted:
                raise ConflictError("data admission is immutable; use a new data version")
            return {"data_version": data_version, "manifest_sha256": existing["manifest_sha256"], "accepted": bool(existing["accepted"]), "registered_by": existing["registered_by"]}
        with self.connection:
            self.connection.execute(
                "INSERT INTO data_admissions VALUES (?,?,?,?,?)",
                (data_version, manifest_sha256, int(accepted), _utc_now(), registered_by),
            )
        return {"data_version": data_version, "manifest_sha256": manifest_sha256, "accepted": accepted, "registered_by": registered_by}

    def data_admission(self, data_version: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM data_admissions WHERE data_version=?", (data_version,)).fetchone()
        if row is None:
            raise KeyError("data admission not found")
        result = dict(row)
        result["accepted"] = bool(result["accepted"])
        return result

    def register_boundary_admission(
        self, boundary_version: str, geometry_sha256: str, area_km2: float, crs: str, accepted: bool,
        registered_by: str = "system",
    ) -> dict[str, Any]:
        """Persist one immutable boundary review for a task's full-region scope."""
        if not boundary_version.strip() or not crs.strip() or not registered_by.strip():
            raise ValueError("boundary version and CRS are required")
        if len(geometry_sha256) != 64 or any(character not in "0123456789abcdef" for character in geometry_sha256.lower()):
            raise ValueError("boundary geometry must have a SHA-256 hash")
        if isinstance(area_km2, bool) or not isinstance(area_km2, (int, float)) or not math.isfinite(area_km2) or area_km2 <= 0:
            raise ValueError("boundary area must be a positive finite square-kilometre value")
        existing = self.connection.execute(
            "SELECT geometry_sha256,area_km2,crs,accepted,registered_by FROM boundary_admissions WHERE boundary_version=?",
            (boundary_version,),
        ).fetchone()
        if existing is not None:
            expected = (geometry_sha256.lower(), float(area_km2), crs, int(accepted))
            actual = (existing["geometry_sha256"], existing["area_km2"], existing["crs"], existing["accepted"])
            if actual != expected:
                raise ConflictError("boundary admission is immutable; use a new boundary version")
            return {"boundary_version": boundary_version, "geometry_sha256": existing["geometry_sha256"], "area_km2": existing["area_km2"], "crs": existing["crs"], "accepted": bool(existing["accepted"]), "registered_by": existing["registered_by"]}
        with self.connection:
            self.connection.execute(
                "INSERT INTO boundary_admissions VALUES (?,?,?,?,?,?,?)",
                (boundary_version, geometry_sha256.lower(), float(area_km2), crs, int(accepted), _utc_now(), registered_by),
            )
        return {"boundary_version": boundary_version, "geometry_sha256": geometry_sha256.lower(), "area_km2": float(area_km2), "crs": crs, "accepted": accepted, "registered_by": registered_by}

    def boundary_admission(self, boundary_version: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM boundary_admissions WHERE boundary_version=?", (boundary_version,)).fetchone()
        if row is None:
            raise KeyError("boundary admission not found")
        result = dict(row)
        result["accepted"] = bool(result["accepted"])
        return result

    def _event(self, task_id: str, node_id: str | None, event_type: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO events(task_id,node_id,type,created_utc,payload_json) VALUES (?,?,?,?,?)",
            (task_id, node_id, event_type, _utc_now(), json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )

    def _bump_graph_version(self, task_id: str) -> None:
        self.connection.execute("UPDATE tasks SET graph_version=graph_version+1 WHERE task_id=?", (task_id,))

    def create_task(
        self, region_code: str, year: int, boundary_version: str, standard_version: str, data_version: str,
    ) -> dict[str, str]:
        if region_code != "110108" or year != 2024:
            raise ValueError("this demo only accepts Haidian 110108 for year 2024")
        if not all(str(value).strip() for value in (boundary_version, standard_version, data_version)):
            raise ValueError("boundary, standard, and data versions are required")
        task_id = uuid.uuid4().hex
        self.connection.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
            (task_id, region_code, year, boundary_version, standard_version, data_version, _utc_now(), 1),
        )
        categories = (("material", "物质产品"), ("regulating", "调节服务"), ("cultural", "文化服务"))
        for key, label in categories:
            self._insert_node(task_id, key, None, "category", label, key, False, None, None, {}, "ready", "unsubmitted", "pending")
        for key, label, category in INDICATORS:
            card = METHOD_CARDS[key]
            self._insert_node(
                task_id, key, category, "indicator", label, category, True, None, None,
                {"method_id": card.method_id, "standard_clause": card.standard_clause,
                 "required_fields": card.required_fields, "applicability_rule": card.applicability_rule,
                 "deduplication_rule": card.deduplication_rule, "approval_status": card.approval_status},
                "awaiting_agent", "unsubmitted", "pending",
            )
        self._insert_node(
            task_id, "P1.maize.quantity", "P1", "input", "玉米产量", "material", True, 2935.1, "t/a",
            {
                "source_id": "haidian_yearbook_2025", "source_file": "01_raw/statistics/yearbook_2025_bulletin_chapters_1_9.pdf",
                "table_id": "5-11", "printed_page": 71, "region_code": "110108", "year": 2024,
                "metric": "玉米产量", "source_type": "observed",
            },
            "acquired", "pending_review", "applicable",
        )
        for card in method_cards():
            for field in card.required_fields:
                if card.indicator_id == "P1" and field == "quantity":
                    continue
                node_key = f"P1.maize.{field}" if card.indicator_id == "P1" else f"{card.indicator_id}.{field}"
                self._insert_node(
                    task_id, node_key, card.indicator_id, "input", field, next(
                        category for indicator_id, _, category in INDICATORS if indicator_id == card.indicator_id
                    ), True, None, None,
                    {"method_id": card.method_id, "standard_clause": card.standard_clause,
                     "field": field, "source_requirement": "awaiting source acquisition and human review"},
                    "awaiting_agent", "unsubmitted", "pending",
                )
        self._event(task_id, None, "task.created", {"indicator_count": len(INDICATORS), "data_version": data_version})
        self.connection.commit()
        return {"task_id": task_id}

    @staticmethod
    def _node_blockers(nodes: list[dict[str, Any]]) -> list[str]:
        indicators = {node["node_key"]: node for node in nodes if node["kind"] == "indicator"}
        blocking = []
        for node in nodes:
            if not node["required"]:
                continue
            if node["kind"] == "indicator":
                if node["applicability_status"] not in {"applicable", "not_applicable", "verified_zero"}:
                    blocking.append(node["node_key"])
                elif node["review_status"] != "approved":
                    blocking.append(node["node_key"])
                continue
            parent = indicators.get(node["parent_key"])
            if parent is not None and parent["applicability_status"] in {"not_applicable", "verified_zero"}:
                continue
            if node["review_status"] != "approved" or node["value"] is None:
                blocking.append(node["node_key"])
        return blocking

    def _formal_blockers(self, graph: dict[str, Any]) -> list[str]:
        """Return the same complete gate set used before freezing a formal snapshot."""
        nodes = graph["nodes"]
        indicators = {node["node_key"]: node for node in nodes if node["kind"] == "indicator"}
        blocking = self._node_blockers(nodes)
        for indicator_id, indicator in indicators.items():
            if indicator["applicability_status"] != "applicable":
                continue
            formula = self.connection.execute(
                "SELECT 1 FROM formula_versions WHERE indicator_id=? AND data_version=? AND status='approved' LIMIT 1",
                (indicator_id, graph["task"]["data_version"]),
            ).fetchone()
            if formula is None:
                blocking.append(f"formula_version:{indicator_id}")
        admission = self.connection.execute(
            "SELECT accepted FROM data_admissions WHERE data_version=?", (graph["task"]["data_version"],)
        ).fetchone()
        if admission is None or not bool(admission["accepted"]):
            blocking.append(f"data_version:{graph['task']['data_version']}")
        boundary = self.connection.execute(
            "SELECT accepted FROM boundary_admissions WHERE boundary_version=?", (graph["task"]["boundary_version"],)
        ).fetchone()
        if boundary is None or not bool(boundary["accepted"]):
            blocking.append(f"boundary_version:{graph['task']['boundary_version']}")
        return blocking

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return persistent task-center summaries without creating or changing a task."""
        task_rows = self.connection.execute(
            "SELECT * FROM tasks ORDER BY created_utc DESC, task_id DESC"
        ).fetchall()
        summaries = []
        for task_row in task_rows:
            task = dict(task_row)
            graph = self.graph(task["task_id"])
            nodes = graph["nodes"]
            latest_run = self.connection.execute(
                "SELECT runs.run_id,runs.status,runs.reason,runs.created_utc FROM runs "
                "JOIN snapshots ON snapshots.snapshot_id=runs.snapshot_id "
                "WHERE snapshots.task_id=? ORDER BY runs.created_utc DESC,runs.run_id DESC LIMIT 1",
                (task["task_id"],),
            ).fetchone()
            blocked_supplements = self.connection.execute(
                "SELECT COUNT(*) FROM supplement_jobs WHERE task_id=? AND status='blocked'", (task["task_id"],)
            ).fetchone()[0]
            summaries.append({
                **task,
                "pending_review_count": sum(node["review_status"] == "pending_review" for node in nodes),
                "node_blocker_count": len(self._node_blockers(nodes)),
                "formal_blocker_count": len(self._formal_blockers(graph)),
                "blocked_supplement_count": blocked_supplements,
                "latest_run": dict(latest_run) if latest_run is not None else None,
            })
        return summaries

    def readiness(self, task_id: str) -> dict[str, Any]:
        """Explain the current formal snapshot gate without creating a snapshot."""
        graph = self.graph(task_id)
        blocking = self._formal_blockers(graph)
        return {
            "task_id": task_id,
            "graph_version": graph["task"]["graph_version"],
            "ready_for_snapshot": not blocking,
            "blocking_node_count": len(blocking),
            "blocking_nodes": blocking,
        }

    def snapshots(self, task_id: str) -> list[dict[str, Any]]:
        """List immutable snapshots for task recovery without exposing mutable graph state."""
        self.graph(task_id)
        rows = self.connection.execute(
            "SELECT snapshot_id,created_utc FROM snapshots WHERE task_id=? ORDER BY created_utc DESC,snapshot_id DESC",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

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

    def appendix_e(self, task_id: str) -> dict[str, Any]:
        """Return the current 22-indicator Appendix E view without calculating a GEP total.

        This is intentionally a live completeness report, rather than an export from
        a frozen snapshot.  It makes every missing or unreviewed input visible while
        preserving the rule that no formal total exists before a valid run.
        """
        graph = self.graph(task_id)
        nodes = graph["nodes"]
        indicators = {node["node_key"]: node for node in nodes if node["kind"] == "indicator"}
        inputs_by_indicator: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            if node["kind"] == "input":
                inputs_by_indicator.setdefault(node["parent_key"], []).append(node)

        rows = []
        for indicator_id, label, category in INDICATORS:
            indicator = indicators[indicator_id]
            input_nodes = inputs_by_indicator.get(indicator_id, [])
            blocking_nodes = []
            if indicator["applicability_status"] not in {"applicable", "not_applicable", "verified_zero"}:
                blocking_nodes.append(indicator_id)
            elif indicator["review_status"] != "approved":
                blocking_nodes.append(indicator_id)
            if indicator["applicability_status"] not in {"not_applicable", "verified_zero"}:
                for input_node in input_nodes:
                    if input_node["review_status"] != "approved" or input_node["value"] is None:
                        blocking_nodes.append(input_node["node_key"])
            rows.append({
                "indicator_id": indicator_id,
                "label": label,
                "category": category,
                "applicability_status": indicator["applicability_status"],
                "review_status": indicator["review_status"],
                "method": indicator["evidence"],
                "input_nodes": [{
                    "node_key": input_node["node_key"], "label": input_node["label"],
                    "value": input_node["value"], "unit": input_node["unit"],
                    "acquisition_status": input_node["acquisition_status"],
                    "review_status": input_node["review_status"], "evidence": input_node["evidence"],
                } for input_node in input_nodes],
                "value_yuan": None,
                "blocking_nodes": blocking_nodes,
                "status": "blocked" if blocking_nodes else "ready_for_run",
            })
        task = graph["task"]
        return {
            "schema_version": 1,
            "report_type": "appendix_e_incomplete_current_task",
            "task_id": task_id,
            "region_code": task["region_code"],
            "year": task["year"],
            "boundary_version": task["boundary_version"],
            "standard_version": task["standard_version"],
            "data_version": task["data_version"],
            "formal_gep_value": None,
            "row_count": len(rows),
            "rows": rows,
        }

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
            self._bump_graph_version(row["task_id"])
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
            self._bump_graph_version(row["task_id"])
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

    @staticmethod
    def _candidate_from_workflow(payload: Any) -> dict[str, Any]:
        """Accept only a fully traceable, JSON-safe candidate from an agent workflow."""
        if not isinstance(payload, dict):
            raise ValueError("workflow response must be a JSON object")
        value = payload.get("value")
        if value is None:
            raise ValueError("workflow candidate requires a non-null value")
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("workflow candidate value must be JSON-safe") from error
        unit = payload.get("unit")
        explanation = payload.get("explanation")
        evidence = payload.get("evidence")
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError("workflow candidate requires a unit")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError("workflow candidate requires an explanation")
        if not isinstance(evidence, dict):
            raise ValueError("workflow candidate requires structured evidence")
        required_evidence = (
            "source_id", "source_type", "locator", "source_sha256", "license_or_access",
            "tool_run_id", "extracted_fragment",
        )
        if any(not str(evidence.get(key, "")).strip() for key in required_evidence):
            raise ValueError("workflow evidence is missing a required source or execution field")
        source_sha256 = str(evidence["source_sha256"])
        if len(source_sha256) != 64 or any(character not in "0123456789abcdef" for character in source_sha256.lower()):
            raise ValueError("workflow evidence requires a SHA-256 source hash")
        return {
            "value": value,
            "unit": unit.strip(),
            "explanation": explanation.strip(),
            "evidence": {**evidence, "source_sha256": source_sha256.lower()},
        }

    def _supplement_work_order(self, task_id: str, node: sqlite3.Row) -> dict[str, Any]:
        graph = self.graph(task_id)
        task = graph["task"]
        indicator_id = node["parent_key"]
        card = METHOD_CARDS.get(indicator_id)
        return {
            "task_id": task_id,
            "node_id": node["node_id"],
            "node_key": node["node_key"],
            "indicator_id": indicator_id,
            "method_id": card.method_id if card else None,
            "required_fields": list(card.required_fields) if card else [],
            "region_code": task["region_code"],
            "year": task["year"],
            "boundary_version": task["boundary_version"],
            "data_version": task["data_version"],
        }

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
        job_id = uuid.uuid4().hex
        try:
            candidate = self._candidate_from_workflow(self.supplement_workflow.run(self._supplement_work_order(task_id, node)))
        except (OSError, RuntimeError, ValueError) as error:
            reason = str(error)
            acquisition_status = "awaiting_agent" if "not configured" in reason else "agent_failed"
            with self.connection:
                self.connection.execute(
                    "INSERT INTO supplement_jobs VALUES (?,?,?,?,?,?,?)",
                    (job_id, task_id, node_id, idempotency_key, "blocked", reason, _utc_now()),
                )
                self.connection.execute("UPDATE nodes SET acquisition_status=? WHERE node_id=?", (acquisition_status, node_id))
                self._event(task_id, node_id, "supplement.blocked", {"job_id": job_id, "reason": reason})
            return {"job_id": job_id, "status": "blocked", "reason": reason}

        current_evidence = json.loads(node["evidence_json"])
        candidate_evidence = {
            **candidate["evidence"],
            "explanation": candidate["explanation"],
            "result_type": "agent_candidate",
            "received_utc": _utc_now(),
        }
        combined_evidence = {"original": current_evidence, "current": candidate_evidence}
        next_version = node["version"] + 1
        with self.connection:
            self.connection.execute(
                "INSERT INTO supplement_jobs VALUES (?,?,?,?,?,?,?)",
                (job_id, task_id, node_id, idempotency_key, "completed_pending_review", "candidate persisted; human review required", _utc_now()),
            )
            updated = self.connection.execute(
                "UPDATE nodes SET value_json=?,unit=?,evidence_json=?,acquisition_status='candidate_ready',review_status='pending_review',version=? WHERE node_id=? AND version=?",
                (json.dumps(candidate["value"], ensure_ascii=False, allow_nan=False), candidate["unit"],
                 json.dumps(combined_evidence, ensure_ascii=False, sort_keys=True), next_version, node_id, node["version"]),
            )
            if updated.rowcount != 1:
                raise ConflictError("node version is stale")
            self._bump_graph_version(task_id)
            self._event(task_id, node_id, "supplement.candidate_persisted", {
                "job_id": job_id, "version": next_version, "source_id": candidate["evidence"]["source_id"],
                "source_sha256": candidate["evidence"]["source_sha256"], "tool_run_id": candidate["evidence"]["tool_run_id"],
            })
        return {"job_id": job_id, "status": "completed_pending_review", "reason": "candidate persisted; human review required"}

    def create_snapshot(self, task_id: str) -> dict[str, str]:
        graph = self.graph(task_id)
        nodes = graph["nodes"]
        indicators = {node["node_key"]: node for node in nodes if node["kind"] == "indicator"}
        blocking = self._formal_blockers(graph)
        formula_versions: list[dict[str, Any]] = []
        for indicator_id, indicator in indicators.items():
            if indicator["applicability_status"] != "applicable":
                continue
            formula = self.connection.execute(
                "SELECT formula_version_id,indicator_id,data_version,method_id,standard_clause,card_sha256,parameter_manifest_sha256,source_id,source_sha256 "
                "FROM formula_versions WHERE indicator_id=? AND data_version=? AND status='approved' "
                "ORDER BY created_utc DESC LIMIT 1",
                (indicator_id, graph["task"]["data_version"]),
            ).fetchone()
            if formula is not None:
                formula_versions.append(dict(formula))
        admission = self.connection.execute(
            "SELECT manifest_sha256,accepted FROM data_admissions WHERE data_version=?", (graph["task"]["data_version"],)
        ).fetchone()
        boundary = self.connection.execute(
            "SELECT geometry_sha256,area_km2,crs,accepted FROM boundary_admissions WHERE boundary_version=?",
            (graph["task"]["boundary_version"],),
        ).fetchone()
        if blocking:
            raise SnapshotBlocked(blocking)
        graph["data_admission"] = {
            "data_version": graph["task"]["data_version"], "manifest_sha256": admission["manifest_sha256"],
        }
        graph["boundary_admission"] = {
            "boundary_version": graph["task"]["boundary_version"], "geometry_sha256": boundary["geometry_sha256"],
            "area_km2": boundary["area_km2"], "crs": boundary["crs"],
        }
        graph["formula_versions"] = formula_versions
        snapshot_id = uuid.uuid4().hex
        graph_json = json.dumps(graph, ensure_ascii=False, sort_keys=True)
        with self.connection:
            self.connection.execute("INSERT INTO snapshots VALUES (?,?,?,?)", (snapshot_id, task_id, graph_json, _utc_now()))
            self._event(task_id, None, "snapshot.created", {"snapshot_id": snapshot_id})
        return {"snapshot_id": snapshot_id}

    def create_run(self, snapshot_id: str, idempotency_key: str) -> dict[str, str]:
        """Record a deterministic-run request without fabricating a calculation result."""
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        snapshot = self.connection.execute(
            "SELECT task_id,graph_json FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        if snapshot is None:
            raise KeyError("snapshot not found")
        existing = self.connection.execute(
            "SELECT run_id,status,reason FROM runs WHERE snapshot_id=? AND idempotency_key=?",
            (snapshot_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        run_id = uuid.uuid4().hex
        parent = self.connection.execute(
            "SELECT runs.run_id FROM runs JOIN snapshots ON snapshots.snapshot_id=runs.snapshot_id "
            "WHERE snapshots.task_id=? AND runs.snapshot_id<>? "
            "ORDER BY runs.created_utc DESC,runs.run_id DESC LIMIT 1",
            (snapshot["task_id"], snapshot_id),
        ).fetchone()
        parent_run_id = parent["run_id"] if parent is not None else None
        graph = json.loads(snapshot["graph_json"])
        evaluation = evaluate_frozen_graph(graph)
        calculation = {
            "formal_gep_value_yuan": evaluation.formal_gep_value_yuan,
            "item_results": evaluation.item_results,
            "partial_category_totals_yuan": evaluation.partial_category_totals_yuan,
            "blocking_nodes": evaluation.blocking_nodes,
        }
        status = "succeeded" if evaluation.formal_gep_value_yuan is not None else "blocked"
        reason = (
            "formal GEP calculation completed"
            if status == "succeeded"
            else f"formal GEP remains blocked by {len(evaluation.blocking_nodes)} deterministic calculation requirements"
        )
        chain = {
            "snapshot_id": snapshot_id,
            "parent_run_id": parent_run_id,
            "input_graph_sha256": hashlib.sha256(snapshot["graph_json"].encode("utf-8")).hexdigest(),
            "status": status,
            "reason": reason,
            "calculation": calculation,
        }
        with self.connection:
            self.connection.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
                (run_id, snapshot_id, parent_run_id, idempotency_key, status, reason,
                 json.dumps(chain, ensure_ascii=False, sort_keys=True), _utc_now()),
            )
            self._event(snapshot["task_id"], None, f"run.{status}", {"run_id": run_id, "reason": reason})
        return {"run_id": run_id, "status": status, "reason": reason}

    def snapshot_export(self, snapshot_id: str) -> dict[str, Any]:
        """Build a self-hashing audit envelope from one immutable frozen snapshot."""
        snapshot = self.connection.execute(
            "SELECT snapshot_id,task_id,graph_json,created_utc FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        if snapshot is None:
            raise KeyError("snapshot not found")
        graph = json.loads(snapshot["graph_json"])
        node_reviews = []
        for node in graph["nodes"]:
            review = self.connection.execute(
                "SELECT review_id,node_id,version,decision,reviewer,note,created_utc FROM reviews "
                "WHERE node_id=? AND version=? ORDER BY created_utc",
                (node["node_id"], node["version"]),
            ).fetchone()
            if review is not None:
                node_reviews.append({"node_key": node["node_key"], "review": dict(review)})
        formula_versions = graph.get("formula_versions", [])
        formula_reviews = []
        for formula in formula_versions:
            rows = self.connection.execute(
                "SELECT formula_review_id,formula_version_id,review_version,decision,reviewer,note,created_utc "
                "FROM formula_reviews WHERE formula_version_id=? ORDER BY created_utc",
                (formula["formula_version_id"],),
            ).fetchall()
            formula_reviews.append({
                "formula_version_id": formula["formula_version_id"], "reviews": [dict(row) for row in rows],
            })
        exported = {
            "schema_version": 1,
            "scope": "frozen_snapshot_audit",
            "snapshot_id": snapshot["snapshot_id"],
            "task_id": snapshot["task_id"],
            "snapshot_created_utc": snapshot["created_utc"],
            "input_graph_sha256": hashlib.sha256(snapshot["graph_json"].encode("utf-8")).hexdigest(),
            "formal_gep_value": None,
            "frozen_graph": graph,
            "data_admission": graph.get("data_admission"),
            "boundary_admission": graph.get("boundary_admission"),
            "node_reviews": node_reviews,
            "formula_versions": formula_versions,
            "formula_reviews": formula_reviews,
        }
        exported["export_sha256"] = hashlib.sha256(
            json.dumps(exported, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return exported

    def propose_formula_version(
        self, indicator_id: str, data_version: str, parameter_manifest_sha256: str, source_id: str,
        source_sha256: str, proposer: str, idempotency_key: str,
    ) -> dict[str, Any]:
        if indicator_id not in METHOD_CARDS:
            raise ValueError("formula version must reference one of the 22 method cards")
        for name, value in (("parameter manifest", parameter_manifest_sha256), ("source", source_sha256)):
            normalized = str(value).lower()
            if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
                raise ValueError(f"{name} must have a SHA-256 hash")
        if not all(str(value).strip() for value in (data_version, source_id, proposer, idempotency_key)):
            raise ValueError("data_version, source_id, proposer, and idempotency_key are required")
        existing = self.connection.execute(
            "SELECT * FROM formula_versions WHERE indicator_id=? AND data_version=? AND idempotency_key=?",
            (indicator_id, data_version, idempotency_key),
        ).fetchone()
        if existing is not None:
            if (
                existing["parameter_manifest_sha256"] == parameter_manifest_sha256.lower()
                and existing["source_id"] == source_id
                and existing["source_sha256"] == source_sha256.lower()
                and existing["proposer"] == proposer
            ):
                return dict(existing)
            raise ConflictError("formula idempotency key was already used with different content")
        card = METHOD_CARDS[indicator_id]
        card_sha256 = hashlib.sha256(json.dumps(card.__dict__, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        formula_version_id = uuid.uuid4().hex
        created_utc = _utc_now()
        with self.connection:
            self.connection.execute(
                "INSERT INTO formula_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (formula_version_id, indicator_id, data_version, card.method_id, card.standard_clause, card_sha256,
                 parameter_manifest_sha256.lower(), source_id, source_sha256.lower(), proposer,
                 idempotency_key, "pending_review", 1, created_utc),
            )
        return self.formula_version(formula_version_id)

    def formula_version(self, formula_version_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM formula_versions WHERE formula_version_id=?", (formula_version_id,)
        ).fetchone()
        if row is None:
            raise KeyError("formula version not found")
        return dict(row)

    def review_formula_version(
        self, formula_version_id: str, expected_version: int, decision: str, reviewer: str, note: str,
    ) -> dict[str, Any]:
        if decision not in {"approved", "returned"} or not reviewer.strip() or not note.strip():
            raise ValueError("decision, reviewer, and note are required")
        current = self.formula_version(formula_version_id)
        if current["review_version"] != expected_version or current["status"] != "pending_review":
            raise ConflictError("formula version is stale or not awaiting review")
        status = "approved" if decision == "approved" else "returned"
        with self.connection:
            updated = self.connection.execute(
                "UPDATE formula_versions SET status=?,review_version=? WHERE formula_version_id=? AND review_version=? AND status='pending_review'",
                (status, expected_version + 1, formula_version_id, expected_version),
            )
            if updated.rowcount != 1:
                raise ConflictError("formula version is stale or not awaiting review")
            self.connection.execute(
                "INSERT INTO formula_reviews VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, formula_version_id, expected_version, decision, reviewer, note, _utc_now()),
            )
        return self.formula_version(formula_version_id)

    def formula_review_history(self, formula_version_id: str) -> list[dict[str, Any]]:
        self.formula_version(formula_version_id)
        rows = self.connection.execute(
            "SELECT * FROM formula_reviews WHERE formula_version_id=? ORDER BY created_utc", (formula_version_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def run(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("run not found")
        result = dict(row)
        result.pop("chain_json")
        return result

    def run_chain(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT chain_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("run not found")
        return json.loads(row["chain_json"])
