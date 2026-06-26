"""Read endpoints backing the model-picker modal.

Routing over F-04 and nothing else: no provider is called from here, `catalogue.json` is never
read here, and a caller's key is held only for the duration of the request that carried it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr

from deskfleet.api.auth import require_credentials
from deskfleet.config import get_logger
from deskfleet.models import (
    Credentials,
    DiscoveryError,
    InvalidApiKeyError,
    ModelSpec,
    ProviderSpec,
    UnknownProviderError,
    discover_models,
    get_model_spec,
    list_providers,
)

logger = get_logger(__name__)

router = APIRouter(tags=["models"])

#: `/providers` and `/models/{id}` are fixed for the life of a deployment.
STATIC_CACHE = {"Cache-Control": "public, max-age=3600"}

#: What to call the credential field in the modal, per provider.
CREDENTIAL_LABELS = {
    "openai": "OpenAI API key",
    "groq": "Groq API key",
    "custom": "API key",
}


class ProviderView(BaseModel):
    """`ProviderSpec.settings_key` names a server-side setting and is not the client's business."""

    id: str
    label: str
    base_url: str | None
    credential_label: str
    requires_base_url: bool


class ProvidersResponse(BaseModel):
    providers: list[ProviderView]


class DiscoveryRequest(BaseModel):
    # SecretStr so an accidental log or repr of this body cannot spill the key.
    api_key: SecretStr = Field(min_length=1)
    base_url: str | None = None


class ModelsResponse(BaseModel):
    models: list[ModelSpec]


def _view(spec: ProviderSpec) -> ProviderView:
    return ProviderView(
        id=spec.id,
        label=spec.label,
        base_url=spec.base_url,
        credential_label=CREDENTIAL_LABELS.get(spec.id, "API key"),
        requires_base_url=spec.requires_base_url,
    )


def _error(status_code: int, error: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error, **extra})


@router.get("/providers")
def providers() -> JSONResponse:
    """Open even when `API_KEY` is set: the registry is public information."""
    body = ProvidersResponse(providers=[_view(spec) for spec in list_providers()])
    return JSONResponse(content=body.model_dump(mode="json"), headers=STATIC_CACHE)


@router.post("/providers/{provider_id}/models")
def provider_models(
    provider_id: str,
    body: DiscoveryRequest,
    creds: Annotated[Credentials, Depends(require_credentials)],
) -> JSONResponse:
    """A POST because the key is in the body — a URL lands in access logs and browser history."""
    if provider_id == "custom" and not body.base_url:
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "missing_base_url",
            provider=provider_id,
            field="base_url",
        )

    try:
        found = discover_models(provider_id, body.api_key.get_secret_value(), body.base_url)
    except UnknownProviderError:
        return _error(status.HTTP_404_NOT_FOUND, "unknown_provider", provider=provider_id)
    except InvalidApiKeyError:
        # Logged without the key: knowing which provider rejected it is the whole diagnostic value.
        logger.info("discovery_key_rejected", extra={"provider": provider_id})
        return _error(status.HTTP_401_UNAUTHORIZED, "invalid_key", provider=provider_id)
    except DiscoveryError:
        logger.warning("discovery_unreachable", extra={"provider": provider_id})
        return _error(status.HTTP_502_BAD_GATEWAY, "provider_unreachable", provider=provider_id)

    return JSONResponse(content=ModelsResponse(models=found).model_dump(mode="json"))


@router.get("/models/{model_id}")
def model_detail(model_id: str) -> JSONResponse:
    spec = get_model_spec(model_id)
    if spec is None:
        # Not `unknown_model` — that is for a model a provider actually offers.
        return _error(status.HTTP_404_NOT_FOUND, "unknown_model", model=model_id)
    return JSONResponse(content=spec.model_dump(mode="json"), headers=STATIC_CACHE)
