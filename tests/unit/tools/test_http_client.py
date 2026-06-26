import itertools
from collections.abc import Callable, Iterable

import httpx
import pytest

from deskfleet.config import constants
from deskfleet.tools import http_client
from deskfleet.tools.http_client import HttpErr, HttpOk


@pytest.fixture(autouse=True)
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record backoff delays instead of waiting them out."""
    recorded: list[float] = []
    monkeypatch.setattr(http_client, "_sleep", recorded.append)
    return recorded


@pytest.fixture
def mount(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[httpx.Request]]:
    """Serve a scripted sequence of responses (or exceptions) and capture the requests."""

    def _mount(responses: Iterable[httpx.Response | Exception]) -> list[httpx.Request]:
        seen: list[httpx.Request] = []
        script = iter(responses)
        last = itertools.repeat(httpx.Response(500))

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            outcome = next(script, next(last))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        client = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(http_client, "get_client", lambda: client)
        return seen

    return _mount


def test_success_returns_parsed_json(mount: Callable[..., list[httpx.Request]]) -> None:
    mount([httpx.Response(200, json={"status": "shipped"})])

    result = http_client.get_json("http://orders.test/orders/1")

    assert result == HttpOk(data={"status": "shipped"}, status=200)


def test_429_then_success_retries_once(
    mount: Callable[..., list[httpx.Request]], slept: list[float]
) -> None:
    mount([httpx.Response(429), httpx.Response(200, json={"ok": True})])

    result = http_client.get_json("http://orders.test/orders/1")

    assert isinstance(result, HttpOk)
    assert len(slept) == 1


def test_exhaustion_on_5xx_returns_error(
    mount: Callable[..., list[httpx.Request]], slept: list[float]
) -> None:
    seen = mount([httpx.Response(500)] * 4)

    result = http_client.get_json("http://orders.test/orders/1")

    assert isinstance(result, HttpErr)
    assert result.attempts == 4
    assert result.status == 500
    assert result.reason
    assert len(seen) == 4
    assert len(slept) == 3


def test_404_is_not_retried(mount: Callable[..., list[httpx.Request]], slept: list[float]) -> None:
    seen = mount([httpx.Response(404)])

    result = http_client.get_json("http://orders.test/orders/999")

    assert isinstance(result, HttpErr)
    assert result.status == 404
    assert result.attempts == 1
    assert len(seen) == 1
    assert slept == []


def test_connection_error_returns_error(mount: Callable[..., list[httpx.Request]]) -> None:
    mount([httpx.ConnectError("refused")] * 4)

    result = http_client.get_json("http://orders.test/orders/1")

    assert isinstance(result, HttpErr)
    assert result.status is None
    assert result.attempts == 4


def test_timeout_returns_error(mount: Callable[..., list[httpx.Request]]) -> None:
    mount([httpx.ReadTimeout("slow")] * 4)

    result = http_client.get_json("http://orders.test/orders/1")

    assert isinstance(result, HttpErr)
    assert "timed out" in result.reason


def test_total_wait_never_exceeds_the_ceiling(
    mount: Callable[..., list[httpx.Request]], slept: list[float]
) -> None:
    mount([httpx.Response(503)] * 20)

    http_client.get_json("http://orders.test/orders/1", max_attempts=12)

    # The budget is decremented in floating point, so the sum can land a rounding step above it.
    assert sum(slept) <= constants.HTTP_BACKOFF_TOTAL_CEILING_S + 1e-9


def test_retry_after_header_is_honoured(
    mount: Callable[..., list[httpx.Request]], slept: list[float]
) -> None:
    mount([httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json={})])

    http_client.get_json("http://orders.test/orders/1")

    assert slept[0] >= 2.0


def test_malformed_json_returns_error(mount: Callable[..., list[httpx.Request]]) -> None:
    mount([httpx.Response(200, text="not json at all")])

    result = http_client.get_json("http://orders.test/orders/1")

    assert isinstance(result, HttpErr)
    assert "not valid JSON" in result.reason


def test_headers_and_query_never_reach_the_log(
    mount: Callable[..., list[httpx.Request]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    mount([httpx.Response(500)] * 4)

    with caplog.at_level("DEBUG"):
        http_client.get_json(
            "http://models.test/v1/models?token=leaky",
            headers={"Authorization": "Bearer sk-abc123def456"},
        )

    emitted = "\n".join(
        f"{r.getMessage()} {r.__dict__}" for r in caplog.records if r.name.startswith("deskfleet.")
    )
    assert "sk-abc123def456" not in emitted
    assert "leaky" not in emitted
