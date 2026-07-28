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


WORKFLOW_PATH = ROOT / ".github" / "workflows" / "deploy.yml"

#: Every secret Cloud Run reads at runtime. Any of these appearing in --set-env-vars would write it
#: in clear into the revision spec, readable by anyone holding run.viewer.
RUNTIME_SECRET_NAMES = (
    "DATABASE_URL",
    "OPENAI_API_KEY",
    "API_KEY",
    "LANGCHAIN_API_KEY",
    "GROQ_API_KEY",
    "GRAFANA_CLOUD_PROM_URL",
    "GRAFANA_CLOUD_PROM_USER",
    "GRAFANA_CLOUD_PROM_KEY",
)


def _workflow() -> dict:
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _step(job: str, name: str) -> dict:
    for step in _workflow()["jobs"][job]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in job {job!r}")


def test_the_deploy_workflow_gates_deploys_on_tests() -> None:
    workflow = _workflow()

    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"]["contents"] == "read"
    assert workflow["jobs"]["deploy"]["needs"] == "validate"
    assert "workflow_dispatch" in workflow["jobs"]["deploy"]["if"]
    assert "refs/heads/main" in workflow["jobs"]["deploy"]["if"]


def test_a_deploy_in_flight_is_never_cancelled_by_a_later_push() -> None:
    guard = _workflow()["concurrency"]["cancel-in-progress"]

    assert guard == "${{ github.ref != 'refs/heads/main' }}"


def test_the_deploy_workflow_runs_the_expected_steps_in_order() -> None:
    workflow = _workflow()

    validate_steps = [step["name"] for step in workflow["jobs"]["validate"]["steps"]]
    deploy_steps = [step["name"] for step in workflow["jobs"]["deploy"]["steps"]]

    assert validate_steps == [
        "Check out repository",
        "Set up Python",
        "Install uv",
        "Restore uv cache",
        "Sync environment",
        "Lint",
        "Check formatting",
        "Test",
    ]
    assert deploy_steps == [
        "Check out repository",
        "Authenticate to Google Cloud",
        "Set up gcloud",
        "Configure Docker for Artifact Registry",
        "Build and push images",
        "Publish secrets to Secret Manager",
        "Deploy to Cloud Run",
        "Verify the deployed revision",
    ]


def test_the_validate_job_checks_formatting_as_well_as_lint() -> None:
    assert "ruff format --check" in _step("validate", "Check formatting")["run"]


def test_the_deploy_workflow_uses_the_required_cloud_run_flags() -> None:
    build = _step("deploy", "Build and push images")["run"]
    deploy = _step("deploy", "Deploy to Cloud Run")["run"]

    assert 'gcloud run deploy "${MOCK_SERVICE_NAME}"' in deploy
    assert 'gcloud run deploy "${API_SERVICE_NAME}"' in deploy
    assert 'gcloud run deploy "${STREAMLIT_SERVICE_NAME}"' in deploy
    assert "--allow-unauthenticated" in deploy
    assert "--min-instances 0" in deploy
    assert "--timeout 300" in deploy
    assert "--port 8081" in deploy
    assert "--port 8080" in deploy
    assert "--port 8501" in deploy
    assert "docker build -f deploy/Dockerfile.mockapi" in build
    assert "docker build -f deploy/Dockerfile.api" in build
    assert "docker build -f deploy/Dockerfile.streamlit" in build


def test_images_are_tagged_with_the_commit_sha() -> None:
    build = _step("deploy", "Build and push images")["run"]

    assert ":${GITHUB_SHA}" in build
    assert ":latest" not in build


def test_no_runtime_secret_is_passed_as_a_plain_environment_variable() -> None:
    deploy = _step("deploy", "Deploy to Cloud Run")["run"]
    env_var_args = re.findall(r"--set-env-vars \"([^\"]*)\"", deploy)

    assert env_var_args
    assert "--set-secrets" in deploy
    for argument in env_var_args:
        for name in RUNTIME_SECRET_NAMES:
            assert f"{name}=" not in argument


def test_env_vars_are_passed_with_a_non_comma_delimiter() -> None:
    """A comma inside a DATABASE_URL would otherwise start a new variable mid-value."""
    deploy = _step("deploy", "Deploy to Cloud Run")["run"]

    assert '--set-env-vars "^@^ORDER_API_BASE_URL=' in deploy


def test_secret_values_never_reach_a_command_line() -> None:
    publish = _step("deploy", "Publish secrets to Secret Manager")["run"]

    assert "--data-file=-" in publish
    assert "--data-file=- " not in publish.replace("--data-file=- >", "")
    assert "printf '%s' \"${value}\" |" in publish


def test_every_runtime_secret_is_declared_for_publication() -> None:
    declared = _workflow()["env"]["RUNTIME_SECRETS"].split()
    supplied = _step("deploy", "Publish secrets to Secret Manager")["env"]

    assert set(declared) == set(RUNTIME_SECRET_NAMES)
    assert set(supplied) == set(RUNTIME_SECRET_NAMES)


