import tempfile
import unittest
from pathlib import Path

from gep.agent.store import AgentStore
from gep.agent.tools import ToolRegistry
from gep.agent.types import AgentAction, ToolCall, ToolResult, ToolSpec


def spec(tool_id, required, *, network=False):
    return ToolSpec(
        tool_id=tool_id, title_zh=tool_id, description=tool_id,
        input_schema={"type": "object", "required": list(required), "properties": {key: {} for key in required}},
        output_schema={"type": "object"}, risk_level="medium" if network else "low", network_access=network,
    )


class ScriptedPlanner:
    def __init__(self, actions): self.actions = list(actions)
    def next_action(self, _context): return self.actions.pop(0)


class NeverPlanner:
    def next_action(self, _context):
        raise AssertionError("planner must not run when a reusable observation exists")


class AgentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Path(self.tmp.name) / "agent.sqlite3"
        self.work_order = {
            "task_id": "task-1", "node_id": "node-1", "node_version": 1,
            "node_key": "R1.ecosystem_area", "node_label": "ecosystem_area", "node_kind": "input",
            "indicator_id": "R1", "region_code": "110108", "year": 2024,
            "data_version": "smart-data-2024-v1",
        }

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def observation(value=23044.15, source="obs-1", evidence_class="public_calculation"):
        return {
            "observation_id": source, "metric": "ecosystem_area", "value": value, "unit": "hm2",
            "region_code": "110108", "year": 2024, "method_id": "worldcover.area.v1",
            "evidence_class": evidence_class,
        }

    def workflow_with_observations(self, records, planner=None):
        from gep.agent.workflow import AgentWorkflow

        registry = ToolRegistry()
        registry.register(
            spec("smart.observation.search", ("metric", "year", "region_code")),
            lambda _arguments: ToolResult(status="ok", data={"records": records}),
        )
        return AgentWorkflow(self.database, registry, planner or NeverPlanner())

    def test_same_work_order_retry_does_not_duplicate_ledger(self):
        """Break caught: a worker retry could duplicate runs, evidence, or decisions."""
        workflow = self.workflow_with_observations([self.observation()])
        try:
            first = workflow.run(dict(self.work_order))
            second = workflow.run(dict(self.work_order))
            self.assertEqual(first, second)
            self.assertEqual(workflow.store.connection.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0], 1)
            self.assertEqual(workflow.store.connection.execute("SELECT COUNT(*) FROM agent_decisions").fetchone()[0], 1)
        finally:
            workflow.close()

    def test_model_failure_does_not_block_reusable_local_observation(self):
        """Break caught: a DeepSeek outage could hide a value already present in the data backend."""
        workflow = self.workflow_with_observations([self.observation()])
        try:
            result = workflow.run(dict(self.work_order))
            self.assertEqual(result["outcome"], "candidate")
            self.assertEqual(result["value"], 23044.15)
            self.assertEqual(result["risk_tier"], "B")
            self.assertEqual(result["searched_tools"], ["smart.observation.search"])
        finally:
            workflow.close()

    def test_search_failure_returns_specific_error_and_next_step(self):
        """Break caught: a search outage could collapse into a vague wait-for-data status."""
        from gep.agent.workflow import AgentWorkflow

        registry = ToolRegistry()
        registry.register(
            spec("smart.observation.search", ("metric", "year", "region_code")),
            lambda _arguments: ToolResult(status="ok", data={"records": []}),
        )
        registry.register(
            spec("web.search", ("query",), network=True),
            lambda _arguments: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
        )
        workflow = AgentWorkflow(
            self.database, registry,
            ScriptedPlanner([AgentAction(kind="call_tool", tool_id="web.search", arguments={"query": "海淀生态公报"})]),
        )
        try:
            result = workflow.run(dict(self.work_order))
            self.assertEqual(result["outcome"], "research_complete")
            self.assertEqual(result["tool_error"], "RuntimeError")
            self.assertIn("web.search", result["searched_tools"])
            self.assertEqual(result["next_action"], "检查对应工具服务后自动重试")
        finally:
            workflow.close()

    def test_successful_evidence_is_kept_when_later_search_fails(self):
        """Break caught: a later network failure could erase evidence already obtained from a local tool."""
        from gep.agent.workflow import AgentWorkflow

        registry = ToolRegistry()
        registry.register(
            spec("smart.observation.search", ("metric", "year", "region_code")),
            lambda _arguments: ToolResult(status="ok", data={"records": []}),
        )
        local_evidence = {
            "source_id": "local-1", "source_type": "admitted_record", "locator": "表 2",
            "source_sha256": "a" * 64, "license_or_access": "project",
            "tool_run_id": "local:1", "extracted_fragment": "面积 23044.15 hm2",
        }
        registry.register(
            spec("local.catalog.search", ("work_order",)),
            lambda _arguments: ToolResult(status="ok", data={"records": [local_evidence]}, evidence=(local_evidence,)),
        )
        registry.register(
            spec("web.search", ("query",), network=True),
            lambda _arguments: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
        )
        planner = ScriptedPlanner([
            AgentAction(kind="call_tool", tool_id="local.catalog.search", arguments={"work_order": self.work_order}),
            AgentAction(kind="call_tool", tool_id="web.search", arguments={"query": "海淀生态公报"}),
        ])
        workflow = AgentWorkflow(self.database, registry, planner)
        try:
            result = workflow.run(dict(self.work_order))
            self.assertEqual(result["outcome"], "research_complete")
            self.assertEqual(workflow.store.connection.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0], 1)
            stored = workflow.store.connection.execute("SELECT source_id FROM evidence_items").fetchone()[0]
            self.assertEqual(stored, "local-1")
        finally:
            workflow.close()

    def test_conflicting_observations_become_one_human_work_package(self):
        """Break caught: the workflow could silently choose the first of two conflicting backend values."""
        workflow = self.workflow_with_observations([
            self.observation(value=23044.15, source="obs-1"),
            self.observation(value=21000.0, source="obs-2"),
        ])
        try:
            result = workflow.run(dict(self.work_order))
            self.assertEqual(result["outcome"], "manual_required")
            self.assertEqual(result["reason_code"], "source_conflict")
            self.assertEqual(result["result_class"], "needs_business_decision")
            self.assertEqual(set(result["human_action"]["source_ids"]), {"obs-1", "obs-2"})
        finally:
            workflow.close()

    def test_tier_c_candidate_is_valid_for_demo_but_never_auto_adopted(self):
        """Break caught: a model estimate could be rejected entirely or accidentally enter formal auto-adoption."""
        from gep.task_service import GepStore

        candidate = GepStore._workflow_result({
            "outcome": "candidate", "risk_tier": "C", "auto_adopt": True,
            "value": 23044.15, "unit": "hm2", "explanation": "跨区域代理，仅用于智能试算。",
            "evidence": {
                "source_id": "paper-1", "source_type": "paper", "locator": "第 3 页",
                "source_sha256": "b" * 64, "license_or_access": "open-access",
                "tool_run_id": "knowledge:1", "extracted_fragment": "代理参数",
            },
        }, "input")
        self.assertEqual(candidate["risk_tier"], "C")
        self.assertFalse(candidate["auto_adopt"])
        self.assertTrue(candidate["demo_auto_adopt"])


if __name__ == "__main__":
    unittest.main()
