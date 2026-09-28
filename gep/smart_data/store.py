"""SQLite persistence for reusable assets, observations, plans, and runs."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .types import AssetRecord, CalculationPlan, CalculationResult, ObservationRecord


class SmartDataConflictError(ValueError):
    """An immutable smart-data identity was reused with different content."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _business(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "created_utc"}


class SmartDataStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS data_assets (
                asset_id TEXT PRIMARY KEY, asset_version TEXT NOT NULL, asset_type TEXT NOT NULL,
                title TEXT NOT NULL, publisher TEXT NOT NULL, source_url TEXT,
                license_or_access TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
                region_code TEXT NOT NULL, bbox_json TEXT, crs TEXT, local_path TEXT,
                sha256 TEXT NOT NULL, quality_status TEXT NOT NULL, quality_json TEXT NOT NULL,
                created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS derived_observations (
                observation_id TEXT PRIMARY KEY, metric TEXT NOT NULL, value REAL NOT NULL,
                unit TEXT NOT NULL, region_code TEXT NOT NULL, year INTEGER NOT NULL,
                spatial_grain TEXT NOT NULL, method_id TEXT NOT NULL, method_version TEXT NOT NULL,
                input_asset_ids_json TEXT NOT NULL, confidence REAL NOT NULL,
                uncertainty_json TEXT NOT NULL, evidence_class TEXT NOT NULL,
                artifact_path TEXT, artifact_sha256 TEXT, created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calculation_plans (
                plan_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                node_id TEXT NOT NULL REFERENCES nodes(node_id), target_metric TEXT NOT NULL,
                method_id TEXT NOT NULL, method_version TEXT NOT NULL,
                input_bindings_json TEXT NOT NULL, operations_json TEXT NOT NULL,
                planner TEXT NOT NULL, planner_model TEXT NOT NULL, explanation TEXT NOT NULL,
                schema_version TEXT NOT NULL, status TEXT NOT NULL, created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calculation_runs (
                calculation_run_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL REFERENCES calculation_plans(plan_id), code_version TEXT NOT NULL,
                input_manifest_sha256 TEXT NOT NULL, parameter_manifest_sha256 TEXT NOT NULL,
                result_json TEXT NOT NULL, result_sha256 TEXT NOT NULL, quality_json TEXT NOT NULL,
                status TEXT NOT NULL, error_code TEXT, created_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS observations_lookup
                ON derived_observations(metric,year,region_code,unit);
            CREATE INDEX IF NOT EXISTS plans_node_created
                ON calculation_plans(node_id,created_utc);
            CREATE INDEX IF NOT EXISTS runs_plan_created
                ON calculation_runs(plan_id,created_utc);
            """
        )
        self.connection.commit()

    @staticmethod
    def _asset_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["bbox"] = json.loads(result.pop("bbox_json")) if result["bbox_json"] is not None else None
        result["quality"] = json.loads(result.pop("quality_json"))
        return result

    @staticmethod
    def _observation_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["input_asset_ids"] = json.loads(result.pop("input_asset_ids_json"))
        result["uncertainty"] = json.loads(result.pop("uncertainty_json"))
        return result

    @staticmethod
    def _plan_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["input_bindings"] = json.loads(result.pop("input_bindings_json"))
        result["operations"] = json.loads(result.pop("operations_json"))
        return result

    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json"))
        result["quality"] = json.loads(result.pop("quality_json"))
        return result

    def register_asset(self, asset: AssetRecord) -> dict[str, Any]:
        existing = self.connection.execute("SELECT * FROM data_assets WHERE asset_id=?", (asset.asset_id,)).fetchone()
        if existing is not None:
            current = self._asset_row(existing)
            if _business(current) != _business(asset.as_dict()):
                raise SmartDataConflictError("asset version is immutable; use a new asset_id or version")
            return current
        payload = asset.as_dict()
        with self.connection:
            self.connection.execute(
                "INSERT INTO data_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    payload["asset_id"], payload["asset_version"], payload["asset_type"], payload["title"],
                    payload["publisher"], payload["source_url"], payload["license_or_access"],
                    payload["period_start"], payload["period_end"], payload["region_code"],
                    _json(payload["bbox"]) if payload["bbox"] is not None else None, payload["crs"],
                    payload["local_path"], payload["sha256"], payload["quality_status"],
                    _json(payload["quality"]), payload["created_utc"],
                ),
            )
        return payload

    def asset(self, asset_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM data_assets WHERE asset_id=?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError("smart data asset not found")
        return self._asset_row(row)

    def list_assets(
        self, *, asset_type: str | None = None, year: int | None = None,
        quality_status: str | None = None, region_code: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, parameters = [], []
        if asset_type is not None: clauses.append("asset_type=?"); parameters.append(asset_type)
        if year is not None:
            clauses.append("CAST(substr(period_start,1,4) AS INTEGER)<=? AND CAST(substr(period_end,1,4) AS INTEGER)>=?")
            parameters.extend((year, year))
        if quality_status is not None: clauses.append("quality_status=?"); parameters.append(quality_status)
        if region_code is not None: clauses.append("region_code=?"); parameters.append(region_code)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(f"SELECT * FROM data_assets{where} ORDER BY asset_id", parameters).fetchall()
        return [self._asset_row(row) for row in rows]

    def register_observation(self, observation: ObservationRecord) -> dict[str, Any]:
        for asset_id in observation.input_asset_ids:
            self.asset(asset_id)
        existing = self.connection.execute(
            "SELECT * FROM derived_observations WHERE observation_id=?", (observation.observation_id,)
        ).fetchone()
        if existing is not None:
            current = self._observation_row(existing)
            if _business(current) != _business(observation.as_dict()):
                raise SmartDataConflictError("observation is immutable; use a new observation_id")
            return current
        payload = observation.as_dict()
        with self.connection:
            self.connection.execute(
                "INSERT INTO derived_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    payload["observation_id"], payload["metric"], payload["value"], payload["unit"],
                    payload["region_code"], payload["year"], payload["spatial_grain"], payload["method_id"],
                    payload["method_version"], _json(payload["input_asset_ids"]), payload["confidence"],
                    _json(payload["uncertainty"]), payload["evidence_class"], payload["artifact_path"],
                    payload["artifact_sha256"], payload["created_utc"],
                ),
            )
        return payload

    def find_observations(
        self, *, metric: str, year: int, region_code: str, unit: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM derived_observations WHERE metric=? AND year=? AND region_code=?"
        parameters: list[Any] = [metric, year, region_code]
        if unit is not None:
            query += " AND unit=?"; parameters.append(unit)
        query += " ORDER BY observation_id"
        return [self._observation_row(row) for row in self.connection.execute(query, parameters).fetchall()]

    def register_plan(self, plan: CalculationPlan) -> dict[str, Any]:
        for observation_id in plan.input_bindings.values():
            if self.connection.execute(
                "SELECT 1 FROM derived_observations WHERE observation_id=?", (observation_id,)
            ).fetchone() is None:
                raise KeyError("plan observation not found")
        existing = self.connection.execute("SELECT * FROM calculation_plans WHERE plan_id=?", (plan.plan_id,)).fetchone()
        if existing is not None:
            current = self._plan_row(existing)
            if _business(current) != _business(plan.as_dict()):
                raise SmartDataConflictError("calculation plan is immutable; use a new plan_id")
            return current
        payload = plan.as_dict()
        with self.connection:
            self.connection.execute(
                "INSERT INTO calculation_plans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    payload["plan_id"], payload["task_id"], payload["node_id"], payload["target_metric"],
                    payload["method_id"], payload["method_version"], _json(payload["input_bindings"]),
                    _json(payload["operations"]), payload["planner"], payload["planner_model"],
                    payload["explanation"], payload["schema_version"], payload["status"], payload["created_utc"],
                ),
            )
        return payload

    def register_run(self, run: CalculationResult) -> dict[str, Any]:
        existing = self.connection.execute(
            "SELECT * FROM calculation_runs WHERE calculation_run_id=?", (run.calculation_run_id,)
        ).fetchone()
        if existing is not None:
            current = self._run_row(existing)
            if _business(current) != _business(run.as_dict()):
                raise SmartDataConflictError("calculation run is immutable; use a new calculation_run_id")
            return current
        payload = run.as_dict()
        with self.connection:
            self.connection.execute(
                "INSERT INTO calculation_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    payload["calculation_run_id"], payload["plan_id"], payload["code_version"],
                    payload["input_manifest_sha256"], payload["parameter_manifest_sha256"],
                    _json(payload["result"]), payload["result_sha256"], _json(payload["quality"]),
                    payload["status"], payload["error_code"], payload["created_utc"],
                ),
            )
        return payload

    def calculation_chain(self, node_id: str) -> dict[str, Any]:
        plan_row = self.connection.execute(
            "SELECT * FROM calculation_plans WHERE node_id=? ORDER BY created_utc DESC,plan_id DESC LIMIT 1",
            (node_id,),
        ).fetchone()
        if plan_row is None:
            raise KeyError("calculation chain not found")
        plan = self._plan_row(plan_row)
        observations = []
        for binding in sorted(plan["input_bindings"]):
            observation_id = plan["input_bindings"][binding]
            row = self.connection.execute(
                "SELECT * FROM derived_observations WHERE observation_id=?", (observation_id,)
            ).fetchone()
            observations.append(self._observation_row(row))
        asset_ids = sorted({asset_id for observation in observations for asset_id in observation["input_asset_ids"]})
        assets = [self.asset(asset_id) for asset_id in asset_ids]
        run_row = self.connection.execute(
            "SELECT * FROM calculation_runs WHERE plan_id=? ORDER BY created_utc DESC,calculation_run_id DESC LIMIT 1",
            (plan["plan_id"],),
        ).fetchone()
        return {
            "plan": plan, "observations": observations, "assets": assets,
            "run": self._run_row(run_row) if run_row is not None else None,
        }
