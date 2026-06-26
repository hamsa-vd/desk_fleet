"""Runs against a live F-03 container. Start it with `uvicorn mock_api.app:app --port 8081`."""

import os

import pytest

from deskfleet.config import get_settings
from deskfleet.tools import dispatch

MOCK_URL = os.getenv("MOCK_API_URL", "http://localhost:8081")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("MOCK_API_URL"), reason="MOCK_API_URL is not set"),
]


@pytest.fixture(autouse=True)
def _point_at_the_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORDER_API_BASE_URL", MOCK_URL)
    monkeypatch.setenv("PRODUCT_API_BASE_URL", MOCK_URL)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_order_lookup_against_the_live_mock() -> None:
    call = dispatch("get_order_status", {"order_id": "1042"})

    assert call.ok
    assert "shipped" in call.result_summary


def test_search_against_the_live_mock() -> None:
    call = dispatch("search_products", {"query": "joggers"})

    assert call.ok
    assert "matched" in call.result_summary


def test_the_researcher_gathers_order_facts_from_the_live_mock() -> None:
    """The node's own path — executor, dispatch, fact extraction — over real HTTP."""
    from deskfleet.agents.researcher import researcher_node
    from deskfleet.graph.state import initial_state
    from tests.conftest import researcher_calling

    model = researcher_calling([{"name": "get_order_status", "args": {"order_id": "1042"}}])

    state = researcher_node(model)(initial_state("t-int", "Where is my order 1042?", "1042"))

    assert [call.name for call in state["tool_calls"]] == ["get_order_status"]
    assert any(fact.key == "order.status" for fact in state["facts"])
