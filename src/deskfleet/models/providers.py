"""The provider registry. All three speak the OpenAI wire shape, so there is one client class."""

from deskfleet.models.schema import ProviderSpec

PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        id="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        settings_key="openai_api_key",
    ),
    "groq": ProviderSpec(
        id="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        settings_key="groq_api_key",
    ),
    "custom": ProviderSpec(
        id="custom",
        label="Custom OpenAI-compatible endpoint",
        base_url=None,
        settings_key=None,
        requires_base_url=True,
    ),
}


class UnknownProviderError(ValueError):
    pass


def list_providers() -> list[ProviderSpec]:
    return list(PROVIDERS.values())


def get_provider(provider_id: str) -> ProviderSpec:
    try:
        return PROVIDERS[provider_id]
    except KeyError:
        raise UnknownProviderError(f"unknown provider {provider_id!r}") from None
