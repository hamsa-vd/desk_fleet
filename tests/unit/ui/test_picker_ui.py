"""Drives the picker widgets in the real Streamlit script against a faked service."""

import json
import re

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from streamlit_app import client as client_module
from streamlit_app import model_picker as picker_module

SCRIPT = "src/streamlit_app/main.py"

PROVIDERS = {
    "providers": [
        {
            "id": "openai",
            "label": "OpenAI",
            "base_url": "https://api.example/v1",
            "credential_label": "OpenAI API key",
            "requires_base_url": False,
        },
        {
            "id": "custom",
            "label": "Custom OpenAI-compatible endpoint",
            "base_url": None,
            "credential_label": "API key",
            "requires_base_url": True,
        },
    ]
}

MODELS = {
    "models": [
        {
            "id": "fast-small",
            "provider_id": "openai",
            "context_window": 128000,
            "price_in_per_m": 0.15,
            "price_out_per_m": 0.60,
            "supports_tools": True,
            "metadata_available": True,
            "params": [
                {
                    "name": "temperature",
                    "type": "float",
                    "default": 0.2,
                    "minimum": 0.0,
                    "maximum": 2.0,
                },
                {"name": "max_tokens", "type": "int", "default": 1024, "minimum": 1},
            ],
        },
        {
            "id": "deep-thinker",
            "provider_id": "openai",
            "context_window": 200000,
            "price_in_per_m": 1.10,
            "price_out_per_m": 4.40,
            "supports_tools": True,
            "metadata_available": True,
            "params": [
                {
                    "name": "reasoning_effort",
                    "type": "string",
                    "default": "medium",
                    "options": ["low", "medium", "high"],
                }
            ],
        },
        {
            "id": "brand-new",
            "provider_id": "openai",
            "metadata_available": False,
            "params": [],
        },
    ]
}

RESULT = {
    "ticket_id": "t-1",
    "decision": "resolved",
    "reply": "All good.",
    "tool_calls": [],
    "langsmith_trace_url": None,
}

DONE = f"event: done\ndata: {json.dumps(RESULT)}\n\n"

KEY = "sk-picker-secret-9f2a"


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch):
    """Serves S-07's endpoints and the resolve stream; records every request."""
    seen: list[httpx.Request] = []

    def install(models_response: httpx.Response | None = None):
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            path = request.url.path
            if path == "/providers":
                return httpx.Response(200, json=PROVIDERS)
            if path.endswith("/models"):
                return models_response or httpx.Response(200, json=MODELS)
            if path.endswith("/stream"):
                return httpx.Response(200, text=DONE)
            return httpx.Response(200, json=RESULT)

        original = httpx.Client

        def fake_client(*args, **kwargs):
            kwargs.pop("transport", None)
            return original(*args, transport=httpx.MockTransport(handler), **kwargs)

        for module in (client_module, picker_module):
            monkeypatch.setattr(module.httpx, "Client", fake_client, raising=False)
        return seen

    return install


def page_text(app: AppTest) -> str:
    """What a reader sees, not the markup. The page styles a summary line by wrapping parts of it
    in tags, which must not change whether the line reads as "Classifier · server default"."""
    parts = [
        *[e.value for e in app.markdown],
        *[e.value for e in app.caption],
        *[e.value for e in app.error],
        *[e.value for e in app.warning],
        *[e.value for e in app.info],
    ]
    return "\n".join(re.sub(r"<[^>]+>", "", str(p)) for p in parts)


def configured(**selections: picker_module.Selection) -> AppTest:
    """A session that already has selections, as if the modal had been driven and applied.

    `st.dialog` deltas linger in AppTest's element tree after the modal closes, and it reads
    their values when submitting the next interaction, so clicking on *after* an apply is not
    something AppTest supports. Seeding the state exercises the same code from the same input.
    """
    app = AppTest.from_file(SCRIPT, default_timeout=30)
    app.session_state["picker"] = picker_module.PickerState(
        selections=dict(selections),
        credentials={"openai": KEY},
    )
    return app.run()


