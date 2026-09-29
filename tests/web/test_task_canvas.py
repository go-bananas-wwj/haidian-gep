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
        for asset in ("api.js", "graph.js", "guide.js", "map.js"):
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

    def test_page_uses_an_embedded_icon_without_a_failing_favicon_request(self):
        index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="icon" href="data:image/svg+xml', index)

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

    def test_every_indicator_opens_its_input_branch_not_only_material_products(self):
        """Break caught: official green/AEF inputs could be hidden behind a non-expandable regulating node."""
        graph = (WEB_ROOT / "graph.js").read_text(encoding="utf-8")

        self.assertNotIn('["P1", "P2", "P3", "P4"].includes(key)', graph)
        self.assertIn("this.onDetail?.(node, detailDescriptions[key]", graph)

    def test_product_fishbone_uses_readable_accounting_field_labels(self):
        graph = (WEB_ROOT / "graph.js").read_text(encoding="utf-8")
        self.assertIn("资本回报", graph)
        self.assertIn("中间投入成本", graph)
        self.assertIn("玉米产量", graph)
        self.assertIn("生态系统面积", graph)
        self.assertIn("本地生态供水量", graph)

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
        self.assertIn("drawerRequestVersion", app)
        self.assertIn("requestVersion !== drawerRequestVersion", app)

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
        self.assertIn("@keyframes edge-stream", styles)
        self.assertIn("prefers-reduced-motion", styles)

    def test_all_agent_terminal_and_progress_states_are_distinct(self):
        """Break caught: queued, failed, or manual nodes could all look like generic pending work."""
        graph = (WEB_ROOT / "graph.js").read_text(encoding="utf-8")
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        for label in ("智能体排队中", "智能体补充中", "已自动采用·待整批确认", "已补充·建议复核", "已自动检索·等待数据", "需专家介入", "执行失败·可重试", "退回重查", "审核通过"):
            self.assertIn(label, graph)
        for summary in ("自动采用", "建议复核", "等待数据", "专家介入", "执行失败", "处理中"):
            self.assertIn(summary, app)

    def test_restoring_a_historical_task_heals_its_automatic_queue(self):
        """Break caught: tasks created before auto-scheduling could remain forever at awaiting-agent."""
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn("await taskApi.autoSupplement", app)

    def test_a1_drawer_is_source_first_and_has_no_model_monologue_heading(self):
        """Break caught: the drawer could keep foregrounding the model instead of the calculation lesson."""
        index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("智能体如何补充", index)
        headings = (
            "核算对象", "本步目标", "所需输入", "计算方法", "代入与计算",
            "结果怎么理解", "数据来源", "工作执行记录", "风险与人工事项", "审核操作",
        )
        positions = [index.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("已自动采用·待整批确认", index)
        self.assertIn("标记问题", index)

    def test_drawer_uses_chinese_first_field_labels_and_agent_detail_api(self):
        """Break caught: raw program fields and English statuses could leak into the first-time user view."""
        labels = (WEB_ROOT / "labels.js").read_text(encoding="utf-8")
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        api = (WEB_ROOT / "api.js").read_text(encoding="utf-8")
        self.assertIn('ecosystem_area: "生态系统面积"', labels)
        self.assertIn("fieldLabel", app)
        self.assertIn("taskApi.agentDetail", app)
        self.assertIn("agent-detail", api)
        self.assertIn("requestVersion !== drawerRequestVersion", app)
        self.assertNotIn('textContent = evidence.applicability_status', app)

    def test_task_ui_distinguishes_a_b_gap_c_and_failure(self):
        """Break caught: completed automatic research could still look like blanket manual intervention."""
        graph = (WEB_ROOT / "graph.js").read_text(encoding="utf-8")
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        for label in ("已自动采用·待整批确认", "已补充·建议复核", "已自动检索·等待数据", "需专家介入", "执行失败·可重试"):
            self.assertIn(label, graph)
        for summary in ("自动采用", "建议复核", "等待数据", "专家介入", "执行失败"):
            self.assertIn(summary, app)

    def test_batch_confirmation_modal_supports_confirm_and_cancel_paths(self):
        """Break caught: users could not choose between bulk default review and item-by-item review."""
        index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="batch-review"', index)
        self.assertIn('id="batch-review-dialog"', index)
        self.assertIn('id="confirm-batch-review"', index)
        self.assertIn('id="cancel-batch-review"', index)
        self.assertIn("taskApi.batchPreview", app)
        self.assertIn("taskApi.batchReview", app)
        self.assertIn("submitBatchReview(true)", app)
        self.assertIn("submitBatchReview(false)", app)
        self.assertIn("individualReviewMode", app)
        self.assertIn('reviewButton(evidence, "approved", "确认采用", true)', app)


if __name__ == "__main__":
    unittest.main()
