import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


class Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class DeepSeekWorkflowTests(unittest.TestCase):
    def test_posts_json_work_order_and_returns_structured_result(self):
        """Break caught: the worker could call the wrong API/model or lose structured output."""
        from gep.deepseek import DeepSeekWorkflow

        result = {
            "outcome": "manual_required",
            "reason_code": "source_missing",
            "explanation": "准入资料没有该字段。",
        }
        response = Response({
            "id": "chat-1",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(result, ensure_ascii=False),
            }}],
            "model": "deepseek-flash",
        })

        workflow = DeepSeekWorkflow("https://api.deepseek.com/", "test-secret")
        with patch("gep.deepseek.urlopen", return_value=response) as urlopen:
            actual = workflow.run({"task_id": "task-1", "node_id": "node-1", "year": 2024})

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertFalse(payload["stream"])
        self.assertIn("JSON", payload["messages"][0]["content"])
        self.assertIn('"outcome":"candidate"', payload["messages"][0]["content"])
        self.assertIn('"outcome":"applicability_candidate"', payload["messages"][0]["content"])
        self.assertIn('"outcome":"manual_required"', payload["messages"][0]["content"])
        self.assertIn("source_sha256", payload["messages"][0]["content"])
        self.assertEqual(json.loads(payload["messages"][1]["content"])["node_id"], "node-1")
        self.assertEqual(actual, result)

    def test_from_environment_requires_a_key(self):
        """Break caught: an empty credential could create a misleading configured provider."""
        from gep.deepseek import DeepSeekWorkflow

        self.assertIsNone(DeepSeekWorkflow.from_environment({}))
        workflow = DeepSeekWorkflow.from_environment({"DEEPSEEK_API_KEY": "runtime-secret"})
        self.assertEqual(workflow.base_url, "https://api.deepseek.com")
        self.assertEqual(workflow.model, "deepseek-flash")

    def test_rejects_empty_or_invalid_model_content(self):
        """Break caught: truncated model output could be persisted as a candidate."""
        from gep.deepseek import DeepSeekWorkflow

        workflow = DeepSeekWorkflow("https://api.deepseek.com", "runtime-secret")
        for content in ("", "not-json"):
            response = Response({"choices": [{"message": {"content": content}}]})
            with self.subTest(content=content), patch("gep.deepseek.urlopen", return_value=response):
                with self.assertRaises(ValueError):
                    workflow.run({"node_id": "node-1"})

    def test_http_errors_are_sanitized(self):
        """Break caught: a provider error could leak credentials or its response body."""
        from gep.deepseek import DeepSeekWorkflow

        secret = "runtime-secret-value"
        error = HTTPError(
            "https://api.deepseek.com/chat/completions", 401, "body-including-secret", {}, None,
        )
        workflow = DeepSeekWorkflow("https://api.deepseek.com", secret)
        with patch("gep.deepseek.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                workflow.run({"node_id": "node-1"})
        self.assertIn("HTTP 401", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("body-including-secret", str(raised.exception))

    def test_provider_factory_selects_deepseek_dify_or_none(self):
        """Break caught: deployment selection could silently run the wrong workflow."""
        from gep.deepseek import DeepSeekWorkflow
        from gep.dify import DifyWorkflow
        from gep.supplement import workflow_from_environment

        self.assertIsInstance(workflow_from_environment({
            "SUPPLEMENT_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "key",
        }), DeepSeekWorkflow)
        self.assertIsInstance(workflow_from_environment({
            "SUPPLEMENT_PROVIDER": "dify", "DIFY_API_BASE_URL": "https://dify.internal", "DIFY_API_KEY": "key",
        }), DifyWorkflow)
        self.assertIsNone(workflow_from_environment({"SUPPLEMENT_PROVIDER": "none"}))
        with self.assertRaises(ValueError):
            workflow_from_environment({"SUPPLEMENT_PROVIDER": "unknown"})

    def test_explicit_empty_environment_does_not_inherit_process_credentials(self):
        """Break caught: a caller requesting no provider could accidentally inherit a real process key."""
        from gep.deepseek import DeepSeekWorkflow
        from gep.supplement import workflow_from_environment

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "process-secret", "SUPPLEMENT_PROVIDER": "deepseek"}, clear=True):
            self.assertIsNone(DeepSeekWorkflow.from_environment({}))
            self.assertIsNone(workflow_from_environment({}))


if __name__ == "__main__":
    unittest.main()
