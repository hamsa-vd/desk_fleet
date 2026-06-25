"""Turn a per-node model request into a concrete client config, then into a client."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from deskfleet.config import constants, get_settings
from deskfleet.models.catalogue import get_model_spec, unknown_model
from deskfleet.models.providers import get_provider
from deskfleet.models.schema import (
    Credentials,
    ModelSelection,
    NodeName,
    ResolvedModel,
)

#: Per-node defaults. The Reviewer only returns a verdict, so its output is capped (D-10).
NODE_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "classifier": {"temperature": 0.0},
    "researcher": {"temperature": 0.0},
    "responder": {"temperature": 0.3},
    "reviewer": {"temperature": 0.0, "max_tokens": constants.REVIEWER_MAX_OUTPUT_TOKENS},
}


class MissingCredentialError(RuntimeError):
    """No key for the selected provider. Never silently fall back to a different provider's key."""


class ParamValidationError(ValueError):
    """A parameter the selected model does not accept."""


def credentials_from_settings(byok: dict[str, str] | None = None) -> Credentials:
    settings = get_settings()
    server: dict[str, str] = {}
    for provider_id in ("openai", "groq"):
        key = getattr(settings, f"{provider_id}_api_key", None)
        if key is not None:
            server[provider_id] = key.get_secret_value()
    return Credentials(byok=byok or {}, server=server)


def _key_for(provider_id: str, keys: Credentials) -> str:
    for source in (keys.byok, keys.server):
        secret = source.get(provider_id)
        if secret and secret.get_secret_value():
            return secret.get_secret_value()
    raise MissingCredentialError(f"no API key available for provider {provider_id!r}")


def _validated_params(spec_param_names: set[str], params: dict[str, Any]) -> dict[str, Any]:
    unsupported = sorted(set(params) - spec_param_names)
    if unsupported:
        raise ParamValidationError(f"unsupported parameters: {', '.join(unsupported)}")
    return dict(params)


def resolve(
    node: NodeName,
    selection: ModelSelection | None,
    keys: Credentials,
) -> ResolvedModel:
    selection = selection or ModelSelection(
        provider_id=constants.DEFAULT_PROVIDER_ID,
        model_id=constants.DEFAULT_MODEL_ID,
    )
    provider = get_provider(selection.provider_id)
    base_url = selection.base_url or provider.base_url
    if not base_url:
        raise ParamValidationError(f"provider {provider.id!r} requires a base_url")

    spec = get_model_spec(selection.model_id) or unknown_model(selection.model_id, provider.id)
    allowed = {p.name for p in spec.params}
    params = {**NODE_DEFAULT_PARAMS[node], **_validated_params(allowed, selection.params)}

    return ResolvedModel(
        spec=spec,
        base_url=base_url,
        api_key=_key_for(provider.id, keys),
        params=params,
    )


def build_client(resolved: ResolvedModel) -> BaseChatModel:
    params = {k: v for k, v in resolved.params.items() if v is not None}
    return ChatOpenAI(
        model=resolved.spec.id,
        base_url=resolved.base_url,
        api_key=resolved.api_key,
        timeout=constants.LLM_TIMEOUT_S,
        **params,
    )
