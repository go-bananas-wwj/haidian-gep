import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from gep.server import build_server


WEB_ROOT = Path(__file__).parents[2] / "gep" / "web"


class TaskCanvasContractTests(unittest.TestCase):
    """Break caught: the web UI regresses to a card list or raw JSON evidence view."""

    def test_canvas_is_split_into_loadable_assets(self):
        index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("styles.css", index)
        self.assertIn("app.js", index)
        for asset in ("api.js", "graph.js", "map.js"):
            self.assertTrue((WEB_ROOT / asset).is_file())

        with tempfile.TemporaryDirectory() as directory:
            server = build_server("127.0.0.1", 0, Path(directory) / "tasks.sqlite3")
            worker = threading.Thread(target=server.handle_request)
            worker.start()
            with urlopen(f"http://127.0.0.1:{server.server_port}/styles.css", timeout=2) as response:
                stylesheet = response.read().decode("utf-8")
            worker.join(timeout=2)
            server.server_close()
        self.assertIn(".canvas", stylesheet)

    def test_five_step_evidence_first_workflow_is_present(self):
        index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        for label in ("任务中心", "数据准备", "核算方案", "执行核算", "结果与交付"):
            self.assertIn(label, index)
        self.assertIn("智能体补充", index)
        self.assertIn("待审核", index)
        self.assertNotIn("JSON.stringify", index)

    def test_catalogue_has_fixed_22_indicator_graph_and_product_detail(self):
        graph = (WEB_ROOT / "graph.js").read_text(encoding="utf-8")
        self.assertIn("P1", graph)
        self.assertIn("R12", graph)
        self.assertIn("C3", graph)
        self.assertIn("农产品", graph)
        self.assertIn("林产品", graph)
        self.assertIn("鱼骨", graph)
        self.assertIn("localStorage", graph)

    def test_product_fishbone_uses_readable_accounting_field_labels(self):
        graph = (WEB_ROOT / "graph.js").read_text(encoding="utf-8")
        self.assertIn("资本回报", graph)
        self.assertIn("中间投入成本", graph)
        self.assertIn("玉米产量", graph)

    def test_canvas_matches_the_overleaf_accounting_board_hierarchy(self):
        graph = (WEB_ROOT / "graph.js").read_text(encoding="utf-8")
        self.assertIn("物质产品 + 调节服务 + 文化服务", graph)
        self.assertIn("7 个科目", graph)
        self.assertIn("12 个科目", graph)
        self.assertIn("3 个科目", graph)
        self.assertIn("粮食作物", graph)
        self.assertIn("小麦（候选）", graph)

    def test_indicator_and_evidence_details_share_one_right_drawer(self):
        """Break caught: node details could open below the viewport or in a second competing modal."""
        index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertEqual(index.count('id="detail-drawer"'), 1)
        self.assertIn('role="dialog"', index)
        self.assertIn('aria-modal="true"', index)
        self.assertIn('aria-labelledby="drawer-title"', index)
        self.assertNotIn('id="detail-board"', index)
        self.assertNotIn('id="evidence-dialog"', index)
        self.assertIn("openIndicatorDrawer", app)
        self.assertIn("openEvidenceDrawer", app)
        self.assertIn("closeDrawer", app)

    def test_drawer_is_responsive_and_keyboard_accessible(self):
        """Break caught: the right drawer could trap focus or overflow a phone viewport."""
        styles = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn(".detail-drawer", styles)
        self.assertRegex(styles, r"\.detail-drawer\s*\{[^}]*width:\s*(4[2-8]0px|min\()")
        self.assertIn("transition:", styles)
        self.assertIn(":focus-visible", styles)
        self.assertRegex(styles, r"\.drawer-overlay\[hidden\]\s*\{[^}]*display:\s*none")
        self.assertRegex(styles, r"@media\s*\(max-width:\s*600px\)[\s\S]*\.detail-drawer[^{]*\{[^}]*width:\s*(100%|min\()")
        self.assertIn('event.key === "Escape"', app)
        self.assertIn("lastDrawerTrigger", app)

    def test_persisted_events_flow_along_svg_edges(self):
        """Break caught: progress could be represented by a generic card flash instead of its real dependency path."""
        graph = (WEB_ROOT / "graph.js").read_text(encoding="utf-8")
        styles = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn("createElementNS", graph)
        self.assertIn("edge-layer", graph)
        self.assertIn("layoutEdges", graph)
        self.assertIn("root:${category}", graph)
        self.assertIn("${category}:${key}", graph)
        for event_type in (
            "graph.initialized", "supplement.queued", "supplement.running",
            "supplement.candidate_persisted", "supplement.manual_required",
            "supplement.failed", "supplement.stale",
        ):
            self.assertIn(event_type, graph)
        self.assertIn("if (!edge) continue", graph)
        self.assertIn("stroke-dashoffset", styles)
        self.assertIn("@keyframes edge-flow", styles)
        self.assertIn("prefers-reduced-motion", styles)

    def test_all_agent_terminal_and_progress_states_are_distinct(self):
        """Break caught: queued, failed, or manual nodes could all look like generic pending work."""
        graph = (WEB_ROOT / "graph.js").read_text(encoding="utf-8")
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        for label in ("智能体排队中", "智能体补充中", "智能体已补充·待审核", "待人工介入", "补充失败·可重试", "退回重查", "审核通过"):
            self.assertIn(label, graph)
        for summary in ("待审核", "待人工介入", "补充失败", "处理中"):
            self.assertIn(summary, app)


if __name__ == "__main__":
    unittest.main()
