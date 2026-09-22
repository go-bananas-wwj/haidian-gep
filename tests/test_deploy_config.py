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

    def test_canvas_uses_nginx_api_route_on_the_9088_web_entrypoint(self):
        page = (Path(__file__).parents[1] / "gep" / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("const apiBase='/api';", page)


if __name__ == "__main__":
    unittest.main()
