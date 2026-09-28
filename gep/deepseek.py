"""Minimal DeepSeek adapter for evidence-scoped supplement work orders."""
from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SYSTEM_PROMPT = """Return one JSON object only. Use only records in allowed_evidence. Never approve a node, invent a local value, use outside knowledge as evidence, or calculate formal GEP.
For an input node with one direct non-null admitted record, return exactly this shape: {"outcome":"candidate","value":number,"unit":"copy admitted unit","explanation":"Chinese evidence summary and review cautions","evidence":{"source_id":"copy exactly","source_type":"copy exactly","locator":"copy exactly","source_sha256":"copy exactly","license_or_access":"copy exactly","tool_run_id":"copy exactly","extracted_fragment":"copy exactly"}}.
For an indicator node only when admitted evidence supports an applicability proposal, return: {"outcome":"applicability_candidate","applicability_status":"applicable|not_applicable|verified_zero","explanation":"Chinese explanation and review cautions","evidence":{"source_id":"copy exactly","source_type":"copy exactly","locator":"copy exactly","source_sha256":"copy exactly","license_or_access":"copy exactly","tool_run_id":"copy exactly","extracted_fragment":"copy exactly"}}.
If evidence is blank, indirect, conflicting, insufficient, or cannot support the requested field, return: {"outcome":"manual_required","reason_code":"source_missing|scope_conflict|permission_required|insufficient_evidence","explanation":"Chinese summary of checked evidence and exact human next step"}.
Do not add keys outside the selected shape. Copy evidence identity fields character-for-character from one allowed_evidence record. Output JSON, not Markdown."""


class DeepSeekWorkflow:
    """Call DeepSeek JSON Output without granting it review authority."""

    def __init__(
        self, base_url: str, api_key: str, *, model: str = "deepseek-flash", timeout_seconds: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("DeepSeek base URL must use HTTP(S)")
        if not self.api_key.strip():
            raise ValueError("DeepSeek API key is required")
        if not self.model.strip():
            raise ValueError("DeepSeek model is required")
        if self.timeout_seconds <= 0:
            raise ValueError("DeepSeek timeout must be positive")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None):
        environment = environment or os.environ
        api_key = environment.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            environment.get("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com").strip(),
            api_key,
            model=environment.get("DEEPSEEK_MODEL", "deepseek-flash").strip(),
            timeout_seconds=int(environment.get("DEEPSEEK_TIMEOUT_SECONDS", "30")),
        )

    def run(self, work_order: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(work_order, ensure_ascii=False, sort_keys=True, allow_nan=False),
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(f"DeepSeek workflow HTTP {error.code}; no candidate was generated") from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError("DeepSeek workflow is unavailable; no candidate was generated") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("DeepSeek workflow returned invalid JSON") from error

        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("DeepSeek workflow response has no structured message content") from error
        if not isinstance(content, str) or not content.strip():
            raise ValueError("DeepSeek workflow returned empty content")
        try:
            result = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("DeepSeek workflow content is not valid JSON") from error
        if not isinstance(result, dict):
            raise ValueError("DeepSeek workflow content must be a JSON object")
        return result
