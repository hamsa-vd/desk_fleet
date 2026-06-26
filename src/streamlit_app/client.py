"""HTTP access to the DeskFleet service.

Deliberately imports nothing from `deskfleet`: the demo client talks to the service over the wire
only, so nothing here can drift into being business logic the graded service depends on.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

STREAM_TIMEOUT_S = 180.0

JSON_TIMEOUT_S = 180.0

#: Node order as the graph runs them, so the progress panel can show pending nodes up front.
NODES = ["classifier", "researcher", "responder", "reviewer"]

NODE_LABELS = {
    "classifier": "Classifier",
    "researcher": "Researcher",
    "responder": "Responder",
    "reviewer": "Reviewer",
}


class StreamUnavailable(RuntimeError):
    """The live view failed. The caller falls back to POST /resolve rather than showing nothing."""


@dataclass
class ServiceConfig:
    base_url: str = "http://localhost:8080"
    api_key: str = ""
    openai_key: str = ""
    #: Keys entered in the model picker, by provider id. One header per provider, per S-01.
    provider_keys: dict[str, str] = field(default_factory=dict)

    def headers(self) -> dict[str, str]:
        supplied = {"x-api-key": self.api_key, "x-openai-key": self.openai_key}
        for provider_id, key in self.provider_keys.items():
            supplied[f"x-{provider_id}-key"] = key
        return {name: value.strip() for name, value in supplied.items() if value.strip()}

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"


@dataclass
class StreamEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


def parse_sse(lines: Iterator[str]) -> Iterator[StreamEvent]:
    """Frames are `event:`/`data:` pairs separated by a blank line.

    Anything else — a heartbeat comment, a stray field, an unparsable payload — is skipped rather
    than raised: one malformed frame must not kill a run that is otherwise progressing.
    """
    event_type: str | None = None
    payload: str | None = None

    def dispatch(event_type: str | None, payload: str | None) -> StreamEvent | None:
        if not event_type or payload is None:
            return None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return StreamEvent(type=event_type, data=data) if isinstance(data, dict) else None

    for raw in lines:
        line = raw.rstrip("\r\n")

        if not line:
            event = dispatch(event_type, payload)
            if event:
                yield event
            event_type, payload = None, None
            continue

        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_type = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            chunk = line.removeprefix("data:").strip()
            payload = chunk if payload is None else f"{payload}\n{chunk}"

    # A stream cut off before its terminating blank line still carried a complete frame often
    # enough to matter; unparsable remnants are dropped by `dispatch` anyway.
    trailing = dispatch(event_type, payload)
    if trailing:
        yield trailing


def _body(ticket: str, order_id: str | None, models: dict[str, Any] | None) -> dict[str, Any]:
    body: dict[str, Any] = {"ticket": ticket}
    if order_id:
        body["order_id"] = order_id
    if models:
        body["models"] = models
    return body


def stream_ticket(
    config: ServiceConfig,
    ticket: str,
    order_id: str | None = None,
    models: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> Iterator[StreamEvent]:
    """Yield events as the crew works. Raises `StreamUnavailable` if the transport itself fails."""
    body = _body(ticket, order_id, models)

    owned = client is None
    http = client or httpx.Client(timeout=STREAM_TIMEOUT_S)
    try:
        with http.stream(
            "POST", config.url("/resolve/stream"), json=body, headers=config.headers()
        ) as response:
            if response.status_code != 200:
                response.read()
                raise StreamUnavailable(f"the service answered {response.status_code}")
            yield from parse_sse(response.iter_lines())
    except httpx.HTTPError as exc:
        raise StreamUnavailable(str(exc)) from exc
    finally:
        if owned:
            http.close()


def resolve_ticket(
    config: ServiceConfig,
    ticket: str,
    order_id: str | None = None,
    models: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """The non-streaming fallback. Same run, same result, no progress."""
    body = _body(ticket, order_id, models)

    owned = client is None
    http = client or httpx.Client(timeout=JSON_TIMEOUT_S)
    try:
        response = http.post(config.url("/resolve"), json=body, headers=config.headers())
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise StreamUnavailable(str(exc)) from exc
    finally:
        if owned:
            http.close()
