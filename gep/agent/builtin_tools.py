"""Adapters exposing existing GEP data and calculators through ToolRegistry."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from ..smart_data import calculators
from ..smart_data.methods import SMART_METHODS
from .tools import ToolRegistry
from .types import ToolResult, ToolSpec


@dataclass(frozen=True)
class BuiltinToolContext:
    local_catalog: Any
    observation_store: Any
    official_registry: Any
    knowledge_base: Any
    search_provider: Any
    web_reader: Any
    pdf_reader: Any
    aef_tool: Any
    evidence_validator: Any


def _object_schema(*required: str) -> dict[str, Any]:
    return {"type": "object", "required": list(required), "properties": {key: {} for key in required}}


def _spec(tool_id: str, title: str, description: str, required: tuple[str, ...], *, network: bool = False, risk: str = "low") -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        title_zh=title,
        description=description,
        input_schema=_object_schema(*required),
        output_schema={"type": "object"},
        risk_level=risk,
        network_access=network,
    )


def _require(component: Any, name: str) -> Any:
    if component is None:
        raise RuntimeError(f"tool dependency is unavailable: {name}")
    return component


def _local(context: BuiltinToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    records = _require(context.local_catalog, "local_catalog").for_work_order(dict(arguments["work_order"]))
    return ToolResult(status="ok", data={"records": records}, evidence=tuple(records))


def _observations(context: BuiltinToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    query = {key: arguments[key] for key in ("metric", "year", "region_code", "unit") if key in arguments}
    records = _require(context.observation_store, "observation_store").find_observations(**query)
    return ToolResult(status="ok", data={"records": records}, evidence=tuple(records))


def _official(context: BuiltinToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    records = _require(context.official_registry, "official_registry").search(dict(arguments["work_order"]))
    return ToolResult(status="ok", data={"records": records}, evidence=tuple(records))


def _knowledge(context: BuiltinToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    hits = _require(context.knowledge_base, "knowledge_base").search(
        str(arguments["query"]),
        filters=arguments.get("filters"),
        limit=int(arguments.get("limit", 5)),
    )
    return ToolResult(status="ok", data={"hits": hits}, evidence=tuple(hits))


def _web_search(context: BuiltinToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    hits = _require(context.search_provider, "search_provider").search(
        str(arguments["query"]),
        domains=tuple(arguments.get("domains", ())),
        limit=int(arguments.get("limit", 5)),
        language=str(arguments.get("language", "zh-CN")),
    )
    return ToolResult(status="ok", data={"hits": [asdict(hit) for hit in hits]})


def _read(context: BuiltinToolContext, arguments: Mapping[str, Any], *, pdf: bool) -> ToolResult:
    reader = _require(context.pdf_reader if pdf else context.web_reader, "pdf_reader" if pdf else "web_reader")
    result = reader.read(str(arguments["url"]), pages=arguments.get("pages")) if pdf else reader.read(str(arguments["url"]))
    source_id = f"{'pdf' if pdf else 'web'}:{result.sha256[:16]}"
    evidence = result.to_evidence(source_id, source_type="pdf_document" if pdf else "web_page")
    return ToolResult(status="ok", data={"document": asdict(result)}, evidence=(evidence,))


def _aef(context: BuiltinToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    result = _require(context.aef_tool, "aef_tool").inspect(dict(arguments["work_order"]))
    return ToolResult(status="ok", data={"result": result})


def _calculate(arguments: Mapping[str, Any]) -> ToolResult:
    method_id = str(arguments["method_id"])
    method = SMART_METHODS.get(method_id)
    if method is None:
        raise ValueError(f"unknown method: {method_id}")
    raw_inputs = arguments["inputs"]
    if not isinstance(raw_inputs, Mapping):
        raise ValueError("inputs must be an object")
    values: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    for field, expected_unit in method.input_units.items():
        binding = raw_inputs.get(field)
        if not isinstance(binding, Mapping):
            raise ValueError(f"input {field} requires value and unit")
        if not str(binding.get("unit", "")).strip():
            raise ValueError(f"input {field} unit is required")
        if str(binding["unit"]) != expected_unit:
            raise ValueError(f"input {field} unit must be {expected_unit}")
        if "value" not in binding:
            raise ValueError(f"input {field} value is required")
        values[field] = binding["value"]
        steps.append({"field": field, "value": binding["value"], "unit": binding["unit"]})
    calculator = getattr(calculators, method.calculator)
    result = calculator(**values)
    return ToolResult(status="ok", data={
        "method_id": method.method_id,
        "method_version": method.version,
        "indicator_id": method.indicator_id,
        "target_metric": method.target_metric,
        "formula": method.formula,
        "inputs": steps,
        "result": result,
    })


def _validate(context: BuiltinToolContext, arguments: Mapping[str, Any]) -> ToolResult:
    result = _require(context.evidence_validator, "evidence_validator").validate(
        dict(arguments["target"]), tuple(arguments["items"])
    )
    return ToolResult(status="ok", data=asdict(result))


def register_builtin_tools(registry: ToolRegistry, context: BuiltinToolContext) -> ToolRegistry:
    tools = (
        (_spec("local.catalog.search", "本地数据检索", "查询准入数据台账", ("work_order",)), lambda a: _local(context, a)),
        (_spec("smart.observation.search", "后台观测检索", "查询可复用派生观测", ("metric", "year", "region_code")), lambda a: _observations(context, a)),
        (_spec("official.registry.search", "官方来源检索", "查询预登记官方来源", ("work_order",)), lambda a: _official(context, a)),
        (_spec("knowledge.search", "项目知识检索", "查询标准、方法和已审核知识", ("query",)), lambda a: _knowledge(context, a)),
        (_spec("web.search", "互联网搜索", "发现公开网页线索", ("query",), network=True, risk="medium"), lambda a: _web_search(context, a)),
        (_spec("web.read", "网页原文读取", "安全读取网页正文", ("url",), network=True, risk="medium"), lambda a: _read(context, a, pdf=False)),
        (_spec("document.read", "PDF 原文读取", "安全读取 PDF 指定页", ("url",), network=True, risk="medium"), lambda a: _read(context, a, pdf=True)),
        (_spec("geo.alphaearth.inspect", "AlphaEarth 空间检查", "检查 AlphaEarth 空间资产", ("work_order",)), lambda a: _aef(context, a)),
        (_spec("gep.method.execute", "GEP 方法计算", "执行已登记的确定性核算方法", ("method_id", "inputs"), risk="medium"), _calculate),
        (_spec("evidence.validate", "证据校验", "校验来源、地区、年度、单位和冲突", ("target", "items")), lambda a: _validate(context, a)),
    )
    for spec, handler in tools:
        registry.register(spec, handler)
    return registry
