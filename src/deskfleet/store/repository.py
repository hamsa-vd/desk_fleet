"""Raw SQL over Neon Postgres.

Every write swallows its own errors: a lost audit row beats a lost reply to a customer.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import psycopg

from deskfleet.config import get_logger, get_settings

logger = get_logger(__name__)

INSERT_TICKET = """
    INSERT INTO tickets (
        ticket_id, body, category, decision, reply,
        escalation_reason, latency_ms, tokens_in, tokens_out, usd
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (ticket_id) DO UPDATE SET
        body = EXCLUDED.body,
        category = EXCLUDED.category,
        decision = EXCLUDED.decision,
        reply = EXCLUDED.reply,
        escalation_reason = EXCLUDED.escalation_reason,
        latency_ms = EXCLUDED.latency_ms,
        tokens_in = EXCLUDED.tokens_in,
        tokens_out = EXCLUDED.tokens_out,
        usd = EXCLUDED.usd
"""

INSERT_TOOL_CALL = """
    INSERT INTO tool_calls (ticket_id, name, args_json, ok, rejected, result_summary, latency_ms)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

INSERT_ESCALATION = """
    INSERT INTO escalations (ticket_id, reason, detail, best_draft, tool_calls_json)
    VALUES (%s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class TicketRow:
    ticket_id: str
    #: Redacted body only — never the raw ticket.
    body: str
    category: str | None
    decision: str
    reply: str | None
    escalation_reason: str | None
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0


@dataclass(frozen=True)
class ToolCallRow:
    ticket_id: str
    name: str
    args_json: str
    ok: bool
    rejected: bool = False
    result_summary: str = ""
    latency_ms: int = 0


@dataclass(frozen=True)
class EscalationRow:
    ticket_id: str
    reason: str
    detail: str | None = None
    best_draft: str | None = None
    tool_calls_json: str = "[]"


def _dsn() -> str | None:
    url = get_settings().database_url
    return url.get_secret_value() if url else None


def _connect() -> psycopg.Connection:
    """Short-lived connections only — Neon freezes compute between requests."""
    dsn = _dsn()
    if dsn is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(dsn)


def _execute(statement: str, params: Sequence[Any], *, operation: str) -> bool:
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute(statement, params)
        return True
    except Exception as exc:
        logger.error("store_write_failed", extra={"operation": operation, "cause": str(exc)})
        return False


def write_ticket(row: TicketRow) -> None:
    _execute(
        INSERT_TICKET,
        (
            row.ticket_id,
            row.body,
            row.category,
            row.decision,
            row.reply,
            row.escalation_reason,
            row.latency_ms,
            row.tokens_in,
            row.tokens_out,
            row.usd,
        ),
        operation="write_ticket",
    )


def write_tool_calls(rows: Sequence[ToolCallRow]) -> None:
    if not rows:
        return
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.executemany(
                INSERT_TOOL_CALL,
                [
                    (
                        r.ticket_id,
                        r.name,
                        r.args_json,
                        r.ok,
                        r.rejected,
                        r.result_summary,
                        r.latency_ms,
                    )
                    for r in rows
                ],
            )
    except Exception as exc:
        logger.error(
            "store_write_failed", extra={"operation": "write_tool_calls", "cause": str(exc)}
        )


def write_escalation(row: EscalationRow) -> None:
    _execute(
        INSERT_ESCALATION,
        (row.ticket_id, row.reason, row.detail, row.best_draft, row.tool_calls_json),
        operation="write_escalation",
    )


def health() -> bool:
    """Diagnostics only — /health stays dependency-free or Cloud Run's traffic gate misbehaves."""
    try:
        with _connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


@dataclass
class InMemoryRepository:
    """The test double every later chunk's tests bind to. Same surface as the module."""

    tickets: dict[str, TicketRow] = field(default_factory=dict)
    tool_calls: list[ToolCallRow] = field(default_factory=list)
    escalations: list[EscalationRow] = field(default_factory=list)
    migrated: bool = False

    def migrate(self) -> None:
        self.migrated = True

    def write_ticket(self, row: TicketRow) -> None:
        self.tickets[row.ticket_id] = row

    def write_tool_calls(self, rows: Sequence[ToolCallRow]) -> None:
        self.tool_calls.extend(rows)

    def write_escalation(self, row: EscalationRow) -> None:
        self.escalations.append(row)

    def health(self) -> bool:
        return True


def tool_calls_to_json(rows: Sequence[ToolCallRow]) -> str:
    """The audit trail S-05 attaches to an escalation."""
    return json.dumps(
        [
            {
                "name": r.name,
                "args": json.loads(r.args_json) if r.args_json else {},
                "ok": r.ok,
                "rejected": r.rejected,
                "result_summary": r.result_summary,
                "latency_ms": r.latency_ms,
            }
            for r in rows
        ]
    )
