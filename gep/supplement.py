"""Runtime selection for supplement workflow providers."""
from __future__ import annotations

import os
from typing import Any, Mapping

from .deepseek import DeepSeekWorkflow
from .dify import DifyWorkflow
from .evidence_catalog import EvidenceCatalog
from .geo.aef_tool import AefSpatialTool
from .official_sources import OfficialSourceRegistry
from .research import ResearchWorkflow
from .task_service import SupplementWorkflow
from .agent.workflow import AgentWorkflow


class EvidenceAwareWorkflow(ResearchWorkflow):
    """Add admitted evidence and reject citations outside that bounded set."""

    def __init__(self, provider: SupplementWorkflow, catalog: EvidenceCatalog):
        super().__init__(provider, catalog)


def workflow_from_environment(
    environment: Mapping[str, str] | None = None,
    *, database_path: str | os.PathLike[str] | None = None,
) -> SupplementWorkflow | None:
    if environment is None:
        environment = os.environ
    agent_enabled = environment.get("GEP_AGENT_ENABLED", "").strip().lower() in {"1", "true", "yes"}
    if agent_enabled:
        if database_path is None:
            raise ValueError("native agent requires a database path")
        return AgentWorkflow.from_environment(database_path=database_path, environment=environment)
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
        return ResearchWorkflow(
            workflow, EvidenceCatalog(data_root), OfficialSourceRegistry(), AefSpatialTool(data_root),
        ) if data_root else workflow
    if provider == "dify":
        workflow = DifyWorkflow.from_environment(environment)
        if workflow is None:
            raise ValueError("Dify provider requires DIFY_API_BASE_URL and DIFY_API_KEY")
        return workflow
    if provider == "none":
        return None
    raise ValueError("SUPPLEMENT_PROVIDER must be deepseek, dify, or none")
