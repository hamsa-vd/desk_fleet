"""The dashboard and the deployment files are artifacts, so they are checked like code.

The point of the metric-name cross-check is that a panel querying a metric nobody emits looks
perfectly healthy in Grafana — it just draws nothing. Comparing every `expr` against the live
registry is what stops the dashboard drifting away from `observability/metrics.py`.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from deskfleet.observability import metrics as metrics_module

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
ROOT = DEPLOY.parent
DASHBOARD = DEPLOY / "grafana" / "dashboards" / "deskfleet.json"

METRIC_REFERENCE = re.compile(r"\bdeskfleet_[a-z0-9_]+")

REQUIRED_PANELS = ["Ticket throughput", "P99 ticket latency", "Token spend", "Escalation rate"]


@pytest.fixture(scope="module")
def dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def expressions(dashboard: dict) -> list[tuple[str, str]]:
    return [
        (panel["title"], target["expr"])
        for panel in dashboard["panels"]
        for target in panel["targets"]
    ]


@pytest.fixture(scope="module")
def emitted() -> set[str]:
    """Every series name the app can actually expose, histogram suffixes included."""
    names: set[str] = set()
    for metric in metrics_module.metrics().values():
        base = metric._name
        names.add(base)
        if type(metric).__name__ == "Counter":
            names.add(f"{base}_total")
        if type(metric).__name__ == "Histogram":
            names.update({f"{base}_bucket", f"{base}_count", f"{base}_sum"})
    return names


# --- the dashboard -----------------------------------------------------------------------


def test_the_dashboard_is_valid_json_with_a_stable_uid(dashboard: dict) -> None:
    assert dashboard["uid"] == "deskfleet"
    assert dashboard["title"] == "DeskFleet"
    assert dashboard["panels"], "a dashboard with no panels provisions silently and shows nothing"


def test_every_required_panel_is_present(dashboard: dict) -> None:
    titles = [panel["title"] for panel in dashboard["panels"]]

    assert [title for title in REQUIRED_PANELS if title not in titles] == []


def test_panel_ids_are_unique(dashboard: dict) -> None:
    ids = [panel["id"] for panel in dashboard["panels"]]

    assert len(ids) == len(set(ids))


def test_every_queried_metric_exists_in_the_registry(expressions, emitted: set[str]) -> None:
    unknown = {
        (title, name)
        for title, expr in expressions
        for name in METRIC_REFERENCE.findall(expr)
        if name not in emitted
    }

    assert unknown == set(), "panels query metrics F-09 does not emit"


def test_every_panel_has_at_least_one_target(dashboard: dict) -> None:
    empty = [panel["title"] for panel in dashboard["panels"] if not panel["targets"]]

    assert empty == []


def test_no_panel_computes_an_average_latency(expressions) -> None:
    offenders = [
        (title, expr)
        for title, expr in expressions
        if "latency_seconds_sum" in expr or re.search(r"\bavg\(", expr)
    ]

    assert offenders == [], "averages hide the tail; use histogram_quantile"


@pytest.mark.parametrize(
    "counter",
    [
        "deskfleet_tickets_total",
        "deskfleet_tokens_total",
        "deskfleet_escalations_total",
        "deskfleet_refusals_total",
        "deskfleet_budget_exceeded_total",
        "deskfleet_tool_calls_total",
        "deskfleet_http_requests_total",
    ],
)
def test_rate_counters_are_never_graphed_raw(expressions, counter: str) -> None:
    """A raw counter graph is a staircase that resets on every cold start."""
    for title, expr in expressions:
        for match in re.finditer(re.escape(counter), expr):
            window = expr[max(0, match.start() - 40) : match.start()]
            assert "rate(" in window or "increase(" in window, f"{title}: {expr}"


def test_the_cumulative_cost_panel_is_the_one_deliberate_raw_counter(expressions) -> None:
    """Total spend to date is a total; the exception is called out rather than left implicit."""
    raw = [
        (title, expr)
        for title, expr in expressions
        if "deskfleet_cost_usd_total" in expr and "rate(" not in expr
    ]

    assert [title for title, _ in raw] == ["Cumulative USD"]


def test_every_target_points_at_the_provisioned_datasource(dashboard: dict) -> None:
    types = {
        target["datasource"]["type"] for panel in dashboard["panels"] for target in panel["targets"]
    }

    assert types == {"prometheus"}


# --- prometheus --------------------------------------------------------------------------


def test_prometheus_scrapes_the_api_over_the_compose_network() -> None:
    config = yaml.safe_load((DEPLOY / "prometheus.yml").read_text(encoding="utf-8"))

    api = next(j for j in config["scrape_configs"] if j["job_name"] == "deskfleet-api")
    assert api["static_configs"][0]["targets"] == ["api:8080"]
    assert api["metrics_path"] == "/metrics"
    assert config["global"]["scrape_interval"] == "15s"


def test_prometheus_loads_the_alert_rules() -> None:
    config = yaml.safe_load((DEPLOY / "prometheus.yml").read_text(encoding="utf-8"))

    assert "/etc/prometheus/alerts.yml" in config["rule_files"]


def test_the_alert_rules_parse_and_reference_real_metrics(emitted: set[str]) -> None:
    rules = yaml.safe_load((DEPLOY / "alerts.yml").read_text(encoding="utf-8"))

    expressions = [rule["expr"] for group in rules["groups"] for rule in group["rules"]]
    assert expressions
    unknown = {n for expr in expressions for n in METRIC_REFERENCE.findall(expr)} - emitted
    assert unknown == set()


def test_alerts_are_symptoms_not_causes() -> None:
    rules = yaml.safe_load((DEPLOY / "alerts.yml").read_text(encoding="utf-8"))

    expressions = " ".join(rule["expr"] for g in rules["groups"] for rule in g["rules"])
    assert "container_cpu" not in expressions
    assert "container_memory" not in expressions


def test_every_alert_waits_before_firing() -> None:
    rules = yaml.safe_load((DEPLOY / "alerts.yml").read_text(encoding="utf-8"))

    for group in rules["groups"]:
        for rule in group["rules"]:
            assert rule.get("for"), f"{rule['alert']} would fire on a single scrape blip"


# --- the remote_write switch ---------------------------------------------------------------


def render_prometheus_config(tmp_path: Path, env: dict[str, str]) -> str:
    """Runs the real entrypoint with a stub binary so only the config rendering is exercised."""
    binary = tmp_path / "fake-prometheus"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    target = tmp_path / "rendered.yml"

    subprocess.run(
        ["/bin/sh", str(DEPLOY / "prometheus-entrypoint.sh")],
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "PROMETHEUS_BINARY": str(binary),
            "PROMETHEUS_CONFIG_SOURCE": str(DEPLOY / "prometheus.yml"),
            "PROMETHEUS_CONFIG_TARGET": str(target),
            **env,
        },
    )
    return target.read_text(encoding="utf-8")


def test_the_stack_starts_with_the_grafana_cloud_variables_unset(tmp_path: Path) -> None:
    rendered = render_prometheus_config(tmp_path, {})

    assert "remote_write" not in rendered
    assert yaml.safe_load(rendered)["scrape_configs"]


def test_a_partial_grafana_cloud_configuration_is_ignored(tmp_path: Path) -> None:
    rendered = render_prometheus_config(
        tmp_path, {"GRAFANA_CLOUD_PROM_URL": "https://prom.example/api/prom/push"}
    )

    assert "remote_write" not in rendered


def test_all_three_variables_together_enable_remote_write(tmp_path: Path) -> None:
    rendered = render_prometheus_config(
        tmp_path,
        {
            "GRAFANA_CLOUD_PROM_URL": "https://prom.example/api/prom/push",
            "GRAFANA_CLOUD_PROM_USER": "123456",
            "GRAFANA_CLOUD_PROM_KEY": "glc_secret",
        },
    )

    config = yaml.safe_load(rendered)
    assert config["remote_write"][0]["url"] == "https://prom.example/api/prom/push"
    assert config["remote_write"][0]["basic_auth"] == {
        "username": "123456",
        "password": "glc_secret",
    }
    assert config["scrape_configs"], "push must not replace local scraping"


# --- grafana provisioning ------------------------------------------------------------------


def test_the_datasource_is_provisioned_from_a_file() -> None:
    source = yaml.safe_load((DEPLOY / "grafana" / "datasource.yml").read_text(encoding="utf-8"))

    datasource = source["datasources"][0]
    assert datasource["type"] == "prometheus"
    assert datasource["url"] == "http://prometheus:9090"
    assert datasource["isDefault"] is True


def test_the_dashboard_provider_points_at_the_mounted_directory() -> None:
    provider = yaml.safe_load((DEPLOY / "grafana" / "dashboards.yml").read_text(encoding="utf-8"))

    assert provider["providers"][0]["options"]["path"] == "/var/lib/grafana/dashboards"


# --- github actions ----------------------------------------------------------------------


def test_the_deploy_workflow_gates_deploys_on_tests() -> None:
    workflow = yaml.load(
        (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"]["contents"] == "read"
    assert workflow["jobs"]["deploy"]["needs"] == "validate"
    assert "workflow_dispatch" in workflow["jobs"]["deploy"]["if"]
    assert "refs/heads/main" in workflow["jobs"]["deploy"]["if"]


def test_the_deploy_workflow_runs_the_expected_steps_in_order() -> None:
    workflow = yaml.load(
        (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    validate_steps = [step["name"] for step in workflow["jobs"]["validate"]["steps"]]
    deploy_steps = [step["name"] for step in workflow["jobs"]["deploy"]["steps"]]

    assert validate_steps == [
        "Check out repository",
        "Set up Python",
        "Install uv",
        "Sync environment",
        "Lint",
        "Test",
    ]
    assert deploy_steps == [
        "Check out repository",
        "Authenticate to Google Cloud",
        "Set up gcloud",
        "Configure Docker for Artifact Registry",
        "Build, push, and deploy",
    ]


def test_the_deploy_workflow_uses_the_required_cloud_run_flags() -> None:
    workflow = yaml.load(
        (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    run_script = workflow["jobs"]["deploy"]["steps"][-1]["run"]
    assert "gcloud run deploy \"${MOCK_SERVICE_NAME}\"" in run_script
    assert "gcloud run deploy \"${API_SERVICE_NAME}\"" in run_script
    assert "--allow-unauthenticated" in run_script
    assert "--min-instances 0" in run_script
    assert "--timeout 300" in run_script
    assert "--port 8081" in run_script
    assert "--port 8080" in run_script
    assert "docker build -f deploy/Dockerfile.mockapi" in run_script
    assert "docker build -f deploy/Dockerfile.api" in run_script


# --- compose and images ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))


def test_the_stack_has_all_four_services(compose: dict) -> None:
    assert set(compose["services"]) == {"api", "mockapi", "prometheus", "grafana"}


def test_the_api_reaches_the_mock_by_service_name(compose: dict) -> None:
    environment = compose["services"]["api"]["environment"]

    assert environment["ORDER_API_BASE_URL"] == "http://mockapi:8081"
    assert environment["PRODUCT_API_BASE_URL"] == "http://mockapi:8081"


def test_the_database_url_is_passed_through_rather_than_baked_in(compose: dict) -> None:
    assert compose["services"]["api"]["environment"]["DATABASE_URL"] == "${DATABASE_URL:-}"


def test_no_secret_is_committed_in_the_compose_file(compose: dict) -> None:
    for service in compose["services"].values():
        for name, value in (service.get("environment") or {}).items():
            if name.endswith(("KEY", "PASSWORD", "URL", "USER")):
                assert str(value).startswith("${") or "://" in str(value), name


def test_grafana_provisioning_is_mounted_read_only(compose: dict) -> None:
    mounts = compose["services"]["grafana"]["volumes"]

    provisioned = [m for m in mounts if "provisioning" in m or "dashboards" in m]
    assert len(provisioned) == 3
    assert all(m.endswith(":ro") for m in provisioned)


@pytest.mark.parametrize("name", ["Dockerfile.api", "Dockerfile.mockapi"])
def test_images_run_as_a_non_root_user_and_bind_all_interfaces(name: str) -> None:
    dockerfile = (DEPLOY / name).read_text(encoding="utf-8")

    assert re.search(r"^USER (?!root)", dockerfile, re.MULTILINE), "runtime stage must drop root"
    assert "--host 0.0.0.0" in dockerfile
    assert "${PORT:-" in dockerfile, "the port must come from the environment"


@pytest.mark.parametrize("name", ["Dockerfile.api", "Dockerfile.mockapi"])
def test_dependencies_install_before_source_is_copied(name: str) -> None:
    """A source edit must not invalidate the dependency layer."""
    lines = (DEPLOY / name).read_text(encoding="utf-8").splitlines()

    install = next(
        i for i, line in enumerate(lines) if "uv sync" in line or "uv pip install" in line
    )
    copies = [i for i, line in enumerate(lines) if line.startswith("COPY") and " ./src" in line]
    assert copies, "expected the source to be copied"
    assert min(copies) > install


def test_the_api_image_carries_the_policy_file() -> None:
    """`policy/loader.py` reads policy.md from the directory above src/."""
    dockerfile = (DEPLOY / "Dockerfile.api").read_text(encoding="utf-8")

    assert "policy.md" in dockerfile


def test_the_build_context_excludes_the_plan_directory() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    for entry in (".ai/", ".git/", ".venv/", "tests/"):
        assert entry in ignored


def test_the_build_context_keeps_the_policy_file() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "!policy.md" in ignored
    assert ignored.index("*.md") < ignored.index("!policy.md"), "negation must come after"
