"""The one retrying HTTP client. Returns a typed result and never raises into its caller."""

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from deskfleet.config import constants, get_logger

logger = get_logger(__name__)

# httpx logs every request at INFO with the full URL, query string included.
logging.getLogger("httpx").setLevel(logging.WARNING)


@dataclass(frozen=True)
class HttpOk:
    data: Any
    status: int


@dataclass(frozen=True)
class HttpErr:
    reason: str
    status: int | None
    attempts: int


HttpResult = HttpOk | HttpErr

_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    """One reused connection pool for the process."""
    global _client
    if _client is None:
        _client = httpx.Client(follow_redirects=True)
    return _client


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _safe_url(url: str) -> str:
    """Query strings can carry caller data; log only the path."""
    return url.split("?", 1)[0]


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _backoff_delay(attempt: int) -> float:
    """Full-jitter exponential backoff; `attempt` is 1-based."""
    ceiling = constants.HTTP_BACKOFF_BASE_S * (constants.HTTP_BACKOFF_FACTOR ** (attempt - 1))
    return random.uniform(ceiling / 2, ceiling)


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_s: float = constants.HTTP_TIMEOUT_S,
    max_attempts: int = constants.HTTP_MAX_ATTEMPTS,
) -> HttpResult:
    client = get_client()
    safe_url = _safe_url(url)
    budget_left = constants.HTTP_BACKOFF_TOTAL_CEILING_S
    last_status: int | None = None
    last_reason = "no attempt was made"

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(url, params=params, headers=headers, timeout=timeout_s)
        except httpx.TimeoutException:
            last_status, last_reason = None, f"{safe_url} timed out after {timeout_s:g}s"
        except httpx.HTTPError as exc:
            last_status = None
            last_reason = f"{safe_url} could not be reached ({type(exc).__name__})"
        else:
            last_status = response.status_code
            if response.is_success:
                try:
                    return HttpOk(data=response.json(), status=response.status_code)
                except (json.JSONDecodeError, ValueError):
                    return HttpErr(
                        reason=f"{safe_url} returned a body that is not valid JSON",
                        status=response.status_code,
                        attempts=attempt,
                    )
            last_reason = f"{safe_url} returned HTTP {response.status_code}"
            if response.status_code not in constants.HTTP_RETRY_STATUS_CODES:
                return HttpErr(reason=last_reason, status=last_status, attempts=attempt)

        if attempt == max_attempts:
            break

        delay = _backoff_delay(attempt)
        if last_status == 429:
            retry_after = _retry_after_seconds(response)
            if retry_after is not None:
                delay = max(delay, retry_after)
        delay = min(delay, budget_left)
        if delay <= 0:
            break
        budget_left -= delay

        logger.warning(
            "http_retry",
            extra={
                "url": safe_url,
                "attempt": attempt,
                "status": last_status,
                "delay_s": round(delay, 3),
            },
        )
        _sleep(delay)

    attempts = min(attempt, max_attempts)
    return HttpErr(
        reason=f"{last_reason} after {attempts} attempt{'s' if attempts != 1 else ''}",
        status=last_status,
        attempts=attempts,
    )
