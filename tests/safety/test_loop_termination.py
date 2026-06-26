"""CI-gating safety test (FR-081): the Responder↔Reviewer cycle must always terminate.

M6 S55 prices an unbounded agent loop at roughly $1,300 per twelve hours. Two independent
safeguards are asserted here: the explicit stop condition, and the framework recursion limit
behind it. Either one alone is a single point of failure.
"""

import json

import pytest

from deskfleet.agents.reviewer import route_after_review
from deskfleet.agents.schemas import Decision, EscalationReason, Fact
from deskfleet.config import constants
from deskfleet.graph.state import initial_state
from deskfleet.models import Credentials
from deskfleet.runner.events import EventDone, ResolveRequest
from deskfleet.runner.run import run_ticket
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

pytestmark = pytest.mark.usefixtures("fresh_registry")


def _reviewed_state(**overrides: object):
    state = initial_state("t-loop", "Where is order 1042?", "1042")
    state["facts"] = [Fact(key="order.status", value="shipped", source="get_order")]
    state["draft"] = "Your order has shipped."
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def test_an_approved_draft_leaves_the_graph() -> None:
    state = _reviewed_state(decision=Decision.RESOLVED, iterations=1)

    assert route_after_review(state) == "end"


def test_a_rejected_draft_below_the_cap_goes_back_to_the_responder() -> None:
    state = _reviewed_state(iterations=constants.MAX_ITERS - 1)

    assert route_after_review(state) == "responder"


def test_a_rejected_draft_at_the_cap_leaves_the_graph() -> None:
    state = _reviewed_state(
        iterations=constants.MAX_ITERS,
        decision=Decision.ESCALATE,
        escalation_reason=EscalationReason.MAX_ITERS_EXHAUSTED,
    )

    assert route_after_review(state) == "end"


@pytest.mark.parametrize("iterations", range(0, constants.MAX_ITERS + 4))
def test_routing_never_loops_once_a_decision_is_recorded(iterations: int) -> None:
    """Whatever the counter says, a terminal decision ends the run."""
    state = _reviewed_state(iterations=iterations, decision=Decision.ESCALATE)

    assert route_after_review(state) == "end"


def test_a_reviewer_that_never_approves_still_terminates(
    client_factory, classifier_says, repository
) -> None:
    responder = responder_says("Your parcel arrives on Tuesday.")
    client_factory(classifier_says("order"), responder=responder, reviewer=FakeChatModel(REJECT))

    events = list(run_ticket(ResolveRequest(ticket="Where is my order 1042?"), KEYS))

    done = events[-1]
    assert isinstance(done, EventDone)
    assert done.result.decision is Decision.ESCALATE
    assert done.result.escalation_reason == EscalationReason.MAX_ITERS_EXHAUSTED.value
    assert responder.call_count == constants.MAX_ITERS


def test_the_recursion_limit_catches_a_broken_stop_condition(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    client_factory,
    classifier_says,
    repository,
) -> None:
    """Sabotage the explicit guard; the framework fallback must still degrade to a 200 ESCALATE."""
    from deskfleet.graph import build as graph_build

    monkeypatch.setattr(graph_build, "route_after_review", lambda _state: "responder")
    client_factory(
        classifier_says("order"),
        responder=responder_says("Your parcel arrives on Tuesday."),
        reviewer=FakeChatModel(REJECT),
    )

    with caplog.at_level("ERROR"):
        events = list(run_ticket(ResolveRequest(ticket="Where is my order 1042?"), KEYS))

    done = events[-1]
    assert isinstance(done, EventDone)
    assert done.result.decision is Decision.ESCALATE
    assert done.result.escalation_reason == EscalationReason.MAX_ITERS_EXHAUSTED.value
    assert any(record.message == "graph_recursion_limit" for record in caplog.records)
