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
    """Granular facts, one per claimable field.

    S-04's Reviewer grounds individual draft claims against `Fact.value`, so a single fact
    holding a whole summary would ground everything or nothing.
    """
    if call.rejected or not call.ok:
        return []
    extract = _EXTRACTORS.get(call.name)
    fields = extract(call.result_summary) if extract else {}
    prefix = _FACT_PREFIXES.get(call.name, call.name)
    if not fields:
        return [Fact(source=call.name, key=f"{call.name}.result", value=call.result_summary)]
    return [
        Fact(source=call.name, key=f"{prefix}.{name}", value=value)
        for name, value in fields.items()
    ]


_FACT_PREFIXES = {
    "get_order_status": "order",
    "get_product": "product",
    "search_products": "search",
}


def _order_fields(summary: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for phrase in summary.split("; "):
        if phrase.startswith("order ") and " is " in phrase:
            fields["id"], _, fields["status"] = phrase[len("order ") :].partition(" is ")
        elif phrase == "no eta on record":
            fields["eta"] = "none on record"
        elif phrase.startswith("refunded "):
            when, _, amount = phrase[len("refunded ") :].partition(" for ")
            fields["refunded_at"] = when
            fields["refund_amount"] = amount
        elif phrase.startswith("delay reason: "):
            fields["delay_reason"] = phrase[len("delay reason: ") :]
        else:
            for label, name in _ORDER_LABELS.items():
                if phrase.startswith(label):
                    fields[name] = phrase[len(label) :]
                    break
    return fields


_ORDER_LABELS = {
    "placed ": "placed_at",
    "delivered ": "delivered_at",
    "eta ": "eta",
    "carrier ": "carrier",
    "tracking ": "tracking",
    "total ": "total",
    "items: ": "items",
}


def _product_fields(summary: str) -> dict[str, str]:
    head, _, specs = summary.partition(". Specs: ")
    head, _, description = head.partition(". Description: ")
    identifier, _, rest = head.partition(": ")
    title, _, attributes = rest.partition(" — ")
    fields = {"id": identifier, "title": title}
    labels = ("price", "category", "availability")
    for name, value in zip(labels, attributes.split(", "), strict=False):
        fields[name] = value
    if description:
        fields["description"] = description
    if specs:
        fields["specs"] = specs
    return fields


def _search_fields(summary: str) -> dict[str, str]:
    if summary.startswith("no products matched "):
        return {"match_count": "0", "query": summary[len("no products matched ") :]}
    header, _, matches = summary.partition(": ")
    count, _, rest = header.partition(" product(s) matched ")
    fields = {"match_count": count, "query": rest.removesuffix(" (showing the first 5)")}
    for index, line in enumerate(matches.split(" | "), start=1):
        if line:
            fields[f"result.{index}"] = line
    return fields


_EXTRACTORS: dict[str, Callable[[str], dict[str, str]]] = {
    "get_order_status": _order_fields,
    "get_product": _product_fields,
    "search_products": _search_fields,
}
