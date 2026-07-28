"""DeskFleet demo UI.

Talks to the service over HTTP only. Every rule about what a decision means lives server-side; this
file arranges what comes back. Layout follows the demo mockup: config and models on the left, the
composer in the middle, the live run on the right, and the outcome underneath.
"""

import os

import streamlit as st

from streamlit_app import model_picker, picker_ui, render, theme
from streamlit_app.client import (
    NODE_LABELS,
    NODES,
    AuthenticationError,
    ServiceConfig,
    StreamUnavailable,
    resolve_ticket,
    stream_ticket,
)
from streamlit_app.examples import EXAMPLES

st.set_page_config(page_title="DeskFleet", page_icon="🎫", layout="wide")

PENDING, ACTIVE, DONE = "pending", "active", "done"


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


def config_panel() -> ServiceConfig:
    """Service credentials and per-node models, in the two-tab card from the mockup."""
    service_tab, models_tab = st.tabs(["Service", "Models"])

    with service_tab:
        st.caption("Where the crew runs, and the key it authenticates with.")
        base_url = st.text_input(
            "Service URL",
            value=os.getenv("API_BASE_URL", "http://localhost:8080"),
            key="base_url",
        )
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

    with models_tab:
        st.caption("Tune cost against quality, node by node.")
        picker_ui.draw_models(ServiceConfig(base_url=base_url, api_key=api_key))

    config = ServiceConfig(base_url=base_url, api_key=api_key, openai_key=openai_key)
    return model_picker.with_credentials(config, picker_ui.state())


def examples() -> None:
    st.markdown(theme.section_label_html("Try one"), unsafe_allow_html=True)
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
    st.session_state.node_state = dict.fromkeys(NODES, (PENDING, "", ""))
    st.session_state.notice = ""
    st.session_state.error = ""


def draw_progress(slot) -> None:
    with slot.container():
        rows = [
            theme.progress_row_html(
                NODE_LABELS[node],
                *st.session_state.node_state.get(node, (PENDING, "")),
            )
            for node in NODES
        ]
        st.markdown("".join(rows), unsafe_allow_html=True)


def draw_tools(slot) -> None:
    rows = st.session_state.tool_rows
    with slot.container():
        st.markdown(theme.section_label_html("Live tool calls", top=22), unsafe_allow_html=True)
        if rows:
            st.markdown("".join(theme.tool_line_html(row) for row in rows), unsafe_allow_html=True)
        else:
            st.caption("No tool calls yet.")


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
                    data = event.data.get("data")
                    summary = render.node_summary(node, data)
                    detail = render.node_detail(node, data)
                    st.session_state.node_state[node] = (marker, summary, detail)
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
    except AuthenticationError as exc:
        st.session_state.error = str(exc)
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
        st.session_state.error = str(exc)


def draw_result() -> None:
    result = st.session_state.result
    if not result:
        return

    st.divider()
    decision = result.get("decision")
    badge = render.badge_for(decision)
    reason = render.explain_reason(result.get("escalation_reason"))
    st.markdown(theme.banner_html(decision, badge.label, reason), unsafe_allow_html=True)

    detail = result.get("escalation_detail")
    if detail and detail != reason:
        st.caption(detail)

    heading, body, approved = render.reply_panel(result)
    st.subheader(heading)
    if body:
        st.markdown(theme.draft_html(body, approved), unsafe_allow_html=True)
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
    right.markdown(
        theme.meta_html(render.cost_line(result), str(result.get("ticket_id", ""))),
        unsafe_allow_html=True,
    )


def main() -> None:
    init_state()
    st.markdown(theme.CSS, unsafe_allow_html=True)
    st.markdown(theme.header_html(), unsafe_allow_html=True)
    st.markdown(theme.intro_html(), unsafe_allow_html=True)

    config_column, composer_column, run_column = st.columns([1.5, 2.0, 1.45], gap="large")

    with config_column, st.container(border=True):
        config = config_panel()

    picker_ui.draw_modal(config)

    with composer_column:
        examples()
        st.text_area("Ticket", key="ticket", height=140, disabled=running())
        order_column, action_column = st.columns([1, 1], vertical_alignment="bottom")
        order_column.text_input("Order ID (optional)", key="order_id", disabled=running())
        # Disabled while in flight so a second click cannot start a duplicate run.
        submit = action_column.button(
            "Resolve",
            type="primary",
            disabled=running() or not st.session_state.ticket.strip(),
        )

    with run_column, st.container(border=True):
        st.markdown(theme.section_label_html("Progress"), unsafe_allow_html=True)
        progress_slot = st.empty()
        tool_slot = st.empty()

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

    draw_result()


main()
