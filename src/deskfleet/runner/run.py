"""run_ticket(): the one place the end-to-end sequence is written.

It is a generator by design. /resolve drains it and returns the final result; S-06's SSE endpoint
re-emits every event. Collapsing it to a plain function would make that transport expensive.
"""

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from deskfleet.agents.schemas import Category, Decision, RefusalReason, ToolCall
from deskfleet.config import constants, get_logger
from deskfleet.graph.build import build_graph, invocation_config
from deskfleet.graph.state import initial_state
from deskfleet.guardrails import log_blocked, scan_input, scan_output
from deskfleet.models import Credentials, build_client, resolve
from deskfleet.observability import (
    estimate_tokens,
    note_budget_exceeded,
    observe_node,
    observe_refusal,
    observe_ticket,
    observe_tool_call,
    record_usage,
    traced_run,
)
from deskfleet.runner.events import (
    Event,
    EventDone,
    EventNode,
    EventTool,
    ResolveRequest,
    TicketResult,
)
from deskfleet.store import TicketRow, ToolCallRow, write_ticket, write_tool_calls

logger = get_logger(__name__)

NODES = ("classifier", "researcher")

#: TEMPORARY. The Responder (S-03) replaces this with a real drafted reply.
PLACEHOLDER_REPLY = (
    "Thanks for getting in touch — we have your ticket and a colleague is looking into it."
)


class _Usage:
    def __init__(self) -> None:
        self.tokens_in = 0
        self.tokens_out = 0

    def add(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out


def _build_clients(req: ResolveRequest, creds: Credentials) -> dict[str, Any]:
    overrides = req.models or {}
    return {node: build_client(resolve(node, overrides.get(node), creds)) for node in NODES}


def _model_id(req: ResolveRequest, node: str) -> str:
    selection = (req.models or {}).get(node)
    return selection.model_id if selection else constants.DEFAULT_MODEL_ID


def _refusal(ticket_id: str, reason: RefusalReason, body: str, latency_ms: int) -> TicketResult:
    return TicketResult(
        ticket_id=ticket_id,
        decision=Decision.REFUSE,
        reply=None,
        category=Category.OTHER if reason is RefusalReason.OUT_OF_SCOPE else None,
        escalation_reason=reason.value,
        escalation_detail=body,
        latency_ms=latency_ms,
    )


def _persist(result: TicketResult, redacted_body: str) -> None:
    write_ticket(
        TicketRow(
            ticket_id=result.ticket_id,
            body=redacted_body,
            category=result.category.value if result.category else None,
            decision=result.decision.value,
            reply=result.reply,
            escalation_reason=result.escalation_reason,
            latency_ms=result.latency_ms,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            usd=result.usd,
        )
    )


def _persist_tool_calls(ticket_id: str, calls: list[ToolCall]) -> None:
    write_tool_calls(
        [
            ToolCallRow(
                ticket_id=ticket_id,
                name=call.name,
                args_json=json.dumps(call.args),
                ok=call.ok,
                rejected=call.rejected,
                result_summary=call.result_summary,
                latency_ms=call.latency_ms,
            )
            for call in calls
        ]
    )


def run_ticket(req: ResolveRequest, creds: Credentials) -> Iterator[Event]:
    ticket_id = str(uuid.uuid4())
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    scan = scan_input(req.ticket)
    redacted = scan.clean_text

    if scan.injection_detected:
        log_blocked(ticket_id, scan)
        observe_refusal(RefusalReason.INJECTION.value)
        result = _refusal(
            ticket_id,
            RefusalReason.INJECTION,
            "the ticket contained instructions aimed at the assistant",
            elapsed_ms(),
        )
        observe_ticket(result.decision.value, None, elapsed_ms() / 1000)
        _persist(result, redacted)
        yield EventDone(result=result)
        return

    model_id = _model_id(req, "classifier")
    estimated_in = estimate_tokens(redacted, model_id)
    if estimated_in > constants.TOKEN_BUDGET_PER_TICKET:
        note_budget_exceeded(ticket_id, estimated_in)

    usage = _Usage()
    state = initial_state(ticket_id, redacted, req.order_id)

    with traced_run(ticket_id) as run:
        graph = build_graph(_build_clients(req, creds), on_usage=usage.add)
        node_started = time.perf_counter()
        reported_calls = 0
        for update in graph.stream(
            state, config=invocation_config(ticket_id), stream_mode="updates"
        ):
            for node, node_state in update.items():
                observe_node(node, time.perf_counter() - node_started)
                node_started = time.perf_counter()
                state = {**state, **node_state}
                for call in state["tool_calls"][reported_calls:]:
                    observe_tool_call(call.name, call.ok, call.rejected)
                    yield EventTool(
                        name=call.name,
                        ok=call.ok,
                        latency_ms=call.latency_ms,
                        rejected=call.rejected,
                    )
                reported_calls = len(state["tool_calls"])
                yield EventNode(node=node, status="end", data={"category": state.get("category")})

    _persist_tool_calls(ticket_id, state["tool_calls"])

    if state["category"] == Category.OTHER:
        result = _refusal(
            ticket_id,
            RefusalReason.OUT_OF_SCOPE,
            "the ticket is not a support matter for this retailer",
            elapsed_ms(),
        )
        observe_refusal(RefusalReason.OUT_OF_SCOPE.value)
    else:
        reply = scan_output(state["draft"] or PLACEHOLDER_REPLY).clean_text
        result = TicketResult(
            ticket_id=ticket_id,
            decision=Decision.RESOLVED,
            reply=reply,
            category=state["category"],
            tool_calls=state["tool_calls"],
            latency_ms=elapsed_ms(),
        )

    if usage.tokens_in == 0 and usage.tokens_out == 0:
        usage.add(estimated_in, estimate_tokens(result.reply or "", model_id))

    result = result.model_copy(
        update={
            "tokens_in": usage.tokens_in,
            "tokens_out": usage.tokens_out,
            "usd": record_usage(model_id, usage.tokens_in, usage.tokens_out),
            "langsmith_trace_url": run.trace_url,
            "latency_ms": elapsed_ms(),
        }
    )

    observe_ticket(result.decision.value, result.category, result.latency_ms / 1000)
    _persist(result, redacted)
    logger.info(
        "ticket_resolved",
        extra={
            "ticket_id": ticket_id,
            "decision": result.decision.value,
            "category": result.category,
            "latency_ms": result.latency_ms,
        },
    )
    yield EventDone(result=result)