REVIEWER = picker_module.Selection(
    provider_id="openai",
    model_id="fast-small",
    params={"temperature": 0.2, "max_tokens": 1024},
)


def open_reviewer(app: AppTest) -> AppTest:
    app.button(key="open-reviewer").click()
    return app.run()


def pick_openai(app: AppTest) -> AppTest:
    app.selectbox(key="picker-provider").set_value("openai")
    return app.run()


def enter_key(app: AppTest, key: str = KEY) -> AppTest:
    app.text_input(key="picker-key-openai").set_value(key)
    app.run()
    app.button(key="picker-fetch").click()
    return app.run()


# --- the default path --------------------------------------------------------------------


def test_every_node_shows_the_server_default_on_first_load(service) -> None:
    service()

    app = AppTest.from_file(SCRIPT, default_timeout=30).run()

    text = page_text(app)
    for node in ("Classifier", "Researcher", "Responder", "Reviewer"):
        assert f"{node} · server default" in text


def test_resolving_with_no_interaction_sends_no_models_object(service) -> None:
    seen = service()

    app = AppTest.from_file(SCRIPT, default_timeout=30).run()
    app.text_area(key="ticket").set_value("Where is my order 1042?")
    next(b for b in app.button if b.label == "Resolve").click()
    app.run()

    stream = next(r for r in seen if r.url.path.endswith("/stream"))
    assert "models" not in json.loads(stream.content)


def test_the_provider_list_is_not_fetched_until_a_modal_opens(service) -> None:
    seen = service()

    AppTest.from_file(SCRIPT, default_timeout=30).run()

    assert not [r for r in seen if r.url.path == "/providers"]


# --- the modal flow ----------------------------------------------------------------------


def test_opening_a_modal_offers_the_providers_the_service_advertises(service) -> None:
    service()

    app = open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())

    assert app.selectbox(key="picker-provider").options == [
        "OpenAI",
        "Custom OpenAI-compatible endpoint",
    ]


def test_choosing_a_provider_reveals_its_credential_field(service) -> None:
    service()

    app = pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run()))

    field = app.text_input(key="picker-key-openai")
    assert field.label == "OpenAI API key"
    assert field.proto.type == 1, "the key field must be masked"


def test_a_custom_provider_also_reveals_a_base_url_field(service) -> None:
    service()
    app = open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())

    app.selectbox(key="picker-provider").set_value("custom")
    app.run()

    assert app.text_input(key="picker-url-custom").label == "Base URL"


def test_entering_a_key_lists_the_models_with_their_metadata(service) -> None:
    service()
    app = pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run()))

    app = enter_key(app)

    labels = app.selectbox(key="picker-model").options
    assert [label.split(" — ")[0] for label in labels] == [
        "fast-small",
        "deep-thinker",
        "brand-new",
    ]
    assert "128k ctx" in labels[0]
    assert "$0.15/$0.60 per M" in labels[0]


def test_a_model_with_a_reasoning_effort_param_renders_a_select_for_it(service) -> None:
    service()
    app = enter_key(pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())))

    app.selectbox(key="picker-model").set_value("deep-thinker")
    app.run()

    control = app.selectbox(key="picker-param-reasoning_effort")
    assert control.options == ["low", "medium", "high"]


def test_a_model_without_that_param_renders_no_such_control(service) -> None:
    service()
    app = enter_key(pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())))

    app.selectbox(key="picker-model").set_value("fast-small")
    app.run()

    assert "picker-param-reasoning_effort" not in [w.key for w in app.selectbox]
    assert app.slider(key="picker-param-temperature").value == pytest.approx(0.2)


def test_a_model_with_no_metadata_is_selectable_and_shows_no_param_form(service) -> None:
    service()
    app = enter_key(pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())))

    app.selectbox(key="picker-model").set_value("brand-new")
    app.run()

    assert not [w for w in app.slider if w.key and w.key.startswith("picker-param")]
    assert picker_module.NO_METADATA in page_text(app)


