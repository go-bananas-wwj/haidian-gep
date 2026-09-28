import unittest


class Provider:
    def __init__(self, result=None):
        self.result = result or {"explanation": "工具已完成检索、提取和校验。"}
        self.calls = []

    def run(self, work_order):
        self.calls.append(work_order)
        return self.result


class Catalog:
    def __init__(self, records):
        self.records = records

    def for_work_order(self, _work_order):
        return list(self.records)


class Registry:
    def __init__(self, records=(), error=None):
        self.records = records
        self.error = error

    def search(self, _work_order):
        return list(self.records)

    def verify(self, record):
        if self.error:
            raise self.error
        return {**record, "online_status": "verified", "checked_utc": "2026-09-28T00:00:00+00:00"}


class AefTool:
    def inspect(self, _work_order):
        return {"status": "research_gap", "missing_prerequisites": ["confirmed_boundary", "training_labels"]}


def evidence(**overrides):
    value = {
        "source_id": "yearbook", "source_type": "observed", "source_sha256": "a" * 64,
        "locator": "表 5-11，第 71 页", "license_or_access": "review", "tool_run_id": "catalog-1",
        "extracted_fragment": "玉米产量 2935.1 吨", "metric": "玉米产量", "value": 2935.1,
        "unit": "t/a", "raw_status": "observed",
    }
    return {**value, **overrides}


class ResearchWorkflowTests(unittest.TestCase):
    def test_exact_local_observation_is_risk_a_candidate(self):
        """Break caught: a precise admitted fact could still require per-node manual approval."""
        from gep.research import ResearchWorkflow

        result = ResearchWorkflow(Provider(), Catalog([evidence()]), Registry()).run({
            "node_kind": "input", "node_key": "P1.maize.quantity", "node_label": "玉米产量",
        })

        self.assertEqual(result["outcome"], "candidate")
        self.assertEqual(result["risk_tier"], "A")
        self.assertEqual(result["value"], 2935.1)
        self.assertTrue(result["auto_adopt"])

    def test_official_proxy_is_risk_b_candidate(self):
        """Break caught: an official green-area proxy could be auto-adopted as a method-exact fact."""
        from gep.research import ResearchWorkflow

        official = evidence(
            source_id="green", source_type="official_government", source_sha256="",
            metric="海淀区绿地面积", value=14069.69, unit="hm2", raw_status="official_fact",
            risk_tier="B", risk_reason="绿地面积是生态系统面积代理", url="https://yllhj.beijing.gov.cn/a.pdf",
        )
        result = ResearchWorkflow(Provider(), Catalog([]), Registry([official]), AefTool()).run({
            "node_kind": "input", "node_key": "R6.ecosystem_area", "node_label": "ecosystem_area",
        })

        self.assertEqual(result["outcome"], "candidate")
        self.assertEqual(result["risk_tier"], "B")
        self.assertFalse(result["auto_adopt"])
        self.assertEqual(result["evidence"]["online_status"], "verified")
        self.assertEqual(len(result["evidence"]["source_sha256"]), 64)
        self.assertEqual(result["evidence"]["source_hash_scope"], "registry_fact_record")
        self.assertEqual(result["aef_result"]["status"], "research_gap")
        self.assertIn("confirmed_boundary", result["aef_result"]["missing_prerequisites"])

    def test_no_evidence_after_tools_is_research_complete_not_manual(self):
        """Break caught: an exhausted automatic search could still be mislabeled as required human work."""
        from gep.research import ResearchWorkflow

        provider = Provider()
        result = ResearchWorkflow(provider, Catalog([]), Registry()).run({
            "node_kind": "input", "node_key": "R1.precipitation", "node_label": "precipitation",
        })

        self.assertEqual(result["outcome"], "research_complete")
        self.assertEqual(result["risk_tier"], "GAP")
        self.assertEqual(provider.calls, [])
        self.assertIn("local_catalog", result["searched_tools"])
        self.assertIn("official_registry", result["searched_tools"])

    def test_conflicting_official_values_require_tier_c_expert(self):
        """Break caught: conflicting trusted values could be silently resolved by the model."""
        from gep.research import ResearchWorkflow

        first = evidence(source_id="one", source_type="official_government", source_sha256="", value=100, risk_tier="B", url="https://yllhj.beijing.gov.cn/one.pdf")
        second = evidence(source_id="two", source_type="official_government", source_sha256="", value=120, risk_tier="B", url="https://swj.beijing.gov.cn/two.pdf")
        result = ResearchWorkflow(Provider(), Catalog([]), Registry([first, second])).run({
            "node_kind": "input", "node_key": "X.value", "node_label": "value",
        })

        self.assertEqual(result["outcome"], "manual_required")
        self.assertEqual(result["risk_tier"], "C")
        self.assertEqual(result["reason_code"], "source_conflict")

    def test_permission_limited_local_record_requires_tier_c(self):
        from gep.research import ResearchWorkflow

        result = ResearchWorkflow(Provider(), Catalog([evidence(raw_status="permission_required")]), Registry()).run({
            "node_kind": "input", "node_key": "C3.sample", "node_label": "sample",
        })

        self.assertEqual(result["outcome"], "manual_required")
        self.assertEqual(result["reason_code"], "permission_required")

    def test_unverified_official_source_does_not_become_candidate(self):
        """Break caught: a dead or redirected government link could still populate a value."""
        from gep.research import ResearchWorkflow

        official = evidence(source_type="official_government", source_sha256="", risk_tier="B", url="https://yllhj.beijing.gov.cn/a.pdf")
        result = ResearchWorkflow(Provider(), Catalog([]), Registry([official], RuntimeError("offline"))).run({
            "node_kind": "input", "node_key": "R6.ecosystem_area", "node_label": "ecosystem_area",
        })

        self.assertEqual(result["outcome"], "research_complete")
        self.assertEqual(result["verification_failures"], 1)


if __name__ == "__main__":
    unittest.main()
