import ast
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mock_api import app as mock_app

client = TestClient(mock_app.app)


def test_shipped_order_has_a_future_eta() -> None:
    body = client.get("/orders/1042").json()

    assert body["status"] == "shipped"
    assert date.fromisoformat(body["eta"]) > date.today()


def test_delivered_order_is_outside_the_refund_window() -> None:
    body = client.get("/orders/1001").json()

    assert body["status"] == "delivered"
    assert (date.today() - date.fromisoformat(body["delivered_at"])).days == 40


def test_delayed_order_carries_no_eta() -> None:
    body = client.get("/orders/1077").json()

    assert body["status"] == "delayed"
    assert body.get("eta") is None


@pytest.mark.parametrize(
    ("order_id", "status"),
    [("1088", "refunded"), ("1099", "cancelled")],
)
def test_terminal_order_states(order_id: str, status: str) -> None:
    assert client.get(f"/orders/{order_id}").json()["status"] == status


def test_unknown_order_is_a_404_with_a_typed_error() -> None:
    response = client.get("/orders/9999")

    assert response.status_code == 404
    assert response.json() == {"error": "order_not_found", "order_id": "9999"}


def test_product_lookup() -> None:
    body = client.get("/products/7").json()

    assert body["title"] == "Aeris Wireless Earbuds"
    assert body["price"] == 24.99


def test_product_description_can_overstate_the_specs() -> None:
    body = client.get("/products/7").json()

    assert "active noise cancellation" in body["description"].lower()
    assert body["specs"]["active_noise_cancellation"] is False


def test_unknown_product_is_a_404() -> None:
    response = client.get("/products/nope")

    assert response.status_code == 404
    assert response.json()["error"] == "product_not_found"


def test_search_is_case_insensitive_substring() -> None:
    body = client.get("/products/search", params={"q": "JOGGER"}).json()

    assert body["count"] >= 1
    assert all("jogger" in p["title"].lower() for p in body["results"])


def test_search_with_no_matches_is_an_empty_200() -> None:
    response = client.get("/products/search", params={"q": "zzzznotathing"})

    assert response.status_code == 200
    assert response.json() == {"query": "zzzznotathing", "count": 0, "results": []}


def test_health_reads_no_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object, **__: object) -> str:
        raise AssertionError("fixtures must be loaded once at startup, not per request")

    monkeypatch.setattr(Path, "read_text", explode)

    assert client.get("/health").status_code == 200
    assert client.get("/orders/1042").status_code == 200


def test_the_mock_never_imports_deskfleet() -> None:
    for source in Path(mock_app.__file__).parent.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not a.name.startswith("deskfleet") for a in node.names), source
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("deskfleet"), source


def test_products_cover_three_categories() -> None:
    categories = {p["category"] for p in mock_app.PRODUCTS.values()}

    assert len(mock_app.PRODUCTS) >= 12
    assert len(categories) >= 3
