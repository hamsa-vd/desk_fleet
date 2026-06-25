from deskfleet.models.catalogue import catalogue_models, get_model_spec
from deskfleet.models.discovery import DiscoveryError, InvalidApiKeyError, discover_models
from deskfleet.models.providers import UnknownProviderError, get_provider, list_providers
from deskfleet.models.resolver import (
    MissingCredentialError,
    ParamValidationError,
    build_client,
    credentials_from_settings,
    resolve,
)
from deskfleet.models.schema import (
    Credentials,
    ModelSelection,
    ModelSpec,
    NodeName,
    ParamSpec,
    ProviderSpec,
    ResolvedModel,
)

__all__ = [
    "Credentials",
    "DiscoveryError",
    "InvalidApiKeyError",
    "MissingCredentialError",
    "ModelSelection",
    "ModelSpec",
    "NodeName",
    "ParamSpec",
    "ParamValidationError",
    "ProviderSpec",
    "ResolvedModel",
    "UnknownProviderError",
    "build_client",
    "catalogue_models",
    "credentials_from_settings",
    "discover_models",
    "get_model_spec",
    "get_provider",
    "list_providers",
    "resolve",
]
