"""/health and /metrics."""

from fastapi import APIRouter
from starlette.responses import Response

from deskfleet.api.contracts import HealthResponse
from deskfleet.observability import metrics_response

router = APIRouter(tags=["ops"])

SERVICE_NAME = "deskfleet"
VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Answered from memory. No database, no LLM, no upstream — Cloud Run gates traffic on this."""
    return HealthResponse(status="ok", service=SERVICE_NAME, version=VERSION)


@router.get("/metrics")
def metrics() -> Response:
    return metrics_response()
