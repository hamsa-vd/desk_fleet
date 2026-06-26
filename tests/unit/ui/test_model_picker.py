import httpx
import pytest

from streamlit_app import model_picker as picker
from streamlit_app.client import ServiceConfig

GPT = {
    "id": "gpt-4o-mini",
    "provider_id": "openai",
    "context_window": 128000,
    "price_in_per_m": 0.15,
    "price_out_per_m": 0.60,
    "supports_tools": True,
    "metadata_available": True,
    "params": [
        {"name": "temperature", "type": "float", "default": 0.2, "minimum": 0.0, "maximum": 2.0},
        {"name": "max_tokens", "type": "int", "default": 1024, "minimum": 1},
    ],
}

REASONER = {
    **GPT,
    "id": "o4-mini",
    "params": [
        *GPT["params"],
        {
            "name": "reasoning_effort",
            "type": "string",
            "default": "medium",
            "options": ["low", "medium", "high"],
        },
    ],
}

UNKNOWN = {
    "id": "gpt-6-preview",
    "provider_id": "openai",
    "metadata_available": False,
    "params": [],
}

MODELS = [GPT, REASONER, UNKNOWN]


@pytest.fixture
def opened() -> picker.PickerState:
    state = picker.PickerState()
    picker.open_modal(state, "reviewer")
    return state


def transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- key fingerprinting ------------------------------------------------------------------


def test_the_same_key_fingerprints_the_same_way() -> None:
    assert picker.fingerprint("sk-abc") == picker.fingerprint("sk-abc")


def test_different_keys_fingerprint_differently() -> None:
    assert picker.fingerprint("sk-abc") != picker.fingerprint("sk-abd")


def test_a_fingerprint_never_contains_the_key() -> None:
    key = "sk-supersecret-value-123"

    assert key not in picker.fingerprint(key)
    assert len(picker.fingerprint(key)) < len(key)


# --- opening and closing -----------------------------------------------------------------


def test_a_fresh_node_opens_at_the_provider_step() -> None:
    state = picker.PickerState()

    picker.open_modal(state, "reviewer")

    assert state.open_node == "reviewer"
    assert state.draft.step == "provider"
    assert state.draft.provider_id is None


def test_reopening_a_configured_node_starts_from_its_current_selection() -> None:
    state = picker.PickerState(
        selections={
            "reviewer": picker.Selection("groq", "llama-3.3-70b", params={"max_tokens": 256})
        }
    )

    picker.open_modal(state, "reviewer")

    assert state.draft.provider_id == "groq"
    assert state.draft.model_id == "llama-3.3-70b"
    assert state.draft.params == {"max_tokens": 256}


def test_a_key_already_entered_for_that_provider_is_reused() -> None:
    state = picker.PickerState(
        selections={"reviewer": picker.Selection("openai", "gpt-4o-mini")},
        credentials={"openai": "sk-known"},
    )

    picker.open_modal(state, "reviewer")

    assert state.draft.api_key == "sk-known"


def test_acting_with_no_modal_open_is_an_error_not_a_silent_no_op() -> None:
    with pytest.raises(picker.PickerError):
        picker.choose_provider(picker.PickerState(), "openai")


# --- choosing a provider -----------------------------------------------------------------


def test_choosing_a_provider_advances_to_the_credential_step(opened) -> None:
    picker.choose_provider(opened, "openai")

    assert opened.draft.provider_id == "openai"
    assert opened.draft.step == "credential"


def test_switching_provider_clears_the_fetched_list_and_the_chosen_model(opened) -> None:
    picker.choose_provider(opened, "openai")
    picker.set_credential(opened, "sk-abc")
    picker.set_models(opened, MODELS)
    picker.choose_model(opened, "gpt-4o-mini")

    picker.choose_provider(opened, "groq")

    assert opened.draft.models == []
    assert opened.draft.model_id is None
    assert opened.draft.params == {}


def test_reselecting_the_same_provider_keeps_the_work_so_far(opened) -> None:
    picker.choose_provider(opened, "openai")
    picker.set_models(opened, MODELS)
    picker.choose_model(opened, "gpt-4o-mini")

    picker.choose_provider(opened, "openai")

    assert opened.draft.model_id == "gpt-4o-mini"


# --- choosing a model --------------------------------------------------------------------


