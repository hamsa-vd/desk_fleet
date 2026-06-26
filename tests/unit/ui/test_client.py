import json

import httpx
import pytest

from streamlit_app.client import (
    ServiceConfig,
    StreamUnavailable,
    parse_sse,
    resolve_ticket,
    stream_ticket,
)

RESULT = {
    "ticket_id": "t-1",
    "decision": "resolved",
    "reply": "Your order is on its way.",
    "tool_calls": [],
    "langsmith_trace_url": None,
}


def frames(*blocks: str):
    """Each block is one SSE frame; the extra newline is the blank line that terminates it."""
    return iter("".join(block + "\n" for block in blocks).split("\n"))


def transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- SSE parsing -------------------------------------------------------------------------


def test_a_frame_becomes_a_typed_event() -> None:
    events = list(parse_sse(frames('event: node\ndata: {"node": "classifier"}\n')))

    assert [(e.type, e.data) for e in events] == [("node", {"node": "classifier"})]


def test_the_whole_event_vocabulary_parses() -> None:
    stream = frames(
        'event: node\ndata: {"node": "classifier", "status": "end"}\n',
        'event: tool\ndata: {"name": "get_order_status", "ok": true}\n',
        'event: done\ndata: {"decision": "resolved"}\n',
        'event: error\ndata: {"message": "boom"}\n',
    )

    assert [e.type for e in parse_sse(stream)] == ["node", "tool", "done", "error"]


def test_heartbeat_comments_are_ignored() -> None:
    stream = frames(
        ": heartbeat\n",
        ": heartbeat\n",
        'event: done\ndata: {"decision": "resolved"}\n',
    )

    assert [e.type for e in parse_sse(stream)] == ["done"]


def test_a_malformed_payload_does_not_kill_the_run() -> None:
    stream = frames(
        "event: node\ndata: {not json at all\n",
        'event: done\ndata: {"decision": "resolved"}\n',
    )

    assert [e.type for e in parse_sse(stream)] == ["done"]


def test_a_frame_with_no_data_line_is_skipped() -> None:
    stream = frames("event: node\n", 'event: done\ndata: {"decision": "resolved"}\n')

    assert [e.type for e in parse_sse(stream)] == ["done"]


def test_a_non_object_payload_is_skipped() -> None:
    stream = frames("event: node\ndata: [1, 2, 3]\n", 'event: done\ndata: {"ok": true}\n')

    assert [e.type for e in parse_sse(stream)] == ["done"]


def test_a_multi_line_data_field_is_rejoined() -> None:
    events = list(parse_sse(frames('event: done\ndata: {"reply":\ndata: "hello"}\n')))

    assert events[0].data == {"reply": "hello"}


def test_a_complete_frame_missing_its_terminator_is_still_delivered() -> None:
    """A stream cut short after a full `done` frame should not lose the result."""
    events = list(parse_sse(iter(["event: done", 'data: {"decision": "resolved"}'])))

    assert [(e.type, e.data) for e in events] == [("done", {"decision": "resolved"})]


def test_a_truncated_payload_is_dropped_rather_than_half_parsed() -> None:
    events = list(parse_sse(iter(["event: done", 'data: {"decision": "reso'])))

    assert events == []


# --- the streaming call ------------------------------------------------------------------


def test_streaming_posts_the_ticket_and_yields_its_events() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            text=(
                'event: node\ndata: {"node": "classifier"}\n\n'
                'event: done\ndata: {"decision": "resolved"}\n\n'
            ),
        )

    config = ServiceConfig(base_url="http://svc:8080/")
    with transport(handler) as client:
        events = list(stream_ticket(config, "where is order 1042", "1042", client=client))

    assert str(seen[0].url) == "http://svc:8080/resolve/stream"
    assert json.loads(seen[0].content) == {"ticket": "where is order 1042", "order_id": "1042"}
    assert [e.type for e in events] == ["node", "done"]


def test_resolving_issues_exactly_one_stream_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text='event: done\ndata: {"decision": "resolved"}\n\n')

    with transport(handler) as client:
        list(stream_ticket(ServiceConfig(), "hello", client=client))

    assert len(seen) == 1


def test_an_omitted_order_id_is_not_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="event: done\ndata: {}\n\n")

    with transport(handler) as client:
        list(stream_ticket(ServiceConfig(), "hello", client=client))

    assert json.loads(seen[0].content) == {"ticket": "hello"}


def test_a_non_200_is_a_stream_failure_not_a_silent_empty_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "nope"})

    with transport(handler) as client, pytest.raises(StreamUnavailable, match="401"):
        list(stream_ticket(ServiceConfig(), "hello", client=client))


def test_a_transport_failure_is_a_stream_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with transport(handler) as client, pytest.raises(StreamUnavailable, match="refused"):
        list(stream_ticket(ServiceConfig(), "hello", client=client))


def test_a_stream_that_ends_without_done_yields_what_it_got() -> None:
    """The caller detects the missing `done` and falls back; the client does not guess."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='event: node\ndata: {"node": "classifier"}\n\n')

    with transport(handler) as client:
        events = list(stream_ticket(ServiceConfig(), "hello", client=client))

    assert [e.type for e in events] == ["node"]


# --- the JSON fallback -------------------------------------------------------------------


def test_the_fallback_returns_the_result_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/resolve")
        return httpx.Response(200, json=RESULT)

    with transport(handler) as client:
        assert resolve_ticket(ServiceConfig(), "hello", client=client) == RESULT


def test_a_failing_fallback_raises_rather_than_returning_a_half_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "nope"})

    with transport(handler) as client, pytest.raises(StreamUnavailable):
        resolve_ticket(ServiceConfig(), "hello", client=client)


# --- credentials -------------------------------------------------------------------------


def test_credentials_travel_in_headers_and_never_in_the_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="event: done\ndata: {}\n\n")

    config = ServiceConfig(api_key="shared-secret-123", openai_key="sk-user-abc")
    with transport(handler) as client:
        list(stream_ticket(config, "hello", client=client))

    assert seen[0].headers["x-api-key"] == "shared-secret-123"
    assert seen[0].headers["x-openai-key"] == "sk-user-abc"
    assert "shared-secret-123" not in str(seen[0].url)
    assert "sk-user-abc" not in str(seen[0].url)


def test_blank_credentials_are_not_sent_as_empty_headers() -> None:
    assert ServiceConfig(api_key="  ", openai_key="").headers() == {}


def test_a_trailing_slash_on_the_service_url_does_not_double_up() -> None:
    assert ServiceConfig(base_url="http://svc:8080/").url("/resolve") == "http://svc:8080/resolve"
