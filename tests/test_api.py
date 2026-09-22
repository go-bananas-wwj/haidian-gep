import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from gep.api import make_app
from gep.release import seal
from gep.task_service import INDICATORS


class ApiTests(unittest.TestCase):
    """Break caught: an HTTP caller could bypass the task graph's review gate."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.data_root = Path(self.directory.name) / "data"
        package = self.data_root / "05_release" / "reference-2024-v0.1"
        package.mkdir(parents=True)
        (package / "README.md").write_text("reference package\n", encoding="utf-8")
        (package / "quality_report.json").write_text(json.dumps({
            "accounting_ready": False, "full_gep_computed": False,
            "remaining": ["confirmed 2024 boundary", "production costs and prices"],
        }), encoding="utf-8")
        (package / "missing_inputs.csv").write_text(
            "item,name,status,required_next_step\nP1,农产品,pending,价格和成本\nR6,固碳,pending,NPP和价格\n",
            encoding="utf-8",
        )
        catalog = self.data_root / "00_catalog"
        catalog.mkdir()
        (catalog / "aef_2024_candidate_tiles.json").write_text(json.dumps({
            "tiles": [
                {"year": 2024, "boundary_status": "unconfirmed_osm_demo_boundary", "selection": "bbox_candidates_not_coverage_validation"},
                {"year": 2024, "boundary_status": "unconfirmed_osm_demo_boundary", "selection": "bbox_candidates_not_coverage_validation"},
            ],
        }), encoding="utf-8")
        seal(package, "reference-2024-v0.1")
        self.app = make_app(
            Path(self.directory.name) / "tasks.sqlite3", reviewer_header="HTTP_X_GEP_ACTOR", data_root=self.data_root,
        )

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

    def approve_all_formula_versions(self, data_version):
        """Provide reviewed method/parameter records for a fully admitted test snapshot."""
        for number, (indicator_id, _, _) in enumerate(INDICATORS, 1):
            proposal = self.app.store.propose_formula_version(
                indicator_id, data_version, "a" * 64, f"method-note-{number}", "b" * 64,
                "analyst", f"request-{number}",
            )
            self.app.store.review_formula_version(
                proposal["formula_version_id"], 1, "approved", "method-reviewer", "verified",
            )

    def register_test_boundary(self, boundary_version="b1"):
        self.app.store.register_boundary_admission(boundary_version, "c" * 64, 430.0, "EPSG:4326", accepted=True)

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

    def test_task_center_lists_persisted_task_state_and_latest_run(self):
        """Break caught: a refresh could leave users unable to find a persisted task or its blockers."""
        _, first, _ = self.request("POST", "/tasks", {
            "region_code": "110108", "year": 2024, "boundary_version": "b1",
            "standard_version": "GB/T 46869-2025", "data_version": "reference-2024-v0.1",
        })
        _, second, _ = self.request("POST", "/tasks", {
            "region_code": "110108", "year": 2024, "boundary_version": "b2",
            "standard_version": "GB/T 46869-2025", "data_version": "reference-2024-v0.1",
        })

        status, listing, _ = self.request("GET", "/tasks")

        self.assertEqual(status, 200)
        self.assertEqual([task["task_id"] for task in listing["tasks"]], [second["task_id"], first["task_id"]])
        item = listing["tasks"][0]
        self.assertEqual(item["region_code"], "110108")
        self.assertEqual(item["year"], 2024)
        self.assertEqual(item["graph_version"], 1)
        self.assertEqual(item["pending_review_count"], 1)
        self.assertGreater(item["node_blocker_count"], 0)
        self.assertEqual(item["latest_run"], None)

    def test_task_center_increments_graph_version_after_a_reviewed_node_change(self):
        """Break caught: task-center graph versions could stay stale after an audited graph mutation."""
        _, task, _ = self.request("POST", "/tasks", {
            "region_code": "110108", "year": 2024, "boundary_version": "b1",
            "standard_version": "GB/T 46869-2025", "data_version": "reference-2024-v0.1",
        })
        _, graph, _ = self.request("GET", f"/tasks/{task['task_id']}/graph")
        maize = next(node for node in graph["nodes"] if node["node_key"] == "P1.maize.quantity")
        self.request("POST", f"/nodes/{maize['node_id']}/reviews", {
            "expected_version": 1, "decision": "approved", "note": "verified",
        })

        _, listing, _ = self.request("GET", "/tasks")

        self.assertEqual(listing["tasks"][0]["graph_version"], 2)

    def test_appendix_e_keeps_an_incomplete_task_at_null_formal_gep(self):
        """Break caught: an incomplete task could hide indicator gaps or invent a formal total."""
        _, task, _ = self.request("POST", "/tasks", {
            "region_code": "110108", "year": 2024, "boundary_version": "b1",
            "standard_version": "GB/T 46869-2025", "data_version": "reference-2024-v0.1",
        })

        status, appendix, _ = self.request("GET", f"/tasks/{task['task_id']}/appendix-e")

        self.assertEqual(status, 200)
        self.assertEqual(appendix["formal_gep_value"], None)
        self.assertEqual(appendix["row_count"], 22)
        self.assertEqual(len(appendix["rows"]), 22)
        maize = next(row for row in appendix["rows"] if row["indicator_id"] == "P1")
        self.assertEqual(maize["category"], "material")
        maize_quantity = next(node for node in maize["input_nodes"] if node["node_key"] == "P1.maize.quantity")
        self.assertEqual(maize_quantity["value"], 2935.1)
        self.assertIn("P1", maize["blocking_nodes"])

    def test_root_exposes_the_incomplete_appendix_e_action(self):
        """Break caught: the task canvas could offer no user-visible route to its Appendix E report."""
        status, page, _ = self.request("GET", "/")

        self.assertEqual(status, 200)
        self.assertIn('id="appendix-e"', page["html"])

    def test_root_exposes_the_persisted_task_center(self):
        """Break caught: the browser could not reopen a task saved in the persistent service."""
        status, page, _ = self.request("GET", "/")

        self.assertEqual(status, 200)
        self.assertIn('id="task-list"', page["html"])

    def test_data_version_catalog_exposes_a_verified_blocked_reference_package(self):
        """Break caught: the canvas could call a reference package accounting-ready without its manifest or gaps."""
        list_status, listing, _ = self.request("GET", "/data-versions")
        status, package, _ = self.request("GET", "/data-versions/reference-2024-v0.1")

        self.assertEqual(list_status, 200)
        self.assertEqual(listing["data_versions"], ["reference-2024-v0.1"])
        self.assertEqual(status, 200)
        self.assertFalse(package["accounting_ready"])
        self.assertFalse(package["full_gep_computed"])
        self.assertTrue(package["release_verification"]["valid"])
        self.assertEqual(package["missing_input_count"], 2)
        self.assertEqual(package["remaining"], ["confirmed 2024 boundary", "production costs and prices"])
        self.assertEqual(package["alphaearth_candidates"]["candidate_tile_count"], 2)
        self.assertEqual(package["alphaearth_candidates"]["boundary_statuses"], ["unconfirmed_osm_demo_boundary"])
        self.assertFalse(package["alphaearth_candidates"]["coverage_validated"])

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
        self.approve_all_formula_versions("audited-2024-v1")
        self.register_test_boundary()
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
        self.approve_all_formula_versions("audited-2024-v1")
        self.register_test_boundary()
        snapshot = self.app.store.create_snapshot(task["task_id"])
        run = self.app.store.create_run(snapshot["snapshot_id"], "run-request-1")

        status_code, status, _ = self.request("GET", f"/runs/{run['run_id']}")
        chain_code, chain, _ = self.request("GET", f"/runs/{run['run_id']}/chain")

        self.assertEqual(status_code, 200)
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(chain_code, 200)
        self.assertEqual(chain["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(len(chain["input_graph_sha256"]), 64)

    def test_snapshot_export_preserves_frozen_evidence_without_a_gep_value(self):
        """Break caught: exporting a frozen snapshot could omit review evidence or invent a GEP total."""
        self.app.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.app.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.app.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.app.store.connection.commit()
        self.approve_all_formula_versions("audited-2024-v1")
        self.register_test_boundary()
        snapshot = self.app.store.create_snapshot(task["task_id"])

        status, exported, _ = self.request("GET", f"/snapshots/{snapshot['snapshot_id']}/export")

        self.assertEqual(status, 200)
        self.assertEqual(exported["schema_version"], 1)
        self.assertEqual(exported["formal_gep_value"], None)
        self.assertEqual(exported["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(len(exported["input_graph_sha256"]), 64)
        self.assertEqual(exported["data_admission"]["manifest_sha256"], "a" * 64)
        self.assertEqual(exported["boundary_admission"]["geometry_sha256"], "c" * 64)
        self.assertEqual(len(exported["formula_versions"]), 22)
        self.assertEqual(len(exported["formula_reviews"]), 22)
        self.assertEqual(len(exported["export_sha256"]), 64)
        exported_hash = exported.pop("export_sha256")
        self.assertEqual(
            exported_hash,
            hashlib.sha256(json.dumps(exported, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        )

    def test_formula_version_proposal_uses_the_trusted_proxy_identity(self):
        """Break caught: a client could forge the method proposer in a formula approval record."""
        proposal_status, proposal, _ = self.request("POST", "/formula-versions", {
            "indicator_id": "R6", "data_version": "audited-2024-v1", "parameter_manifest_sha256": "a" * 64,
            "source_id": "carbon-method-note", "source_sha256": "b" * 64, "proposer": "forged-client", "idempotency_key": "r6-1",
        }, actor="verified-method-analyst")

        self.assertEqual(proposal_status, 201)
        self.assertEqual(proposal["proposer"], "verified-method-analyst")

    def test_formula_version_review_uses_the_trusted_proxy_identity(self):
        """Break caught: a client could forge the reviewer in a formula approval record."""
        proposal = self.app.store.propose_formula_version(
            "R6", "audited-2024-v1", "a" * 64, "carbon-method-note", "b" * 64, "analyst", "r6-1"
        )

        status, reviewed, _ = self.request("POST", f"/formula-versions/{proposal['formula_version_id']}/reviews", {
            "expected_version": 1, "decision": "approved", "reviewer": "forged-client", "note": "checked",
        }, actor="verified-method-reviewer")

        self.assertEqual(status, 200)
        self.assertEqual(reviewed["status"], "approved")
        self.assertEqual(
            self.app.store.formula_review_history(proposal["formula_version_id"])[0]["reviewer"],
            "verified-method-reviewer",
        )

    def test_formula_review_history_is_readable_after_refresh(self):
        """Break caught: a reviewed formula could lose its audit history when the client reconnects."""
        proposal = self.app.store.propose_formula_version(
            "R6", "audited-2024-v1", "a" * 64, "carbon-method-note", "b" * 64, "analyst", "r6-1"
        )
        self.app.store.review_formula_version(
            proposal["formula_version_id"], 1, "approved", "method-reviewer", "checked"
        )

        status, payload, _ = self.request("GET", f"/formula-versions/{proposal['formula_version_id']}/reviews")

        self.assertEqual(status, 200)
        self.assertEqual(payload["reviews"][0]["reviewer"], "method-reviewer")

    def test_root_serves_the_task_canvas(self):
        status, payload, headers = self.request("GET", "/")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("GEP", payload["html"])


if __name__ == "__main__":
    unittest.main()
