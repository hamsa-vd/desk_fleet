"""A standalone fake vendor API. Imports nothing from deskfleet — that is what keeps it honest."""

import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

FIXTURES = Path(__file__).parent / "fixtures"

# Fixtures store day offsets so the shipped order's ETA is always in the future; the responses
# themselves carry absolute ISO dates.
_DATE_OFFSET_FIELDS = {
    "placed_at_days_ago": ("placed_at", -1),
    "delivered_at_days_ago": ("delivered_at", -1),
    "refunded_at_days_ago": ("refunded_at", -1),
    "cancelled_at_days_ago": ("cancelled_at", -1),
    "eta_days_ahead": ("eta", 1),
}

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("mock_api")


def _materialise_dates(order: dict[str, Any], today: date) -> dict[str, Any]:
    resolved = {k: v for k, v in order.items() if k not in _DATE_OFFSET_FIELDS}
    for offset_field, (target_field, sign) in _DATE_OFFSET_FIELDS.items():
        if offset_field in order:
            shifted = today + timedelta(days=sign * order[offset_field])
            resolved[target_field] = shifted.isoformat()
    return resolved


def _load(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _build_orders() -> dict[str, dict[str, Any]]:
    today = date.today()
    return {o["order_id"]: _materialise_dates(o, today) for o in _load("orders")}


ORDERS = _build_orders()
PRODUCTS = {p["product_id"]: p for p in _load("products")}

LATENCY_MS = int(os.getenv("MOCK_API_LATENCY_MS", "0"))

app = FastAPI(title="DeskFleet mock vendor API", version="1.0.0")


@app.middleware("http")
async def artificial_latency(request: Any, call_next: Any) -> Any:
    if LATENCY_MS:
        time.sleep(LATENCY_MS / 1000)
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "orders": len(ORDERS), "products": len(PRODUCTS)}


@app.get("/orders/{order_id}")
def get_order(order_id: str) -> Any:
    order = ORDERS.get(order_id)
    if order is None:
        return JSONResponse(
            status_code=404, content={"error": "order_not_found", "order_id": order_id}
        )
    return order


@app.get("/products/search")
def search_products(q: str = "") -> dict[str, Any]:
    needle = q.strip().lower()
    results = [
        p
        for p in PRODUCTS.values()
        if needle in p["title"].lower() or needle in p["description"].lower()
    ]
    return {"query": q, "count": len(results), "results": results}


@app.get("/products/{product_id}")
def get_product(product_id: str) -> Any:
    product = PRODUCTS.get(product_id)
    if product is None:
        return JSONResponse(
            status_code=404, content={"error": "product_not_found", "product_id": product_id}
        )
    return product
