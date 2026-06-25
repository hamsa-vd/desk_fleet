"""The three tools.

Each returns a short string — a summary or a readable error — and never raises. An LLM can
reason about an error string; it cannot reason about a traceback.
"""

from typing import Any

from deskfleet.config import get_settings
from deskfleet.tools.http_client import HttpOk, get_json

# A tool never raises, so the registry recognises a failed lookup by the phrasing it returns.
# An empty search is deliberately absent: no matches is a valid answer, not a failure.
FAILURE_MARKERS = ("was not found", "could not be reached", "failed unexpectedly")


def is_failure(summary: str) -> bool:
    return any(marker in summary for marker in FAILURE_MARKERS)


def _order_url(path: str) -> str:
    return f"{get_settings().order_api_base_url.rstrip('/')}{path}"


def _product_url(path: str) -> str:
    return f"{get_settings().product_api_base_url.rstrip('/')}{path}"


def _summarise_product(product: dict[str, Any]) -> str:
    stock = "in stock" if product.get("in_stock") else "out of stock"
    return (
        f"{product.get('product_id')}: {product.get('title')} — "
        f"{product.get('price')} {product.get('currency')}, "
        f"{product.get('category')}, {stock}"
    )


def get_order_status(order_id: str) -> str:
    """Look up one order by its ID."""
    try:
        result = get_json(_order_url(f"/orders/{order_id}"))
        if not isinstance(result, HttpOk):
            if result.status == 404:
                return f"order {order_id} was not found"
            return f"the order service could not be reached: {result.reason}"

        order = result.data
        parts = [f"order {order.get('order_id')} is {order.get('status')}"]
        if order.get("placed_at"):
            parts.append(f"placed {order['placed_at']}")
        if order.get("delivered_at"):
            parts.append(f"delivered {order['delivered_at']}")
        if order.get("eta"):
            parts.append(f"eta {order['eta']}")
        else:
            parts.append("no eta on record")
        if order.get("carrier"):
            parts.append(f"carrier {order['carrier']}")
        if order.get("tracking"):
            parts.append(f"tracking {order['tracking']}")
        if order.get("delay_reason"):
            parts.append(f"delay reason: {order['delay_reason']}")
        if order.get("refunded_at"):
            parts.append(f"refunded {order['refunded_at']} for {order.get('refund_amount')}")
        parts.append(f"total {order.get('total')} {order.get('currency')}")
        items = ", ".join(
            f"{i.get('qty')}x {i.get('title')} (product {i.get('product_id')})"
            for i in order.get("items", [])
        )
        if items:
            parts.append(f"items: {items}")
        return "; ".join(parts)
    except Exception as exc:
        return f"the order lookup failed unexpectedly: {type(exc).__name__}"


def get_product(product_id: str) -> str:
    """Look up one product by its ID."""
    try:
        result = get_json(_product_url(f"/products/{product_id}"))
        if not isinstance(result, HttpOk):
            if result.status == 404:
                return f"product {product_id} was not found"
            return f"the product service could not be reached: {result.reason}"

        product = result.data
        summary = _summarise_product(product)
        if product.get("description"):
            summary += f". Description: {product['description']}"
        if product.get("specs"):
            specs = ", ".join(f"{k}={v}" for k, v in product["specs"].items())
            summary += f". Specs: {specs}"
        return summary
    except Exception as exc:
        return f"the product lookup failed unexpectedly: {type(exc).__name__}"


def search_products(query: str) -> str:
    """Search the product catalogue by keyword."""
    try:
        result = get_json(_product_url("/products/search"), params={"q": query})
        if not isinstance(result, HttpOk):
            return f"the product search could not be reached: {result.reason}"

        results = result.data.get("results", [])
        if not results:
            return f"no products matched {query!r}"
        lines = [_summarise_product(p) for p in results[:5]]
        header = f"{len(results)} product(s) matched {query!r}"
        if len(results) > 5:
            header += " (showing the first 5)"
        return header + ": " + " | ".join(lines)
    except Exception as exc:
        return f"the product search failed unexpectedly: {type(exc).__name__}"
