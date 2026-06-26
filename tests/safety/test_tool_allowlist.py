"""CI-gating safety test (FR-080): an off-allowlist tool call must be blocked and logged."""

import pytest

from deskfleet.tools import allowed_names, dispatch


@pytest.mark.parametrize(
    "name",
    ["delete_database", "issue_refund", "get_order_status ", "GET_ORDER_STATUS", "os.system"],
)
def test_an_off_allowlist_tool_call_is_rejected(
    name: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        call = dispatch(name, {})

    assert call.rejected is True
    assert call.ok is False
    assert name in call.result_summary
    assert any(record.__dict__.get("tool") == name for record in caplog.records)


def test_rejection_happens_before_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """The allowlist check runs before dispatch, not after the model has already been obeyed."""
    from deskfleet.tools import registry

    def explode(*_: object, **__: object) -> str:
        raise AssertionError("an unregistered name must never reach a callable")

    monkeypatch.setattr(registry, "_normalise_args", explode)

    assert dispatch("delete_database", {}).rejected is True


def test_the_allowlist_has_not_grown() -> None:
    assert allowed_names() == frozenset({"get_order_status", "get_product", "search_products"})


def test_the_researcher_records_an_off_allowlist_request_rather_than_making_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model asking for a tool it does not have must be evidence, not an outage."""
    from deskfleet.agents.researcher import researcher_node
    from deskfleet.graph.state import initial_state
    from deskfleet.tools import impl
    from tests.conftest import researcher_calling

    def never(*_: object, **__: object) -> object:
        raise AssertionError("an unregistered name must never reach the HTTP layer")

    monkeypatch.setattr(impl, "get_json", never)
    model = researcher_calling([{"name": "issue_refund", "args": {"order_id": "1042"}}])

    state = researcher_node(model)(initial_state("t-safety", "Refund order 1042", "1042"))

    assert [(c.name, c.rejected) for c in state["tool_calls"]] == [("issue_refund", True)]
    assert state["facts"] == []