def test_the_confirm_screen_shows_the_selection_before_apply(service) -> None:
    service()
    app = enter_key(pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())))

    app.selectbox(key="picker-model").set_value("fast-small")
    app.run()

    text = page_text(app)
    assert "**Provider** — openai" in text
    assert "**Model** — fast-small" in text
    assert "**temperature** — 0.2" in text
    assert "**max_tokens** — 1024" in text


def test_apply_updates_the_node_summary_in_the_main_view(service) -> None:
    service()
    app = enter_key(pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())))
    app.selectbox(key="picker-model").set_value("fast-small")
    app.run()

    app.button(key="picker-apply").click()
    app.run()

    assert "Reviewer · fast-small · openai" in page_text(app)


def test_cancel_leaves_the_node_on_the_server_default(service) -> None:
    service()
    app = enter_key(pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())))
    app.selectbox(key="picker-model").set_value("fast-small")
    app.run()

    app.button(key="picker-cancel").click()
    app.run()

    assert "Reviewer · server default" in page_text(app)


def test_a_configured_reviewer_travels_on_the_resolve_request(service) -> None:
    seen = service()
    app = configured(reviewer=REVIEWER)

    app.text_area(key="ticket").set_value("Where is my order 1042?")
    next(b for b in app.button if b.label == "Resolve").click()
    app.run()

    body = json.loads(next(r for r in seen if r.url.path.endswith("/stream")).content)
    assert body["models"]["reviewer"]["model_id"] == "fast-small"
    assert body["models"]["reviewer"]["provider_id"] == "openai"
    assert body["models"]["reviewer"]["params"]["temperature"] == pytest.approx(0.2)


def test_reset_returns_every_node_to_the_server_default(service) -> None:
    seen = service()
    app = configured(reviewer=REVIEWER)

    next(b for b in app.button if "Reset" in b.label).click()
    app.run()

    assert "Reviewer · server default" in page_text(app)

    app.text_area(key="ticket").set_value("Where is my order 1042?")
    next(b for b in app.button if b.label == "Resolve").click()
    app.run()

    stream = next(r for r in seen if r.url.path.endswith("/stream"))
    assert "x-openai-key" not in stream.headers, "reset must forget the stored credential"
    assert "models" not in json.loads(stream.content)


# --- errors ------------------------------------------------------------------------------


def test_a_rejected_key_reads_differently_from_an_unreachable_provider(service) -> None:
    service(httpx.Response(401, json={"error": "invalid_key", "provider": "openai"}))
    app = enter_key(pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())))
    rejected = page_text(app)

    assert "rejected by OpenAI" in rejected
    assert "picker-model" not in [w.key for w in app.selectbox]


def test_an_unreachable_provider_says_so(service) -> None:
    service(httpx.Response(502, json={"error": "provider_unreachable", "provider": "openai"}))

    app = enter_key(pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())))

    assert "Could not reach OpenAI" in page_text(app)


# --- the key must not escape -------------------------------------------------------------


def test_the_entered_key_is_never_rendered_and_never_reaches_a_url(service) -> None:
    seen = service()
    app = enter_key(pick_openai(open_reviewer(AppTest.from_file(SCRIPT, default_timeout=30).run())))
    app.selectbox(key="picker-model").set_value("fast-small")
    app.run()
    app.button(key="picker-apply").click()
    app.run()

    assert KEY not in page_text(app)
    assert all(KEY not in str(request.url) for request in seen)


def test_the_entered_key_becomes_the_byok_header_on_the_run(service) -> None:
    seen = service()
    app = configured(reviewer=REVIEWER)

    app.text_area(key="ticket").set_value("Where is my order 1042?")
    next(b for b in app.button if b.label == "Resolve").click()
    app.run()

    stream = next(r for r in seen if r.url.path.endswith("/stream"))
    assert stream.headers["x-openai-key"] == KEY


# --- no hardcoded catalogue --------------------------------------------------------------


def test_the_ui_hardcodes_no_provider_or_model_data() -> None:
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[3] / "src" / "streamlit_app"
    banned = ("gpt-4o-mini", "api.openai.com", "api.groq.com")

    for path in app_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not [token for token in banned if token in source], path.name
