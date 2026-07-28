import re
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from deskfleet.config import Settings, get_settings
from deskfleet.observability import (
    cost,
    estimate_tokens,
    metrics,
    metrics_response,
    note_budget_exceeded,
    observe_escalation,
    observe_estimate_error,
    observe_node,
    observe_refusal,
    observe_ticket,
    observe_tool_call,
    record_usage,
    setup_tracing,
    traced_run,
    tracing,
    usd_for,
    use_registry,
)

FORBIDDEN_LABELS = {"ticket_id", "user", "body", "email", "prompt"}

EXPECTED_METRICS = {
    "deskfleet_tickets_total",
    "deskfleet_ticket_latency_seconds",
    "deskfleet_node_latency_seconds",
    "deskfleet_tokens_total",
    "deskfleet_cost_usd_total",
    "deskfleet_tool_calls_total",
    "deskfleet_escalations_total",
    "deskfleet_refusals_total",
    "deskfleet_budget_exceeded_total",
    "deskfleet_token_estimate_error_ratio",
}


@pytest.fixture(autouse=True)
def fresh_registry() -> CollectorRegistry:
    registry = CollectorRegistry()
    use_registry(registry)
    return registry


def _value(registry: CollectorRegistry, name: str, **labels: str) -> float:
    return registry.get_sample_value(name, labels or None) or 0.0


def test_ticket_metrics_carry_decision_and_category(fresh_registry: CollectorRegistry) -> None:
    observe_ticket("resolved", "order", 2.5)

    assert _value(fresh_registry, "deskfleet_tickets_total", decision="resolved", category="order")


def test_a_missing_category_becomes_a_bounded_label(fresh_registry: CollectorRegistry) -> None:
    observe_ticket("refuse", None, 0.1)

    assert _value(fresh_registry, "deskfleet_tickets_total", decision="refuse", category="none")


def test_node_escalation_refusal_and_budget_counters(fresh_registry: CollectorRegistry) -> None:
    observe_node("reviewer", 1.2)
    observe_escalation("max_iters_exhausted")
    observe_refusal("injection")
    note_budget_exceeded("T-1", 21_000)

    assert _value(fresh_registry, "deskfleet_node_latency_seconds_count", node="reviewer") == 1
    assert _value(fresh_registry, "deskfleet_escalations_total", reason="max_iters_exhausted") == 1
    assert _value(fresh_registry, "deskfleet_refusals_total", reason="injection") == 1
    assert _value(fresh_registry, "deskfleet_budget_exceeded_total") == 1


def test_rejected_tool_calls_do_not_widen_the_tool_label(
    fresh_registry: CollectorRegistry,
) -> None:
    observe_tool_call("get_order_status", ok=True, rejected=False)
    observe_tool_call("delete_database", ok=False, rejected=True)

    assert _value(
        fresh_registry,
        "deskfleet_tool_calls_total",
        tool="get_order_status",
        ok="true",
        rejected="false",
    )
    assert _value(
        fresh_registry,
        "deskfleet_tool_calls_total",
        tool="unregistered",
        ok="false",
        rejected="true",
    )


def test_cost_is_computed_from_the_catalogue(fresh_registry: CollectorRegistry) -> None:
    usd = record_usage("gpt-4o-mini", 1000, 500)

    assert usd == pytest.approx((1000 * 0.15 + 500 * 0.6) / 1_000_000)
    assert _value(fresh_registry, "deskfleet_tokens_total", direction="in", model="gpt-4o-mini")
    assert _value(fresh_registry, "deskfleet_cost_usd_total", model="gpt-4o-mini") > 0


