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


if __name__ == "__main__":
    unittest.main()
