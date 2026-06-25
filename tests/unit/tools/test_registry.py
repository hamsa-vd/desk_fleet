import re
from pathlib import Path
from typing import Any

import pytest

from deskfleet.tools import REGISTRY, allowed_names, dispatch, facts_from, impl, langchain_tools
from deskfleet.tools.http_client import HttpErr, HttpOk

ORDER_1042 = {
    "order_id": "1042",
    "status": "shipped",
    "placed_at": "2026-07-24",
    "eta": "2026-07-29",
    "carrier": "DHL",
    "tracking": "JD0002210091827364",
    "items": [{"product_id": "7", "title": "Aeris Wireless Earbuds", "qty": 1, "price": 24.99}],
    "total": 24.99,
    "currency": "GBP",
}

PRODUCT_7 = {
    "product_id": "7",
    "title": "Aeris Wireless Earbuds",
    "price": 24.99,
    "currency": "GBP",
    "category": "electronics",
    "description": "Bluetooth 5.3 earbuds with active noise cancellation.",
    "in_stock": True,
    "specs": {"active_noise_cancellation": False},
}


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch):
    def _mount(result: HttpOk | HttpErr) -> list[dict[str, Any]]:
        captured: list[dict[str, Any]] = []

        def fake_get_json(url: str, **kwargs: Any) -> HttpOk | HttpErr:
            captured.append({"url": url, **kwargs})
            return result

        monkeypatch.setattr(impl, "get_json", fake_get_json)
        return captured

    return _mount


def test_the_allowlist_holds_exactly_three_tools() -> None:
    assert allowed_names() == frozenset({"get_order_status", "get_product", "search_products"})


def test_the_name_triple_matches_for_every_tool() -> None:
    for key, tool in REGISTRY.items():
        assert key == tool.name == tool.fn.__name__ == tool.schema["function"]["name"]


def test_every_schema_describes_itself_and_its_parameters() -> None:
    for tool in REGISTRY.values():
        function = tool.schema["function"]
        assert function["description"].strip()
        for parameter in function["parameters"]["properties"].values():
            assert parameter["description"].strip()


def test_order_lookup_summarises_the_order(upstream) -> None:
    upstream(HttpOk(data=ORDER_1042, status=200))

    call = dispatch("get_order_status", {"order_id": "1042"})

    assert call.ok
    assert "1042 is shipped" in call.result_summary
    assert "eta 2026-07-29" in call.result_summary
    assert call.latency_ms >= 0


def test_arguments_as_a_json_string_and_as_a_dict_behave_identically(upstream) -> None:
    upstream(HttpOk(data=ORDER_1042, status=200))

    from_string = dispatch("get_order_status", '{"order_id": "1042"}')
    from_dict = dispatch("get_order_status", {"order_id": "1042"})

    assert from_string.ok and from_dict.ok
    assert from_string.result_summary == from_dict.result_summary
    assert from_string.args == from_dict.args == {"order_id": "1042"}


def test_malformed_argument_json_is_reported_not_raised(upstream) -> None:
    upstream(HttpOk(data=ORDER_1042, status=200))

    call = dispatch("get_order_status", "{order_id: 1042")

    assert call.ok is False
    assert "not valid JSON" in call.result_summary


def test_wrong_arguments_are_reported_not_raised(upstream) -> None:
    upstream(HttpOk(data=ORDER_1042, status=200))

    call = dispatch("get_order_status", {"orderId": "1042"})

    assert call.ok is False
    assert "wrong arguments" in call.result_summary


def test_a_missing_order_is_a_readable_string(upstream) -> None:
    upstream(HttpErr(reason="not found", status=404, attempts=1))

    call = dispatch("get_order_status", {"order_id": "9999"})

    assert call.ok is False
    assert call.result_summary == "order 9999 was not found"


def test_an_unreachable_upstream_degrades_the_answer(upstream) -> None:
    upstream(HttpErr(reason="order service timed out after 4 attempts", status=None, attempts=4))

    call = dispatch("get_order_status", {"order_id": "1042"})

    assert call.ok is False
    assert "could not be reached" in call.result_summary


def test_product_lookup_includes_specs(upstream) -> None:
    upstream(HttpOk(data=PRODUCT_7, status=200))

    call = dispatch("get_product", {"product_id": "7"})

    assert call.ok
    assert "Aeris Wireless Earbuds" in call.result_summary
    assert "active_noise_cancellation=False" in call.result_summary


def test_search_returns_matches(upstream) -> None:
    upstream(HttpOk(data={"query": "earbuds", "count": 1, "results": [PRODUCT_7]}, status=200))

    call = dispatch("search_products", {"query": "earbuds"})

    assert call.ok
    assert "1 product(s) matched" in call.result_summary


def test_an_empty_search_is_a_valid_answer(upstream) -> None:
    upstream(HttpOk(data={"query": "zzz", "count": 0, "results": []}, status=200))

    call = dispatch("search_products", {"query": "zzz"})

    assert call.ok is True
    assert "no products matched" in call.result_summary


def test_orders_and_products_use_their_own_base_urls(upstream) -> None:
    captured = upstream(HttpOk(data=ORDER_1042, status=200))
    dispatch("get_order_status", {"order_id": "1042"})
    dispatch("get_product", {"product_id": "7"})

    assert captured[0]["url"].endswith("/orders/1042")
    assert captured[1]["url"].endswith("/products/7")


def test_facts_are_produced_only_for_successful_calls(upstream) -> None:
    upstream(HttpOk(data=ORDER_1042, status=200))
    ok_call = dispatch("get_order_status", {"order_id": "1042"})
    rejected = dispatch("delete_database", {})

    facts = facts_from(ok_call)

    assert len(facts) == 1
    assert facts[0].source == "get_order_status"
    assert facts[0].value == ok_call.result_summary
    assert facts_from(rejected) == []


def test_langchain_tools_mirror_the_registry() -> None:
    bound = langchain_tools()

    assert {t.name for t in bound} == allowed_names()
    assert all(t.description for t in bound)


def test_the_tool_layer_contains_no_retry_logic() -> None:
    tools_dir = Path(impl.__file__).parent
    for name in ("impl.py", "registry.py"):
        source = (tools_dir / name).read_text(encoding="utf-8")
        assert not re.search(r"\b(retry|backoff|sleep)\b", source, re.IGNORECASE)
