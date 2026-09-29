"""SupplementWorkflow adapter for the native tool-using GEP agent."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from ..deepseek import DeepSeekWorkflow
from ..evidence_catalog import EvidenceCatalog
from ..geo.aef_tool import AefSpatialTool
from ..official_sources import OfficialSourceRegistry
from ..smart_data.store import SmartDataStore
from .builtin_tools import BuiltinToolContext, register_builtin_tools
from .evidence import EvidenceValidator
from .http import SafeHttpClient
from .kernel import AgentKernel
from .knowledge import KnowledgeBase
from .planner import DeepSeekPlanner, TemplatePlanner
from .readers import PdfReader, WebReader
from .search import DuckDuckGoHtmlSearchProvider, SearxngSearchProvider
from .store import AgentStore
from .tools import ToolRegistry
from .types import AgentBudget, ToolResult


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class _EmptyCatalog:
    def for_work_order(self, _work_order): return []


class _EmptyAef:
    def inspect(self, _work_order): return {"status": "not_applicable"}


class _KernelValidation:
    def validate(self, _work_order, observations):
        return {"observation_count": len(observations)}


class _RunLedger:
    def __init__(self, store: AgentStore, run_id: str, node_id: str):
        self.store = store
        self.run_id = run_id
        self.node_id = node_id
        self.sequence = 0

    def record(self, event: str, payload: Any) -> None:
        if event != "tool_result":
            return
        result = payload["result"]
        self.sequence += 1
        sequence = self.sequence
        tool_id = str(payload["tool_id"])
        self.store.record_tool_run({
            "run_id": self.run_id,
            "node_id": self.node_id,
            "sequence": sequence,
            "tool_id": tool_id,
            "status": result.status,
            "elapsed_ms": result.elapsed_ms,
            "result": asdict(result),
        })
        for index, evidence in enumerate(result.evidence):
            item = dict(evidence)
            item.setdefault("source_id", f"{tool_id}:{sequence}:{index}")
            item.setdefault("source_type", "tool_result")
            item.setdefault("locator", tool_id)
            item.setdefault("source_sha256", hashlib.sha256(_json(item).encode()).hexdigest())
            item.setdefault("checked_utc", "recorded-by-agent")
            item.update({
                "run_id": self.run_id,
                "node_id": self.node_id,
                "risk_tier": item.get("risk_tier", "unclassified"),
            })
            self.store.record_evidence(item)


class AgentWorkflow:
    def __init__(
        self,
        database_path: str | Path,
        registry: ToolRegistry,
        planner: Any,
        *,
        store: AgentStore | None = None,
        budget: AgentBudget = AgentBudget(),
    ):
        self.store = store or AgentStore(database_path)
        self.registry = registry
        self.planner = planner
        self.budget = budget

    @classmethod
    def from_environment(
        cls,
        *,
        database_path: str | Path,
        environment: Mapping[str, str],
    ) -> "AgentWorkflow":
        store = AgentStore(database_path)
        smart_store = SmartDataStore(store.connection)
        knowledge = KnowledgeBase(store.connection)
        client = SafeHttpClient(timeout_seconds=float(environment.get("GEP_WEB_TIMEOUT_SECONDS", "10")))
        provider_name = environment.get("GEP_SEARCH_PROVIDER", "duckduckgo").strip().lower()
        if provider_name == "searxng":
            base_url = environment.get("GEP_SEARXNG_URL", "").strip()
            if not base_url:
                store.close()
                raise ValueError("GEP_SEARXNG_URL is required for the searxng provider")
            search = SearxngSearchProvider(client, base_url)
        elif provider_name == "duckduckgo":
            search = DuckDuckGoHtmlSearchProvider(client)
        else:
            store.close()
            raise ValueError("GEP_SEARCH_PROVIDER must be duckduckgo or searxng")
        data_root = environment.get("GEP_DATA_ROOT", "").strip()
        registry = ToolRegistry()
        register_builtin_tools(registry, BuiltinToolContext(
            local_catalog=EvidenceCatalog(data_root) if data_root else _EmptyCatalog(),
            observation_store=smart_store,
            official_registry=OfficialSourceRegistry(),
            knowledge_base=knowledge,
            search_provider=search,
            web_reader=WebReader(client),
            pdf_reader=PdfReader(client),
            aef_tool=AefSpatialTool(data_root) if data_root else _EmptyAef(),
            evidence_validator=EvidenceValidator(),
        ))
        provider = DeepSeekWorkflow.from_environment(environment)
        planner = DeepSeekPlanner(provider, registry) if provider is not None else TemplatePlanner()
        return cls(database_path, registry, planner, store=store)

    def close(self) -> None:
        self.store.close()

    @staticmethod
    def _run_id(work_order: Mapping[str, Any]) -> str:
        identity = {key: work_order.get(key) for key in (
            "task_id", "node_id", "node_version", "data_version", "year", "region_code",
        )}
        return "agent-" + hashlib.sha256(_json(identity).encode()).hexdigest()[:24]

    def _cached(self, run_id: str) -> dict[str, Any] | None:
        row = self.store.connection.execute(
            "SELECT payload_json FROM agent_decisions WHERE decision_id=?", (f"decision-{run_id}",)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"]).get("result")

    def _save(self, run_id: str, work_order: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(result)
        self.store.record_decision({
            "decision_id": f"decision-{run_id}",
            "run_id": run_id,
            "node_id": str(work_order.get("node_id", "")),
            "decision": str(payload.get("outcome", "research_complete")),
            "reason": str(payload.get("reason_code") or payload.get("explanation") or ""),
            "result": payload,
        })
        return payload

    @staticmethod
    def _candidate_from_observation(record: Mapping[str, Any]) -> dict[str, Any]:
        identity_hash = hashlib.sha256(_json(record).encode()).hexdigest()
        evidence_class = str(record.get("evidence_class") or "model_estimate")
        tier = "B" if evidence_class in {"public_calculation", "official_fact"} else "C"
        source_id = str(record.get("observation_id") or record.get("source_id") or f"observation:{identity_hash[:16]}")
        return {
            "outcome": "candidate",
            "risk_tier": tier,
            "auto_adopt": False,
            "value": record["value"],
            "unit": str(record["unit"]),
            "result_class": evidence_class,
            "explanation": f"已从数据后台复用 {source_id}，并保留其证据等级用于智能试算。",
            "searched_tools": ["smart.observation.search"],
            "evidence": {
                "source_id": source_id,
                "source_type": "derived_observation",
                "locator": f"derived_observations/{source_id}",
                "source_sha256": identity_hash,
                "license_or_access": str(record.get("license_or_access") or "registered-data-asset"),
                "tool_run_id": str(record.get("method_id") or "smart.observation.search"),
                "extracted_fragment": f"{record.get('metric')}={record['value']} {record['unit']}",
            },
        }

    @staticmethod
    def _candidate_from_local(record: Mapping[str, Any], searched: list[str]) -> dict[str, Any] | None:
        value = record.get("value")
        unit = str(record.get("unit") or "").strip()
        required = (
            "source_id", "source_type", "locator", "source_sha256", "license_or_access",
            "tool_run_id", "extracted_fragment",
        )
        if (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value))
                or not unit or any(not str(record.get(key, "")).strip() for key in required)):
            return None
        evidence = {key: record[key] for key in required}
        return {
            "outcome": "candidate",
            "risk_tier": "A",
            "auto_adopt": True,
            "value": value,
            "unit": unit,
            "result_class": "admitted_observation",
            "explanation": "本地准入记录与目标字段、区域、年度和单位精确匹配，已形成高可信候选。",
            "searched_tools": list(searched),
            "evidence": evidence,
        }

    @staticmethod
    def _candidate_from_tool_results(observations: tuple[ToolResult, ...], searched: list[str]) -> dict[str, Any] | None:
        observed_identities = {
            (
                str(item.get("source_id") or ""),
                str(item.get("source_sha256") or item.get("content_sha256") or ""),
            )
            for result in observations for item in result.evidence
        }
        for observation in reversed(observations):
            data = observation.data
            accepted = data.get("accepted_items") if isinstance(data, Mapping) else None
            tier = str(data.get("risk_tier") or "") if isinstance(data, Mapping) else ""
            if accepted and tier in {"A", "B", "C"}:
                item = dict(accepted[0])
                value = item.get("normalized_value")
                unit = str(item.get("normalized_unit") or "")
                source_hash = item.get("source_sha256") or item.get("content_sha256")
                identity = (str(item.get("source_id") or ""), str(source_hash or ""))
                if identity not in observed_identities:
                    continue
                required = {
                    "source_id": item.get("source_id"),
                    "source_type": item.get("source_type"),
                    "locator": item.get("locator"),
                    "source_sha256": source_hash,
                    "license_or_access": item.get("license_or_access"),
                    "tool_run_id": item.get("tool_run_id") or "evidence.validate",
                    "extracted_fragment": item.get("extracted_fragment") or f"{item.get('metric')}={value} {unit}",
                }
                if value is not None and unit and all(str(value or "").strip() for value in required.values()):
                    return {
                        "outcome": "candidate", "risk_tier": tier, "auto_adopt": tier == "A",
                        "value": value, "unit": unit,
                        "result_class": "public_calculation" if tier == "B" else ("model_estimate" if tier == "C" else "admitted_observation"),
                        "explanation": "候选值来自已登记工具并通过地区、年度、单位和来源校验。",
                        "searched_tools": list(searched), "evidence": required,
                    }
        return None

    def run(self, work_order: dict[str, Any]) -> dict[str, Any]:
        run_id = self._run_id(work_order)
        cached = self._cached(run_id)
        if cached is not None:
            return cached
        if self.store.connection.execute("SELECT 1 FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() is None:
            self.store.start_run({
                "run_id": run_id,
                "task_id": str(work_order.get("task_id", "")),
                "node_id": str(work_order.get("node_id", "")),
                "status": "running",
                "work_order": dict(work_order),
            })

        searched: list[str] = []
        ledger = _RunLedger(self.store, run_id, str(work_order.get("node_id", "")))
        sequence = 1
        metric = str(work_order.get("node_label") or work_order.get("target_metric") or "")
        try:
            observed = self.registry.call("smart.observation.search", {
                "metric": metric,
                "year": int(work_order.get("year") or 0),
                "region_code": str(work_order.get("region_code") or ""),
            })
            searched.append("smart.observation.search")
            ledger.record("tool_result", {"sequence": sequence, "tool_id": "smart.observation.search", "result": observed})
            sequence += 1
            records = list(observed.data.get("records", ()))
            if records:
                distinct = {
                    _json({"value": record.get("value"), "unit": record.get("unit")})
                    for record in records
                }
                if len(distinct) > 1:
                    source_ids = [
                        str(record.get("observation_id") or record.get("source_id") or f"observation-{index}")
                        for index, record in enumerate(records)
                    ]
                    return self._save(run_id, work_order, {
                        "outcome": "manual_required",
                        "risk_tier": "D",
                        "reason_code": "source_conflict",
                        "result_class": "needs_business_decision",
                        "explanation": "数据后台存在同一指标、区域和年度的冲突数值，需要一次口径确认。",
                        "searched_tools": ["smart.observation.search"],
                        "human_action": {
                            "title": "确认冲突数据口径",
                            "reason_code": "source_conflict",
                            "source_ids": source_ids,
                        },
                    })
                return self._save(run_id, work_order, self._candidate_from_observation(records[0]))
        except (KeyError, OSError, RuntimeError, ValueError) as error:
            observation_error = type(error).__name__
        else:
            observation_error = ""

        available_tools = {spec.tool_id for spec in self.registry.specs()}
        if "local.catalog.search" in available_tools:
            try:
                local_result = self.registry.call("local.catalog.search", {"work_order": dict(work_order)})
                searched.append("local.catalog.search")
                ledger.record("tool_result", {"sequence": sequence, "tool_id": "local.catalog.search", "result": local_result})
                sequence += 1
                local_records = list(local_result.data.get("records", ()))
                exact = [
                    record for record in local_records
                    if record.get("metric") == metric and record.get("raw_status") == "observed"
                ]
                if len(exact) == 1:
                    local_candidate = self._candidate_from_local(exact[0], searched)
                    if local_candidate is not None:
                        return self._save(run_id, work_order, local_candidate)
            except (KeyError, OSError, RuntimeError, ValueError) as error:
                observation_error = observation_error or type(error).__name__

        try:
            outcome = AgentKernel(
                self.registry, self.planner, _KernelValidation(), ledger, budget=self.budget,
            ).run(work_order)
        except (KeyError, OSError, RuntimeError, ValueError) as error:
            searched.extend(spec.tool_id for spec in self.registry.specs() if spec.network_access)
            return self._save(run_id, work_order, {
                "outcome": "research_complete",
                "explanation": f"自动工具执行失败（{type(error).__name__}），已保留此前成功结果并记录具体失败类型。",
                "searched_tools": sorted(set(searched)),
                "verification_failures": 1,
                "aef_result": None,
                "next_action": "检查对应工具服务后自动重试",
                "tool_error": type(error).__name__,
            })
        result = dict(outcome.result)
        searched.extend(
            row[0] for row in self.store.connection.execute(
                "SELECT tool_id FROM tool_runs WHERE run_id=? ORDER BY sequence", (run_id,)
            ).fetchall()
        )
        searched = list(dict.fromkeys(searched))
        grounded_candidate = self._candidate_from_tool_results(outcome.observations, searched)
        if grounded_candidate is not None:
            mapped = grounded_candidate
        elif result.get("outcome") in {"manual_required", "research_complete"}:
            mapped = result
        elif outcome.status == "manual_required":
            mapped = {
                "outcome": "manual_required",
                "reason_code": str(result.get("reason_code") or outcome.reason),
                "explanation": str(result.get("explanation") or "自动工具已执行，剩余事项需要人工确认。"),
                "searched_tools": searched,
                "result_class": "needs_business_decision",
            }
        else:
            mapped = {
                "outcome": "research_complete",
                "explanation": str(result.get("explanation") or "自动检索已完成，尚未形成可采用数值。"),
                "searched_tools": searched,
                "verification_failures": 0,
                "aef_result": None,
                "next_action": "继续读取公开原文或归并数据请求",
            }
        if observation_error:
            mapped.setdefault("observation_error", observation_error)
        return self._save(run_id, work_order, mapped)
