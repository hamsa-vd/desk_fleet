import re
from pathlib import Path
from typing import Any

import pytest

from deskfleet.config import get_settings
from deskfleet.store import (
    EscalationRow,
    InMemoryRepository,
    TicketRow,
    ToolCallRow,
    health,
    migrate,
    repository,
    tool_calls_to_json,
    write_escalation,
    write_ticket,
    write_tool_calls,
)

TICKET = TicketRow(
    ticket_id="T-1",
    body="where is my order <EMAIL_REDACTED>",
    category="order",
    decision="resolved",
    reply="It ships tomorrow.",
    escalation_reason=None,
    latency_ms=1200,
    tokens_in=900,
    tokens_out=140,
    usd=0.0021,
)


class FakeCursor:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, params: Any = None) -> None:
        self.log.append((statement, params))

    def executemany(self, statement: str, params: Any) -> None:
        self.log.append((statement, params))


class FakeConnection:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.log)


@pytest.fixture
def executed(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    log: list[tuple[str, Any]] = []
    monkeypatch.setattr(repository, "_connect", lambda: FakeConnection(log))
    return log


@pytest.fixture
def unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> None:
        raise ConnectionError("could not connect to Neon")

    monkeypatch.setattr(repository, "_connect", refuse)


def test_migrate_is_idempotent(executed: list[tuple[str, Any]]) -> None:
    migrate()
    migrate()

    assert len(executed) == 2
    for statement, _ in executed:
        assert "IF NOT EXISTS" in statement
        assert "DROP" not in statement.upper()


def test_write_ticket_binds_every_value(executed: list[tuple[str, Any]]) -> None:
    write_ticket(TICKET)

    statement, params = executed[0]
    assert params[0] == "T-1"
    assert params[1] == TICKET.body
    assert TICKET.body not in statement
    assert statement.count("%s") == len(params)


def test_empty_tool_call_batch_issues_no_statement(executed: list[tuple[str, Any]]) -> None:
    write_tool_calls([])

    assert executed == []


def test_rejected_tool_calls_are_persisted(executed: list[tuple[str, Any]]) -> None:
    write_tool_calls(
        [
            ToolCallRow("T-1", "get_order_status", '{"order_id": "1042"}', ok=True),
            ToolCallRow("T-1", "delete_everything", "{}", ok=False, rejected=True),
        ]
    )

    _, params = executed[0]
    assert len(params) == 2
    assert params[1][4] is True


def test_escalation_write_binds_the_audit_trail(executed: list[tuple[str, Any]]) -> None:
    write_escalation(
        EscalationRow("T-1", "max_iters_exhausted", "reviewer never approved", "best draft", "[]")
    )

    statement, params = executed[0]
    assert params == ("T-1", "max_iters_exhausted", "reviewer never approved", "best draft", "[]")
    assert "max_iters_exhausted" not in statement


@pytest.mark.usefixtures("unreachable")
def test_writes_never_raise_when_the_database_is_down(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("ERROR"):
        write_ticket(TICKET)
        write_tool_calls([ToolCallRow("T-1", "get_order_status", "{}", ok=True)])
        write_escalation(EscalationRow("T-1", "tool_failure"))
        migrate()

    assert len(caplog.records) == 4


def test_health_is_false_without_a_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    try:
        assert health() is False
    finally:
        get_settings.cache_clear()


def test_no_sql_statement_interpolates_a_value() -> None:
    source = Path(repository.__file__).read_text(encoding="utf-8")
    statements = re.findall(r'"""\s*\n\s*(?:INSERT|SELECT|UPDATE)[\s\S]*?"""', source)

    assert statements
    for statement in statements:
        assert "{" not in statement
        assert "%(" not in statement
        assert not re.search(r"%[sd]?\s*%", statement)


def test_the_store_uses_no_orm() -> None:
    for path in Path(repository.__file__).parent.glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert "sqlalchemy" not in source
        assert "sqlmodel" not in source
        assert "tortoise" not in source


def test_in_memory_repository_mirrors_the_module_surface() -> None:
    repo = InMemoryRepository()

    for name in ("migrate", "write_ticket", "write_tool_calls", "write_escalation", "health"):
        assert callable(getattr(repo, name))

    repo.migrate()
    repo.write_ticket(TICKET)
    repo.write_tool_calls([ToolCallRow("T-1", "get_order_status", "{}", ok=True)])
    repo.write_escalation(EscalationRow("T-1", "no_facts_found"))

    assert repo.migrated
    assert repo.tickets["T-1"].body == TICKET.body
    assert len(repo.tool_calls) == 1
    assert repo.escalations[0].reason == "no_facts_found"
    assert repo.health() is True


def test_tool_calls_serialise_for_the_escalation_payload() -> None:
    payload = tool_calls_to_json(
        [ToolCallRow("T-1", "get_order_status", '{"order_id": "1042"}', ok=True, latency_ms=42)]
    )

    assert '"order_id": "1042"' in payload
    assert '"rejected": false' in payload
