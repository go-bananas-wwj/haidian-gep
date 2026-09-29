"""SupplementWorkflow adapter for the native tool-using GEP agent."""
from __future__ import annotations

import hashlib
import json
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

    def record(self, event: str, payload: Any) -> None:
        if event != "tool_result":
            return
        result = payload["result"]
        sequence = int(payload["sequence"])
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
        metric = str(work_order.get("node_label") or work_order.get("target_metric") or "")
        try:
            observed = self.registry.call("smart.observation.search", {
                "metric": metric,
                "year": int(work_order.get("year") or 0),
                "region_code": str(work_order.get("region_code") or ""),
            })
            searched.append("smart.observation.search")
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

        ledger = _RunLedger(self.store, run_id, str(work_order.get("node_id", "")))
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
        if result.get("outcome") in {"candidate", "manual_required", "research_complete", "applicability_candidate"}:
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
