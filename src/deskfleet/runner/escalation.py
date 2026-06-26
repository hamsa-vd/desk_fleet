"""Turning an ESCALATE decision into a durable handoff a human can actually finish."""

import json

from deskfleet.agents.schemas import EscalationReason, ToolCall
from deskfleet.config import get_logger, get_settings
from deskfleet.graph.state import TicketState
from deskfleet.observability import observe_escalation
from deskfleet.store import EscalationRow, write_escalation
from deskfleet.tools.http_client import HttpErr, post_json

logger = get_logger(__name__)

UNKNOWN_DETAIL = "the run ended without a reply the assistant was willing to send"


def _audit_trail(calls: list[ToolCall]) -> str:
    """Every lookup, including the ones the allowlist refused — that refusal is the evidence."""
    return json.dumps(
        [
            {
                "name": call.name,
                "args": call.args,
                "ok": call.ok,
                "rejected": call.rejected,
                "result_summary": call.result_summary,
                "latency_ms": call.latency_ms,
            }
            for call in calls
        ]
    )


def build_escalation(state: TicketState) -> EscalationRow:
    reason = state["escalation_reason"] or EscalationReason.NO_FACTS_FOUND
    return EscalationRow(
        ticket_id=state["ticket_id"],
        reason=EscalationReason(reason).value,
        detail=state["escalation_detail"] or UNKNOWN_DETAIL,
        # Unapproved, but the loop already paid for it — a human starting from nothing is worse.
        best_draft=state["best_draft"],
        tool_calls_json=_audit_trail(state["tool_calls"]),
    )


def _webhook_payload(row: EscalationRow, state: TicketState) -> dict:
    return {
        "ticket_id": row.ticket_id,
        "reason": row.reason,
        "detail": row.detail,
        # Already redacted on the way into the graph; no credential ever enters this payload.
        "ticket": state["ticket"],
        "best_draft": row.best_draft,
        "review_notes": state["review_notes"],
        "tool_calls": json.loads(row.tool_calls_json),
    }


def _notify(row: EscalationRow, state: TicketState) -> None:
    url = get_settings().escalation_webhook_url
    if not url:
        return
    result = post_json(url, _webhook_payload(row, state))
    if isinstance(result, HttpErr):
        logger.warning(
            "escalation_webhook_failed",
            extra={"ticket_id": row.ticket_id, "cause": result.reason},
        )


def handle_escalation(state: TicketState) -> None:
    """Persist, count and notify. Never raises: a handoff problem must not fail the request."""
    row = build_escalation(state)
    observe_escalation(row.reason)

    try:
        write_escalation(row)
    except Exception as exc:
        logger.error(
            "escalation_write_failed",
            extra={"ticket_id": row.ticket_id, "cause": str(exc)},
        )

    try:
        _notify(row, state)
    except Exception as exc:
        logger.warning(
            "escalation_webhook_failed",
            extra={"ticket_id": row.ticket_id, "cause": str(exc)},
        )
