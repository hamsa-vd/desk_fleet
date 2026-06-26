"""The HTTP request and response shapes.

Both are defined in `runner/events.py` because `run_ticket` takes and returns them and nothing may
import `api`. They are re-exported here so the transport layer still reads as owning its contract.
"""

from pydantic import BaseModel

from deskfleet.runner.events import ResolveRequest, TicketResult

__all__ = ["ErrorResponse", "HealthResponse", "ResolveRequest", "TicketResult"]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ErrorResponse(BaseModel):
    detail: str
    correlation_id: str | None = None
