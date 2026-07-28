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
        "show_api_key": False,
        "show_openai_key": False,
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
        # Keys stay in session state and use the reference's compact Show/Hide control.
        api_key = st.text_input(
            "Service key",
            type="default" if st.session_state.show_api_key else "password",
            key="api_key",
        )
        st.button(
            "Hide" if st.session_state.show_api_key else "Show",
            key="toggle-api-key",
            width="content",
            on_click=toggle_secret,
            args=("show_api_key",),
        )
        openai_key = st.text_input(
            "Your OpenAI key (optional)",
            type="default" if st.session_state.show_openai_key else "password",
            key="openai_key",
        )
        st.button(
            "Hide" if st.session_state.show_openai_key else "Show",
            key="toggle-openai-key",
            width="content",
            on_click=toggle_secret,
            args=("show_openai_key",),
        )

    with models_tab:
        st.caption("Tune cost against quality, node by node.")
        picker_ui.draw_models(ServiceConfig(base_url=base_url, api_key=api_key))

    config = ServiceConfig(base_url=base_url, api_key=api_key, openai_key=openai_key)
    return model_picker.with_credentials(config, picker_ui.state())


def toggle_secret(state_key: str) -> None:
    st.session_state[state_key] = not st.session_state[state_key]


def examples() -> None:
    st.markdown(
        '<div class="df-composer-label">TRY ONE</div>',
        unsafe_allow_html=True,
    )
    # Pixel widths measured from the supplied reference. The final flexible spacer keeps the pills
    # grouped at the left edge instead of stretching them into three equal, oversized controls.
    reference_widths = ((155.4, 120.7, 129.3), (136.6, 113.5, 140.9))
    content_width = 522
    with st.container(key="df-presets"):
        for row_start in range(0, len(EXAMPLES), 3):
            pill_widths = reference_widths[row_start // 3]
            trailing_space = content_width - sum(pill_widths) - 20
            columns = st.columns(
                [
                    pill_widths[0],
                    10,
                    pill_widths[1],
                    10,
                    pill_widths[2],
                    trailing_space,
                ],
                gap=None,
            )
            for index, (column, example) in enumerate(
                zip(
                    (columns[0], columns[2], columns[4]),
                    EXAMPLES[row_start : row_start + 3],
                    strict=False,
                )
            ):
                selected = (
                    st.session_state.ticket == example.ticket
                    and st.session_state.order_id == (example.order_id or "")
                )
                if column.button(
                    example.label,
                    key=f"preset-{row_start + index}",
                    type="primary" if selected else "secondary",
                    width="stretch",
                    disabled=running(),
                ):
                    st.session_state.ticket = example.ticket
                    st.session_state.order_id = example.order_id or ""
                    st.rerun()


def running() -> bool:
    return bool(st.session_state.running)


def reset_run() -> None:
    st.session_state.result = None
    st.session_state.tool_rows = []
    st.session_state.node_state = dict.fromkeys(NODES, (PENDING, "", ""))
    # The classifier starts immediately, before any event has arrived to say so.
    st.session_state.node_state[NODES[0]] = (ACTIVE, "", "")
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
        st.markdown(theme.divider_html(top=0), unsafe_allow_html=True)
        st.markdown(
            theme.section_label_html("Live tool calls", bottom=12), unsafe_allow_html=True
        )
        if rows:
            st.markdown("".join(theme.tool_line_html(row) for row in rows), unsafe_allow_html=True)
        else:
            st.markdown(theme.quiet_text_html("No tool calls yet."), unsafe_allow_html=True)


def consume(config: ServiceConfig, progress_slot, tool_slot, action_slot) -> None:
    """Drive one run, painting each event as it arrives."""
    ticket = st.session_state.ticket
    order_id = st.session_state.order_id or None
    models = model_picker.models_payload(picker_ui.state())
    saw_done = False
    # A fresh key per update: Streamlit forbids re-using a widget key within one script run, and
    # the button is repainted once per node the loop moves on to, possibly several times per node
    # (the Responder/Reviewer pair can repeat).
    step = 0

    try:
        for event in stream_ticket(config, ticket, order_id, models):
            if event.type == "node":
                node = event.data.get("node", "")
                if node in st.session_state.node_state:
                    # The runner only ever reports a node finishing, never starting, so "next node
                    # is now active" is inferred here rather than driven by its own event.
                    data = event.data.get("data")
                    summary = render.node_summary(node, data)
                    detail = render.node_detail(node, data)
                    st.session_state.node_state[node] = (DONE, summary, detail)

                    upcoming = render.next_node(node, (data or {}).get("decision"))
                    if upcoming:
                        st.session_state.node_state[upcoming] = (ACTIVE, "", "")
                        step += 1
                        action_slot.button(
                            render.node_active_summary(upcoming),
                            key=f"df-running-{step}",
                            type="primary",
                            disabled=True,
                            width="content",
                        )
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

    with st.container(key="df-result"):
        decision = result.get("decision")
        badge = render.badge_for(decision)
        reason = render.explain_reason(result.get("escalation_reason"))
        detail = result.get("escalation_detail")
        heading, body, approved = render.reply_panel(result)
        calls = result.get("tool_calls") or []

        blocks = [theme.banner_html(decision, badge.label, reason)]
        if detail and detail != reason:
            blocks.append(theme.result_caption_html(detail))
        blocks.append(theme.result_heading_html(heading))
        blocks.append(
            theme.draft_html(body, approved)
            if body
            else theme.result_empty_html("The crew declined to answer this ticket.")
        )
        blocks.append(theme.result_heading_html("Tool calls"))
        blocks.append(
            theme.tool_table_html([render.tool_row(call) for call in calls])
            if calls
            else theme.result_empty_html("No tools were called.")
        )
        blocks.append(theme.result_footer_space_html())
        st.markdown(theme.result_stack_html(blocks), unsafe_allow_html=True)

        label, url = render.trace_label(result.get("langsmith_trace_url"))
        left, _, right = st.columns(
            [206, 20, 954], gap=None, vertical_alignment="center"
        )
        if url:
            left.link_button(label, url, width="stretch")
        else:
            left.button(label, disabled=True, width="stretch")
        right.markdown(
            theme.meta_html(render.cost_line(result), str(result.get("ticket_id", ""))),
            unsafe_allow_html=True,
        )


def draw_output(slot) -> None:
    """Render the current run outcome into one replaceable region."""
    with slot.container():
        if st.session_state.notice:
            st.info(st.session_state.notice)
        if st.session_state.error:
            st.error(st.session_state.error)
        draw_result()


def main() -> None:
    init_state()
    st.markdown(theme.CSS, unsafe_allow_html=True)
    st.markdown(theme.header_html(), unsafe_allow_html=True)
    st.markdown(theme.intro_html(), unsafe_allow_html=True)

    page_columns = st.columns([280, 24, 572, 24, 280], gap=None)
    config_column, composer_column, run_column = page_columns[::2]

    with config_column, st.container(border=True):
        config = config_panel()

    picker_ui.draw_modal(config)

    with composer_column, st.container(border=True):
        examples()
        st.text_area("Ticket", key="ticket", height=140, disabled=running())
        order_column, _, action_column = st.columns(
            [404, 12, 106], gap=None, vertical_alignment="bottom"
        )
        order_column.text_input("Order ID (optional)", key="order_id", disabled=running())
        # Disabled while in flight so a second click cannot start a duplicate run.
        action_slot = action_column.empty()
        submit = action_slot.button(
            "Resolve",
            key="df-resolve",
            type="primary",
            disabled=running() or not st.session_state.ticket.strip(),
            width="stretch",
        )
        activity_slot = st.empty()

    with run_column, st.container(border=True, key="df-run-panel"):
        st.markdown(theme.section_label_html("Progress", bottom=16), unsafe_allow_html=True)
        progress_slot = st.empty()
        tool_slot = st.empty()

    # Notices and completed results share one placeholder. Clearing it before the blocking stream
    # starts removes the previous outcome immediately instead of leaving stale content below the
    # cards while the new run is in flight.
    with st.container(key="df-output"):
        output_slot = st.empty()

    if submit:
        reset_run()
        output_slot.empty()
        st.session_state.running = True
        action_slot.button(
            render.node_active_summary(NODES[0]),
            key="df-running",
            type="primary",
            disabled=True,
            width="content",
        )
        draw_progress(progress_slot)
        draw_tools(tool_slot)
        try:
            # The selected redesign uses a fixed three-pixel activity rail so the page remains calm
            # while a cold service or provider is waiting to emit its first streamed event.
            activity_slot.markdown(theme.loading_html(), unsafe_allow_html=True)
            consume(config, progress_slot, tool_slot, action_slot)
        finally:
            st.session_state.running = False
            activity_slot.empty()
        # Repaint the action control and completed result immediately after the stream ends.
        st.rerun()
    else:
        draw_progress(progress_slot)
        draw_tools(tool_slot)

    draw_output(output_slot)


main()
