import unittest
from pathlib import Path


class DeploymentConfigTests(unittest.TestCase):
    def test_smart_data_flag_is_on_for_api_and_worker_but_spatial_stack_stays_out_of_runtime(self):
        root = Path(__file__).parents[1]
        compose = (root / "deploy" / "compose.demo.yml").read_text(encoding="utf-8")
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        api = compose.split("  task-api:", 1)[1].split("  task-worker:", 1)[0]
        worker = compose.split("  task-worker:", 1)[1].split("  task-web:", 1)[0]
        self.assertIn("GEP_SMART_DATA_ENABLED: ${GEP_SMART_DATA_ENABLED:-1}", api)
        self.assertIn("GEP_SMART_DATA_ENABLED: ${GEP_SMART_DATA_ENABLED:-1}", worker)
        self.assertNotIn("requirements-spatial", dockerfile)
        self.assertNotIn("scikit-learn", dockerfile)

    def test_deployment_readme_documents_smart_data_rollback(self):
        readme = (Path(__file__).parents[1] / "deploy" / "README.md").read_text(encoding="utf-8")
        self.assertIn("smart-data-2024-v1", readme)
        self.assertIn("上一 release", readme)
        self.assertIn("GEP_SMART_DATA_ENABLED=0", readme)
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

    def test_model_credentials_are_available_only_to_the_worker(self):
        """Break caught: the API or Web container could receive a model credential it never needs."""
        compose = (Path(__file__).parents[1] / "deploy" / "compose.demo.yml").read_text(encoding="utf-8")
        api_section = compose.split("  task-api:", 1)[1].split("  task-worker:", 1)[0]
        worker_section = compose.split("  task-worker:", 1)[1].split("  task-web:", 1)[0]

        self.assertNotIn("DEEPSEEK_API_KEY", api_section)
        self.assertNotIn("DIFY_API_KEY", api_section)
        for name in (
            "SUPPLEMENT_PROVIDER", "DEEPSEEK_API_BASE_URL", "DEEPSEEK_API_KEY",
            "DEEPSEEK_MODEL", "DEEPSEEK_TIMEOUT_SECONDS",
        ):
            self.assertIn(name, worker_section)
        self.assertIn("DIFY_API_BASE_URL: ${DIFY_API_BASE_URL:-}", worker_section)
        self.assertIn("DIFY_API_KEY: ${DIFY_API_KEY:-}", worker_section)
        self.assertNotRegex(compose, r"(?i)(api_key|token):\s+sk-[A-Za-z0-9]")

    def test_worker_uses_the_same_persistent_runtime_without_publishing_a_port(self):
        """Break caught: an agent request could run in the API process or a second worker could get its own state."""
        compose = (Path(__file__).parents[1] / "deploy" / "compose.demo.yml").read_text(encoding="utf-8")
        worker_section = compose.split("  task-worker:", 1)[1].split("  task-web:", 1)[0]

        self.assertIn('command: ["worker", "--database", "/var/lib/haidian-gep/tasks.sqlite3"]', worker_section)
        self.assertNotIn("ports:", worker_section)
        self.assertIn("${GEP_RUNTIME_DIR:?Set GEP_RUNTIME_DIR to the persistent runtime directory}:/var/lib/haidian-gep", worker_section)
        self.assertIn("DIFY_API_KEY: ${DIFY_API_KEY:-}", worker_section)

    def test_web_waits_for_api_health_before_first_start(self):
        compose = (Path(__file__).parents[1] / "deploy" / "compose.demo.yml").read_text(encoding="utf-8")
        api_section, web_section = compose.split("  task-web:", 1)

        self.assertIn("healthcheck:", api_section)
        self.assertIn('"CMD", "python", "-c"', api_section)
        self.assertIn("depends_on:", web_section)
        self.assertIn("condition: service_healthy", web_section)

    def test_loopback_demo_proxy_supplies_the_trusted_batch_reviewer(self):
        """Break caught: the deployed batch-confirm button could always receive HTTP 503."""
        root = Path(__file__).parents[1]
        compose = (root / "deploy" / "compose.demo.yml").read_text(encoding="utf-8")
        nginx = (root / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        api_section = compose.split("  task-api:", 1)[1].split("  task-worker:", 1)[0]

        self.assertIn("GEP_TRUSTED_PROXY_USER_HEADER: HTTP_X_GEP_ACTOR", api_section)
        self.assertIn('proxy_set_header X-GEP-Actor "demo-reviewer"', nginx)
        self.assertIn('"127.0.0.1:9088:8080"', compose)

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

    def test_canvas_shows_persisted_agent_queue_and_running_states(self):
        """Break caught: an accepted async request could still be displayed as a finished candidate."""
        page = (Path(__file__).parents[1] / "gep" / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("agent_queued", page)
        self.assertIn("agent_running", page)
        self.assertIn("智能体补充中", page)

    def test_canvas_flow_is_tied_to_persisted_event_types(self):
        """Break caught: a looping animation could imply work that never happened."""
        graph = (Path(__file__).parents[1] / "gep" / "web" / "graph.js").read_text(encoding="utf-8")

        self.assertIn("animatePersisted", graph)
        self.assertIn("supplement.running", graph)
        self.assertIn("supplement.manual_required", graph)
        self.assertNotIn("setInterval", graph)

    def test_canvas_exposes_risk_tiers_and_batch_review_instead_of_blanket_manual_copy(self):
        page = (Path(__file__).parents[1] / "gep" / "web" / "index.html").read_text(encoding="utf-8")
        app = (Path(__file__).parents[1] / "gep" / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("整批确认", page)
        self.assertIn("batch-review-preview", (Path(__file__).parents[1] / "gep" / "web" / "api.js").read_text(encoding="utf-8"))
        self.assertIn("research_complete", app)
        self.assertNotIn("智能体如何补充", page)


if __name__ == "__main__":
    unittest.main()
