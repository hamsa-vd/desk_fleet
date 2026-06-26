"""Per-node model selection.

Everything the modal needs to decide is a pure function here; `main.py` only draws it. All catalogue
knowledge comes from the service — nothing about a provider or a model is hardcoded in this file.
"""

import hashlib
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from streamlit_app.client import NODES, ServiceConfig

SERVER_DEFAULT = "server default"

NO_METADATA = "metadata unavailable"

FETCH_TIMEOUT_S = 30.0

#: Step names for the modal, in order.
STEPS = ["provider", "credential", "model", "params", "confirm"]


class PickerError(RuntimeError):
    """Carries a message already phrased for the user."""


@dataclass(frozen=True)
class Selection:
    """One node's chosen model. Absent from `state.selections` means the server default."""

    provider_id: str
    model_id: str
    base_url: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"provider_id": self.provider_id, "model_id": self.model_id}
        if self.base_url:
            body["base_url"] = self.base_url
        if self.params:
            body["params"] = dict(self.params)
        return body


@dataclass
class Draft:
    """Work in progress inside one node's modal. Discarded on cancel."""

    node: str
    step: str = "provider"
    provider_id: str | None = None
    base_url: str = ""
    api_key: str = ""
    models: list[dict[str, Any]] = field(default_factory=list)
    model_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def chosen_model(self) -> dict[str, Any] | None:
        return next((m for m in self.models if m.get("id") == self.model_id), None)


@dataclass
class PickerState:
    selections: dict[str, Selection] = field(default_factory=dict)
    #: Keyed by provider so a key entered once serves every node on that provider.
    credentials: dict[str, str] = field(default_factory=dict)
    base_urls: dict[str, str] = field(default_factory=dict)
    #: Keyed by (provider_id, key fingerprint) so stepping back does not re-hit the provider.
    model_cache: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    open_node: str | None = None
    draft: Draft | None = None


# --- credentials -------------------------------------------------------------------------


def fingerprint(api_key: str) -> str:
    """Identifies a key for caching without being reversible to it."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


# --- the reducer -------------------------------------------------------------------------


def open_modal(state: PickerState, node: str) -> PickerState:
    current = state.selections.get(node)
    draft = Draft(node=node)
    if current:
        draft.provider_id = current.provider_id
        draft.base_url = current.base_url or ""
        draft.model_id = current.model_id
        draft.params = dict(current.params)
        draft.step = "credential"
    draft.api_key = state.credentials.get(draft.provider_id or "", "")
    if draft.provider_id:
        draft.base_url = draft.base_url or state.base_urls.get(draft.provider_id, "")
    state.open_node = node
    state.draft = draft
    return state


def choose_provider(state: PickerState, provider_id: str) -> PickerState:
    """Switching provider invalidates the fetched list and the model chosen from it."""
    draft = _require_draft(state)
    if draft.provider_id != provider_id:
        draft.models = []
        draft.model_id = None
        draft.params = {}
    draft.provider_id = provider_id
    draft.api_key = state.credentials.get(provider_id, "")
    draft.base_url = state.base_urls.get(provider_id, "")
    draft.error = ""
    draft.step = "credential"
    return state


def set_credential(state: PickerState, api_key: str, base_url: str = "") -> PickerState:
    """Editing the credential clears the last failure; re-rendering it unchanged must not."""
    draft = _require_draft(state)
    if (api_key, base_url) != (draft.api_key, draft.base_url):
        draft.error = ""
    draft.api_key = api_key
    draft.base_url = base_url
    return state


def set_models(state: PickerState, models: list[dict[str, Any]]) -> PickerState:
    draft = _require_draft(state)
    draft.models = models
    draft.error = ""
    draft.step = "model"
    if draft.model_id and not draft.chosen_model():
        draft.model_id = None
        draft.params = {}
    return state


def fail(state: PickerState, message: str) -> PickerState:
    draft = _require_draft(state)
    draft.models = []
    draft.error = message
    draft.step = "credential"
    return state


def choose_model(state: PickerState, model_id: str) -> PickerState:
    """Seed the parameter form from the spec's defaults, so Apply always sends something valid."""
    draft = _require_draft(state)
    if draft.model_id != model_id:
        draft.params = {}
    draft.model_id = model_id
    spec = draft.chosen_model() or {}
    for param in spec.get("params") or []:
        draft.params.setdefault(param["name"], param.get("default"))
    draft.params = {k: v for k, v in draft.params.items() if v is not None}
    draft.step = "params"
    return state


