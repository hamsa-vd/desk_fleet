import json

import httpx
import pytest

from deskfleet.agents.schemas import Decision, EscalationReason, ToolCall
from deskfleet.config import get_settings
from deskfleet.graph.state import TicketState, initial_state
from deskfleet.guardrails import scan_input
from deskfleet.models import Credentials
from deskfleet.runner import escalation as escalation_module
from deskfleet.runner.escalation import UNKNOWN_DETAIL, build_escalation, handle_escalation
from deskfleet.runner.events import EventDone, ResolveRequest
from deskfleet.runner.run import run_ticket
from deskfleet.tools import http_client
from tests.conftest import FakeChatModel, responder_says

KEYS = Credentials(server={"openai": "sk-server-000"})

REJECT = json.dumps(
    {
        "approved": False,
        "grounded": False,
        "policy_ok": True,
        "score": 4.0,
        "reasons": ["POL-003: promises a delivery date not present in the facts"],
    }
)

CALLS = [
    ToolCall(
        name="get_order_status",
        args={"order_id": "1042"},
        ok=True,
        result_summary="order 1042 is shipped",
        latency_ms=12,
    ),
    ToolCall(
        name="drop_tables",
        args={},
        ok=False,
        result_summary="tool 'drop_tables' is not registered",
        latency_ms=0,
        rejected=True,
    ),
]

pytestmark = pytest.mark.usefixtures("fresh_registry")


def escalated_state(**overrides: object) -> TicketState:
    state = initial_state("t-1", "Where is order 1042?", "1042")
    state["decision"] = Decision.ESCALATE
    state["escalation_reason"] = EscalationReason.MAX_ITERS_EXHAUSTED
    state["escalation_detail"] = "three rewrites did not produce a grounded reply"
    state["best_draft"] = "Your order has shipped."
    state["review_notes"] = ["POL-003: promises a delivery date not present in the facts"]
    state["tool_calls"] = list(CALLS)
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


@pytest.fixture
def webhook(monkeypatch: pytest.MonkeyPatch):
    """Point the webhook at a scripted transport and hand back the requests it received."""

    def _install(handler) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        monkeypatch.setenv("ESCALATION_WEBHOOK_URL", "http://ops.test/hook")
        get_settings.cache_clear()
        http_client.close_client()
        monkeypatch.setattr(
            http_client,
            "get_client",
            lambda: httpx.Client(transport=httpx.MockTransport(respond)),
        )
        return seen

    yield _install
    get_settings.cache_clear()


# --- build_escalation --------------------------------------------------------------------


def test_the_row_carries_the_reason_the_detail_and_the_best_draft() -> None:
    row = build_escalation(escalated_state())

    assert row.ticket_id == "t-1"
    assert row.reason == EscalationReason.MAX_ITERS_EXHAUSTED.value
    assert row.detail == "three rewrites did not produce a grounded reply"
    assert row.best_draft == "Your order has shipped."


def test_the_reason_is_always_a_member_of_the_enum() -> None:
    row = build_escalation(escalated_state(escalation_reason=None))

    assert row.reason in {member.value for member in EscalationReason}


def test_a_missing_detail_is_filled_in_rather_than_left_empty() -> None:
    row = build_escalation(escalated_state(escalation_detail=None))

    assert row.detail == UNKNOWN_DETAIL


def test_an_escalation_before_any_draft_carries_no_best_draft() -> None:
    row = build_escalation(escalated_state(best_draft=None))

    assert row.best_draft is None


def test_the_audit_trail_round_trips_every_call_including_rejected_ones() -> None:
    row = build_escalation(escalated_state())

    trail = json.loads(row.tool_calls_json)
    assert [entry["name"] for entry in trail] == ["get_order_status", "drop_tables"]
    assert trail[1]["rejected"] is True
    assert trail[0]["args"] == {"order_id": "1042"}


# --- handle_escalation -------------------------------------------------------------------


def test_the_row_is_written_once(repository) -> None:
    handle_escalation(escalated_state())

    assert len(repository.escalations) == 1


@pytest.mark.parametrize(
    "reason",
    [
        EscalationReason.MAX_ITERS_EXHAUSTED,
        EscalationReason.NO_FACTS_FOUND,
        EscalationReason.TOOL_FAILURE,
        EscalationReason.POLICY_VIOLATION,
    ],
)
def test_every_reason_is_written_not_only_the_loop_one(reason, repository) -> None:
    handle_escalation(escalated_state(escalation_reason=reason))

    assert repository.escalations[0].reason == reason.value