def test_choosing_a_model_seeds_its_parameters_from_the_spec(opened) -> None:
    picker.choose_provider(opened, "openai")
    picker.set_models(opened, MODELS)

    picker.choose_model(opened, "gpt-4o-mini")

    assert opened.draft.params == {"temperature": 0.2, "max_tokens": 1024}
    assert opened.draft.step == "params"


def test_switching_model_discards_the_previous_models_parameters(opened) -> None:
    picker.choose_provider(opened, "openai")
    picker.set_models(opened, MODELS)
    picker.choose_model(opened, "o4-mini")
    picker.set_param(opened, "reasoning_effort", "high")

    picker.choose_model(opened, "gpt-4o-mini")

    assert "reasoning_effort" not in opened.draft.params


def test_a_model_with_no_metadata_seeds_no_parameters(opened) -> None:
    picker.choose_provider(opened, "openai")
    picker.set_models(opened, MODELS)

    picker.choose_model(opened, "gpt-6-preview")

    assert opened.draft.params == {}


def test_a_refetched_list_that_lost_the_chosen_model_clears_it(opened) -> None:
    picker.choose_provider(opened, "openai")
    picker.set_models(opened, MODELS)
    picker.choose_model(opened, "o4-mini")

    picker.set_models(opened, [GPT])

    assert opened.draft.model_id is None


# --- applying and cancelling -------------------------------------------------------------


def configured(node: str = "reviewer", model: str = "gpt-4o-mini") -> picker.PickerState:
    state = picker.PickerState()
    picker.open_modal(state, node)
    picker.choose_provider(state, "openai")
    picker.set_credential(state, "sk-abc")
    picker.set_models(state, MODELS)
    picker.choose_model(state, model)
    return state


def test_apply_records_the_selection_and_closes_the_modal() -> None:
    state = configured()

    picker.apply(state)

    assert state.selections["reviewer"] == picker.Selection(
        "openai", "gpt-4o-mini", None, {"temperature": 0.2, "max_tokens": 1024}
    )
    assert state.draft is None
    assert state.open_node is None


def test_apply_remembers_the_key_for_that_provider() -> None:
    state = configured()

    picker.apply(state)

    assert state.credentials["openai"] == "sk-abc"


def test_apply_records_an_edited_parameter() -> None:
    state = configured()
    picker.set_param(state, "temperature", 0.9)

    picker.apply(state)

    assert state.selections["reviewer"].params["temperature"] == 0.9


def test_cancel_leaves_the_previous_selection_untouched() -> None:
    state = configured()
    picker.apply(state)
    before = state.selections["reviewer"]

    picker.open_modal(state, "reviewer")
    picker.choose_provider(state, "groq")
    picker.set_models(state, [{"id": "llama-3.3-70b", "params": []}])
    picker.choose_model(state, "llama-3.3-70b")
    picker.cancel(state)

    assert state.selections["reviewer"] == before
    assert state.draft is None


def test_cancel_on_a_never_configured_node_leaves_it_on_the_server_default() -> None:
    state = configured("responder")

    picker.cancel(state)

    assert "responder" not in state.selections


def test_apply_without_a_model_refuses_rather_than_writing_a_half_selection() -> None:
    state = picker.PickerState()
    picker.open_modal(state, "reviewer")
    picker.choose_provider(state, "openai")

    with pytest.raises(picker.PickerError):
        picker.apply(state)

    assert "reviewer" not in state.selections


def test_a_custom_endpoint_carries_its_base_url_into_the_selection() -> None:
    state = picker.PickerState()
    picker.open_modal(state, "reviewer")
    picker.choose_provider(state, "custom")
    picker.set_credential(state, "sk-local", "http://localhost:11434/v1")
    picker.set_models(state, [{"id": "local-llama", "params": []}])
    picker.choose_model(state, "local-llama")

    picker.apply(state)

    assert state.selections["reviewer"].base_url == "http://localhost:11434/v1"
    assert state.base_urls["custom"] == "http://localhost:11434/v1"


# --- reset -------------------------------------------------------------------------------


def test_reset_returns_every_node_to_the_server_default_and_forgets_keys() -> None:
    state = configured()
    picker.apply(state)

    fresh = picker.reset(state)

    assert fresh.selections == {}
    assert fresh.credentials == {}
    assert fresh.model_cache == {}


# --- the model cache ---------------------------------------------------------------------


