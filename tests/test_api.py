import io
import json
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from gep.api import make_app


class ApiTests(unittest.TestCase):
    """Break caught: an HTTP caller could bypass the task graph's review gate."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = make_app(Path(self.directory.name) / "tasks.sqlite3", reviewer_header="HTTP_X_GEP_ACTOR")

    def tearDown(self):
        self.app.close()
        self.directory.cleanup()

    def request(self, method, path, body=None, actor="trusted-reviewer"):
        encoded = json.dumps(body).encode() if body is not None else b""
        environ = {}
        setup_testing_defaults(environ)
        environ.update({"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": str(len(encoded)), "wsgi.input": io.BytesIO(encoded), "HTTP_X_GEP_ACTOR": actor})
        status, headers = [], []
        payload = b"".join(self.app(environ, lambda s, h: (status.append(s), headers.extend(h))))
        header_map = dict(headers)
        decoded = {"html": payload.decode("utf-8")} if header_map.get("Content-Type") == "text/html; charset=utf-8" else json.loads(payload)
        return int(status[0].split()[0]), decoded, header_map

    def test_create_task_returns_real_graph_and_snapshot_blockers(self):
        status, task, _ = self.request("POST", "/tasks", {
            "region_code": "110108", "year": 2024, "boundary_version": "b1",
            "standard_version": "GB/T 46869-2025", "data_version": "reference-2024-v0.1",
        })
        graph_status, graph, _ = self.request("GET", f"/tasks/{task['task_id']}/graph")
        blocked_status, blocked, _ = self.request("POST", f"/tasks/{task['task_id']}/snapshots", {})

        self.assertEqual(status, 201)
        self.assertEqual(graph_status, 200)
        self.assertEqual(len([n for n in graph["nodes"] if n["kind"] == "indicator"]), 22)
        self.assertEqual(blocked_status, 422)
        self.assertIn("P1.maize.quantity", blocked["blocking_nodes"])

    def test_stale_review_returns_409_and_evidence_is_readable(self):
        _, task, _ = self.request("POST", "/tasks", {
            "region_code": "110108", "year": 2024, "boundary_version": "b1",
            "standard_version": "GB/T 46869-2025", "data_version": "reference-2024-v0.1",
        })
        _, graph, _ = self.request("GET", f"/tasks/{task['task_id']}/graph")
        maize = next(n for n in graph["nodes"] if n["node_key"] == "P1.maize.quantity")
        evidence_status, evidence, _ = self.request("GET", f"/nodes/{maize['node_id']}/evidence")
        first, _, _ = self.request("POST", f"/nodes/{maize['node_id']}/reviews", {
            "expected_version": 1, "decision": "approved", "reviewer": "reviewer", "note": "verified",
        })
        stale, response, _ = self.request("POST", f"/nodes/{maize['node_id']}/reviews", {
            "expected_version": 1, "decision": "approved", "reviewer": "other", "note": "stale",
        })

        self.assertEqual(evidence_status, 200)
        self.assertEqual(evidence["evidence"]["printed_page"], 71)
        self.assertEqual(first, 200)
        self.assertEqual(stale, 409)
        self.assertIn("stale", response["error"])

    def test_proxy_authenticated_actor_overrides_client_supplied_reviewer(self):
        _, task, _ = self.request("POST", "/tasks", {
            "region_code": "110108", "year": 2024, "boundary_version": "b1",
            "standard_version": "GB/T 46869-2025", "data_version": "reference-2024-v0.1",
        })
        _, graph, _ = self.request("GET", f"/tasks/{task['task_id']}/graph")
        maize = next(n for n in graph["nodes"] if n["node_key"] == "P1.maize.quantity")
        status, _, _ = self.request("POST", f"/nodes/{maize['node_id']}/reviews", {
            "expected_version": 1, "decision": "approved", "reviewer": "forged-client-name", "note": "verified",
        }, actor="verified-proxy-user")
        _, events, _ = self.request("GET", f"/tasks/{task['task_id']}/events")

        event = next(item for item in events["events"] if item["type"] == "node.approved")
        self.assertEqual(status, 200)
        self.assertEqual(event["payload"]["reviewer"], "verified-proxy-user")

    def test_proxy_authenticated_actor_overrides_client_supplied_revision_operator(self):
        _, task, _ = self.request("POST", "/tasks", {
            "region_code": "110108", "year": 2024, "boundary_version": "b1",
            "standard_version": "GB/T 46869-2025", "data_version": "reference-2024-v0.1",
        })
        _, graph, _ = self.request("GET", f"/tasks/{task['task_id']}/graph")
        maize = next(n for n in graph["nodes"] if n["node_key"] == "P1.maize.quantity")
        status, _, _ = self.request("POST", f"/nodes/{maize['node_id']}/revisions", {
            "expected_version": 1, "value": 2936.0, "unit": "t/a", "operator": "forged-client-name",
            "reason": "corrected", "evidence": {"source_id": "ledger", "source_type": "manual_correction", "locator": "row 8"},
        }, actor="verified-proxy-user")
        _, events, _ = self.request("GET", f"/tasks/{task['task_id']}/events")

        event = next(item for item in events["events"] if item["type"] == "node.revised")
        self.assertEqual(status, 200)
        self.assertEqual(event["payload"]["operator"], "verified-proxy-user")

    def test_supplement_is_idempotent_and_reports_unconfigured_dify_as_blocked(self):
        _, task, _ = self.request("POST", "/tasks", {
            "region_code": "110108", "year": 2024, "boundary_version": "b1",
            "standard_version": "GB/T 46869-2025", "data_version": "reference-2024-v0.1",
        })
        _, graph, _ = self.request("GET", f"/tasks/{task['task_id']}/graph")
        forest = next(n for n in graph["nodes"] if n["node_key"] == "P2")
        body = {"node_id": forest["node_id"], "idempotency_key": "forest-1"}

        first_status, first, _ = self.request("POST", f"/tasks/{task['task_id']}/supplement", body)
        second_status, second, _ = self.request("POST", f"/tasks/{task['task_id']}/supplement", body)

        self.assertEqual(first_status, 202)
        self.assertEqual(second_status, 202)
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(first["status"], "blocked")
        self.assertIn("Dify", first["reason"])

    def test_run_endpoint_records_a_blocked_run_from_a_frozen_snapshot(self):
        """Break caught: the browser could not request the persisted run required by the task contract."""
        self.app.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.app.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.app.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.app.store.connection.commit()
        snapshot = self.app.store.create_snapshot(task["task_id"])

        status, run, _ = self.request("POST", "/runs", {
            "snapshot_id": snapshot["snapshot_id"], "idempotency_key": "run-request-1",
        })

        self.assertEqual(status, 202)
        self.assertEqual(run["status"], "blocked")
        self.assertTrue(run["run_id"])

    def test_run_status_and_chain_are_readable(self):
        """Break caught: a blocked run could not explain its immutable input chain after a refresh."""
        self.app.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.app.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.app.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.app.store.connection.commit()
        snapshot = self.app.store.create_snapshot(task["task_id"])
        run = self.app.store.create_run(snapshot["snapshot_id"], "run-request-1")

        status_code, status, _ = self.request("GET", f"/runs/{run['run_id']}")
        chain_code, chain, _ = self.request("GET", f"/runs/{run['run_id']}/chain")

        self.assertEqual(status_code, 200)
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(chain_code, 200)
        self.assertEqual(chain["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(len(chain["input_graph_sha256"]), 64)

    def test_root_serves_the_task_canvas(self):
        status, payload, headers = self.request("GET", "/")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("GEP", payload["html"])


if __name__ == "__main__":
    unittest.main()