def test_the_metric_counts_the_escalation_exactly_once(repository, fresh_registry) -> None:
    handle_escalation(escalated_state())

    counted = fresh_registry.get_sample_value(
        "deskfleet_escalations_total", {"reason": "max_iters_exhausted"}
    )
    assert counted == 1


def test_a_database_failure_does_not_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_row: object) -> None:
        raise RuntimeError("neon is asleep")

    monkeypatch.setattr(escalation_module, "write_escalation", explode)

    handle_escalation(escalated_state())


def test_an_unset_webhook_attempts_nothing_and_logs_nothing(
    repository, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode() -> None:
        raise AssertionError("no outbound call may be made without a configured webhook")

    monkeypatch.setattr(http_client, "get_client", explode)

    with caplog.at_level("WARNING"):
        handle_escalation(escalated_state())

    assert caplog.records == []


def test_the_webhook_receives_the_handoff(repository, webhook) -> None:
    seen = webhook(lambda _request: httpx.Response(200, json={"ok": True}))

    handle_escalation(escalated_state())

    payload = json.loads(seen[0].content)
    assert payload["ticket_id"] == "t-1"
    assert payload["reason"] == "max_iters_exhausted"
    assert payload["best_draft"] == "Your order has shipped."
    assert [call["name"] for call in payload["tool_calls"]] == ["get_order_status", "drop_tables"]


def test_a_failing_webhook_is_logged_and_swallowed(
    repository, webhook, caplog: pytest.LogCaptureFixture
) -> None:
    webhook(lambda _request: httpx.Response(500))

    with caplog.at_level("WARNING"):
        handle_escalation(escalated_state())

    assert any(record.message == "escalation_webhook_failed" for record in caplog.records)
    assert len(repository.escalations) == 1


def test_a_hanging_webhook_does_not_fail_the_handoff(repository, webhook) -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    webhook(hang)

    handle_escalation(escalated_state())

    assert len(repository.escalations) == 1


def test_the_payload_carries_no_credential_and_no_raw_pii(repository, webhook) -> None:
    raw = "I am ada@example.com on 07700 900123, where is order 1042?"
    seen = webhook(lambda _request: httpx.Response(200, json={}))
    state = escalated_state(ticket=scan_input(raw).clean_text)

    handle_escalation(state)

    body = seen[0].content.decode()
    assert "ada@example.com" not in body
    assert "900123" not in body
    assert "sk-" not in body


# --- through the runner ------------------------------------------------------------------


def test_an_escalated_ticket_lands_in_the_queue_with_its_audit_trail(
    client_factory, classifier_says, repository
) -> None:
    client_factory(
        classifier_says("order"),
        responder=responder_says("Your parcel arrives on Tuesday."),
        reviewer=FakeChatModel(REJECT),
    )

    events = list(run_ticket(ResolveRequest(ticket="Where is my order 1042?"), KEYS))

    done = events[-1]
    assert isinstance(done, EventDone)
    assert done.result.decision is Decision.ESCALATE
    assert len(repository.escalations) == 1
    row = repository.escalations[0]
    assert row.ticket_id == done.result.ticket_id
    assert row.best_draft
    assert json.loads(row.tool_calls_json)


def test_a_resolved_ticket_writes_no_escalation(
    client_factory, classifier_says, repository
) -> None:
    client_factory(classifier_says("order"))

    _ = list(run_ticket(ResolveRequest(ticket="Where is my order 1042?"), KEYS))

    assert repository.escalations == []


def test_a_refused_ticket_writes_no_escalation(client_factory, classifier_says, repository) -> None:
    client_factory(classifier_says("other"))

    _ = list(run_ticket(ResolveRequest(ticket="Can you write me a poem about bees?"), KEYS))

    assert repository.escalations == []


def test_the_api_response_surfaces_the_reason_and_the_detail(
    client_factory, classifier_says, repository
) -> None:
    client_factory(
        classifier_says("order"),
        responder=responder_says("Your parcel arrives on Tuesday."),
        reviewer=FakeChatModel(REJECT),
    )

    events = list(run_ticket(ResolveRequest(ticket="Where is my order 1042?"), KEYS))

    result = events[-1].result
    assert result.escalation_reason == EscalationReason.MAX_ITERS_EXHAUSTED.value
    assert result.escalation_detail
