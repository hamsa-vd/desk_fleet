import json

import pytest
from fastapi.testclient import TestClient

from deskfleet.api.app import create_app
from deskfleet.config import get_settings

pytestmark = pytest.mark.usefixtures("fresh_registry", "repository")


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, client_factory, classifier_says) -> TestClient:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-000")
    get_settings.cache_clear()
    client_factory(classifier_says("order"))
    # No lifespan: migrate() and setup_tracing() are startup concerns, not request concerns.
    return TestClient(create_app())


@pytest.fixture
def keyed_api(monkeypatch: pytest.MonkeyPatch, client_factory, classifier_says) -> TestClient:
    monkeypatch.setenv("API_KEY", "shared-secret-abc")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-000")
    get_settings.cache_clear()
    client_factory(classifier_says("order"))
    return TestClient(create_app())


def test_resolve_returns_every_result_field(api: TestClient) -> None:
    response = api.post("/resolve", json={"ticket": "Where is my order 1042?"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "ticket_id",
        "decision",
        "reply",
        "category",
        "tool_calls",
        "escalation_reason",
        "escalation_detail",
        "best_draft",
        "langsmith_trace_url",
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "usd",
    }
    assert body["decision"] == "resolved"
    assert body["category"] == "order"


def test_an_omitted_order_id_is_not_a_validation_error(api: TestClient) -> None:
    assert api.post("/resolve", json={"ticket": "Where is my order?"}).status_code == 200


def test_an_empty_ticket_is_rejected_at_422(api: TestClient) -> None:
    assert api.post("/resolve", json={"ticket": ""}).status_code == 422


def test_auth_is_open_when_no_shared_secret_is_configured(api: TestClient) -> None:
    assert api.post("/resolve", json={"ticket": "Where is my order 1042?"}).status_code == 200


def test_a_missing_shared_secret_is_a_401(keyed_api: TestClient) -> None:
    response = keyed_api.post("/resolve", json={"ticket": "Where is my order 1042?"})

    assert response.status_code == 401


def test_a_correct_shared_secret_is_accepted(keyed_api: TestClient) -> None:
    response = keyed_api.post(
        "/resolve",
        json={"ticket": "Where is my order 1042?"},
        headers={"X-API-Key": "shared-secret-abc"},
    )

    assert response.status_code == 200


def test_a_byok_key_bypasses_the_shared_secret(
    monkeypatch: pytest.MonkeyPatch, client_factory, classifier_says
) -> None:
    monkeypatch.setenv("API_KEY", "shared-secret-abc")
    get_settings.cache_clear()
    captured: dict = {}

    from deskfleet.runner import run as runner_module
    from tests.conftest import researcher_calling

    def spy_build_client(resolved):
        captured["key"] = resolved.api_key.get_secret_value()
        # Answers the Classifier and the Researcher alike: valid JSON, no tool calls.
        return researcher_calling(answer=json.dumps({"category": "order", "rationale": "x"}))

    monkeypatch.setattr(runner_module, "build_client", spy_build_client)
    api = TestClient(create_app())

    response = api.post(
        "/resolve",
        json={"ticket": "Where is my order 1042?"},
        headers={"X-OpenAI-Key": "sk-caller-999"},
    )

    assert response.status_code == 200
    assert captured["key"] == "sk-caller-999"


def test_no_supplied_key_appears_in_the_response_or_the_logs(
    keyed_api: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        response = keyed_api.post(
            "/resolve",
            json={"ticket": "Where is my order 1042?"},
            headers={"X-API-Key": "shared-secret-abc", "X-OpenAI-Key": "sk-caller-999"},
        )

    emitted = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "sk-caller-999" not in response.text
    assert "shared-secret-abc" not in response.text
    assert "sk-caller-999" not in emitted
    assert "shared-secret-abc" not in emitted


def test_health_is_fast_and_needs_no_database(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deskfleet.store import repository

    def refuse() -> None:
        raise ConnectionError("Neon is asleep")

    monkeypatch.setattr(repository, "_connect", refuse)
    response = api.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "deskfleet", "version": "0.1.0"}
    assert response.elapsed.total_seconds() < 0.05


def test_metrics_exposes_the_ticket_counter(api: TestClient) -> None:
    api.post("/resolve", json={"ticket": "Where is my order 1042?"})

    body = api.get("/metrics").text

    assert "deskfleet_tickets_total" in body
