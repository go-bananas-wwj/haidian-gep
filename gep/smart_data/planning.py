"""Deterministic plan resolution and safe execution over immutable observations."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable

from . import calculators
from .methods import METHOD_BY_TARGET, SMART_METHODS
from .types import CalculationPlan, CalculationResult, ObservationRecord


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _records(observations: Iterable[ObservationRecord | dict[str, Any]]) -> list[ObservationRecord]:
    result = []
    for item in observations:
        if isinstance(item, ObservationRecord): result.append(item)
        else:
            value = item.get("value") if isinstance(item, dict) else None
            if isinstance(value, float) and not math.isfinite(value): raise ValueError("non-finite observation value")
            result.append(ObservationRecord.from_dict(item))
    return result


def resolve_plan(
    work_order: dict[str, Any], observations: Iterable[ObservationRecord | dict[str, Any]], provider: Any = None,
) -> CalculationPlan | None:
    method = METHOD_BY_TARGET.get((work_order.get("indicator_id"), work_order.get("target_metric")))
    if method is None: return None
    records = _records(observations); bindings = {}
    for metric, unit in method.input_units.items():
        candidates = [item for item in records if item.metric == metric and item.unit == unit
                      and item.year == work_order.get("year") and item.region_code == work_order.get("region_code")]
        if not candidates: return None
        chosen = sorted(candidates, key=lambda item: (-item.confidence, item.observation_id))[0]
        bindings[metric] = chosen.observation_id
    explanation = f"按版本化方法 {method.method_id} 绑定可审计观测并执行确定性计算。"
    planner_model = "none"
    if provider is not None:
        planner_model = str(getattr(provider, "model", provider.__class__.__name__))
        try:
            response = provider.run({"mode":"calculation_explanation", "method_id":method.method_id,
                                     "input_bindings":bindings, "formula":method.formula})
            if isinstance(response, dict) and isinstance(response.get("explanation"), str) and response["explanation"].strip():
                explanation = response["explanation"].strip()
        except (OSError, RuntimeError, ValueError):
            pass
    identity = {"task_id":work_order["task_id"], "node_id":work_order["node_id"], "node_version":work_order.get("node_version"),
                "method_id":method.method_id, "bindings":bindings}
    return CalculationPlan.from_dict({
        "plan_id": f"plan-{_hash(identity)[:24]}", "task_id":work_order["task_id"], "node_id":work_order["node_id"],
        "target_metric":method.target_metric, "method_id":method.method_id, "method_version":method.version,
        "input_bindings":dict(sorted(bindings.items())),
        "operations":[{"op":"calculate", "method_id":method.method_id, "method_version":method.version}],
        "planner":"deterministic", "planner_model":planner_model, "explanation":explanation,
        "schema_version":"1", "status":"ready",
    })


def execute_plan(
    plan: CalculationPlan, observations: Iterable[ObservationRecord | dict[str, Any]],
) -> CalculationResult:
    method = SMART_METHODS.get(plan.method_id)
    if method is None or plan.method_version != method.version:
        raise ValueError("unknown smart method or version")
    if len(set(plan.input_bindings.values())) != len(plan.input_bindings):
        raise ValueError("duplicate observation binding")
    expected_operation = {"op":"calculate", "method_id":method.method_id, "method_version":method.version}
    if list(plan.operations) != [expected_operation]:
        raise ValueError("operation schema is not allowlisted")
    if set(plan.input_bindings) != set(method.input_units):
        raise ValueError("plan inputs do not match the method contract")
    by_id = {item.observation_id:item for item in _records(observations)}
    selected = {}
    for metric, observation_id in plan.input_bindings.items():
        item = by_id.get(observation_id)
        if item is None: raise ValueError("missing bound observation")
        if item.metric != metric or item.unit != method.input_units[metric]:
            raise ValueError("bound observation metric or unit mismatch")
        selected[metric] = item
    years = {item.year for item in selected.values()}; regions = {item.region_code for item in selected.values()}
    if len(years) != 1 or len(regions) != 1: raise ValueError("bound observations have mismatched year or region")
    calculator = getattr(calculators, method.calculator)
    result = calculator(*(selected[metric].value for metric in method.input_units))
    if result.get("unit") != method.output_unit: raise ValueError("calculator output unit mismatch")
    if isinstance(result.get("value"), float) and not math.isfinite(result["value"]): raise ValueError("calculator output is non-finite")
    input_manifest = [selected[metric].as_dict() for metric in sorted(selected)]
    input_hash = _hash(input_manifest); parameter_hash = _hash({"method_id":method.method_id,"version":method.version})
    result_hash = _hash(result)
    return CalculationResult.from_dict({
        "calculation_run_id": f"calc-{_hash({'plan':plan.plan_id,'input':input_hash})[:24]}",
        "plan_id":plan.plan_id, "code_version":"smart-calculators-v1",
        "input_manifest_sha256":input_hash, "parameter_manifest_sha256":parameter_hash,
        "result":result, "result_sha256":result_hash,
        "quality":{"evidence_classes":sorted({item.evidence_class for item in selected.values()}),
                   "year":next(iter(years)), "region_code":next(iter(regions))},
        "status":"succeeded", "error_code":None,
    })
