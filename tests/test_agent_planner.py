import unittest

from gep.agent.tools import ToolRegistry
from gep.agent.types import AgentAction, ToolResult, ToolSpec


class Provider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, system_prompt, payload):
        self.calls.append((system_prompt, payload))
        return self.responses.pop(0)


class Fallback:
    def __init__(self): self.calls = 0
    def next_action(self, _context):
        self.calls += 1
        return AgentAction(kind="manual_required", payload={"reason_code": "planner_unavailable"})


def registry():
    value = ToolRegistry()
    value.register(
        ToolSpec(
            tool_id="safe.read", title_zh="安全读取", description="Read one source",
            input_schema={"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
            output_schema={"type": "object"}, risk_level="medium", network_access=True,
        ),
        lambda arguments: ToolResult(status="ok", data={"url": arguments["url"]}),
    )
    return value


class DeepSeekPlannerTests(unittest.TestCase):
    def context(self):
        return {"work_order": {"node_id": "n1", "node_label": "生态系统面积"}, "observations": (), "round": 1}

    def test_valid_registered_action_is_returned(self):
        """Break caught: valid structured model output could be lost or reshaped incorrectly."""
        from gep.agent.planner import DeepSeekPlanner

        provider = Provider([{
            "kind": "call_tools",
            "tool_calls": [{"tool_id": "safe.read", "arguments": {"url": "https://example.com"}}],
        }])
        action = DeepSeekPlanner(provider, registry()).next_action(self.context())
        self.assertEqual(action.kind, "call_tools")
        self.assertEqual(action.tool_calls[0].tool_id, "safe.read")
        self.assertEqual(provider.calls[0][1]["tools"][0]["tool_id"], "safe.read")

    def test_unknown_tool_is_rejected_before_valid_retry(self):
        """Break caught: the model could invent shell or database tools outside the registry."""
        from gep.agent.planner import DeepSeekPlanner

        provider = Provider([
            {"kind": "call_tool", "tool_id": "shell.execute", "arguments": {"command": "whoami"}},
            {"kind": "complete", "payload": {"message": "没有执行未知工具"}},
        ])
        action = DeepSeekPlanner(provider, registry()).next_action(self.context())
        self.assertEqual(action.kind, "complete")
        self.assertEqual(len(provider.calls), 2)

    def test_wrong_field_type_is_retried_once(self):
        """Break caught: malformed model arguments could reach the tool registry."""
        from gep.agent.planner import DeepSeekPlanner

        provider = Provider([
            {"kind": "call_tool", "tool_id": "safe.read", "arguments": "not-an-object"},
            {"kind": "call_tool", "tool_id": "safe.read", "arguments": {"url": "https://example.com"}},
        ])
        action = DeepSeekPlanner(provider, registry()).next_action(self.context())
        self.assertEqual(action.tool_id, "safe.read")
        self.assertEqual(len(provider.calls), 2)

    def test_second_invalid_response_uses_template_fallback(self):
        """Break caught: repeated invalid JSON plans could fail the whole deterministic workflow."""
        from gep.agent.planner import DeepSeekPlanner

        provider = Provider([
            {"kind": "call_tool", "tool_id": "safe.read", "arguments": []},
            {"kind": "unexpected"},
        ])
        fallback = Fallback()
        action = DeepSeekPlanner(provider, registry(), fallback=fallback).next_action(self.context())
        self.assertEqual(action.kind, "manual_required")
        self.assertEqual(action.payload["reason_code"], "planner_unavailable")
        self.assertEqual(fallback.calls, 1)

    def test_explanation_uses_calculation_numbers_not_model_numbers(self):
        """Break caught: fluent model text could contradict the deterministic calculator result."""
        from gep.agent.planner import GroundedExplainer

        provider = Provider([{"summary_zh": "模型声称结果是 999 吨。"}])
        explanation = GroundedExplainer(provider).explain({
            "method_id": "R7.oxygen_link.demo.v1",
            "formula": "CO2 × 32/44",
            "inputs": [{"field": "carbon_sequestration_rate", "value": 44.0, "unit": "tCO2/a"}],
            "result": {"value": 32.0, "unit": "tO2/a"},
        })
        self.assertNotIn("999", explanation)
        self.assertIn("44.0 tCO2/a", explanation)
        self.assertIn("32.0 tO2/a", explanation)
        self.assertIn("CO2 × 32/44", explanation)


if __name__ == "__main__":
    unittest.main()
