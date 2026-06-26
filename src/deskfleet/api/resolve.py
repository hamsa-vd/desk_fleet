"""POST /resolve. Validate, call the runner, shape the output — no business logic here."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from deskfleet.api.auth import require_credentials
from deskfleet.api.contracts import ResolveRequest, TicketResult
from deskfleet.config import get_logger
from deskfleet.models import Credentials, MissingCredentialError, ParamValidationError
from deskfleet.runner.events import EventDone
from deskfleet.runner.run import run_ticket

logger = get_logger(__name__)

router = APIRouter(tags=["resolve"])


@router.post("/resolve", response_model=TicketResult)
def resolve_ticket(
    req: ResolveRequest,
    creds: Annotated[Credentials, Depends(require_credentials)],
) -> TicketResult:
    try:
        for event in run_ticket(req, creds):
            if isinstance(event, EventDone):
                return event.result
    except MissingCredentialError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except ParamValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="the run produced no result",
    )