def test_a_fetched_list_is_reused_for_the_same_provider_and_key() -> None:
    state = picker.PickerState()

    picker.cache_models(state, "openai", "sk-abc", MODELS)

    assert picker.cached_models(state, "openai", "sk-abc") == MODELS


def test_a_different_key_does_not_hit_the_cache() -> None:
    state = picker.PickerState()
    picker.cache_models(state, "openai", "sk-abc", MODELS)

    assert picker.cached_models(state, "openai", "sk-different") is None


def test_the_cache_never_stores_the_key_itself() -> None:
    state = picker.PickerState()
    picker.cache_models(state, "openai", "sk-supersecret", MODELS)

    assert "sk-supersecret" not in str(list(state.model_cache))


# --- the parameter form ------------------------------------------------------------------


def test_a_bounded_float_becomes_a_slider() -> None:
    control = next(c for c in picker.param_controls(GPT) if c.name == "temperature")

    assert control.kind == "slider"
    assert (control.minimum, control.maximum) == (0.0, 2.0)


def test_an_open_ended_int_becomes_a_number_input() -> None:
    control = next(c for c in picker.param_controls(GPT) if c.name == "max_tokens")

    assert control.kind == "number"


def test_an_enumerated_parameter_becomes_a_select() -> None:
    control = next(c for c in picker.param_controls(REASONER) if c.name == "reasoning_effort")

    assert control.kind == "select"
    assert control.options == ["low", "medium", "high"]


def test_a_model_without_that_parameter_renders_no_such_control() -> None:
    assert not [c for c in picker.param_controls(GPT) if c.name == "reasoning_effort"]


def test_a_model_with_no_metadata_renders_no_form_at_all() -> None:
    assert picker.param_controls(UNKNOWN) == []
    assert picker.param_controls(None) == []


def test_no_control_is_invented_beyond_what_the_server_advertised() -> None:
    names = {c.name for c in picker.param_controls(GPT)}

    assert names == {param["name"] for param in GPT["params"]}


# --- labels and summaries ----------------------------------------------------------------


def test_a_model_label_shows_context_window_and_price() -> None:
    label = picker.model_label(GPT)

    assert "128k ctx" in label
    assert "$0.15/$0.60 per M" in label
    assert "tools" in label


def test_a_model_without_metadata_says_so_and_shows_no_price() -> None:
    label = picker.model_label(UNKNOWN)

    assert picker.NO_METADATA in label
    assert "$" not in label


def test_an_unconfigured_node_summarises_as_the_server_default() -> None:
    assert picker.summary_line("reviewer", None) == f"Reviewer · {picker.SERVER_DEFAULT}"


def test_a_configured_node_summarises_model_provider_and_parameters() -> None:
    selection = picker.Selection("groq", "llama-3.3-70b", params={"max_tokens": 256})

    assert picker.summary_line("reviewer", selection) == (
        "Reviewer · llama-3.3-70b · groq · max_tokens 256"
    )


def test_the_confirm_screen_shows_provider_model_price_and_every_parameter() -> None:
    state = configured()
    picker.set_param(state, "temperature", 0.9)

    rows = dict(picker.confirm_rows(state.draft))

    assert rows["Provider"] == "openai"
    assert rows["Model"] == "gpt-4o-mini"
    assert rows["temperature"] == "0.9"
    assert rows["max_tokens"] == "1024"
    assert "$0.15 in" in rows["Price per M tokens"]


def test_the_confirm_screen_admits_when_pricing_is_unknown() -> None:
    state = configured(model="gpt-6-preview")

    rows = dict(picker.confirm_rows(state.draft))

    assert rows["Pricing"] == picker.NO_METADATA
    assert "Price per M tokens" not in rows


# --- error mapping -----------------------------------------------------------------------


def test_a_rejected_key_and_an_unreachable_provider_read_differently() -> None:
    rejected = picker.error_message({"error": "invalid_key"}, "OpenAI")
    unreachable = picker.error_message({"error": "provider_unreachable"}, "OpenAI")

    assert rejected != unreachable
    assert "rejected" in rejected
    assert "reach" in unreachable
    assert "OpenAI" in rejected and "OpenAI" in unreachable


def test_a_missing_base_url_tells_the_user_what_to_type() -> None:
    message = picker.error_message({"error": "missing_base_url"}, "Custom")

    assert "base URL" in message