def test_an_uncatalogued_model_still_records_tokens_but_costs_nothing(
    fresh_registry: CollectorRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        usd = record_usage("some-local-model", 100, 50)

    assert usd == 0.0
    assert _value(fresh_registry, "deskfleet_tokens_total", direction="in", model="other") == 100
    assert any(r.getMessage() == "model_not_priced" for r in caplog.records)


def test_token_estimation_uses_tiktoken_where_available() -> None:
    assert estimate_tokens("where is my order 1042", "gpt-4o-mini") > 0


def test_token_estimation_falls_back_for_an_unknown_encoding() -> None:
    text = "a" * 400

    assert estimate_tokens(text, "some-local-model") == 100


def test_estimate_error_ratio_is_recorded(fresh_registry: CollectorRegistry) -> None:
    observe_estimate_error(estimated=900, actual=1000)
    observe_estimate_error(estimated=900, actual=0)

    assert _value(fresh_registry, "deskfleet_token_estimate_error_ratio_count") == 1


def test_exposition_contains_every_metric() -> None:
    observe_ticket("resolved", "order", 1.0)
    observe_node("classifier", 0.2)
    record_usage("gpt-4o-mini", 10, 5)
    observe_tool_call("get_product", ok=True, rejected=False)
    observe_escalation("tool_failure")
    observe_refusal("out_of_scope")
    note_budget_exceeded("T-1", 1)
    observe_estimate_error(10, 10)

    body = metrics_response().body.decode()

    for name in EXPECTED_METRICS:
        assert name in body


def test_no_metric_declares_a_high_cardinality_label(fresh_registry: CollectorRegistry) -> None:
    for collector in list(fresh_registry._collector_to_names):
        assert not FORBIDDEN_LABELS & set(getattr(collector, "_labelnames", ()))


def test_latency_metrics_are_histograms_not_summaries() -> None:
    source = Path(metrics.__file__).read_text(encoding="utf-8")

    assert "Summary(" not in source
    assert re.search(r"deskfleet_ticket_latency_seconds", source)


@pytest.mark.parametrize(
    ("call", "args"),
    [
        (observe_ticket, ("resolved", "order", 1.0)),
        (observe_node, ("reviewer", 1.0)),
        (observe_tool_call, ("get_product", True, False)),
        (observe_escalation, ("tool_failure",)),
        (observe_refusal, ("injection",)),
        (note_budget_exceeded, ("T-1", 1)),
        (observe_estimate_error, (10, 10)),
    ],
)
def test_every_metric_entry_point_swallows_its_own_failure(
    monkeypatch: pytest.MonkeyPatch, call, args
) -> None:
    def explode() -> dict:
        raise RuntimeError("prometheus is on fire")

    monkeypatch.setattr(metrics, "metrics", explode)

    assert call(*args) is None


def test_usage_recording_swallows_its_own_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object, **__: object) -> float:
        raise RuntimeError("catalogue is on fire")

    monkeypatch.setattr(cost, "usd_for", explode)

    assert record_usage("gpt-4o-mini", 10, 5) == 0.0


def test_metrics_response_survives_a_broken_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_: object) -> bytes:
        raise RuntimeError("exposition is on fire")

    monkeypatch.setattr(metrics, "generate_latest", explode)

    assert metrics_response().status_code == 200


def test_setup_tracing_sets_every_langchain_variable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = Settings(
        _env_file=None,
        langchain_api_key="lsv2_pt_test",
        langchain_project="deskfleet-test",
    )

    with caplog.at_level("INFO"):
        setup_tracing(settings)

    import os

    # Asserted against the settings object, not against hardcoded defaults: which region and
    # project a deployment points at is configuration, and changing it must not fail this test.
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGCHAIN_ENDPOINT"] == settings.langchain_endpoint
    assert os.environ["LANGCHAIN_PROJECT"] == "deskfleet-test"
    assert os.environ["LANGCHAIN_API_KEY"] == "lsv2_pt_test"
    assert any(r.getMessage() == "tracing_configured" for r in caplog.records)


def test_setup_tracing_swallows_its_own_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class HostileEnviron(dict):
        def __setitem__(self, *_: object) -> None:
            raise RuntimeError("environ is read-only")

    class FakeOs:
        environ = HostileEnviron()

    monkeypatch.setattr(tracing, "os", FakeOs)

    assert setup_tracing(Settings(_env_file=None)) is None


def test_traced_run_is_inert_when_tracing_is_disabled() -> None:
    get_settings.cache_clear()
    try:
        with traced_run("T-1") as handle:
            pass
    finally:
        get_settings.cache_clear()

    assert handle.run_id is None
    assert handle.trace_url is None


def test_traced_run_captures_a_per_run_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRun:
        id = "11111111-2222-3333-4444-555555555555"

    class FakeCallback:
        latest_run = FakeRun()

        def get_run_url(self) -> str:
            return f"https://smith.langchain.com/o/x/p/y/r/{FakeRun.id}"

    tracer = FakeCallback()
    monkeypatch.setattr(tracing, "_is_enabled", lambda _: True)
    monkeypatch.setattr(tracing, "LangChainTracer", lambda **_: tracer)

    with traced_run("T-1") as handle:
        # The tracer reaches the graph as a callback, never as a ContextVar: `traced_run` wraps a
        # yield inside a generator the SSE transport steps through one context at a time.
        assert handle.callbacks == [tracer]

    assert handle.run_id == FakeRun.id
    assert handle.trace_url is not None
    assert FakeRun.id in handle.trace_url


def test_a_failing_trace_url_warns_about_region_mismatch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class FakeCallback:
        latest_run = None

        def get_run_url(self) -> str:
            raise RuntimeError("failed to post")

    monkeypatch.setattr(tracing, "_is_enabled", lambda _: True)
    monkeypatch.setattr(tracing, "LangChainTracer", lambda **_: FakeCallback())

    with caplog.at_level("WARNING"), traced_run("T-1") as handle:
        pass

    assert handle.trace_url is None
    assert any("region" in str(r.__dict__.get("hint", "")) for r in caplog.records)


def test_pricing_helper_is_zero_for_an_unpriced_model() -> None:
    assert usd_for("some-local-model", 1000, 1000) == 0.0
