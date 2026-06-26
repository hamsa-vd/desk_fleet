import ast
import inspect
import io
import json
import tokenize

import pytest
from fastapi.testclient import TestClient

from deskfleet.api import models_routes
from deskfleet.api.app import create_app
from deskfleet.models import DiscoveryError, InvalidApiKeyError, ModelSpec, UnknownProviderError

KEY = "sk-caller-supplied-8f3a2b1c9d"

BODY = {"api_key": KEY}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def discovery(monkeypatch: pytest.MonkeyPatch):
    """Replace F-04's discovery so no test touches the network."""
    calls: list[tuple] = []

    def install(outcome):
        def fake(provider_id: str, api_key: str, base_url: str | None = None):
            calls.append((provider_id, api_key, base_url))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(models_routes, "discover_models", fake)
        return calls

    return install


def spec(model_id: str, **kwargs) -> ModelSpec:
    return ModelSpec(id=model_id, provider_id="openai", **kwargs)


# --- GET /providers ----------------------------------------------------------------------


def test_the_registry_lists_all_three_providers(client) -> None:
    providers = client.get("/providers").json()["providers"]

    assert [p["id"] for p in providers] == ["openai", "groq", "custom"]


def test_the_custom_provider_declares_that_it_needs_a_base_url(client) -> None:
    providers = {p["id"]: p for p in client.get("/providers").json()["providers"]}

    assert providers["custom"]["requires_base_url"] is True
    assert providers["custom"]["base_url"] is None
    assert providers["openai"]["requires_base_url"] is False


def test_each_provider_names_the_credential_the_modal_should_ask_for(client) -> None:
    providers = {p["id"]: p for p in client.get("/providers").json()["providers"]}

    assert providers["openai"]["credential_label"] == "OpenAI API key"
    assert providers["custom"]["credential_label"] == "API key"


def test_the_registry_never_exposes_which_server_setting_holds_a_key(client) -> None:
    body = client.get("/providers").text

    assert "settings_key" not in body
    assert "openai_api_key" not in body


def test_the_registry_is_open_without_any_credential(
    monkeypatch: pytest.MonkeyPatch, client
) -> None:
    monkeypatch.setenv("API_KEY", "shared-secret")

    assert TestClient(create_app()).get("/providers").status_code == 200


def test_the_registry_is_cacheable(client) -> None:
    assert "max-age" in client.get("/providers").headers["cache-control"]


# --- POST /providers/{id}/models ---------------------------------------------------------


def test_discovery_returns_the_models_the_provider_offers(client, discovery) -> None:
    discovery([spec("gpt-4o-mini", context_window=128000), spec("gpt-4o")])

    models = client.post("/providers/openai/models", json=BODY).json()["models"]

    assert [m["id"] for m in models] == ["gpt-4o-mini", "gpt-4o"]
    assert models[0]["context_window"] == 128000


def test_the_supplied_key_is_passed_through_to_the_provider(client, discovery) -> None:
    calls = discovery([spec("gpt-4o-mini")])

    client.post("/providers/openai/models", json=BODY)

    assert calls == [("openai", KEY, None)]


def test_a_custom_endpoint_forwards_its_base_url(client, discovery) -> None:
    calls = discovery([spec("local-llama")])

    client.post(
        "/providers/custom/models",
        json={"api_key": KEY, "base_url": "http://localhost:11434/v1"},
    )

    assert calls == [("custom", KEY, "http://localhost:11434/v1")]


def test_a_model_the_catalogue_has_never_heard_of_is_still_offered(client, discovery) -> None:
    discovery([spec("gpt-4o-mini"), spec("gpt-6-preview", metadata_available=False)])

    models = client.post("/providers/openai/models", json=BODY).json()["models"]

    assert [m["metadata_available"] for m in models] == [True, False]


def test_a_rejected_key_is_reported_as_such(client, discovery) -> None:
    discovery(InvalidApiKeyError("the OpenAI key was rejected"))

    response = client.post("/providers/openai/models", json=BODY)

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_key", "provider": "openai"}


def test_an_unreachable_provider_is_a_gateway_failure_not_a_bad_key(client, discovery) -> None:
    discovery(DiscoveryError("could not list OpenAI models: timeout"))

    response = client.post("/providers/openai/models", json=BODY)

    assert response.status_code == 502
    assert response.json() == {"error": "provider_unreachable", "provider": "openai"}


def test_an_unknown_provider_is_a_not_found(client, discovery) -> None:
    discovery(UnknownProviderError("unknown provider 'nope'"))

    response = client.post("/providers/nope/models", json=BODY)

    assert response.status_code == 404
    assert response.json() == {"error": "unknown_provider", "provider": "nope"}


