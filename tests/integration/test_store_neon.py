import os
import uuid

import pytest

from deskfleet.store import TicketRow, health, migrate, write_ticket

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not set"),
]


def test_migrate_and_write_against_a_real_database() -> None:
    migrate()

    row = TicketRow(
        ticket_id=f"itest-{uuid.uuid4()}",
        body="where is my order",
        category="order",
        decision="resolved",
        reply="It ships tomorrow.",
        escalation_reason=None,
    )
    write_ticket(row)

    assert health() is True
