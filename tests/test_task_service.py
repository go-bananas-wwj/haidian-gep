import sqlite3
import json
import tempfile
import unittest
from pathlib import Path

from gep.task_service import INDICATORS, ConflictError, GepStore, SnapshotBlocked


class TaskServiceTests(unittest.TestCase):
    """Break caught: removing the formal-review gate could turn reference data into GEP."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = GepStore(Path(self.directory.name) / "tasks.sqlite3")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def approve_all_formula_versions(self, data_version):
        """Provide reviewed method/parameter records for a fully admitted test snapshot."""
        for number, (indicator_id, _, _) in enumerate(INDICATORS, 1):
            proposal = self.store.propose_formula_version(
                indicator_id, data_version, "a" * 64, f"method-note-{number}", "b" * 64,
                "analyst", f"request-{number}",
            )
            self.store.review_formula_version(
                proposal["formula_version_id"], 1, "approved", "method-reviewer", "verified",
            )

    def register_test_boundary(self, boundary_version="b1"):
        self.store.register_boundary_admission(boundary_version, "c" * 64, 430.0, "EPSG:4326", accepted=True)

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

    def test_configured_task_creation_auto_queues_every_unresolved_node_once(self):
        """Break caught: a completed initial graph could leave every node waiting for manual clicks."""
        database = Path(self.directory.name) / "auto-tasks.sqlite3"
        store = GepStore(database, auto_enqueue_on_create=True)
        try:
            task = store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
            graph = store.graph(task["task_id"])
            jobs = store.connection.execute(
                "SELECT node_id,status FROM supplement_jobs WHERE task_id=?", (task["task_id"],)
            ).fetchall()
            maize = next(node for node in graph["nodes"] if node["node_key"] == "P1.maize.quantity")
            unresolved = [node for node in graph["nodes"] if node["kind"] in {"indicator", "input"} and node["node_id"] != maize["node_id"]]
            events = store.events(task["task_id"])

            self.assertEqual(len(jobs), len(unresolved))
            self.assertTrue(all(job["status"] == "queued" for job in jobs))
            self.assertEqual(maize["acquisition_status"], "acquired")
            self.assertEqual({node["acquisition_status"] for node in unresolved}, {"agent_queued"})
            self.assertIn("graph.initialized", [event["type"] for event in events])
            self.assertIn("supplement.auto_enqueued", [event["type"] for event in events])

            repeated = store.enqueue_all_supplements(task["task_id"])
            job_count = store.connection.execute(
                "SELECT COUNT(*) FROM supplement_jobs WHERE task_id=?", (task["task_id"],)
            ).fetchone()[0]
            self.assertEqual(repeated["queued_count"], 0)
            self.assertEqual(repeated["skipped_by_reason"]["already_scheduled"], len(unresolved))
            self.assertEqual(job_count, len(unresolved))
        finally:
            store.close()

    def test_configured_workflow_persists_a_structured_candidate_pending_review(self):
        """Break caught: a model response could be mistaken for an approved input or lose its source trail."""
        class Workflow:
            def run(self, work_order):
                self.work_order = work_order
                return {
                    "value": 2100,
                    "unit": "yuan/t",
                    "explanation": "从已归档的价格表提取了海淀区 2024 年玉米生产者价格。",
                    "evidence": {
                        "source_id": "price-register-2024",
                        "source_type": "official_register",
                        "locator": "table=maize;row=2024;column=producer_price",
                        "source_sha256": "a" * 64,
                        "license_or_access": "internal-review-required",
                        "tool_run_id": "dify-run-001",
                        "extracted_fragment": "玉米，2024，2100 元/吨",
                    },
                }

        workflow = Workflow()
        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "tasks.sqlite3", supplement_workflow=workflow)
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        node = self.store.node(task["task_id"], "P1.maize.producer_price")

        job = self.store.request_supplement(task["task_id"], node["node_id"], "price-request-1")
        queued = self.store.node(task["task_id"], "P1.maize.producer_price")

        self.assertEqual(job["status"], "queued")
        self.assertEqual(queued["value"], None)
        self.assertEqual(queued["acquisition_status"], "agent_queued")

        job = self.store.process_next_supplement()

        current = self.store.node(task["task_id"], "P1.maize.producer_price")
        self.assertEqual(job["status"], "completed_pending_review")
        self.assertEqual(current["value"], 2100)
        self.assertEqual(current["unit"], "yuan/t")
        self.assertEqual(current["review_status"], "pending_review")
        self.assertEqual(current["acquisition_status"], "candidate_ready")
        self.assertEqual(current["evidence"]["current"]["source_id"], "price-register-2024")
        self.assertEqual(workflow.work_order["node_id"], node["node_id"])
        self.assertEqual(workflow.work_order["year"], 2024)

    def test_supplement_refuses_to_overwrite_a_node_changed_while_workflow_was_running(self):
        """Break caught: a late model result could overwrite a human's newer evidence version."""
        database = Path(self.directory.name) / "tasks.sqlite3"
        concurrent = GepStore(database)

        class Workflow:
            def run(self, work_order):
                concurrent.revise_node(
                    work_order["node_id"], 1, 2050, "yuan/t", "operator", "manual correction arrived first", {
                        "source_id": "manual-price-register", "source_type": "official_register",
                        "locator": "row=2024", "source_sha256": "b" * 64,
                    },
                )
                return {
                    "value": 2100, "unit": "yuan/t", "explanation": "late agent result",
                    "evidence": {"source_id": "agent-price-register", "source_type": "official_register",
                                 "locator": "row=2024", "source_sha256": "a" * 64,
                                 "license_or_access": "review", "tool_run_id": "dify-run-2",
                                 "extracted_fragment": "2100"},
                }

        self.store.close()
        self.store = GepStore(database, supplement_workflow=Workflow())
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        node = self.store.node(task["task_id"], "P1.maize.producer_price")
        try:
            self.store.request_supplement(task["task_id"], node["node_id"], "price-request-race")
            job = self.store.process_next_supplement()
        finally:
            concurrent.close()

        current = self.store.node(task["task_id"], "P1.maize.producer_price")
        self.assertEqual(job["status"], "stale")
        self.assertEqual(current["value"], 2050)
        jobs = self.store.connection.execute("SELECT * FROM supplement_jobs").fetchall()
        self.assertEqual(jobs[0]["status"], "stale")

    def test_worker_records_a_configured_workflow_failure_without_creating_a_candidate(self):
        """Break caught: a source or permission failure could be mislabeled as an ordinary configuration block."""
        class Workflow:
            def run(self, _work_order):
                raise RuntimeError("Dify workflow HTTP 403; no candidate was generated")

        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "tasks.sqlite3", supplement_workflow=Workflow())
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        node = self.store.node(task["task_id"], "P1.maize.producer_price")
        self.store.request_supplement(task["task_id"], node["node_id"], "price-request-failure")

        job = self.store.process_next_supplement()
        current = self.store.node(task["task_id"], "P1.maize.producer_price")

        self.assertEqual(job["status"], "failed")
        self.assertEqual(current["value"], None)
        self.assertEqual(current["acquisition_status"], "agent_failed")
        self.assertIn("supplement.failed", [event["type"] for event in self.store.events(task["task_id"])])

    def test_workflow_persists_an_applicability_candidate_for_review(self):
        """Break caught: a model applicability opinion could be lost or treated as already approved."""
        class Workflow:
            def run(self, _work_order):
                return {
                    "outcome": "applicability_candidate", "applicability_status": "not_applicable",
                    "explanation": "海淀区为内陆行政区，需人工核对边界证据。",
                    "evidence": {
                        "source_id": "boundary-register", "source_type": "official_boundary",
                        "locator": "district=110108", "source_sha256": "c" * 64,
                        "license_or_access": "internal-review", "tool_run_id": "deepseek-1",
                        "extracted_fragment": "海淀区行政边界",
                    },
                }

        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "tasks.sqlite3", supplement_workflow=Workflow())
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        node = self.store.node(task["task_id"], "R4")
        self.store.request_supplement(task["task_id"], node["node_id"], "applicability-1")

        job = self.store.process_next_supplement()
        current = self.store.node(task["task_id"], "R4")

        self.assertEqual(job["status"], "completed_pending_review")
        self.assertEqual(current["value"], None)
        self.assertEqual(current["applicability_status"], "not_applicable")
        self.assertEqual(current["review_status"], "pending_review")
        self.assertEqual(current["acquisition_status"], "candidate_ready")

    def test_workflow_persists_manual_intervention_without_a_value(self):
        """Break caught: a missing source could remain pending forever or be converted to zero."""
        class Workflow:
            def run(self, _work_order):
                return {
                    "outcome": "manual_required", "reason_code": "source_missing",
                    "explanation": "未找到 2024 年生产者价格，需要人工提供价格台账。",
                }

        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "tasks.sqlite3", supplement_workflow=Workflow())
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        node = self.store.node(task["task_id"], "P1.maize.producer_price")
        self.store.request_supplement(task["task_id"], node["node_id"], "manual-required-1")

        job = self.store.process_next_supplement()
        current = self.store.node(task["task_id"], "P1.maize.producer_price")
        events = self.store.events(task["task_id"])

        self.assertEqual(job["status"], "manual_required")
        self.assertEqual(current["value"], None)
        self.assertEqual(current["acquisition_status"], "manual_required")
        self.assertEqual(current["review_status"], "unsubmitted")
        self.assertEqual(current["evidence"]["current"]["reason_code"], "source_missing")
        self.assertIn("supplement.manual_required", [event["type"] for event in events])

    def test_workflow_persists_research_complete_without_manual_action(self):
        """Break caught: a completed source search with no fact could still flood the manual queue."""
        class Workflow:
            def run(self, _work_order):
                return {
                    "outcome": "research_complete", "risk_tier": "GAP",
                    "explanation": "已检查本地目录和官方来源，尚无该字段。",
                    "searched_tools": ["local_catalog", "official_registry"],
                    "next_action": "等待主管部门数据或后续自动重试",
                }

        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "tasks.sqlite3", supplement_workflow=Workflow())
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        node = self.store.node(task["task_id"], "P1.maize.producer_price")
        self.store.request_supplement(task["task_id"], node["node_id"], "research-gap-1")

        job = self.store.process_next_supplement()
        current = self.store.node(task["task_id"], "P1.maize.producer_price")

        self.assertEqual(job["status"], "research_complete")
        self.assertEqual(current["acquisition_status"], "research_complete")
        self.assertEqual(current["review_status"], "unsubmitted")
        self.assertEqual(current["evidence"]["current"]["risk_tier"], "GAP")
        self.assertIn("research.completed", [event["type"] for event in self.store.events(task["task_id"])])

    def test_risk_a_candidate_is_auto_verified_while_b_remains_pending_review(self):
        """Break caught: every candidate could still demand the same per-node manual review."""
        class Workflow:
            def __init__(self):
                self.tier = "A"

            def run(self, _work_order):
                return {
                    "outcome": "candidate", "risk_tier": self.tier, "auto_adopt": self.tier == "A",
                    "value": 2100, "unit": "yuan/t", "explanation": "官方来源已校验。",
                    "evidence": {"source_id": "official", "source_type": "official_government", "locator": "row=1",
                                 "source_sha256": "a" * 64, "license_or_access": "public", "tool_run_id": "research-1",
                                 "extracted_fragment": "2100"},
                }

        workflow = Workflow()
        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "tasks.sqlite3", supplement_workflow=workflow)
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        first = self.store.node(task["task_id"], "P1.maize.producer_price")
        self.store.request_supplement(task["task_id"], first["node_id"], "risk-a")
        self.store.process_next_supplement()
        auto = self.store.node(task["task_id"], "P1.maize.producer_price")

        workflow.tier = "B"
        second = self.store.node(task["task_id"], "P1.maize.intermediate_cost")
        self.store.request_supplement(task["task_id"], second["node_id"], "risk-b")
        self.store.process_next_supplement()
        review = self.store.node(task["task_id"], "P1.maize.intermediate_cost")

        self.assertEqual(auto["review_status"], "auto_verified")
        self.assertEqual(auto["evidence"]["current"]["risk_tier"], "A")
        self.assertEqual(review["review_status"], "pending_review")
        self.assertEqual(review["evidence"]["current"]["risk_tier"], "B")

    def test_research_v2_reschedules_only_legacy_source_missing_manual_nodes(self):
        """Break caught: old blanket manual states could remain stuck or overwrite genuine expert decisions."""
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        source_missing = self.store.node(task["task_id"], "R1.precipitation")
        expert = self.store.node(task["task_id"], "R1.surface_runoff")
        for node, reason in ((source_missing, "source_missing"), (expert, "method_choice")):
            self.store.connection.execute(
                "UPDATE nodes SET acquisition_status='manual_required',evidence_json=?,version=2 WHERE node_id=?",
                (json.dumps({"current": {"result_type": "manual_required", "reason_code": reason}}), node["node_id"]),
            )
        self.store.connection.commit()

        result = self.store.enqueue_all_supplements(task["task_id"], scheduler_version="research-v2")
        source_missing = self.store.node(task["task_id"], "R1.precipitation")
        expert = self.store.node(task["task_id"], "R1.surface_runoff")

        self.assertEqual(source_missing["acquisition_status"], "agent_queued")
        self.assertEqual(expert["acquisition_status"], "manual_required")
        self.assertGreater(result["queued_count"], 0)

    def _prepare_batch_review_states(self, task_id):
        states = {
            "P1.maize.producer_price": ("candidate_ready", "auto_verified", "A"),
            "P1.maize.intermediate_cost": ("candidate_ready", "pending_review", "B"),
            "R1.precipitation": ("research_complete", "unsubmitted", "GAP"),
            "R1.surface_runoff": ("manual_required", "unsubmitted", "C"),
        }
        for node_key, (acquisition, review, tier) in states.items():
            node = self.store.node(task_id, node_key)
            evidence_json = json.dumps({"current": {"risk_tier": tier, "result_type": "test"}})
            value_json = "1" if tier in {"A", "B"} else None
            self.store.connection.execute(
                "UPDATE nodes SET acquisition_status=?,review_status=?,evidence_json=?,value_json=?,unit='test-unit' WHERE node_id=?",
                (acquisition, review, evidence_json, value_json, node["node_id"]),
            )
        self.store.connection.commit()

    def test_batch_review_preview_separates_reviewable_and_hard_blockers(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        self._prepare_batch_review_states(task["task_id"])

        preview = self.store.batch_review_preview(task["task_id"])

        self.assertIn("P1.maize.producer_price", preview["auto_ready_nodes"])
        self.assertIn("P1.maize.intermediate_cost", preview["review_ready_nodes"])
        self.assertIn("R1.precipitation", preview["research_gap_nodes"])
        self.assertIn("R1.surface_runoff", preview["expert_intervention_nodes"])
        self.assertIn("R1.precipitation", preview["hard_blocker_nodes"])
        self.assertEqual(preview["reviewable_count"], 3)  # includes preloaded maize quantity

    def test_cancelled_batch_review_does_not_mutate_nodes_or_audit_tables(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        self._prepare_batch_review_states(task["task_id"])
        version = self.store.graph(task["task_id"])["task"]["graph_version"]

        result = self.store.create_batch_review(
            task["task_id"], version, False, "reviewer", "逐项审核",
        )

        self.assertEqual(result["status"], "individual_review_required")
        self.assertEqual(self.store.node(task["task_id"], "P1.maize.producer_price")["review_status"], "auto_verified")
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM batch_reviews").fetchone()[0], 0)

    def test_batch_confirmation_approves_a_and_b_but_preserves_blockers(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        self._prepare_batch_review_states(task["task_id"])
        version = self.store.graph(task["task_id"])["task"]["graph_version"]

        result = self.store.create_batch_review(
            task["task_id"], version, True, "batch-reviewer", "确认自动核验与中风险候选",
        )

        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["approved_count"], 3)
        self.assertEqual(self.store.node(task["task_id"], "P1.maize.producer_price")["review_status"], "approved")
        self.assertEqual(self.store.node(task["task_id"], "P1.maize.intermediate_cost")["review_status"], "approved")
        self.assertEqual(self.store.node(task["task_id"], "R1.precipitation")["review_status"], "unsubmitted")
        self.assertEqual(self.store.node(task["task_id"], "R1.surface_runoff")["review_status"], "unsubmitted")
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM batch_review_nodes WHERE batch_review_id=?", (result["batch_review_id"],)
        ).fetchone()[0], 3)
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM reviews WHERE reviewer='batch-reviewer'"
        ).fetchone()[0], 3)

    def test_stale_batch_graph_version_is_all_or_nothing(self):
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        self._prepare_batch_review_states(task["task_id"])

        with self.assertRaises(ConflictError):
            self.store.create_batch_review(task["task_id"], 999, True, "reviewer", "stale")

        self.assertEqual(self.store.node(task["task_id"], "P1.maize.producer_price")["review_status"], "auto_verified")
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM batch_reviews").fetchone()[0], 0)

    def test_workflow_failure_reason_does_not_persist_raw_provider_text(self):
        """Break caught: a provider exception could leak a response body into SQLite events."""
        class Workflow:
            def run(self, _work_order):
                raise RuntimeError("raw-provider-body-with-secret")

        self.store.close()
        self.store = GepStore(Path(self.directory.name) / "tasks.sqlite3", supplement_workflow=Workflow())
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "reference-2024-v0.1")
        node = self.store.node(task["task_id"], "P1.maize.producer_price")
        self.store.request_supplement(task["task_id"], node["node_id"], "failure-redaction-1")

        job = self.store.process_next_supplement()
        events = self.store.events(task["task_id"])

        self.assertEqual(job["status"], "failed")
        self.assertNotIn("raw-provider-body-with-secret", str(job))
        self.assertNotIn("raw-provider-body-with-secret", str(events))

    def test_existing_task_database_migrates_to_include_graph_version(self):
        """Break caught: the deployed pre-versioned SQLite task table could not support task-center summaries."""
        legacy_path = Path(self.directory.name) / "legacy-tasks.sqlite3"
        with sqlite3.connect(legacy_path) as legacy:
            legacy.execute(
                "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, region_code TEXT NOT NULL, year INTEGER NOT NULL, "
                "boundary_version TEXT NOT NULL, standard_version TEXT NOT NULL, data_version TEXT NOT NULL, "
                "created_utc TEXT NOT NULL)"
            )
            legacy.execute(
                "INSERT INTO tasks VALUES ('old', '110108', 2024, 'b1', 'GB/T 46869-2025', "
                "'reference-2024-v0.1', '2026-09-22T00:00:00+00:00')"
            )

        migrated = GepStore(legacy_path)
        try:
            columns = {row[1] for row in migrated.connection.execute("PRAGMA table_info(tasks)")}
        finally:
            migrated.close()

        self.assertIn("graph_version", columns)

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
        self.approve_all_formula_versions("audited-2024-v1")
        self.register_test_boundary()

        snapshot = self.store.create_snapshot(task["task_id"])

        self.assertTrue(snapshot["snapshot_id"])

    def test_snapshot_requires_an_approved_formula_version_for_every_applicable_indicator(self):
        """Break caught: reviewed input data could freeze despite unreviewed methods or parameters."""
        self.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.store.connection.commit()

        with self.assertRaises(SnapshotBlocked) as raised:
            self.store.create_snapshot(task["task_id"])

        self.assertIn("formula_version:P1", raised.exception.blocking)
        self.assertIn("formula_version:C3", raised.exception.blocking)

    def test_snapshot_requires_a_reviewed_boundary_version_and_freezes_its_hash(self):
        """Break caught: an arbitrary boundary label could enter a formal 2024 full-region snapshot."""
        self.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.store.connection.commit()
        self.approve_all_formula_versions("audited-2024-v1")

        with self.assertRaises(SnapshotBlocked) as raised:
            self.store.create_snapshot(task["task_id"])
        self.assertIn("boundary_version:b1", raised.exception.blocking)

        self.register_test_boundary()
        snapshot = self.store.create_snapshot(task["task_id"])
        graph_json = self.store.connection.execute(
            "SELECT graph_json FROM snapshots WHERE snapshot_id=?", (snapshot["snapshot_id"],)
        ).fetchone()["graph_json"]

        self.assertIn('"geometry_sha256": "' + "c" * 64 + '"', graph_json)

    def test_run_rejects_an_unknown_snapshot(self):
        """Break caught: a caller could launch a calculation without frozen reviewed inputs."""
        with self.assertRaises(KeyError):
            self.store.create_run("missing-snapshot", "request-1")

    def test_formula_version_rejects_an_indicator_outside_the_22_card_catalog(self):
        """Break caught: an arbitrary formula could be inserted without a GB/T method-card identity."""
        with self.assertRaises(ValueError):
            self.store.propose_formula_version(
                "X99", "audited-2024-v1", "a" * 64, "source-a", "b" * 64, "analyst", "request-1"
            )

    def test_formula_version_is_persisted_pending_review_with_method_and_parameter_hashes(self):
        """Break caught: a formula proposal could lose the method-card or parameter provenance needed for review."""
        proposal = self.store.propose_formula_version(
            "R6", "audited-2024-v1", "a" * 64, "carbon-method-note", "b" * 64, "analyst", "request-1"
        )
        stored = self.store.formula_version(proposal["formula_version_id"])

        self.assertEqual(proposal["indicator_id"], "R6")
        self.assertEqual(proposal["method_id"], "regulating.carbon_sequestration.v1")
        self.assertEqual(proposal["parameter_manifest_sha256"], "a" * 64)
        self.assertEqual(proposal["source_sha256"], "b" * 64)
        self.assertEqual(proposal["status"], "pending_review")
        self.assertEqual(stored, proposal)

    def test_formula_version_review_approves_a_specific_pending_version_with_audit_record(self):
        """Break caught: a reviewer could approve an unspecified formula version without an audit trail."""
        proposal = self.store.propose_formula_version(
            "R6", "audited-2024-v1", "a" * 64, "carbon-method-note", "b" * 64, "analyst", "request-1"
        )

        approved = self.store.review_formula_version(
            proposal["formula_version_id"], 1, "approved", "method-reviewer", "GB/T reference and parameters checked"
        )
        history = self.store.formula_review_history(proposal["formula_version_id"])

        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["review_version"], 2)
        self.assertEqual(history[0]["reviewer"], "method-reviewer")
        self.assertEqual(history[0]["decision"], "approved")

    def test_formula_version_proposal_is_idempotent(self):
        """Break caught: a retry could create two competing pending formula versions."""
        first = self.store.propose_formula_version(
            "R6", "audited-2024-v1", "a" * 64, "carbon-method-note", "b" * 64, "analyst", "request-1"
        )
        retried = self.store.propose_formula_version(
            "R6", "audited-2024-v1", "a" * 64, "carbon-method-note", "b" * 64, "analyst", "request-1"
        )

        self.assertEqual(first["formula_version_id"], retried["formula_version_id"])

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
        self.approve_all_formula_versions("audited-2024-v1")
        self.register_test_boundary()

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
        self.approve_all_formula_versions("audited-2024-v1")
        self.register_test_boundary()
        snapshot = self.store.create_snapshot(task["task_id"])

        first = self.store.create_run(snapshot["snapshot_id"], "run-request-1")
        retried = self.store.create_run(snapshot["snapshot_id"], "run-request-1")
        events = [event for event in self.store.events(task["task_id"]) if event["type"] == "run.blocked"]

        self.assertEqual(first["run_id"], retried["run_id"])
        self.assertEqual(first["status"], "blocked")
        self.assertTrue(first["reason"])
        self.assertEqual(len(events), 1)

    def test_new_run_links_to_prior_run_after_a_reviewed_input_correction(self):
        """Break caught: correcting a price could erase its predecessor run and make the recalculation untraceable."""
        self.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        self.store.connection.commit()
        self.approve_all_formula_versions("audited-2024-v1")
        self.register_test_boundary()
        first_snapshot = self.store.create_snapshot(task["task_id"])
        first_run = self.store.create_run(first_snapshot["snapshot_id"], "baseline-run")
        price = self.store.node(task["task_id"], "P1.maize.producer_price")
        revised = self.store.revise_node(
            price["node_id"], price["version"], 101.0, "元/t", "analyst", "2024 price correction",
            {"source_id": "approved-price-ledger", "source_type": "manual_correction", "locator": "row 4"},
        )
        self.store.review_node(revised["node_id"], revised["version"], "approved", "reviewer", "checked")
        second_snapshot = self.store.create_snapshot(task["task_id"])

        second_run = self.store.create_run(second_snapshot["snapshot_id"], "price-revision-run")
        chain = self.store.run_chain(second_run["run_id"])

        self.assertEqual(self.store.run(second_run["run_id"])["parent_run_id"], first_run["run_id"])
        self.assertEqual(chain["parent_run_id"], first_run["run_id"])
        self.assertIsNone(self.store.run(first_run["run_id"])["parent_run_id"])

    def test_run_chain_records_partial_calculation_and_exact_formal_blockers(self):
        """Break caught: a blocked run could discard available deterministic results or invent a total."""
        self.store.register_data_admission("audited-2024-v1", "a" * 64, accepted=True)
        task = self.store.create_task("110108", 2024, "b1", "GB/T 46869-2025", "audited-2024-v1")
        self.store.connection.execute(
            "UPDATE nodes SET value_json='1', review_status='approved', applicability_status='applicable' WHERE task_id=? AND required=1",
            (task["task_id"],),
        )
        values = {
            "P1.maize.quantity": (10_000, "t/a"),
            "P1.maize.producer_price": (100, "元/t"),
            "P1.maize.intermediate_cost": (300_000, "元/a"),
            "P1.maize.labor": (200_000, "元/a"),
            "P1.maize.depreciation": (80_000, "元/a"),
            "P1.maize.tax_net": (20_000, "元/a"),
            "P1.maize.capital_return": (50_000, "元/a"),
        }
        for node_key, (value, unit) in values.items():
            self.store.connection.execute(
                "UPDATE nodes SET value_json=?,unit=? WHERE task_id=? AND node_key=?",
                (str(value), unit, task["task_id"], node_key),
            )
        self.store.connection.commit()
        self.approve_all_formula_versions("audited-2024-v1")
        self.register_test_boundary()
        snapshot = self.store.create_snapshot(task["task_id"])

        run = self.store.create_run(snapshot["snapshot_id"], "partial-run-1")
        chain = self.store.run_chain(run["run_id"])

        self.assertEqual(run["status"], "blocked")
        self.assertIsNone(chain["calculation"]["formal_gep_value_yuan"])
        self.assertEqual(chain["calculation"]["item_results"]["P1"]["value_yuan"], 350_000)
        self.assertIn("P4:producer_price", chain["calculation"]["blocking_nodes"])
        self.assertIn("P4:production_cost", chain["calculation"]["blocking_nodes"])

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
