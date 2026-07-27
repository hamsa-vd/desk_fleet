"""BYOK-or-shared-secret auth (D-11).

The cost vector this protects is spending the *server's* credit. A caller on their own key creates
no exposure, so gating them would only block the self-service demo.
"""

import secrets

from fastapi import HTTPException, Request, status

from deskfleet.config import Settings, get_logger, get_settings
from deskfleet.models import Credentials, credentials_from_settings

logger = get_logger(__name__)

API_KEY_HEADER = "x-api-key"

#: One header per provider. Keys are request-scoped and are never logged or persisted.
BYOK_HEADERS: dict[str, str] = {
    "openai": "x-openai-key",
    "groq": "x-groq-key",
    "custom": "x-custom-key",
}


def _byok_from(request: Request) -> dict[str, str]:
    supplied = {}
    for provider_id, header in BYOK_HEADERS.items():
        value = request.headers.get(header)
        if value and value.strip():
            supplied[provider_id] = value.strip()
    return supplied


def _holds_shared_secret(request: Request, settings: Settings) -> bool:
    if settings.api_key is None:
        return True
    supplied = request.headers.get(API_KEY_HEADER, "")
    return bool(supplied) and secrets.compare_digest(supplied, settings.api_key.get_secret_value())


def require_credentials(request: Request) -> Credentials:
    settings = get_settings()
    byok = _byok_from(request)

    if _holds_shared_secret(request, settings):
        return credentials_from_settings(byok)

    # A BYOK caller bypasses the shared secret, so they get *no* server keys: otherwise a header for
    # a provider they are not using would let the resolver fall back to the server's key for the
    # provider they are. Selecting a provider they did not supply now raises MissingCredentialError.
    if byok:
        return Credentials(byok=byok)

    logger.warning("auth_rejected", extra={"path": request.url.path})
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="a valid X-API-Key header or your own provider key is required",
    )
