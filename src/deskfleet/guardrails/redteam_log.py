"""Blocked inputs are logged with their pattern names for review. Never with the text itself."""

from deskfleet.config import get_logger
from deskfleet.guardrails.scan import ScanResult

logger = get_logger("deskfleet.redteam")


def log_blocked(ticket_id: str, result: ScanResult) -> None:
    logger.warning(
        "input_blocked",
        extra={
            "ticket_id": ticket_id,
            "matched_patterns": result.matched_patterns,
            "pii_classes": sorted(result.pii_found),
        },
    )