def run_secrets_step(
    tmp_path: Path, env: dict[str, str], *, existing: str
) -> subprocess.CompletedProcess:
    """Runs the real workflow step with a stub gcloud: publication exercised, not described."""
    calls = tmp_path / "calls.log"
    gcloud = tmp_path / "gcloud"
    gcloud.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {calls}\n'
        'if [ "$1" = "secrets" ] && [ "$2" = "describe" ]; then\n'
        f'  case " {existing} " in *" $3 "*) exit 0;; *) exit 1;; esac\n'
        "fi\n"
        "if [ \"$2\" = 'versions' ]; then cat > /dev/null; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    gcloud.chmod(0o755)

    script = tmp_path / "step.sh"
    script.write_text(_step("deploy", "Publish secrets to Secret Manager")["run"], encoding="utf-8")

    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "PROJECT_ID": "proj",
            "RUNTIME_SECRETS": " ".join(RUNTIME_SECRET_NAMES),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            **{name: "" for name in RUNTIME_SECRET_NAMES},
            **env,
        },
    )
    result.calls = calls.read_text(encoding="utf-8") if calls.exists() else ""  # type: ignore[attr-defined]
    output = tmp_path / "output"
    result.set_secrets = (  # type: ignore[attr-defined]
        output.read_text(encoding="utf-8").strip().removeprefix("set_secrets=")
        if output.exists()
        else ""
    )
    return result


def test_only_the_secrets_that_are_configured_are_published(tmp_path: Path) -> None:
    result = run_secrets_step(
        tmp_path,
        {"DATABASE_URL": "postgresql://u:p@h/db", "API_KEY": "shared"},
        existing=" ".join(RUNTIME_SECRET_NAMES),
    )

    assert result.returncode == 0
    assert result.set_secrets == "DATABASE_URL=DATABASE_URL:latest,API_KEY=API_KEY:latest"
    assert "skipping OPENAI_API_KEY" in result.stdout


def test_a_secret_value_never_appears_in_a_gcloud_argument(tmp_path: Path) -> None:
    result = run_secrets_step(
        tmp_path,
        {"DATABASE_URL": "postgresql://user:hunter2@host/db"},
        existing=" ".join(RUNTIME_SECRET_NAMES),
    )

    assert "versions add DATABASE_URL" in result.calls
    assert "hunter2" not in result.calls
    assert "hunter2" not in result.stdout + result.stderr


def test_a_missing_secret_manager_secret_fails_the_deploy_with_the_fix(tmp_path: Path) -> None:
    result = run_secrets_step(tmp_path, {"API_KEY": "shared"}, existing="")

    assert result.returncode == 1
    assert "gcloud secrets create API_KEY" in result.stdout


def test_the_deployed_revision_is_verified_before_the_job_succeeds() -> None:
    verify = _step("deploy", "Verify the deployed revision")["run"]

    assert "/health" in verify
    assert 'test "${health}" = "200"' in verify
    assert "GET streamlit" in verify
    assert 'test "${web}" = "200"' in verify
    assert 'test "${unauth}" = "401"' in verify


# --- compose and images ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))


def test_the_stack_has_all_five_services(compose: dict) -> None:
    assert set(compose["services"]) == {
        "api",
        "mockapi",
        "streamlit",
        "prometheus",
        "grafana",
    }


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


@pytest.mark.parametrize("name", ["Dockerfile.api", "Dockerfile.mockapi", "Dockerfile.streamlit"])
def test_images_run_as_a_non_root_user_and_bind_all_interfaces(name: str) -> None:
    dockerfile = (DEPLOY / name).read_text(encoding="utf-8")

    assert re.search(r"^USER (?!root)", dockerfile, re.MULTILINE), "runtime stage must drop root"
    assert "--host 0.0.0.0" in dockerfile or "--server.address 0.0.0.0" in dockerfile
    assert "${PORT:-" in dockerfile, "the port must come from the environment"


@pytest.mark.parametrize("name", ["Dockerfile.api", "Dockerfile.mockapi", "Dockerfile.streamlit"])
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


def test_the_streamlit_image_carries_the_app_theme() -> None:
    """Cloud Run must not fall back to its visitor's preferred colour scheme."""
    dockerfile = (DEPLOY / "Dockerfile.streamlit").read_text(encoding="utf-8")

    assert "COPY --chown=streamlit:streamlit .streamlit ./.streamlit" in dockerfile


def test_the_build_context_excludes_the_plan_directory() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    for entry in (".ai/", ".git/", ".venv/", "tests/"):
        assert entry in ignored


def test_the_build_context_keeps_the_policy_file() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "!policy.md" in ignored
    assert ignored.index("*.md") < ignored.index("!policy.md"), "negation must come after"
