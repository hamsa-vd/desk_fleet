"""Server-sent events for /resolve/stream.

A transport adapter and nothing else: `run_ticket` already yields the events, and the `done`
payload is byte-identical to what `POST /resolve` returns. Nothing here may change a run's outcome.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from starlette.concurrency import iterate_in_threadpool

from deskfleet.config import constants, get_logger
from deskfleet.models import Credentials
from deskfleet.runner.events import Event, EventDone, EventError, ResolveRequest
from deskfleet.runner.run import run_ticket

logger = get_logger(__name__)

HEARTBEAT = ": heartbeat\n\n"

MEDIA_TYPE = "text/event-stream"

#: `X-Accel-Buffering` is what stops a proxy holding the whole stream back until the run ends.
HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_EXHAUSTED = object()


def encode(event: Event) -> str:
    # The `done` frame carries the TicketResult itself, so a client reading only the last event
    # gets exactly the JSON contract.
    payload = event.result if isinstance(event, EventDone) else event
    body = payload.model_dump_json(exclude={"type"})
    return f"event: {event.type}\ndata: {body}\n\n"


async def _next(events: AsyncIterator[Event]) -> Any:
    try:
        return await anext(events)
    except StopAsyncIteration:
        return _EXHAUSTED


async def event_stream(
    request: Request,
    req: ResolveRequest,
    creds: Credentials,
    heartbeat_s: float = constants.SSE_HEARTBEAT_S,
) -> AsyncIterator[str]:
    # run_ticket is synchronous; blocking the event loop would stop /health answering, and Cloud
    # Run kills a revision that stops answering.
    events = iterate_in_threadpool(run_ticket(req, creds))
    pending: asyncio.Task | None = None

    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(_next(events))
            try:
                # Shielded: a heartbeat must not cancel the work already in flight.
                event = await asyncio.wait_for(asyncio.shield(pending), heartbeat_s)
            except TimeoutError:
                yield HEARTBEAT
                continue

            pending = None
            if event is _EXHAUSTED:
                break

            yield encode(event)

            if await request.is_disconnected():
                # An abandoned tab would otherwise keep burning tokens to completion.
                logger.info("stream_abandoned", extra={"path": str(request.url.path)})
                break
    except Exception as exc:
        # The 200 was committed with the first byte, so a failure can only be reported in-band.
        logger.error("stream_failed", extra={"cause": type(exc).__name__})
        yield encode(EventError(message="the run could not be completed"))
    finally:
        if pending is not None:
            pending.cancel()
        await events.aclose()
