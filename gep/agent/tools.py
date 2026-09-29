"""Explicit tool registration and small JSON-schema validation subset."""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable, Mapping

from .types import ToolResult, ToolSpec


ToolHandler = Callable[[Mapping[str, Any]], ToolResult]


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, (list, tuple))
    raise ValueError(f"unsupported schema type: {expected}")


def validate_schema(value: Any, schema: Mapping[str, Any], *, path: str = "value") -> None:
    expected = schema.get("type")
    if expected and not _matches_type(value, str(expected)):
        raise ValueError(f"{path} must be {expected}")
    if expected == "object":
        required = schema.get("required", ())
        for key in required:
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        for key, child_schema in schema.get("properties", {}).items():
            if key in value:
                validate_schema(value[key], child_schema, path=str(key))
    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            validate_schema(item, schema["items"], path=f"{path}[{index}]")


class ToolRegistry:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._tools: dict[str, tuple[ToolSpec, ToolHandler]] = {}
        self._clock = clock

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.tool_id in self._tools:
            raise ValueError(f"tool already registered: {spec.tool_id}")
        self._tools[spec.tool_id] = (spec, handler)

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(spec for spec, _handler in self._tools.values())

    def call(self, tool_id: str, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            spec, handler = self._tools[tool_id]
        except KeyError as error:
            raise KeyError(f"unknown tool: {tool_id}") from error
        validate_schema(arguments, spec.input_schema, path="arguments")
        started = self._clock()
        result = handler(dict(arguments))
        if not isinstance(result, ToolResult):
            raise TypeError(f"tool {tool_id} must return ToolResult")
        validate_schema(result.data, spec.output_schema, path="result.data")
        elapsed_ms = max(0, int((self._clock() - started) * 1000))
        return replace(result, elapsed_ms=elapsed_ms)
