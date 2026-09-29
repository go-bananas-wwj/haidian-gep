"""Immutable value objects shared by the native agent runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    title_zh: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    risk_level: str
    network_access: bool

    def __post_init__(self) -> None:
        if not self.tool_id or not self.title_zh:
            raise ValueError("tool_id and title_zh are required")


@dataclass(frozen=True)
class ToolResult:
    status: str
    data: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    elapsed_ms: int = 0


@dataclass(frozen=True)
class ToolCall:
    tool_id: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentAction:
    kind: str
    tool_id: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    tool_calls: tuple[ToolCall, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentBudget:
    max_tool_calls: int = 8
    max_rounds: int = 3
    max_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_tool_calls <= 0 or self.max_rounds <= 0 or self.max_seconds <= 0:
            raise ValueError("agent budget values must be positive")


@dataclass(frozen=True)
class AgentOutcome:
    status: str
    result: Mapping[str, Any] = field(default_factory=dict)
    observations: tuple[ToolResult, ...] = ()
    reason: str = ""
    tool_calls: int = 0
    rounds: int = 0
    elapsed_ms: int = 0
