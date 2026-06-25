"""GET /v1/models against a provider. Doubles as the check that a BYOK key is real."""

from deskfleet.config import get_logger
from deskfleet.models.catalogue import catalogue_models, get_model_spec, unknown_model
from deskfleet.models.providers import get_provider
from deskfleet.models.schema import ModelSpec
from deskfleet.tools.http_client import HttpOk, get_json

logger = get_logger(__name__)


class DiscoveryError(RuntimeError):
    pass


class InvalidApiKeyError(DiscoveryError):
    """A 401 is a bad key, which is a different problem from a provider with no models."""


def discover_models(
    provider_id: str,
    api_key: str,
    base_url: str | None = None,
) -> list[ModelSpec]:
    provider = get_provider(provider_id)
    resolved_base_url = base_url or provider.base_url
    if not resolved_base_url:
        raise DiscoveryError(f"provider {provider_id!r} needs a base_url")

    result = get_json(
        f"{resolved_base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if not isinstance(result, HttpOk):
        if result.status in (401, 403):
            raise InvalidApiKeyError(f"the {provider.label} key was rejected")
        raise DiscoveryError(f"could not list {provider.label} models: {result.reason}")

    live_ids = [
        entry["id"]
        for entry in (result.data or {}).get("data", [])
        if isinstance(entry, dict) and entry.get("id")
    ]
    if not live_ids:
        # Some OpenAI-compatible servers do not implement /models at all.
        return catalogue_models(provider_id)

    return [
        get_model_spec(model_id) or unknown_model(model_id, provider_id) for model_id in live_ids
    ]