def test_an_unrecognised_error_is_reported_rather_than_hidden() -> None:
    assert "teapot" in picker.error_message({"error": "teapot"}, "OpenAI")
    assert picker.error_message(None, "OpenAI")


# --- fetching ----------------------------------------------------------------------------


def test_fetching_providers_returns_the_registry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"providers": [{"id": "openai", "label": "OpenAI"}]})

    with transport(handler) as client:
        assert picker.fetch_providers(ServiceConfig(), client=client)[0]["id"] == "openai"


def test_an_unreachable_service_is_a_picker_error_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with transport(handler) as client, pytest.raises(picker.PickerError):
        picker.fetch_providers(ServiceConfig(), client=client)


def test_fetching_models_posts_the_key_in_the_body_never_in_the_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"models": MODELS})

    with transport(handler) as client:
        models = picker.fetch_models(ServiceConfig(), "openai", "sk-abc", "OpenAI", client=client)

    assert [m["id"] for m in models] == ["gpt-4o-mini", "o4-mini", "gpt-6-preview"]
    assert seen[0].method == "POST"
    assert "sk-abc" not in str(seen[0].url)
    assert b"sk-abc" in seen[0].content


def test_a_rejected_key_surfaces_the_invalid_key_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_key", "provider": "openai"})

    with (
        transport(handler) as client,
        pytest.raises(picker.PickerError, match="rejected by OpenAI"),
    ):
        picker.fetch_models(ServiceConfig(), "openai", "sk-bad", "OpenAI", client=client)


def test_an_unreachable_provider_surfaces_its_own_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": "provider_unreachable", "provider": "openai"})

    with transport(handler) as client, pytest.raises(picker.PickerError, match="Could not reach"):
        picker.fetch_models(ServiceConfig(), "openai", "sk-abc", "OpenAI", client=client)


def test_a_custom_endpoint_forwards_its_base_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"models": []})

    with transport(handler) as client:
        picker.fetch_models(
            ServiceConfig(),
            "custom",
            "sk-abc",
            "Custom",
            base_url="http://localhost:11434/v1",
            client=client,
        )

    assert b"localhost:11434" in seen[0].content


def test_a_failed_fetch_puts_the_modal_back_on_the_credential_step(opened) -> None:
    picker.choose_provider(opened, "openai")
    picker.set_credential(opened, "sk-bad")

    picker.fail(opened, "That key was rejected by OpenAI.")

    assert opened.draft.step == "credential"
    assert opened.draft.models == []
    assert "rejected" in opened.draft.error


# --- the resolve request -----------------------------------------------------------------


def test_nothing_configured_sends_no_models_object_at_all() -> None:
    """The zero-interaction default path must not be altered by the picker existing."""
    assert picker.models_payload(picker.PickerState()) is None


def test_a_configured_reviewer_travels_in_the_models_object() -> None:
    state = configured()
    picker.set_param(state, "max_tokens", 256)
    picker.apply(state)

    payload = picker.models_payload(state)

    assert payload == {
        "reviewer": {
            "provider_id": "openai",
            "model_id": "gpt-4o-mini",
            "params": {"temperature": 0.2, "max_tokens": 256},
        }
    }


def test_only_configured_nodes_appear() -> None:
    state = configured("reviewer")
    picker.apply(state)

    assert set(picker.models_payload(state)) == {"reviewer"}


def test_a_custom_selection_carries_its_base_url_on_the_request() -> None:
    state = picker.PickerState(
        selections={"reviewer": picker.Selection("custom", "local", "http://host/v1")}
    )

    assert picker.models_payload(state)["reviewer"]["base_url"] == "http://host/v1"


def test_picker_keys_become_request_headers_without_mutating_the_sidebar_config() -> None:
    config = ServiceConfig(api_key="shared")
    state = picker.PickerState(credentials={"groq": "gsk-abc"})

    merged = picker.with_credentials(config, state)

    assert merged.headers()["x-groq-key"] == "gsk-abc"
    assert merged.headers()["x-api-key"] == "shared"
    assert config.provider_keys == {}


def test_a_key_never_reaches_a_url() -> None:
    state = picker.PickerState(credentials={"openai": "sk-secret"})
    merged = picker.with_credentials(ServiceConfig(), state)

    assert "sk-secret" not in merged.url("/resolve/stream")
