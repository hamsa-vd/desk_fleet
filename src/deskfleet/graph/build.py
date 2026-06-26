"""Graph wiring.

This file should read as a diagram: no prompts, no LLM calls, no business rules.
"""

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph

from deskfleet.agents.classifier import classifier_node
from deskfleet.agents.researcher import researcher_node
from deskfleet.agents.responder import responder_node
from deskfleet.agents.reviewer import reviewer_node, route_after_review
from deskfleet.agents.schemas import Category
from deskfleet.config import constants
from deskfleet.graph.state import TicketState

CLASSIFIER = "classifier"
RESEARCHER = "researcher"
RESPONDER = "responder"
REVIEWER = "reviewer"

#: Route labels, kept separate from node names so a chunk repoints a destination, not a branch.
REFUSE = "refuse"
CONTINUE = "continue"
REWRITE = "responder"
FINISH = "end"


def route_after_classifier(state: TicketState) -> str:
    """Out-of-scope exits the graph immediately — M6 S53's fourth bounding dimension."""
    return REFUSE if state["category"] == Category.OTHER else CONTINUE


def build_graph(
    clients: dict[str, Any],
    on_usage: Callable[[int, int], None] | None = None,
) -> Any:
    graph = StateGraph(TicketState)
    graph.add_node(CLASSIFIER, classifier_node(clients[CLASSIFIER], on_usage=on_usage))
    graph.add_node(RESEARCHER, researcher_node(clients[RESEARCHER], on_usage=on_usage))
    graph.add_node(RESPONDER, responder_node(clients[RESPONDER], on_usage=on_usage))
    graph.add_node(REVIEWER, reviewer_node(clients[REVIEWER], on_usage=on_usage))
    graph.set_entry_point(CLASSIFIER)
    graph.add_conditional_edges(
        CLASSIFIER,
        route_after_classifier,
        {REFUSE: END, CONTINUE: RESEARCHER},
    )
    graph.add_edge(RESEARCHER, RESPONDER)
    graph.add_edge(RESPONDER, REVIEWER)
    graph.add_conditional_edges(
        REVIEWER,
        route_after_review,
        {REWRITE: RESPONDER, FINISH: END},
    )
    return graph.compile()


def invocation_config(ticket_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": ticket_id},
        "recursion_limit": constants.RECURSION_LIMIT,
    }