def set_param(state: PickerState, name: str, value: Any) -> PickerState:
    draft = _require_draft(state)
    draft.params[name] = value
    return state


def go_to(state: PickerState, step: str) -> PickerState:
    _require_draft(state).step = step
    return state


def apply(state: PickerState) -> PickerState:
    draft = _require_draft(state)
    if not draft.provider_id or not draft.model_id:
        raise PickerError("choose a provider and a model first")

    state.selections[draft.node] = Selection(
        provider_id=draft.provider_id,
        model_id=draft.model_id,
        base_url=draft.base_url or None,
        params=dict(draft.params),
    )
    if draft.api_key.strip():
        state.credentials[draft.provider_id] = draft.api_key.strip()
    if draft.base_url.strip():
        state.base_urls[draft.provider_id] = draft.base_url.strip()
    return close_modal(state)


def cancel(state: PickerState) -> PickerState:
    """Discards the draft entirely, so the previous selection is untouched by construction."""
    return close_modal(state)


def close_modal(state: PickerState) -> PickerState:
    state.open_node = None
    state.draft = None
    return state


def reset(state: PickerState) -> PickerState:
    return PickerState()


def _require_draft(state: PickerState) -> Draft:
    if state.draft is None:
        raise PickerError("no modal is open")
    return state.draft


# --- presentation ------------------------------------------------------------------------


@dataclass(frozen=True)
class Control:
    """A widget to draw, described entirely by what the server advertised."""

    name: str
    kind: str  # slider | number | select | toggle | text
    label: str
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    options: list[str] | None = None
    help: str = ""


def param_controls(spec: dict[str, Any] | None) -> list[Control]:
    """Never render a control the server did not advertise — S-07 would reject it anyway."""
    if not spec or not spec.get("metadata_available", True):
        return []

    controls = []
    for param in spec.get("params") or []:
        controls.append(
            Control(
                name=param["name"],
                kind=_kind(param),
                label=param["name"].replace("_", " "),
                default=param.get("default"),
                minimum=param.get("minimum"),
                maximum=param.get("maximum"),
                options=param.get("options"),
                help=param.get("description", ""),
            )
        )
    return controls


def _kind(param: dict[str, Any]) -> str:
    if param.get("options"):
        return "select"
    param_type = param.get("type")
    if param_type == "bool":
        return "toggle"
    if param_type == "string":
        return "text"
    # A bounded number is a slider; an open-ended one has nothing to slide between.
    bounded = param.get("minimum") is not None and param.get("maximum") is not None
    return "slider" if bounded and param_type == "float" else "number"


def model_label(spec: dict[str, Any]) -> str:
    """One line per model in the list: what it costs and what it can do."""
    if not spec.get("metadata_available", True):
        return f"{spec['id']} — {NO_METADATA}"

    parts = []
    if spec.get("context_window"):
        parts.append(f"{spec['context_window'] // 1000}k ctx")
    if spec.get("price_in_per_m") is not None:
        parts.append(f"${spec['price_in_per_m']:.2f}/${spec.get('price_out_per_m', 0):.2f} per M")
    if spec.get("supports_tools"):
        parts.append("tools")
    return f"{spec['id']}" + (f" — {' · '.join(parts)}" if parts else "")


def summary_line(node: str, selection: Selection | None) -> str:
    if selection is None:
        return f"{node.title()} · {SERVER_DEFAULT}"
    parts = [node.title(), selection.model_id, selection.provider_id]
    parts += [f"{name} {value}" for name, value in sorted(selection.params.items())]
    return " · ".join(parts)


