"""Deterministic tool research and risk classification for supplement jobs."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


EVIDENCE_FIELDS = (
    "source_id", "source_type", "locator", "source_sha256", "license_or_access",
    "tool_run_id", "extracted_fragment",
)


class EmptyOfficialRegistry:
    def search(self, _work_order: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def verify(self, record: dict[str, Any]) -> dict[str, Any]:
        return record


class ResearchWorkflow:
    """Search tools choose facts and risk; the model only writes an explanation."""

    def __init__(self, provider, local_catalog, official_registry=None, aef_tool=None):
        self.provider = provider
        self.local_catalog = local_catalog
        self.official_registry = official_registry or EmptyOfficialRegistry()
        self.aef_tool = aef_tool

    @staticmethod
    def _finite_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    @staticmethod
    def _fact_hash(record: dict[str, Any]) -> str:
        identity = {key: record.get(key) for key in (
            "source_id", "url", "locator", "metric", "value", "unit", "region_code", "year",
        )}
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _explanation(self, work_order: dict[str, Any], evidence: list[dict[str, Any]], default: str) -> str:
        try:
            response = self.provider.run({**work_order, "allowed_evidence": evidence})
        except (OSError, RuntimeError, ValueError):
            return default
        explanation = response.get("explanation") if isinstance(response, dict) else None
        return explanation.strip() if isinstance(explanation, str) and explanation.strip() else default

    @staticmethod
    def _evidence(record: dict[str, Any]) -> dict[str, Any]:
        optional = (
            "url", "final_url", "title", "publisher", "online_status", "checked_utc",
            "http_status", "content_type", "etag", "last_modified", "source_hash_scope", "risk_reason",
        )
        return {
            **{key: record[key] for key in EVIDENCE_FIELDS},
            **{key: record[key] for key in optional if key in record},
        }

    def run(self, work_order: dict[str, Any]) -> dict[str, Any]:
        searched_tools = ["local_catalog", "official_registry"]
        local = self.local_catalog.for_work_order(work_order)
        permission = next((item for item in local if item.get("raw_status") == "permission_required"), None)
        if permission:
            return {
                "outcome": "manual_required", "risk_tier": "C", "reason_code": "permission_required",
                "explanation": "来源已定位，但访问受限，需要有权限的人员提供材料。",
                "searched_tools": searched_tools,
            }

        official, verification_failures = [], 0
        for record in self.official_registry.search(work_order):
            try:
                verified = self.official_registry.verify(record)
            except (OSError, RuntimeError, ValueError):
                verification_failures += 1
                continue
            if verified.get("online_status") != "verified":
                verification_failures += 1
                continue
            verified = {
                **verified,
                "source_sha256": self._fact_hash(verified),
                "source_hash_scope": "registry_fact_record",
                "raw_status": "official_fact",
            }
            official.append(verified)

        if len({json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True) for item in official}) > 1:
            return {
                "outcome": "manual_required", "risk_tier": "C", "reason_code": "source_conflict",
                "explanation": "多个已验证官方来源给出不同值，需要专家确认统计口径。",
                "searched_tools": searched_tools, "conflicting_source_ids": [item["source_id"] for item in official],
            }

        if self.aef_tool is not None:
            searched_tools.append("aef_spatial")
            aef_result = self.aef_tool.inspect(work_order)
        else:
            aef_result = None

        direct = local[0] if len(local) == 1 else None
        if (direct and work_order.get("node_kind") == "input"
                and direct.get("metric") == work_order.get("node_label")
                and direct.get("raw_status") == "observed"
                and self._finite_number(direct.get("value")) and str(direct.get("unit") or "").strip()
                and all(str(direct.get(key, "")).strip() for key in EVIDENCE_FIELDS)):
            explanation = self._explanation(
                work_order, [direct], "本地准入记录与节点、区域、年度和单位精确匹配，已形成高可信候选。",
            )
            return {
                "outcome": "candidate", "risk_tier": "A", "auto_adopt": True,
                "value": direct["value"], "unit": direct["unit"], "explanation": explanation,
                "evidence": self._evidence(direct), "searched_tools": searched_tools,
            }

        if official:
            chosen = official[0]
            explanation = self._explanation(
                work_order, [chosen],
                f"已验证政府官方来源并提取候选；{chosen.get('risk_reason', '该字段仍需口径复核')}。",
            )
            return {
                "outcome": "candidate", "risk_tier": "B", "auto_adopt": False,
                "value": chosen["value"], "unit": chosen["unit"], "explanation": explanation,
                "evidence": self._evidence(chosen), "risk_reason": chosen.get("risk_reason", ""),
                "searched_tools": searched_tools,
            }

        return {
            "outcome": "research_complete", "risk_tier": "GAP",
            "explanation": "已完成本地准入目录、官方来源和适用空间资产检查，尚未取得可直接用于该字段的数值。",
            "searched_tools": searched_tools,
            "verification_failures": verification_failures,
            "aef_result": aef_result,
            "next_action": "等待后续公开数据、部门数据接入或自动重试",
        }
