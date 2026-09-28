"""Small, explicit adapter for a configured Dify workflow.

The adapter deliberately transports a work order and a JSON candidate only.  It
does not grant a model authority to approve or calculate a formal GEP value.
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DifyWorkflow:
    """Call Dify's workflow endpoint using the application key supplied at runtime."""

    def __init__(
        self, base_url: str, api_key: str, *, work_order_input: str = "work_order_json",
        candidate_output: str = "candidate_json", user: str = "haidian-gep-task-service", timeout_seconds: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.work_order_input = work_order_input
        self.candidate_output = candidate_output
        self.user = user
        self.timeout_seconds = timeout_seconds
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("Dify base URL must use HTTP(S)")
        if not self.api_key.strip():
            raise ValueError("Dify API key is required")
        if not self.work_order_input.strip() or not self.candidate_output.strip() or not self.user.strip():
            raise ValueError("Dify input, output, and user identifiers are required")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None):
        if environment is None:
            environment = os.environ
        base_url = environment.get("DIFY_API_BASE_URL", "").strip()
        api_key = environment.get("DIFY_API_KEY", "").strip()
        if not base_url or not api_key:
            return None
        return cls(
            base_url,
            api_key,
            work_order_input=environment.get("DIFY_WORK_ORDER_INPUT", "work_order_json"),
            candidate_output=environment.get("DIFY_CANDIDATE_OUTPUT", "candidate_json"),
            user=environment.get("DIFY_WORKFLOW_USER", "haidian-gep-task-service"),
            timeout_seconds=int(environment.get("DIFY_TIMEOUT_SECONDS", "30")),
        )

    def run(self, work_order: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "inputs": {self.work_order_input: json.dumps(work_order, ensure_ascii=False, sort_keys=True, allow_nan=False)},
            "response_mode": "blocking",
            "user": self.user,
        }
        request = Request(
            f"{self.base_url}/v1/workflows/run",
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(f"Dify workflow HTTP {error.code}; no candidate was generated") from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError("Dify workflow is unavailable; no candidate was generated") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Dify workflow returned invalid JSON") from error

        try:
            candidate = response_payload["data"]["outputs"][self.candidate_output]
        except (KeyError, TypeError) as error:
            raise ValueError("Dify workflow response has no configured structured candidate output") from error
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except json.JSONDecodeError as error:
                raise ValueError("Dify workflow candidate output is not JSON") from error
        if not isinstance(candidate, dict):
            raise ValueError("Dify workflow candidate output must be a JSON object")
        return candidate
