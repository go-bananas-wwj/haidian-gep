import json
import unittest
from unittest.mock import patch


class DifyWorkflowTests(unittest.TestCase):
    def test_workflow_posts_a_scoped_work_order_and_returns_only_structured_candidate(self):
        from gep.dify import DifyWorkflow

        class Response:
            def read(self):
                return json.dumps({
                    "data": {"workflow_run_id": "workflow-run-1", "outputs": {"candidate_json": json.dumps({
                        "value": 2100, "unit": "yuan/t", "explanation": "可追溯说明",
                        "evidence": {"source_id": "s", "source_type": "register", "locator": "row=1",
                                     "source_sha256": "a" * 64, "license_or_access": "review",
                                     "tool_run_id": "tool-1", "extracted_fragment": "2100"},
                    })}}
                }).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        workflow = DifyWorkflow("https://dify.internal/", "not-a-real-key")
        with patch("gep.dify.urlopen", return_value=Response()) as urlopen:
            candidate = workflow.run({"task_id": "task-1", "node_id": "node-1", "year": 2024})

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://dify.internal/v1/workflows/run")
        self.assertEqual(request.get_header("Authorization"), "Bearer not-a-real-key")
        payload = json.loads(request.data)
        self.assertEqual(payload["response_mode"], "blocking")
        self.assertEqual(json.loads(payload["inputs"]["work_order_json"])["node_id"], "node-1")
        self.assertEqual(candidate["value"], 2100)
        self.assertEqual(candidate["evidence"]["tool_run_id"], "tool-1")
