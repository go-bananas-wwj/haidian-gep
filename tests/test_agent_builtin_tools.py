import unittest

from gep.agent.evidence import ValidationResult
from gep.agent.readers import ReadResult
from gep.agent.search import SearchHit
from gep.agent.tools import ToolRegistry


class LocalCatalog:
    def for_work_order(self, work_order):
        return [{"source_id": "local-1", "metric": work_order["node_label"], "value": 1, "unit": "mm/a"}]


class ObservationStore:
    def find_observations(self, **query):
        return [{"observation_id": "obs-1", **query, "value": 2.0}]


class OfficialRegistry:
    def search(self, work_order):
        return [{"source_id": "official-1", "node_key": work_order["node_key"], "value": 3.0, "unit": "hm2"}]


class Knowledge:
    def search(self, query, *, filters=None, limit=5):
        return [{"document_id": "doc-1", "fragment": query, "locator": "第 1 页"}][:limit]


class Search:
    def search(self, query, *, domains=None, limit=5, language="zh-CN"):
        return [SearchHit("结果", "https://example.com", query, "fake", 1)]


class Reader:
    def read(self, url, pages=None):
        return ReadResult(
            title="原文", publisher="发布者", final_url=url, content_type="text/html",
            text="正文", locator="HTML 正文" if pages is None else "PDF 第 1 页",
            sha256="a" * 64, fetched_utc="2026-09-29T00:00:00Z",
        )


class Aef:
    def inspect(self, work_order):
        return {"status": "available", "node_key": work_order["node_key"]}


class Validator:
    def validate(self, target, items):
        return ValidationResult(tuple(items), (), "B", (), (), None)


class BuiltinToolTests(unittest.TestCase):
    def _registry(self):
        from gep.agent.builtin_tools import BuiltinToolContext, register_builtin_tools

        registry = ToolRegistry()
        register_builtin_tools(registry, BuiltinToolContext(
            local_catalog=LocalCatalog(), observation_store=ObservationStore(),
            official_registry=OfficialRegistry(), knowledge_base=Knowledge(), search_provider=Search(),
            web_reader=Reader(), pdf_reader=Reader(), aef_tool=Aef(), evidence_validator=Validator(),
        ))
        return registry

    def test_registers_and_executes_ten_structured_tools(self):
        """Break caught: one data source could bypass the common ToolResult boundary."""
        registry = self._registry()
        self.assertEqual(
            {spec.tool_id for spec in registry.specs()},
            {
                "local.catalog.search", "smart.observation.search", "official.registry.search",
                "knowledge.search", "web.search", "web.read", "document.read",
                "geo.alphaearth.inspect", "gep.method.execute", "evidence.validate",
            },
        )
        calls = {
            "local.catalog.search": {"work_order": {"node_label": "precipitation"}},
            "smart.observation.search": {"metric": "precipitation", "year": 2024, "region_code": "110108"},
            "official.registry.search": {"work_order": {"node_key": "R1.ecosystem_area"}},
            "knowledge.search": {"query": "水源涵养", "limit": 5},
            "web.search": {"query": "海淀区生态公报", "limit": 5},
            "web.read": {"url": "https://example.com/page"},
            "document.read": {"url": "https://example.com/report.pdf", "pages": [1]},
            "geo.alphaearth.inspect": {"work_order": {"node_key": "R1.ecosystem_area"}},
            "gep.method.execute": {
                "method_id": "R7.oxygen_link.demo.v1",
                "inputs": {"carbon_sequestration_rate": {"value": 44.0, "unit": "tCO2/a"}},
            },
            "evidence.validate": {
                "target": {"metric": "area", "region_code": "110108", "year": 2024, "unit": "hm2"},
                "items": [{"source_id": "source-1"}],
            },
        }
        results = {tool_id: registry.call(tool_id, arguments) for tool_id, arguments in calls.items()}
        self.assertTrue(all(result.status == "ok" for result in results.values()))
        self.assertEqual(results["gep.method.execute"].data["result"], {"value": 32.0, "unit": "tO2/a"})
        self.assertTrue(results["web.search"].data["hits"][0]["discovery_only"])
        self.assertEqual(results["web.read"].evidence[0]["source_sha256"], "a" * 64)
        self.assertEqual(results["evidence.validate"].data["risk_tier"], "B")

    def test_calculation_tool_rejects_unknown_method(self):
        """Break caught: the planner could invent a calculator method ID."""
        registry = self._registry()
        with self.assertRaisesRegex(ValueError, "unknown method"):
            registry.call("gep.method.execute", {"method_id": "R1.magic.v9", "inputs": {}})

    def test_calculation_tool_rejects_input_without_unit(self):
        """Break caught: a correct-looking number in the wrong unit could enter a GEP formula."""
        registry = self._registry()
        with self.assertRaisesRegex(ValueError, "unit"):
            registry.call("gep.method.execute", {
                "method_id": "R7.oxygen_link.demo.v1",
                "inputs": {"carbon_sequestration_rate": {"value": 44.0}},
            })


if __name__ == "__main__":
    unittest.main()
