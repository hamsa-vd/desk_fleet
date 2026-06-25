from deskfleet.graph.state import TicketState, initial_state


def test_initial_state_populates_every_declared_key() -> None:
    state = initial_state("T-1", "where is my order?", "1042")

    assert set(state) == set(TicketState.__annotations__)


def test_list_fields_start_empty_not_none() -> None:
    state = initial_state("T-1", "where is my order?")

    assert state["facts"] == []
    assert state["review_notes"] == []
    assert state["tool_calls"] == []
    assert state["node_log"] == []


def test_counters_and_decisions_start_unset() -> None:
    state = initial_state("T-1", "where is my order?")

    assert state["iterations"] == 0
    assert state["decision"] is None
    assert state["escalation_reason"] is None
    assert state["escalation_detail"] is None
    assert state["category"] is None
    assert state["draft"] is None
    assert state["best_draft"] is None
    assert state["best_score"] is None


def test_order_id_is_optional() -> None:
    assert initial_state("T-1", "hello")["order_id"] is None


def test_states_do_not_share_list_instances() -> None:
    first, second = initial_state("T-1", "a"), initial_state("T-2", "b")
    first["node_log"].append("classifier")

    assert second["node_log"] == []
