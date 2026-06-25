"""The shared graph state. Every key is initialised before invoke() — LangGraph checks the shape."""

from typing import TypedDict

from deskfleet.agents.schemas import (
    Category,
    Decision,
    EscalationReason,
    Fact,
    ToolCall,
)


class TicketState(TypedDict):
    ticket_id: str
    #: Already redacted by guardrails before entry. The raw body never enters the graph.
    ticket: str
    order_id: str | None
    #: Written by the Classifier.
    category: Category | None
    #: Written by the Researcher.
    facts: list[Fact]
    #: Written by the Responder.
    draft: str | None
    #: Highest-scoring draft seen so far; the Responder writes it, S-05 hands it to the human.
    best_draft: str | None
    #: Scored by the Reviewer, stored by the Responder alongside `best_draft`.
    best_score: float | None
    #: The Responder is the ONLY writer. Incrementing this anywhere else halves the effective cap.
    iterations: int
    #: Written by the runner on exit, or by the Classifier when it refuses.
    decision: Decision | None
    escalation_reason: EscalationReason | None
    escalation_detail: str | None
    #: Appended by the Reviewer.
    review_notes: list[str]
    #: Appended by the Researcher's tool execution.
    tool_calls: list[ToolCall]
    #: Appended by every node, for the trace.
    node_log: list[str]


def initial_state(ticket_id: str, ticket: str, order_id: str | None = None) -> TicketState:
    return TicketState(
        ticket_id=ticket_id,
        ticket=ticket,
        order_id=order_id,
        category=None,
        facts=[],
        draft=None,
        best_draft=None,
        best_score=None,
        iterations=0,
        decision=None,
        escalation_reason=None,
        escalation_detail=None,
        review_notes=[],
        tool_calls=[],
        node_log=[],
    )
