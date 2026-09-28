"""Runtime selection for supplement workflow providers."""
from __future__ import annotations

import os
import math
from typing import Any, Mapping

from .deepseek import DeepSeekWorkflow
from .dify import DifyWorkflow
from .evidence_catalog import EvidenceCatalog
from .task_service import SupplementWorkflow


class EvidenceAwareWorkflow:
    """Add admitted evidence and reject citations outside that bounded set."""

    def __init__(self, provider: SupplementWorkflow, catalog: EvidenceCatalog):
        self.provider = provider
        self.catalog = catalog

    def run(self, work_order: dict[str, Any]) -> dict[str, Any]:
        evidence = self.catalog.for_work_order(work_order)
        if not evidence:
            return {
                "outcome": "manual_required",
                "reason_code": "source_missing",
                "explanation": "准入数据包中没有与该节点匹配的可核验来源，需要人工补充材料或依据。",
            }
        scoped_order = {**work_order, "allowed_evidence": evidence}
        result = self.provider.run(scoped_order)
        if not isinstance(result, dict):
            raise ValueError("supplement provider must return a JSON object")
        direct = evidence[0] if len(evidence) == 1 else None
        direct_value = direct.get("value") if direct else None
        if (direct and work_order.get("node_kind") == "input"
                and direct.get("metric") == work_order.get("node_label")
                and direct.get("raw_status") == "observed"
                and isinstance(direct_value, (int, float)) and not isinstance(direct_value, bool)
                and math.isfinite(direct_value) and str(direct.get("unit") or "").strip()):
            explanation = result.get("explanation")
            if not isinstance(explanation, str) or not explanation.strip():
                raise ValueError("supplement provider did not explain the admitted observation")
            evidence_fields = (
                "source_id", "source_type", "locator", "source_sha256", "license_or_access",
                "tool_run_id", "extracted_fragment",
            )
            return {
                "outcome": "candidate", "value": direct_value, "unit": direct["unit"],
                "explanation": explanation.strip(),
                "evidence": {key: direct[key] for key in evidence_fields},
            }
        outcome = result.get("outcome", "candidate")
        if outcome in {"candidate", "applicability_candidate"}:
            citation = result.get("evidence")
            if not isinstance(citation, dict):
                raise ValueError("workflow candidate requires structured evidence")
            cited = (str(citation.get("source_id") or ""), str(citation.get("source_sha256") or "").lower())
            allowed = {(item["source_id"], item["source_sha256"].lower()) for item in evidence}
            if cited not in allowed:
                raise ValueError("workflow cited evidence outside the admitted work order")
        return result


def workflow_from_environment(
    environment: Mapping[str, str] | None = None,
) -> SupplementWorkflow | None:
    environment = environment or os.environ
    provider = environment.get("SUPPLEMENT_PROVIDER", "").strip().lower()
    if not provider:
        if environment.get("DEEPSEEK_API_KEY", "").strip():
            provider = "deepseek"
        elif environment.get("DIFY_API_BASE_URL", "").strip() and environment.get("DIFY_API_KEY", "").strip():
            provider = "dify"
        else:
            provider = "none"
    if provider == "deepseek":
        workflow = DeepSeekWorkflow.from_environment(environment)
        if workflow is None:
            raise ValueError("DeepSeek provider requires DEEPSEEK_API_KEY")
        data_root = environment.get("GEP_DATA_ROOT", "").strip()
        return EvidenceAwareWorkflow(workflow, EvidenceCatalog(data_root)) if data_root else workflow
    if provider == "dify":
        workflow = DifyWorkflow.from_environment(environment)
        if workflow is None:
            raise ValueError("Dify provider requires DIFY_API_BASE_URL and DIFY_API_KEY")
        return workflow
    if provider == "none":
        return None
    raise ValueError("SUPPLEMENT_PROVIDER must be deepseek, dify, or none")
