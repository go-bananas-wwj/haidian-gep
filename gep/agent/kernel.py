"""Bounded plan/call/observe loop for the native GEP agent."""
from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from .tools import ToolRegistry
from .types import AgentAction, AgentBudget, AgentOutcome, ToolCall, ToolResult


class AgentKernel:
    def __init__(
        self,
        registry: ToolRegistry,
        planner: Any,
        validator: Any,
        ledger: Any,
        *,
        budget: AgentBudget = AgentBudget(),
        clock: Callable[[], float] = time.monotonic,
    ):
        self.registry = registry
        self.planner = planner
        self.validator = validator
        self.ledger = ledger
        self.budget = budget
        self.clock = clock

    @staticmethod
    def _calls(action: AgentAction) -> tuple[ToolCall, ...]:
        if action.tool_calls:
            return action.tool_calls
        if action.tool_id:
            return (ToolCall(action.tool_id, action.arguments),)
        return ()

    def _outcome(
        self,
        status: str,
        *,
        result: Mapping[str, Any],
        observations: list[ToolResult],
        reason: str,
        tool_calls: int,
        rounds: int,
        started: float,
        now: float,
    ) -> AgentOutcome:
        outcome = AgentOutcome(
            status=status,
            result=dict(result),
            observations=tuple(observations),
            reason=reason,
            tool_calls=tool_calls,
            rounds=rounds,
            elapsed_ms=max(0, int((now - started) * 1000)),
        )
        self.ledger.record("outcome", outcome)
        return outcome

    def run(self, work_order: Mapping[str, Any]) -> AgentOutcome:
        started = self.clock()
        observations: list[ToolResult] = []
        tool_calls = 0
        rounds = 0

        while True:
            now = self.clock()
            if now - started >= self.budget.max_seconds:
                return self._outcome(
                    "budget_exhausted", result={}, observations=observations,
                    reason="elapsed_budget", tool_calls=tool_calls, rounds=rounds,
                    started=started, now=now,
                )
            if rounds >= self.budget.max_rounds:
                return self._outcome(
                    "budget_exhausted", result={}, observations=observations,
                    reason="round_budget", tool_calls=tool_calls, rounds=rounds,
                    started=started, now=now,
                )

            validation = self.validator.validate(work_order, tuple(observations))
            context = {
                "work_order": dict(work_order),
                "observations": tuple(observations),
                "validation": validation,
                "available_tools": self.registry.specs(),
                "round": rounds + 1,
                "remaining_tool_calls": self.budget.max_tool_calls - tool_calls,
            }
            action = self.planner.next_action(context)
            if not isinstance(action, AgentAction):
                raise TypeError("planner must return AgentAction")
            rounds += 1
            self.ledger.record("plan", {"round": rounds, "action": action})
            now = self.clock()
            if now - started >= self.budget.max_seconds:
                return self._outcome(
                    "budget_exhausted", result={}, observations=observations,
                    reason="elapsed_budget", tool_calls=tool_calls, rounds=rounds,
                    started=started, now=now,
                )

            if action.kind == "complete":
                return self._outcome(
                    "complete", result=action.payload, observations=observations,
                    reason="", tool_calls=tool_calls, rounds=rounds,
                    started=started, now=now,
                )
            if action.kind == "manual_required":
                return self._outcome(
                    "manual_required", result=action.payload, observations=observations,
                    reason=str(action.payload.get("reason_code", "manual_required")),
                    tool_calls=tool_calls, rounds=rounds, started=started, now=now,
                )
            if action.kind not in {"call_tool", "call_tools"}:
                return self._outcome(
                    "failed", result=action.payload, observations=observations,
                    reason="invalid_action", tool_calls=tool_calls, rounds=rounds,
                    started=started, now=now,
                )

            calls = self._calls(action)
            if not calls:
                return self._outcome(
                    "failed", result={}, observations=observations,
                    reason="empty_tool_plan", tool_calls=tool_calls, rounds=rounds,
                    started=started, now=now,
                )
            for call in calls:
                now = self.clock()
                if now - started >= self.budget.max_seconds:
                    return self._outcome(
                        "budget_exhausted", result={}, observations=observations,
                        reason="elapsed_budget", tool_calls=tool_calls, rounds=rounds,
                        started=started, now=now,
                    )
                if tool_calls >= self.budget.max_tool_calls:
                    return self._outcome(
                        "budget_exhausted", result={}, observations=observations,
                        reason="tool_call_budget", tool_calls=tool_calls, rounds=rounds,
                        started=started, now=now,
                    )
                result = self.registry.call(call.tool_id, call.arguments)
                tool_calls += 1
                observations.append(result)
                self.ledger.record(
                    "tool_result",
                    {"sequence": tool_calls, "tool_id": call.tool_id, "result": result},
                )