def confirm_rows(draft: Draft) -> list[tuple[str, str]]:
    """The confirm screen is the point of the flow — show everything before it is applied."""
    spec = draft.chosen_model() or {}
    rows = [("Provider", draft.provider_id or ""), ("Model", draft.model_id or "")]
    if draft.base_url:
        rows.append(("Base URL", draft.base_url))
    if spec.get("metadata_available", True) and spec.get("price_in_per_m") is not None:
        rows.append(
            (
                "Price per M tokens",
                f"${spec['price_in_per_m']:.2f} in / ${spec.get('price_out_per_m', 0):.2f} out",
            )
        )
    elif not spec.get("metadata_available", True):
        rows.append(("Pricing", NO_METADATA))
    rows += [(name, str(value)) for name, value in sorted(draft.params.items())]
    return rows


ERRORS = {
    "invalid_key": "That key was rejected by {provider}. Check it and try again.",
    "provider_unreachable": "Could not reach {provider}. It may be down or blocked from here.",
    "unknown_provider": "{provider} is not a provider this service knows about.",
    "missing_base_url": "A custom endpoint needs a base URL, for example http://localhost:11434/v1.",
}


def error_message(body: dict[str, Any] | None, provider_label: str) -> str:
    """Distinct causes get distinct messages — they send a user to completely different fixes."""
    code = (body or {}).get("error", "")
    template = ERRORS.get(code, "Could not list models from {provider} ({code}).")
    return template.format(provider=provider_label, code=code or "unknown error")


# --- talking to S-07 ---------------------------------------------------------------------


def fetch_providers(config: ServiceConfig, client: httpx.Client | None = None) -> list[dict]:
    owned = client is None
    http = client or httpx.Client(timeout=FETCH_TIMEOUT_S)
    try:
        response = http.get(config.url("/providers"), headers=config.headers())
        response.raise_for_status()
        return response.json()["providers"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise PickerError(f"Could not load the provider list: {exc}") from exc
    finally:
        if owned:
            http.close()


def fetch_models(
    config: ServiceConfig,
    provider_id: str,
    api_key: str,
    provider_label: str,
    base_url: str = "",
    client: httpx.Client | None = None,
) -> list[dict]:
    owned = client is None
    http = client or httpx.Client(timeout=FETCH_TIMEOUT_S)
    body: dict[str, Any] = {"api_key": api_key}
    if base_url.strip():
        body["base_url"] = base_url.strip()

    try:
        response = http.post(
            config.url(f"/providers/{provider_id}/models"),
            json=body,
            headers={**config.headers(), f"x-{provider_id}-key": api_key},
        )
    except httpx.HTTPError as exc:
        raise PickerError(f"Could not reach the service: {exc}") from exc
    finally:
        if owned:
            http.close()

    if response.status_code != 200:
        try:
            detail = response.json()
        except ValueError:
            detail = None
        raise PickerError(error_message(detail, provider_label))
    try:
        return response.json()["models"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PickerError(
            f"{provider_label} returned a model list this client cannot read."
        ) from exc


def cached_models(state: PickerState, provider_id: str, api_key: str) -> list[dict] | None:
    return state.model_cache.get((provider_id, fingerprint(api_key)))


def cache_models(
    state: PickerState, provider_id: str, api_key: str, models: list[dict]
) -> PickerState:
    state.model_cache[(provider_id, fingerprint(api_key))] = models
    return state


# --- the resolve request -----------------------------------------------------------------


def models_payload(state: PickerState) -> dict[str, dict[str, Any]] | None:
    """`None` when nothing is configured, so the default path sends no `models` key at all."""
    chosen = {node: state.selections[node].payload() for node in NODES if node in state.selections}
    return chosen or None


def with_credentials(config: ServiceConfig, state: PickerState) -> ServiceConfig:
    """Fold picker-entered keys into the request headers without mutating the sidebar config."""
    return replace(config, provider_keys={**config.provider_keys, **state.credentials})
