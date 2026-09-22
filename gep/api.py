"""Dependency-free WSGI API for the evidence-first GEP task service."""
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from .data_packages import DataPackageCatalog
from .dify import DifyWorkflow
from .methods import method_cards
from .task_service import ConflictError, GepStore, SnapshotBlocked


class DemoApi:
    def __init__(self, database_path: str | Path, reviewer_header: str | None = None, data_root: str | Path | None = None):
        self.store = GepStore(database_path, supplement_workflow=DifyWorkflow.from_environment())
        self.reviewer_header = reviewer_header or os.environ.get("GEP_TRUSTED_PROXY_USER_HEADER")
        self.data_packages = DataPackageCatalog(data_root or os.environ.get("GEP_DATA_ROOT"))

    def close(self) -> None:
        self.store.close()

    @staticmethod
    def _json_body(environ: dict[str, Any]) -> dict[str, Any]:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        if length == 0:
            return {}
        body = environ["wsgi.input"].read(length)
        value = json.loads(body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    @staticmethod
    def _response(start_response: Callable, status: int, payload: dict[str, Any]):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        start_response(f"{status} { {200:'OK', 201:'Created', 202:'Accepted', 400:'Bad Request', 404:'Not Found', 409:'Conflict', 422:'Unprocessable Entity', 500:'Internal Server Error', 503:'Service Unavailable'}[status] }", [
            ("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(data))),
        ])
        return [data]

    @staticmethod
    def _html_response(start_response: Callable, html: bytes):
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(html)))])
        return [html]

    @staticmethod
    def _asset_response(start_response: Callable, asset: Path):
        content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type = f"{content_type}; charset=utf-8"
        data = asset.read_bytes()
        start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(data)))])
        return [data]

    def __call__(self, environ: dict[str, Any], start_response: Callable):
        method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "")
        # The production proxy keeps API requests under /api while the local
        # single-process demo serves the same contract directly.  Supporting
        # both paths makes the canvas runnable in either arrangement.
        if path == "/api":
            path = "/"
        elif path.startswith("/api/"):
            path = path[4:]
        parts = [part for part in path.split("/") if part]
        try:
            if method == "GET" and path == "/":
                return self._html_response(start_response, (Path(__file__).parent / "web" / "index.html").read_bytes())
            if method == "GET" and len(parts) == 1 and parts[0] in {"styles.css", "api.js", "graph.js", "map.js", "app.js"}:
                return self._asset_response(start_response, Path(__file__).parent / "web" / parts[0])
            if method == "GET" and path == "/health":
                return self._response(start_response, 200, {"status": "ok"})
            if method == "GET" and parts == ["indicator-catalog"]:
                return self._response(start_response, 200, {"indicators": [{
                    "indicator_id": card.indicator_id, "standard_clause": card.standard_clause,
                    "method_id": card.method_id, "required_fields": list(card.required_fields),
                    "applicability_rule": card.applicability_rule,
                    "deduplication_rule": card.deduplication_rule,
                    "approval_status": card.approval_status,
                } for card in method_cards()]})
            if method == "GET" and parts == ["data-versions"]:
                return self._response(start_response, 200, {"data_versions": self.data_packages.versions()})
            if method == "GET" and len(parts) == 2 and parts[0] == "data-versions":
                return self._response(start_response, 200, self.data_packages.summary(parts[1]))
            if method == "GET" and len(parts) == 2 and parts[0] == "data-admissions":
                return self._response(start_response, 200, self.store.data_admission(parts[1]))
            if method == "POST" and parts == ["data-admissions"]:
                actor = environ.get(self.reviewer_header, "").strip() if self.reviewer_header else ""
                if not actor:
                    return self._response(start_response, 503, {"error": "trusted data-custodian identity is not configured"})
                return self._response(start_response, 201, self.store.register_data_admission(registered_by=actor, **self._json_body(environ)))
            if method == "POST" and parts == ["boundary-admissions"]:
                actor = environ.get(self.reviewer_header, "").strip() if self.reviewer_header else ""
                if not actor:
                    return self._response(start_response, 503, {"error": "trusted boundary-custodian identity is not configured"})
                return self._response(start_response, 201, self.store.register_boundary_admission(registered_by=actor, **self._json_body(environ)))
            if method == "GET" and len(parts) == 2 and parts[0] == "boundary-admissions":
                return self._response(start_response, 200, self.store.boundary_admission(parts[1]))
            if method == "GET" and parts == ["tasks"]:
                return self._response(start_response, 200, {"tasks": self.store.list_tasks()})
            if method == "POST" and parts == ["tasks"]:
                body = self._json_body(environ)
                task = self.store.create_task(**body)
                return self._response(start_response, 201, task)
            if method == "POST" and parts == ["runs"]:
                body = self._json_body(environ)
                run = self.store.create_run(**body)
                return self._response(start_response, 202, run)
            if method == "POST" and parts == ["formula-versions"]:
                proposer = environ.get(self.reviewer_header, "").strip() if self.reviewer_header else ""
                if not proposer:
                    return self._response(start_response, 503, {"error": "trusted formula-proposer identity is not configured"})
                body = self._json_body(environ)
                body.pop("proposer", None)
                return self._response(start_response, 201, self.store.propose_formula_version(proposer=proposer, **body))
            if len(parts) >= 2 and parts[0] == "formula-versions":
                formula_version_id = parts[1]
                if method == "GET" and parts[2:] == ["reviews"]:
                    return self._response(start_response, 200, {"reviews": self.store.formula_review_history(formula_version_id)})
                if method == "POST" and parts[2:] == ["reviews"]:
                    reviewer = environ.get(self.reviewer_header, "").strip() if self.reviewer_header else ""
                    if not reviewer:
                        return self._response(start_response, 503, {"error": "trusted formula-reviewer identity is not configured"})
                    body = self._json_body(environ)
                    body.pop("reviewer", None)
                    return self._response(start_response, 200, self.store.review_formula_version(
                        formula_version_id, reviewer=reviewer, **body,
                    ))
            if len(parts) >= 2 and parts[0] == "runs":
                run_id = parts[1]
                if method == "GET" and not parts[2:]:
                    return self._response(start_response, 200, self.store.run(run_id))
                if method == "GET" and parts[2:] == ["chain"]:
                    return self._response(start_response, 200, self.store.run_chain(run_id))
            if len(parts) >= 2 and parts[0] == "snapshots":
                if method == "GET" and parts[2:] == ["export"]:
                    return self._response(start_response, 200, self.store.snapshot_export(parts[1]))
            if len(parts) >= 2 and parts[0] == "tasks":
                task_id = parts[1]
                if method == "GET" and parts[2:] == ["graph"]:
                    return self._response(start_response, 200, self.store.graph(task_id))
                if method == "GET" and parts[2:] == ["readiness"]:
                    return self._response(start_response, 200, self.store.readiness(task_id))
                if method == "GET" and parts[2:] == ["appendix-e"]:
                    return self._response(start_response, 200, self.store.appendix_e(task_id))
                if method == "GET" and parts[2:] == ["events"]:
                    after = int(parse_qs(environ.get("QUERY_STRING", "")).get("after", ["0"])[0])
                    return self._response(start_response, 200, {"events": self.store.events(task_id, after)})
                if method == "POST" and parts[2:] == ["supplement"]:
                    return self._response(start_response, 202, self.store.request_supplement(task_id, **self._json_body(environ)))
                if method == "GET" and parts[2:] == ["snapshots"]:
                    return self._response(start_response, 200, {"snapshots": self.store.snapshots(task_id)})
                if method == "POST" and parts[2:] == ["snapshots"]:
                    return self._response(start_response, 201, self.store.create_snapshot(task_id))
            if len(parts) >= 2 and parts[0] == "nodes":
                node_id = parts[1]
                if method == "GET" and parts[2:] == ["evidence"]:
                    return self._response(start_response, 200, self.store.evidence(node_id))
                body = self._json_body(environ)
                if method == "POST" and parts[2:] == ["reviews"]:
                    reviewer = environ.get(self.reviewer_header, "").strip() if self.reviewer_header else ""
                    if not reviewer:
                        return self._response(start_response, 503, {"error": "trusted reviewer identity is not configured"})
                    body.pop("reviewer", None)
                    return self._response(start_response, 200, self.store.review_node(node_id, reviewer=reviewer, **body))
                if method == "POST" and parts[2:] == ["revisions"]:
                    operator = environ.get(self.reviewer_header, "").strip() if self.reviewer_header else ""
                    if not operator:
                        return self._response(start_response, 503, {"error": "trusted operator identity is not configured"})
                    body.pop("operator", None)
                    return self._response(start_response, 200, self.store.revise_node(node_id, operator=operator, **body))
            return self._response(start_response, 404, {"error": "route not found"})
        except SnapshotBlocked as error:
            return self._response(start_response, 422, {"error": str(error), "blocking_nodes": error.blocking})
        except ConflictError as error:
            return self._response(start_response, 409, {"error": str(error)})
        except KeyError as error:
            return self._response(start_response, 404, {"error": str(error)})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self._response(start_response, 400, {"error": str(error)})


def make_app(
    database_path: str | Path, reviewer_header: str | None = None, data_root: str | Path | None = None,
) -> DemoApi:
    return DemoApi(database_path, reviewer_header=reviewer_header, data_root=data_root)
