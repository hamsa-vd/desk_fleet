"""Graph wiring.

This file should read as a diagram: no prompts, no LLM calls, no business rules.
"""

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph

from deskfleet.agents.classifier import classifier_node
from deskfleet.agents.researcher import researcher_node
from deskfleet.agents.schemas import Category
from deskfleet.config import constants
from deskfleet.graph.state import TicketState

CLASSIFIER = "classifier"
RESEARCHER = "researcher"

#: Route labels, kept separate from node names so S-02 … S-04 repoint a destination, not a branch.
REFUSE = "refuse"
CONTINUE = "continue"


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
    graph.set_entry_point(CLASSIFIER)
    graph.add_conditional_edges(
        CLASSIFIER,
        route_after_classifier,
        {REFUSE: END, CONTINUE: RESEARCHER},
    )
    # The Responder (S-03) takes this edge; nothing else about this file changes.
    graph.add_edge(RESEARCHER, END)
    return graph.compile()


def invocation_config(ticket_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": ticket_id},
        "recursion_limit": constants.RECURSION_LIMIT,
    }
