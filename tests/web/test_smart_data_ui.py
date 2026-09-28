import os
import tempfile
import threading
import unittest
from pathlib import Path

from gep.server import build_server

CHROMIUM = os.environ.get("GEP_BROWSER_EXECUTABLE", "/home/wwj/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome")


@unittest.skipUnless(Path(CHROMIUM).is_file(), "Chromium is required")
class SmartDataUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = build_server("127.0.0.1", 0, Path(cls.tmp.name) / "tasks.sqlite3")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.server.shutdown(); cls.server.server_close(); cls.tmp.cleanup()

    def test_renderers_show_asset_quality_and_complete_calculation_chain(self):
        page = self.browser.new_page(); page.goto(self.url)
        result = page.evaluate("""async () => {
          const {renderAssetCatalog, renderCalculationChain} = await import('/smart-data.js');
          const assets = document.createElement('div'), chain = document.createElement('div');
          renderAssetCatalog(assets, [{asset_id:'aef-2024',title:'2024 AlphaEarth',asset_type:'aef',period_start:'2024-01-01',period_end:'2024-12-31',quality_status:'available',sha256:'abc123',license_or_access:'CC-BY 4.0'}]);
          renderCalculationChain(chain,{plan:{method_id:'R1.water_balance.demo.v1',explanation:'水量平衡'},observations:[{metric:'precipitation',value:855.17,unit:'mm/a'}],run:{result:{value:5000,unit:'m3/a'},quality:{evidence_classes:['model_estimate']}}});
          return {assets:assets.textContent,chain:chain.textContent};
        }""")
        self.assertIn("2024 AlphaEarth", result["assets"]); self.assertIn("CC-BY 4.0", result["assets"])
        self.assertIn("R1.water_balance.demo.v1", result["chain"]); self.assertIn("5000", result["chain"])
        page.close()

    def test_smart_task_has_tabs_progress_human_work_and_no_body_overflow(self):
        page = self.browser.new_page(viewport={"width":390,"height":844})
        task = {"task_id":"smart-task","year":2024,"graph_version":3,"pending_review_count":0,"formal_blocker_count":2,"data_version":"smart-data-2024-v1"}
        nodes = [{"node_id":"r1","node_key":"R1","kind":"indicator","label":"水源涵养","category":"regulating","acquisition_status":"ready","review_status":"unsubmitted","applicability_status":"applicable","value":None,"evidence":{}},
                 {"node_id":"precip","node_key":"R1.precipitation","parent_key":"R1","kind":"input","label":"precipitation","category":"regulating","acquisition_status":"candidate_ready","review_status":"unsubmitted","applicability_status":"applicable","value":855.17,"unit":"mm/a","version":2,"evidence":{"current":{"result_class":"model_estimate","demo_auto_adopt":True}}}]
        data_version_requests = []
        def route(r):
            u=r.request.url; method=r.request.method
            if u.endswith('/api/tasks') and method=='GET': return r.fulfill(json={"tasks":[task]})
            if u.endswith('/supplements:auto'): return r.fulfill(json={})
            if u.endswith('/graph'): return r.fulfill(json={"task":task,"nodes":nodes})
            if u.endswith('/snapshots'): return r.fulfill(json={"snapshots":[]})
            if '/events' in u: return r.fulfill(json={"events":[]})
            if u.endswith('/automation-summary'): return r.fulfill(json={"result_classes":{"model_estimate":1,"needs_department_data":1},"human_work":[{"type":"needs_department_data","count":1,"nodes":["C1.visitor_count"]}],"indicator_progress":{"R1":{"total":8,"prepared":7,"active":0,"manual":1,"status":"needs_input"}}})
            if u.endswith('/demo-readiness'): return r.fulfill(json={"demo_ready":False,"formal_ready":False,"estimated_input_ratio":1.0})
            if '/data-assets' in u: return r.fulfill(json={"assets":[{"asset_id":"aef-2024","title":"2024 AlphaEarth","asset_type":"aef","period_start":"2024-01-01","period_end":"2024-12-31","quality_status":"available","sha256":"abc","license_or_access":"CC-BY 4.0"}]})
            if '/data-versions/' in u: data_version_requests.append(u); return r.fulfill(status=404,json={"error":"not registered"})
            return r.fulfill(status=404,json={"error":"not found"})
        page.route("**/api/**", route); page.goto(self.url,wait_until="networkidle")
        page.get_by_role("button",name="恢复任务").click(); page.locator('[data-page-panel="prepare"]').wait_for(state="visible")
        self.assertTrue(page.get_by_role("tab",name="指标图").is_visible())
        self.assertTrue(page.get_by_role("tab",name="数据后台").is_visible())
        self.assertIn("7/8 已自动准备", page.locator('[data-node="R1"]').inner_text())
        self.assertNotIn("已自动检索·等待数据", page.locator('[data-node="R1"]').inner_text())
        page.get_by_role("tab",name="数据后台").click()
        self.assertIn("2024 AlphaEarth", page.locator('#asset-catalog').inner_text())
        self.assertIn("等待部门数据", page.locator('#human-work').inner_text())
        self.assertEqual(data_version_requests, [])
        overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        self.assertFalse(overflow)
        page.close()


if __name__ == "__main__": unittest.main()
