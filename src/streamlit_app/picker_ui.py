"""The per-node picker widgets. Every decision this draws is made in `model_picker`."""

from typing import Any

import streamlit as st

from streamlit_app import model_picker as picker
from streamlit_app import theme
from streamlit_app.client import NODE_LABELS, NODES, ServiceConfig

STATE_KEY = "picker"


def state() -> picker.PickerState:
    if STATE_KEY not in st.session_state:
        st.session_state[STATE_KEY] = picker.PickerState()
    return st.session_state[STATE_KEY]


def providers(config: ServiceConfig) -> list[dict[str, Any]]:
    """Cached for the session: the registry is fixed per deployment."""
    cache = st.session_state.setdefault("provider_cache", {})
    if config.base_url not in cache:
        try:
            cache[config.base_url] = picker.fetch_providers(config)
        except picker.PickerError as exc:
            st.session_state["provider_error"] = str(exc)
            return []
    st.session_state["provider_error"] = ""
    return cache[config.base_url]


def draw_models(config: ServiceConfig) -> None:
    current = state()
    for node in NODES:
        line = picker.summary_line(node, current.selections.get(node))
        # The reference uses a 230 px row with a 74 px action and no inter-column gap.
        with st.container(key=f"model-row-{node}"):
            left, right = st.columns([156, 74], gap=None, vertical_alignment="center")
            left.markdown(theme.model_row_html(line), unsafe_allow_html=True)
            if right.button(
                "Change",
                key=f"open-{node}",
                help=f"Configure the {NODE_LABELS[node]}",
                width="stretch",
            ):
                picker.open_modal(current, node)
                st.rerun()

    if any(current.selections) and st.button("Reset to server defaults", width="stretch"):
        st.session_state[STATE_KEY] = picker.reset(current)
        st.rerun()


def _dismiss() -> None:
    """Streamlit's own X, Esc and click-outside.

    None of those run the Cancel button's code, so without this the discarded draft outlives the
    dialog — and the next rerun, from any unrelated click, draws the dialog straight back on top
    of whatever the user was actually trying to do.
    """
    picker.cancel(state())


def draw_modal(config: ServiceConfig) -> None:
    current = state()
    if current.draft is None:
        return

    dialog = getattr(st, "dialog", None)
    title = f"{NODE_LABELS[current.draft.node]} model"
    if dialog is None:
        # Older Streamlit: the flow matters more than the chrome.
        with st.expander(title, expanded=True):
            _body(config, current)
        return

    @dialog(title, on_dismiss=_dismiss)
    def show() -> None:
        _body(config, current)

    show()


def _body(config: ServiceConfig, current: picker.PickerState) -> None:
    draft = current.draft
    if draft is None:
        return

    catalogue = providers(config)
    if st.session_state.get("provider_error"):
        st.error(st.session_state["provider_error"])
        return

    labels = {p["id"]: p for p in catalogue}
    _provider_step(current, draft, catalogue)

    if not draft.provider_id:
        return

    spec = labels.get(draft.provider_id, {})
    _credential_step(config, current, draft, spec)

    if draft.error:
        st.error(draft.error)
    if draft.models:
        _model_step(current, draft)
    if draft.model_id:
        _param_step(current, draft)
        _confirm_step(current, draft)

    if st.button("Cancel", key="picker-cancel", width="stretch"):
        picker.cancel(current)
        _close()


def _close() -> None:
    """The sidebar summary lives outside the dialog, so closing needs an app-wide rerun."""
    for key in [k for k in st.session_state if str(k).startswith("picker-")]:
        del st.session_state[key]
    st.rerun(scope="app")


def _provider_step(
    current: picker.PickerState, draft: picker.Draft, catalogue: list[dict[str, Any]]
) -> None:
    ids = [p["id"] for p in catalogue]
    if not ids:
        return
    index = ids.index(draft.provider_id) if draft.provider_id in ids else None
    chosen = st.selectbox(
        "Provider",
        ids,
        index=index,
        format_func=lambda pid: next(p["label"] for p in catalogue if p["id"] == pid),
        placeholder="Choose a provider",
        key="picker-provider",
    )
    if chosen and chosen != draft.provider_id:
        picker.choose_provider(current, chosen)
        st.rerun()


def _credential_step(
    config: ServiceConfig,
    current: picker.PickerState,
    draft: picker.Draft,
    spec: dict[str, Any],
) -> None:
    api_key = st.text_input(
        spec.get("credential_label", "API key"),
        type="password",
        value=draft.api_key,
        key=f"picker-key-{draft.provider_id}",
    )
    base_url = draft.base_url
    if spec.get("requires_base_url"):
        base_url = st.text_input(
            "Base URL",
            value=draft.base_url,
            placeholder="http://localhost:11434/v1",
            key=f"picker-url-{draft.provider_id}",
        )
    picker.set_credential(current, api_key, base_url)

    if not api_key.strip():
        st.caption("Enter a key to list the models this provider offers.")
        return

    cached = picker.cached_models(current, draft.provider_id or "", api_key)
    if cached is not None:
        picker.set_models(current, cached)
        return

    if st.button("List models", key="picker-fetch", width="stretch"):
        try:
            models = picker.fetch_models(
                config,
                draft.provider_id or "",
                api_key,
                spec.get("label", draft.provider_id or ""),
                base_url,
            )
        except picker.PickerError as exc:
            picker.fail(current, str(exc))
        else:
            picker.cache_models(current, draft.provider_id or "", api_key, models)
            picker.set_models(current, models)
        st.rerun()


def _model_step(current: picker.PickerState, draft: picker.Draft) -> None:
    ids = [m["id"] for m in draft.models]
    by_id = {m["id"]: m for m in draft.models}
    index = ids.index(draft.model_id) if draft.model_id in ids else None
    chosen = st.selectbox(
        "Model",
        ids,
        index=index,
        format_func=lambda mid: picker.model_label(by_id[mid]),
        placeholder="Choose a model",
        key="picker-model",
    )
    if chosen and chosen != draft.model_id:
        picker.choose_model(current, chosen)
        st.rerun()


def _param_step(current: picker.PickerState, draft: picker.Draft) -> None:
    controls = picker.param_controls(draft.chosen_model())
    if not controls:
        st.caption(picker.NO_METADATA + " — this model takes no configurable parameters here.")
        return

    st.divider()
    for control in controls:
        key = f"picker-param-{control.name}"
        value = draft.params.get(control.name, control.default)
        if control.kind == "slider":
            value = st.slider(
                control.label,
                float(control.minimum or 0),
                float(control.maximum or 1),
                float(value if value is not None else 0),
                key=key,
                help=control.help,
            )
        elif control.kind == "number":
            value = st.number_input(
                control.label,
                min_value=control.minimum,
                max_value=control.maximum,
                value=value,
                key=key,
                help=control.help,
            )
        elif control.kind == "select":
            options = control.options or []
            index = options.index(value) if value in options else 0
            value = st.selectbox(control.label, options, index=index, key=key, help=control.help)
        elif control.kind == "toggle":
            value = st.toggle(control.label, value=bool(value), key=key, help=control.help)
        else:
            value = st.text_input(control.label, value=str(value or ""), key=key)
        picker.set_param(current, control.name, value)


def _confirm_step(current: picker.PickerState, draft: picker.Draft) -> None:
    st.divider()
    st.caption("Confirm")
    for label, value in picker.confirm_rows(draft):
        st.write(f"**{label}** — {value}")

    if st.button("Apply", type="primary", key="picker-apply", width="stretch"):
        picker.apply(current)
        _close()
