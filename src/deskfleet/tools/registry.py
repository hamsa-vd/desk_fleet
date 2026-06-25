"""The registry IS the allowlist. There is no other route from a model-requested name to a call."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.tools import BaseTool, StructuredTool

from deskfleet.agents.schemas import Fact, ToolCall
from deskfleet.config import get_logger
from deskfleet.tools.impl import get_order_status, get_product, is_failure, search_products

logger = get_logger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    fn: Callable[..., str]
    schema: dict
    description: str


def _function_schema(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


# Descriptions say WHEN to call the tool, not just what it does — that is what stops an agent
# reaching for the wrong one.
_ORDER_DESCRIPTION = (
    "Look up the current status of one customer order by its order ID. Call this whenever the "
    "ticket mentions an order number or asks where something is, whether it shipped, when it will "
    "arrive, or whether it was refunded or cancelled. Returns the status, dates, carrier, tracking "
    "number and the items on the order."
)
_PRODUCT_DESCRIPTION = (
    "Look up one product by its product ID. Call this when the ticket asks about a specific "
    "product's price, availability, description or specifications, and you already know its ID — "
    "for example from an order returned by get_order_status."
)
_SEARCH_DESCRIPTION = (
    "Search the product catalogue by keyword. Call this when the ticket names a product by "
    "description rather than by ID, and you need to find which product they mean before looking "
    "up its details."
)

REGISTRY: dict[str, Tool] = {
    "get_order_status": Tool(
        name="get_order_status",
        fn=get_order_status,
        description=_ORDER_DESCRIPTION,
        schema=_function_schema(
            "get_order_status",
            _ORDER_DESCRIPTION,
            {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID as the customer wrote it, e.g. '1042'.",
                    }
                },
                "required": ["order_id"],
            },
        ),
    ),
    "get_product": Tool(
        name="get_product",
        fn=get_product,
        description=_PRODUCT_DESCRIPTION,
        schema=_function_schema(
            "get_product",
            _PRODUCT_DESCRIPTION,
            {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product ID, e.g. '7'. Use search_products if unknown.",
                    }
                },
                "required": ["product_id"],
            },
        ),
    ),
    "search_products": Tool(
        name="search_products",
        fn=search_products,
        description=_SEARCH_DESCRIPTION,
        schema=_function_schema(
            "search_products",
            _SEARCH_DESCRIPTION,
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords from the ticket, e.g. 'wireless earbuds'.",
                    }
                },
                "required": ["query"],
            },
        ),
    ),
}


def allowed_names() -> frozenset[str]:
    return frozenset(REGISTRY)


def _normalise_args(args: dict | str) -> dict:
    """Tool call arguments arrive as a JSON string, not a dict. Accept either."""
    if isinstance(args, str):
        return json.loads(args) if args.strip() else {}
    return dict(args)


def dispatch(name: str, args: dict | str) -> ToolCall:
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    tool = REGISTRY.get(name)
    if tool is None:
        logger.warning("tool_call_rejected", extra={"tool": name, "allowed": sorted(REGISTRY)})
        return ToolCall(
            name=name,
            args={},
            ok=False,
            rejected=True,
            result_summary=f"tool {name!r} is not registered",
            latency_ms=elapsed_ms(),
        )

    try:
        parsed = _normalise_args(args)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ToolCall(
            name=name,
            args={},
            ok=False,
            result_summary=f"arguments for {name} were not valid JSON",
            latency_ms=elapsed_ms(),
        )

    try:
        summary = tool.fn(**parsed)
    except TypeError as exc:
        return ToolCall(
            name=name,
            args=parsed,
            ok=False,
            result_summary=f"{name} was called with the wrong arguments: {exc}",
            latency_ms=elapsed_ms(),
        )

    return ToolCall(
        name=name,
        args=parsed,
        ok=not is_failure(summary),
        result_summary=summary,
        latency_ms=elapsed_ms(),
    )


def langchain_tools() -> list[BaseTool]:
    """The same three tools, bound for the Researcher's AgentExecutor."""
    return [
        StructuredTool.from_function(
            func=tool.fn,
            name=tool.name,
            description=tool.description,
        )
        for tool in REGISTRY.values()
    ]


def facts_from(call: ToolCall) -> list[Fact]:
    if call.rejected or not call.ok:
        return []
    return [Fact(source=call.name, key=f"{call.name}.result", value=call.result_summary)]
