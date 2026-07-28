"""LangSmith setup and per-run trace URL capture. The trace is a graded artifact."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tracers.langchain import LangChainTracer

from deskfleet.config import Settings, get_logger, get_settings

logger = get_logger(__name__)


@dataclass
class RunHandle:
    run_id: str | None = None
    #: The per-run URL. A project URL is near-useless to a reviewer, so None is better than that.
    trace_url: str | None = None
    #: Handed to `graph.stream` as `callbacks`. Empty when tracing is off.
    callbacks: list[Any] = field(default_factory=list)


def setup_tracing(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    try:
        os.environ["LANGCHAIN_TRACING_V2"] = str(settings.langchain_tracing_v2).lower()
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        if settings.langchain_api_key:
            os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key.get_secret_value()
        logger.info(
            "tracing_configured",
            extra={
                "endpoint": settings.langchain_endpoint,
                "project": settings.langchain_project,
                "enabled": settings.langchain_tracing_v2,
                "endpoint_recognised": settings.langchain_endpoint_is_known,
            },
        )
    except Exception as exc:
        logger.error("tracing_setup_failed", extra={"cause": str(exc)})


def _is_enabled(settings: Settings) -> bool:
    return bool(settings.langchain_tracing_v2 and settings.langchain_api_key)


def _capture(handle: RunHandle, callback: object) -> None:
    try:
        latest = getattr(callback, "latest_run", None)
        if latest is not None:
            handle.run_id = str(latest.id)
        handle.trace_url = callback.get_run_url()  # type: ignore[attr-defined]
    except Exception as exc:
        # A US endpoint against an EU workspace fails exactly here, silently and with no traces.
        logger.warning(
            "trace_url_unavailable",
            extra={
                "cause": str(exc),
                "hint": "check LANGCHAIN_ENDPOINT matches your workspace region",
            },
        )


@contextmanager
def traced_run(ticket_id: str) -> Iterator[RunHandle]:
    handle = RunHandle()
    settings = get_settings()
    if not _is_enabled(settings):
        yield handle
        return

    # Deliberately *not* `tracing_v2_enabled()`. That sets a ContextVar on enter and resets its
    # token on exit, and this manager wraps a `yield` inside `run_ticket`, a generator. The SSE
    # transport drives that generator through `iterate_in_threadpool`, which runs every `next()`
    # in a fresh copy of the context — so the token is set in one context and reset in another,
    # and teardown dies with "Token ... was created in a different Context" *after* the run has
    # already produced its result. Passing the tracer as a callback keeps it out of contextvars.
    try:
        tracer = LangChainTracer(
            project_name=settings.langchain_project,
            tags=[f"ticket:{ticket_id}"],
        )
    except Exception as exc:
        logger.warning("tracing_unavailable", extra={"cause": str(exc)})
        yield handle
        return

    handle.callbacks = [tracer]
    try:
        yield handle
    finally:
        _capture(handle, tracer)
