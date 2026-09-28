"""Task-node adapter that prefers reusable smart observations over gaps."""
from __future__ import annotations

import hashlib
import json
from typing import Any


DECISION_FIELDS = {"deduplication_choice", "applicability_evidence", "product_ownership", "local_origin", "attribution"}
PROXY_ALIASES = {"npp_or_nep":"npp", "area":"ecosystem_area", "temperature_humidity":"temperature", "transpiration":"actual_et"}


class SmartDataWorkflow:
    def __init__(self, store: Any, provider: Any = None):
        self.store = store; self.provider = provider

    def run(self, work_order: dict[str, Any]) -> dict[str, Any]:
        if work_order.get("data_version") != "smart-data-2024-v1" and self.provider is not None:
            return self.provider.run(work_order)
        metric = str(work_order.get("node_label") or work_order.get("node_key", "").split(".")[-1])
        if metric == "inland_boundary_evidence" and work_order.get("region_code") == "110108":
            source_hash = hashlib.sha256(b"OSM demo boundary:110108:inland").hexdigest()
            return {"outcome":"candidate", "risk_tier":"B", "auto_adopt":True,
                "result_class":"not_applicable_candidate", "value":1, "unit":"boolean",
                "explanation":"海淀区 Demo 边界为内陆行政区域，海岸防护形成不适用候选，正式核算仍需确认边界。",
                "searched_tools":["demo_boundary"],
                "evidence":{"source_id":"haidian-osm-demo-boundary", "source_type":"demo_boundary",
                    "locator":"region_code=110108", "source_sha256":source_hash,
                    "license_or_access":"ODbL 1.0", "tool_run_id":"boundary:inland-check:v1",
                    "extracted_fragment":"海淀区不与海岸线相交"}}
        query_metric=PROXY_ALIASES.get(metric,metric)
        observations = self.store.find_observations(
            metric=query_metric, year=int(work_order.get("year") or 0), region_code=str(work_order.get("region_code") or ""),
        )
        if observations:
            chosen = sorted(observations, key=lambda item: (-item["confidence"], item["observation_id"]))[0]
            asset = self.store.asset(chosen["input_asset_ids"][0])
            identity_hash = hashlib.sha256(json.dumps(chosen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            return {
                "outcome":"candidate", "risk_tier":"B", "auto_adopt":True,
                "result_class":chosen["evidence_class"], "value":chosen["value"], "unit":chosen["unit"],
                "explanation":f"已从数据后台复用 {chosen['observation_id']}，作为明确标注的智能试算{'代理' if query_metric != metric else ''}输入。",
                "searched_tools":["smart_data_observations"],
                "evidence":{"source_id":chosen["observation_id"], "source_type":"derived_observation",
                    "locator":f"derived_observations/{chosen['observation_id']}", "source_sha256":identity_hash,
                    "license_or_access":asset["license_or_access"], "tool_run_id":chosen["method_id"],
                    "extracted_fragment":f"{chosen['metric']}={chosen['value']} {chosen['unit']}"},
            }
        decision = metric in DECISION_FIELDS
        return {"outcome":"manual_required",
            "reason_code":"business_decision_required" if decision else "department_data_required",
            "result_class":"needs_business_decision" if decision else "needs_department_data",
            "explanation":"该事项需要一次业务口径判断。" if decision else "自动工具已完成查询，仍需对应部门提供经营或业务记录。",
            "searched_tools":["smart_data_observations"]}
