from typing import Any

import pytest

from deskfleet.models import (
    Credentials,
    DiscoveryError,
    InvalidApiKeyError,
    MissingCredentialError,
    ModelSelection,
    ParamValidationError,
    build_client,
    discover_models,
    discovery,
    get_model_spec,
    list_providers,
    resolve,
    resolver,
)
from deskfleet.tools.http_client import HttpErr, HttpOk

BOTH_KEYS = Credentials(byok={"openai": "sk-byok-111"}, server={"openai": "sk-server-222"})
SERVER_ONLY = Credentials(server={"openai": "sk-server-222", "groq": "gsk_server-333"})


@pytest.fixture
def live_models(monkeypatch: pytest.MonkeyPatch):
    def _mount(result: HttpOk | HttpErr) -> list[dict[str, Any]]:
        captured: list[dict[str, Any]] = []

        def fake_get_json(url: str, **kwargs: Any) -> HttpOk | HttpErr:
            captured.append({"url": url, **kwargs})
            return result

        monkeypatch.setattr(discovery, "get_json", fake_get_json)
        return captured

    return _mount


def test_default_resolution_is_gpt_4o_mini_on_openai() -> None:
    resolved = resolve("classifier", None, SERVER_ONLY)

    assert resolved.spec.id == "gpt-4o-mini"
    assert resolved.spec.provider_id == "openai"
    assert resolved.base_url == "https://api.openai.com/v1"


def test_the_reviewer_is_output_capped_by_default() -> None:
    assert resolve("reviewer", None, SERVER_ONLY).params["max_tokens"] == 256


def test_groq_routes_through_the_openai_compatible_base_url() -> None:
    resolved = resolve(
        "responder",
        ModelSelection(provider_id="groq", model_id="llama-3.3-70b-versatile"),
        SERVER_ONLY,
    )

    assert resolved.base_url == "https://api.groq.com/openai/v1"


def test_a_custom_provider_needs_a_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        ModelSelection(provider_id="custom", model_id="mistral-small")

    selection = ModelSelection(
        provider_id="custom", model_id="mistral-small", base_url="http://llm.internal/v1"
    )
    resolved = resolve("responder", selection, Credentials(byok={"custom": "sk-local"}))

    assert resolved.base_url == "http://llm.internal/v1"
    assert resolved.spec.metadata_available is False


def test_byok_wins_over_the_server_key() -> None:
    assert resolve("classifier", None, BOTH_KEYS).api_key.get_secret_value() == "sk-byok-111"


def test_the_server_key_is_used_when_there_is_no_byok() -> None:
    assert resolve("classifier", None, SERVER_ONLY).api_key.get_secret_value() == "sk-server-222"


def test_no_key_for_the_provider_never_borrows_another_ones() -> None:
    keys = Credentials(server={"openai": "sk-server-222"})

    with pytest.raises(MissingCredentialError, match="groq"):
        resolve("responder", ModelSelection(provider_id="groq", model_id="x"), keys)


def test_resolved_model_never_prints_the_key() -> None:
    resolved = resolve("classifier", None, BOTH_KEYS)

    assert "sk-byok-111" not in repr(resolved)
    assert "sk-byok-111" not in str(resolved)


def test_a_parameter_the_model_does_not_accept_is_rejected() -> None:
    selection = ModelSelection(
        provider_id="openai", model_id="gpt-4o-mini", params={"reasoning_effort": "high"}
    )

    with pytest.raises(ParamValidationError, match="reasoning_effort"):
        resolve("classifier", selection, SERVER_ONLY)


def test_an_allowlisted_parameter_overrides_the_node_default() -> None:
    selection = ModelSelection(
        provider_id="openai", model_id="gpt-4o-mini", params={"temperature": 0.9}
    )

    assert resolve("responder", selection, SERVER_ONLY).params["temperature"] == 0.9


def test_discovery_joins_live_ids_against_the_catalogue(live_models) -> None:
    live_models(
        HttpOk(data={"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-5-nano-preview"}]}, status=200)
    )

    known, unknown = discover_models("openai", "sk-test")

    assert known.id == "gpt-4o-mini"
    assert known.metadata_available is True
    assert known.price_in_per_m == 0.15
    assert unknown.id == "gpt-5-nano-preview"
    assert unknown.metadata_available is False


def test_discovery_reports_a_rejected_key_distinctly(live_models) -> None:
    live_models(HttpErr(reason="unauthorized", status=401, attempts=1))

    with pytest.raises(InvalidApiKeyError):
        discover_models("openai", "sk-bad")


def test_discovery_reports_other_failures_as_discovery_errors(live_models) -> None:
    live_models(HttpErr(reason="gateway timeout", status=504, attempts=4))

    with pytest.raises(DiscoveryError):
        discover_models("openai", "sk-test")


def test_discovery_falls_back_to_the_catalogue_when_models_is_unimplemented(live_models) -> None:
    live_models(HttpOk(data={"data": []}, status=200))

    assert {m.id for m in discover_models("groq", "gsk_test")} == {
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    }


def test_discovery_sends_the_key_as_a_bearer_header(live_models) -> None:
    captured = live_models(HttpOk(data={"data": [{"id": "gpt-4o-mini"}]}, status=200))

    discover_models("openai", "sk-test")

    assert captured[0]["url"] == "https://api.openai.com/v1/models"
    assert captured[0]["headers"] == {"Authorization": "Bearer sk-test"}


def test_build_client_passes_model_base_url_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_chat_openai(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "client"

    monkeypatch.setattr(resolver, "ChatOpenAI", fake_chat_openai)
    resolved = resolve("reviewer", None, BOTH_KEYS)

    assert build_client(resolved) == "client"
    assert captured["model"] == "gpt-4o-mini"
    assert captured["base_url"] == "https://api.openai.com/v1"
    assert captured["api_key"].get_secret_value() == "sk-byok-111"
    assert captured["max_tokens"] == 256


def test_the_catalogue_is_seeded_and_dated() -> None:
    spec = get_model_spec("gpt-4o-mini")

    assert spec is not None
    assert spec.context_window == 128000
    assert spec.supports_tools is True
    assert {p.name for p in spec.params} == {"temperature", "max_tokens", "top_p"}


def test_the_provider_registry_covers_the_three_sanctioned_options() -> None:
    assert {p.id for p in list_providers()} == {"openai", "groq", "custom"}
