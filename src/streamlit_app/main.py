"""DeskFleet demo UI.

Talks to the service over HTTP only. Every rule about what a decision means lives server-side; this
file arranges what comes back.
"""

import streamlit as st

from streamlit_app import model_picker, picker_ui, render
from streamlit_app.client import (
    NODE_LABELS,
    NODES,
    ServiceConfig,
    StreamUnavailable,
    resolve_ticket,
    stream_ticket,
)
from streamlit_app.examples import EXAMPLES

st.set_page_config(page_title="DeskFleet", page_icon="🎫", layout="wide")

PENDING, ACTIVE, DONE = "⚪", "🔵", "🟢"


def init_state() -> None:
    defaults = {
        "ticket": "",
        "order_id": "",
        "result": None,
        "tool_rows": [],
        "node_state": {},
        "running": False,
        "notice": "",
        "error": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def sidebar() -> ServiceConfig:
    with st.sidebar:
        st.subheader("Service")
        base_url = st.text_input("Service URL", value="http://localhost:8080", key="base_url")
        # type="password" keeps the key off the screen after entry; it never leaves session state.
        api_key = st.text_input(
            "Service key", type="password", key="api_key", help="Sent as X-API-Key."
        )
        openai_key = st.text_input(
            "Your OpenAI key (optional)",
            type="password",
            key="openai_key",
            help="Bring your own key and the service runs the crew on it instead.",
        )

        st.divider()
        picker_ui.draw_sidebar(ServiceConfig(base_url=base_url, api_key=api_key))

    config = ServiceConfig(base_url=base_url, api_key=api_key, openai_key=openai_key)
    return model_picker.with_credentials(config, picker_ui.state())


def examples() -> None:
    st.caption("Try one:")
    for row_start in range(0, len(EXAMPLES), 3):
        for column, example in zip(
            st.columns(3), EXAMPLES[row_start : row_start + 3], strict=False
        ):
            if column.button(example.label, width="stretch", disabled=running()):
                st.session_state.ticket = example.ticket
                st.session_state.order_id = example.order_id or ""
                st.rerun()


def running() -> bool:
    return bool(st.session_state.running)


def reset_run() -> None:
    st.session_state.result = None
    st.session_state.tool_rows = []
    st.session_state.node_state = dict.fromkeys(NODES, (PENDING, ""))
    st.session_state.notice = ""
    st.session_state.error = ""


def draw_progress(slot) -> None:
    with slot.container():
        for node in NODES:
            marker, summary = st.session_state.node_state.get(node, (PENDING, ""))
            st.write(f"{marker} **{NODE_LABELS[node]}** {summary and '— ' + summary}")


def draw_tools(slot) -> None:
    rows = st.session_state.tool_rows
    if rows:
        slot.dataframe(rows, width="stretch", hide_index=True)
    else:
        slot.caption("No tool calls yet.")


def consume(config: ServiceConfig, progress_slot, tool_slot) -> None:
    """Drive one run, painting each event as it arrives."""
    ticket = st.session_state.ticket
    order_id = st.session_state.order_id or None
    models = model_picker.models_payload(picker_ui.state())
    saw_done = False

    try:
        for event in stream_ticket(config, ticket, order_id, models):
            if event.type == "node":
                node = event.data.get("node", "")
                if node in st.session_state.node_state:
                    marker = ACTIVE if event.data.get("status") == "start" else DONE
                    summary = render.node_summary(node, event.data.get("data"))
                    st.session_state.node_state[node] = (marker, summary)
                    draw_progress(progress_slot)
            elif event.type == "tool":
                st.session_state.tool_rows.append(render.tool_row(event.data))
                draw_tools(tool_slot)
            elif event.type == "done":
                st.session_state.result = event.data
                saw_done = True
            elif event.type == "error":
                st.session_state.error = event.data.get("message", "the run failed")
                return
    except StreamUnavailable as exc:
        st.session_state.notice = f"Live view unavailable ({exc}). Falling back."

    if saw_done:
        return

    # A proxy that buffers the stream would otherwise leave the demo showing nothing at all.
    st.session_state.notice = (
        st.session_state.notice or "The stream ended without a result. Falling back."
    )
    try:
        st.session_state.result = resolve_ticket(config, ticket, order_id, models)
    except StreamUnavailable as exc:
        st.session_state.error = f"The service could not be reached: {exc}"


def draw_result() -> None:
    result = st.session_state.result
    if not result:
        return

    badge = render.badge_for(result.get("decision"))
    reason = render.explain_reason(result.get("escalation_reason"))
    headline = f"{badge.icon} **{badge.label}**" + (f" — {reason}" if reason else "")
    getattr(st, badge.tone)(headline)

    detail = result.get("escalation_detail")
    if detail and detail != reason:
        st.caption(detail)

    heading, body, approved = render.reply_panel(result)
    st.subheader(heading)
    if body:
        (st.success if approved else st.warning)(body)
    else:
        st.caption("The crew declined to answer this ticket.")

    st.subheader("Tool calls")
    calls = result.get("tool_calls") or []
    if calls:
        st.dataframe(
            [render.tool_row(call) for call in calls],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No tools were called.")

    label, url = render.trace_label(result.get("langsmith_trace_url"))
    left, right = st.columns([1, 3])
    if url:
        left.link_button(label, url, width="stretch")
    else:
        left.button(label, disabled=True, width="stretch")
    right.caption(render.cost_line(result))
    right.caption(f"Ticket `{result.get('ticket_id', '')}`")


def main() -> None:
    init_state()
    config = sidebar()

    st.title("🎫 DeskFleet")
    st.caption("Classifier → Researcher → Responder → Reviewer")

    picker_ui.draw_modal(config)

    examples()
    st.text_area("Ticket", key="ticket", height=140, disabled=running())
    st.text_input("Order ID (optional)", key="order_id", disabled=running())

    # Disabled while in flight so a second click cannot start a duplicate run.
    submit = st.button(
        "Resolve", type="primary", disabled=running() or not st.session_state.ticket.strip()
    )

    st.divider()
    left, right = st.columns([1, 2])
    left.subheader("Progress")
    progress_slot = left.empty()
    right.subheader("Live tool calls")
    tool_slot = right.empty()

    if submit:
        reset_run()
        st.session_state.running = True
        draw_progress(progress_slot)
        draw_tools(tool_slot)
        try:
            consume(config, progress_slot, tool_slot)
        finally:
            st.session_state.running = False
    else:
        draw_progress(progress_slot)
        draw_tools(tool_slot)

    if st.session_state.notice:
        st.info(st.session_state.notice)
    if st.session_state.error:
        st.error(st.session_state.error)

    st.divider()
    draw_result()


main()
