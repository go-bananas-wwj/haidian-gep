"""Runtime selection for supplement workflow providers."""
from __future__ import annotations

import os
from typing import Mapping

from .deepseek import DeepSeekWorkflow
from .dify import DifyWorkflow
from .task_service import SupplementWorkflow


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
        return workflow
    if provider == "dify":
        workflow = DifyWorkflow.from_environment(environment)
        if workflow is None:
            raise ValueError("Dify provider requires DIFY_API_BASE_URL and DIFY_API_KEY")
        return workflow
    if provider == "none":
        return None
    raise ValueError("SUPPLEMENT_PROVIDER must be deepseek, dify, or none")
