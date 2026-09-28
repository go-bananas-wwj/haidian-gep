import os
import threading
import time
import unittest
from pathlib import Path

from gep.server import build_server


CHROMIUM = os.environ.get(
    "GEP_BROWSER_EXECUTABLE",
    "/home/wwj/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
)


@unittest.skipUnless(Path(CHROMIUM).is_file(), "Chromium is required for browser UX checks")
class GuidedBrowserUxTests(unittest.TestCase):
    """Real-browser checks for the continuously animated, guided workflow."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.server = build_server("127.0.0.1", 0, Path(cls._testMethodName if hasattr(cls, "_testMethodName") else "/tmp") / "unused.sqlite3")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=CHROMIUM,
            headless=True,
            args=["--no-sandbox"],
        )
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.emulate_media(reduced_motion="no-preference")
        self.page.route("**/api/tasks", lambda route: route.fulfill(json={"tasks": []}))
        self.page.goto(self.base_url, wait_until="networkidle")

    def tearDown(self):
        self.page.close()

    def test_edges_keep_streaming_after_event_highlight_expires(self):
        """Break caught: graph flow stops after a one-shot persisted-event animation."""
        result = self.page.evaluate(
            """async () => {
                const { GepGraph, INDICATORS } = await import('/graph.js');
                document.querySelector('[data-page-panel="centre"]').hidden = true;
                document.querySelector('[data-page-panel="prepare"]').hidden = false;
                const host = document.querySelector('#graph-canvas');
                const nodes = INDICATORS.map(([node_key, label]) => ({
                  node_id: `node-${node_key}`,
                  node_key,
                  label,
                  kind: 'indicator',
                  acquisition_status: 'research_complete',
                  review_status: 'unsubmitted'
                }));
                const graph = new GepGraph(host);
                graph.render(nodes);
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                const edge = host.querySelector('[data-edge="regulating:R1"]');
                const before = getComputedStyle(edge);
                const animation = edge.getAnimations()[0];
                const firstTime = animation.currentTime;
                await new Promise(resolve => setTimeout(resolve, 320));
                const secondTime = animation.currentTime;
                graph.animatePersisted([{type:'research.completed', node_id:'node-R1'}]);
                await new Promise(resolve => setTimeout(resolve, 80));
                const highlighted = edge.classList.contains('flowing');
                await new Promise(resolve => setTimeout(resolve, 1700));
                const after = getComputedStyle(edge);
                return {
                  edgeCount: host.querySelectorAll('.edge-path').length,
                  animationName: after.animationName,
                  iterationCount: after.animationIterationCount,
                  firstTime,
                  secondTime,
                  highlighted,
                  highlightExpired: !edge.classList.contains('flowing')
                };
            }"""
        )
        self.assertEqual(result["edgeCount"], 25)
        self.assertEqual(result["animationName"], "edge-stream")
        self.assertEqual(result["iterationCount"], "infinite")
        self.assertGreater(result["secondTime"], result["firstTime"] + 250)
        self.assertTrue(result["highlighted"])
        self.assertTrue(result["highlightExpired"])

    def test_next_action_guides_each_workflow_state(self):
        """Break caught: a first-time user sees competing actions or no clear next step."""
        cases = self.page.evaluate(
            """async () => {
                const { nextActionFor } = await import('/guide.js');
                return [
                  nextActionFor({active: 3, auto: 0, review: 0, gap: 0, expert: 0, failed: 0}),
                  nextActionFor({active: 0, auto: 2, review: 5, gap: 8, expert: 1, failed: 1}),
                  nextActionFor({active: 0, auto: 2, review: 5, gap: 8, expert: 0, failed: 0}),
                  nextActionFor({active: 0, auto: 0, review: 0, gap: 8, expert: 0, failed: 0}),
                  nextActionFor({active: 0, auto: 0, review: 0, gap: 0, expert: 0, failed: 0})
                ];
            }"""
        )
        self.assertEqual(
            [(item["kind"], item["disabled"]) for item in cases],
            [("wait", True), ("exceptions", False), ("batch", False), ("gaps", False), ("scheme", False)],
        )
        self.assertEqual(
            [item["button"] for item in cases],
            ["等待自动研究完成", "处理 2 个异常", "整批确认 7 项", "查看 8 个数据缺口", "进入核算方案"],
        )

    def test_restored_task_lays_out_flow_after_prepare_page_is_visible(self):
        """Break caught: first open renders all SVG paths at 0,0 while the prepare page is hidden."""
        page = self.browser.new_page()
        page.emulate_media(reduced_motion="no-preference")
        task = {
            "task_id": "task-browser-1", "year": 2024, "graph_version": 1,
            "pending_review_count": 0, "formal_blocker_count": 22,
            "data_version": "reference-2024-v0.1",
        }

        def api(route):
            request = route.request
            path = request.url.split("/api", 1)[1].split("?", 1)[0]
            if path == "/tasks":
                route.fulfill(json={"tasks": [task]})
            elif path == "/tasks/task-browser-1/graph":
                route.fulfill(json={"task": task, "nodes": []})
            elif path == "/tasks/task-browser-1/snapshots":
                route.fulfill(json={"snapshots": []})
            elif path == "/tasks/task-browser-1/events":
                route.fulfill(json={"events": []})
            elif path == "/data-versions/reference-2024-v0.1":
                route.fulfill(json={"accounting_ready": False, "alphaearth_candidates": []})
            else:
                route.fulfill(json={})

        page.route("**/api/**", api)
        page.goto(self.base_url, wait_until="networkidle")
        page.get_by_role("button", name="恢复任务").click()
        page.locator('[data-page-panel="prepare"]').wait_for(state="visible")
        page.locator(".edge-path").first.wait_for(state="attached")
        paths = page.locator(".edge-path").evaluate_all(
            "edges => edges.map(edge => edge.getAttribute('d'))"
        )
        self.assertEqual(len(paths), 25)
        self.assertTrue(all(path and path != "M 0 0 C 0 18, 0 18, 0 0" for path in paths))
        page.close()


if __name__ == "__main__":
    unittest.main()