def test_a_custom_provider_without_a_base_url_names_the_missing_field(client, discovery) -> None:
    calls = discovery([spec("anything")])

    response = client.post("/providers/custom/models", json=BODY)

    assert response.status_code == 422
    assert response.json()["field"] == "base_url"
    assert calls == [], "the provider must not be called when the request cannot be satisfied"


def test_a_request_without_a_key_is_rejected_before_any_provider_call(client, discovery) -> None:
    calls = discovery([spec("anything")])

    assert client.post("/providers/openai/models", json={}).status_code == 422
    assert client.post("/providers/openai/models", json={"api_key": ""}).status_code == 422
    assert calls == []


def test_discovery_needs_no_shared_secret_when_the_caller_brings_a_key(
    monkeypatch: pytest.MonkeyPatch, discovery
) -> None:
    """Discovering on your own key costs the service nothing (D-11)."""
    monkeypatch.setenv("API_KEY", "shared-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-000")
    discovery([spec("gpt-4o-mini")])

    response = TestClient(create_app()).post(
        "/providers/openai/models", json=BODY, headers={"x-openai-key": KEY}
    )

    assert response.status_code == 200


def test_discovery_is_gated_when_no_credential_is_offered_at_all(
    monkeypatch: pytest.MonkeyPatch, discovery
) -> None:
    monkeypatch.setenv("API_KEY", "shared-secret")
    discovery([spec("gpt-4o-mini")])

    assert TestClient(create_app()).post("/providers/openai/models", json=BODY).status_code == 401


# --- GET /models/{id} --------------------------------------------------------------------


def test_a_known_model_returns_its_tunable_parameters(client) -> None:
    body = client.get("/models/gpt-4o-mini").json()

    assert body["id"] == "gpt-4o-mini"
    assert body["params"], "the modal has nothing to render without these"
    assert {p["name"] for p in body["params"]} >= {"temperature", "max_tokens"}


def test_a_known_model_returns_the_pricing_the_modal_displays(client) -> None:
    body = client.get("/models/gpt-4o-mini").json()

    assert body["price_in_per_m"] is not None
    assert body["price_out_per_m"] is not None
    assert body["context_window"] > 0


def test_an_unknown_model_is_a_not_found(client) -> None:
    response = client.get("/models/not-a-model")

    assert response.status_code == 404
    assert response.json() == {"error": "unknown_model", "model": "not-a-model"}


def test_model_metadata_is_cacheable(client) -> None:
    assert "max-age" in client.get("/models/gpt-4o-mini").headers["cache-control"]


# --- the key must not escape -------------------------------------------------------------


def test_the_supplied_key_appears_in_no_response_no_log_and_no_url(
    client, discovery, caplog: pytest.LogCaptureFixture
) -> None:
    discovery([spec("gpt-4o-mini")])

    with caplog.at_level("DEBUG"):
        response = client.post("/providers/openai/models", json=BODY)

    emitted = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert KEY not in response.text
    assert KEY not in json.dumps(dict(response.headers))
    assert KEY not in emitted
    assert KEY not in str(response.request.url)


def test_a_rejected_key_is_not_echoed_back_in_the_error(
    client, discovery, caplog: pytest.LogCaptureFixture
) -> None:
    discovery(InvalidApiKeyError(f"the key {KEY} was rejected"))

    with caplog.at_level("DEBUG"):
        response = client.post("/providers/openai/models", json=BODY)

    emitted = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert KEY not in response.text
    assert KEY not in emitted


def test_the_request_body_model_hides_the_key_from_a_repr() -> None:
    body = models_routes.DiscoveryRequest(api_key=KEY)

    assert KEY not in repr(body)
    assert KEY not in str(body)
    assert body.api_key.get_secret_value() == KEY


# --- delegation --------------------------------------------------------------------------


def executable_source(module) -> str:
    """Source with comments and docstrings removed, so prose about a rule cannot break the rule."""
    text = "".join(
        token.string if token.type not in (tokenize.COMMENT, tokenize.STRING) else '""'
        for token in tokenize.generate_tokens(io.StringIO(inspect.getsource(module)).readline)
    )
    return text


def test_this_module_calls_no_provider_and_reads_no_catalogue() -> None:
    """The chunk's hard boundary: HTTP routing over F-04, nothing more."""
    source = executable_source(models_routes)

    assert "httpx" not in source
    assert "catalogue" not in source
    assert "openai.com" not in source


def test_this_module_imports_only_the_public_face_of_the_model_library() -> None:
    imported = {
        node.module
        for node in ast.walk(ast.parse(inspect.getsource(models_routes)))
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "deskfleet.models" in imported
    assert not [name for name in imported if name.startswith("deskfleet.models.")]
