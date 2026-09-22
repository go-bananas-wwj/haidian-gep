import unittest
from pathlib import Path


class DeploymentConfigTests(unittest.TestCase):
    def test_web_uses_approved_loopback_port_and_api_has_no_host_port(self):
        compose = (Path(__file__).parents[1] / "deploy" / "compose.demo.yml").read_text(encoding="utf-8")
        api_section, web_section = compose.split("  task-web:", 1)

        self.assertNotIn("ports:", api_section)
        self.assertIn('"127.0.0.1:9088:8080"', web_section)
        self.assertNotIn("8000:8000", compose)
        self.assertNotIn("8080:8080", compose)

    def test_api_mounts_the_approved_data_root_read_only(self):
        compose = (Path(__file__).parents[1] / "deploy" / "compose.demo.yml").read_text(encoding="utf-8")
        api_section, _ = compose.split("  task-web:", 1)

        self.assertIn(
            "${GEP_DATA_DIR:?Set GEP_DATA_DIR to the admitted data directory}:/var/lib/haidian-gep-data:ro",
            api_section,
        )

    def test_web_waits_for_api_health_before_first_start(self):
        compose = (Path(__file__).parents[1] / "deploy" / "compose.demo.yml").read_text(encoding="utf-8")
        api_section, web_section = compose.split("  task-web:", 1)

        self.assertIn("healthcheck:", api_section)
        self.assertIn('"CMD", "python", "-c"', api_section)
        self.assertIn("depends_on:", web_section)
        self.assertIn("condition: service_healthy", web_section)

    def test_canvas_uses_nginx_api_route_on_the_9088_web_entrypoint(self):
        page = (Path(__file__).parents[1] / "gep" / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("const apiBase='/api';", page)

    def test_canvas_reads_the_selected_data_package_before_creating_a_task(self):
        """Break caught: a browser could hide that its selected data package is reference-only."""
        page = (Path(__file__).parents[1] / "gep" / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("数据包准入", page)
        self.assertIn("/data-versions/", page)
        self.assertIn("accounting_ready", page)
        self.assertIn("alphaearth_candidates", page)

    def test_canvas_keeps_layout_state_outside_the_accounting_graph(self):
        """Break caught: panning, zooming, collapsing, or moving a card could mutate audited inputs."""
        page = (Path(__file__).parents[1] / "gep" / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("localStorage", page)
        self.assertIn("view-layout", page)
        self.assertIn("折叠全部", page)
        self.assertIn("pointerdown", page)
        self.assertIn("style.zoom", page)

    def test_canvas_expands_an_indicator_from_its_real_required_input_nodes(self):
        """Break caught: every GEP subject could misleadingly show only the maize detail branch."""
        page = (Path(__file__).parents[1] / "gep" / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("parent_key===node.node_key", page)
        self.assertIn("required_inputs", page)
        self.assertIn("acquisition_status", page)

    def test_canvas_polls_only_persisted_task_events(self):
        """Break caught: the graph could animate or claim progress without reading an event sequence."""
        page = (Path(__file__).parents[1] / "gep" / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("/events?after=", page)
        self.assertIn("lastEvent", page)
        self.assertIn("事件记录", page)
        self.assertIn("setInterval", page)


if __name__ == "__main__":
    unittest.main()
