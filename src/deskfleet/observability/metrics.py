"""Prometheus metrics.

Every metric and its label set, so S-10 can build the dashboard without reading this file:

    deskfleet_tickets_total{decision, category}            Counter
    deskfleet_ticket_latency_seconds{decision}             Histogram
    deskfleet_node_latency_seconds{node}                   Histogram
    deskfleet_tokens_total{direction, model}               Counter    direction = in | out
    deskfleet_cost_usd_total{model}                        Counter
    deskfleet_tool_calls_total{tool, ok, rejected}         Counter
    deskfleet_escalations_total{reason}                    Counter
    deskfleet_refusals_total{reason}                       Counter
    deskfleet_budget_exceeded_total                        Counter
    deskfleet_token_estimate_error_ratio                   Histogram
    deskfleet_http_requests_total{method, route, status}   Counter

Labels are drawn from bounded sets only — never a ticket id, never a raw custom model string.
Histograms rather than Summaries throughout: Summary quantiles are computed per instance and
cannot be aggregated, so a global P99 would be unobtainable.

Counters reset on every Cloud Run cold start. That is expected, and it is exactly why the deployed
environment pushes via remote_write instead of relying on scrapes — do not "fix" the reset.
"""

from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

from deskfleet.config import get_logger

logger = get_logger(__name__)

LATENCY_BUCKETS = (0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120)

_registry = CollectorRegistry()
_metrics: dict[str, Any] = {}


def _build(registry: CollectorRegistry) -> dict[str, Any]:
    return {
        "tickets": Counter(
            "deskfleet_tickets_total",
            "Tickets resolved, by decision and category.",
            ["decision", "category"],
            registry=registry,
        ),
        "ticket_latency": Histogram(
            "deskfleet_ticket_latency_seconds",
            "End-to-end ticket latency.",
            ["decision"],
            buckets=LATENCY_BUCKETS,
            registry=registry,
        ),
        "node_latency": Histogram(
            "deskfleet_node_latency_seconds",
            "Per-node latency inside the graph.",
            ["node"],
            buckets=LATENCY_BUCKETS,
            registry=registry,
        ),
        "tokens": Counter(
            "deskfleet_tokens_total",
            "Tokens consumed, split by direction because their unit prices differ.",
            ["direction", "model"],
            registry=registry,
        ),
        "cost": Counter(
            "deskfleet_cost_usd_total",
            "Estimated spend in USD.",
            ["model"],
            registry=registry,
        ),
        "tool_calls": Counter(
            "deskfleet_tool_calls_total",
            "Tool invocations, including rejected off-allowlist attempts.",
            ["tool", "ok", "rejected"],
            registry=registry,
        ),
        "escalations": Counter(
            "deskfleet_escalations_total",
            "Escalations by reason.",
            ["reason"],
            registry=registry,
        ),
        "refusals": Counter(
            "deskfleet_refusals_total",
            "Refusals by reason.",
            ["reason"],
            registry=registry,
        ),
        "budget_exceeded": Counter(
            "deskfleet_budget_exceeded_total",
            "Tickets that went over the soft token budget.",
            registry=registry,
        ),
        "estimate_error": Histogram(
            "deskfleet_token_estimate_error_ratio",
            "tiktoken estimate divided by the provider's reported usage.",
            buckets=(0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0),
            registry=registry,
        ),
        "http_requests": Counter(
            "deskfleet_http_requests_total",
            "HTTP requests by route template and status.",
            ["method", "route", "status"],
            registry=registry,
        ),
    }


def metrics() -> dict[str, Any]:
    if not _metrics:
        _metrics.update(_build(_registry))
    return _metrics


def use_registry(registry: CollectorRegistry) -> None:
    """Swap in a fresh registry so tests do not leak counter values into one another."""
    global _registry
    _registry = registry
    _metrics.clear()
    _metrics.update(_build(registry))


def observe_ticket(decision: str, category: str | None, latency_s: float) -> None:
    try:
        m = metrics()
        m["tickets"].labels(decision=decision, category=category or "none").inc()
        m["ticket_latency"].labels(decision=decision).observe(latency_s)
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "tickets", "cause": str(exc)})


def observe_node(node: str, latency_s: float) -> None:
    try:
        metrics()["node_latency"].labels(node=node).observe(latency_s)
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "node_latency", "cause": str(exc)})


def observe_tokens(model: str, tokens_in: int, tokens_out: int) -> None:
    try:
        tokens = metrics()["tokens"]
        tokens.labels(direction="in", model=model).inc(tokens_in)
        tokens.labels(direction="out", model=model).inc(tokens_out)
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "tokens", "cause": str(exc)})


def observe_cost(model: str, usd: float) -> None:
    try:
        metrics()["cost"].labels(model=model).inc(usd)
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "cost", "cause": str(exc)})


def observe_tool_call(tool: str, ok: bool, rejected: bool) -> None:
    try:
        metrics()["tool_calls"].labels(
            tool=tool if not rejected else "unregistered",
            ok=str(ok).lower(),
            rejected=str(rejected).lower(),
        ).inc()
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "tool_calls", "cause": str(exc)})


def observe_escalation(reason: str) -> None:
    try:
        metrics()["escalations"].labels(reason=reason).inc()
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "escalations", "cause": str(exc)})


def observe_refusal(reason: str) -> None:
    try:
        metrics()["refusals"].labels(reason=reason).inc()
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "refusals", "cause": str(exc)})


def observe_estimate_error(estimated: int, actual: int) -> None:
    try:
        if actual > 0:
            metrics()["estimate_error"].observe(estimated / actual)
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "estimate_error", "cause": str(exc)})


def note_budget_exceeded(ticket_id: str, tokens: int) -> None:
    """Soft cap: warn, count, continue. The hard bound on spend is MAX_ITERS (D-16)."""
    try:
        metrics()["budget_exceeded"].inc()
        logger.warning("token_budget_exceeded", extra={"ticket_id": ticket_id, "tokens": tokens})
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "budget_exceeded", "cause": str(exc)})


def metrics_middleware(app: Any) -> None:
    @app.middleware("http")
    async def _record(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        try:
            route = request.scope.get("route")
            metrics()["http_requests"].labels(
                method=request.method,
                route=getattr(route, "path", "unmatched"),
                status=str(response.status_code),
            ).inc()
        except Exception as exc:
            logger.error("metric_failed", extra={"metric": "http_requests", "cause": str(exc)})
        return response


def metrics_response() -> Response:
    try:
        return Response(generate_latest(_registry), media_type=CONTENT_TYPE_LATEST)
    except Exception as exc:
        logger.error("metric_failed", extra={"metric": "exposition", "cause": str(exc)})
        return Response("", media_type=CONTENT_TYPE_LATEST)
