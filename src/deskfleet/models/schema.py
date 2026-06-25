"""Metadata shapes for providers, models and a resolved per-node selection."""

from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, model_validator

NodeName = Literal["classifier", "researcher", "responder", "reviewer"]


class ParamSpec(BaseModel):
    """One tunable parameter. The list of these is the allowlist for a model's params."""

    name: str
    type: Literal["float", "int", "string", "bool"]
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    options: list[str] | None = None
    description: str = ""


class ProviderSpec(BaseModel):
    id: str
    label: str
    base_url: str | None = None
    #: Which settings field holds this provider's server-side key.
    settings_key: str | None = None
    requires_base_url: bool = False


class ModelSpec(BaseModel):
    id: str
    provider_id: str
    context_window: int | None = None
    #: USD per one million tokens.
    price_in_per_m: float | None = None
    price_out_per_m: float | None = None
    supports_tools: bool | None = None
    params: list[ParamSpec] = Field(default_factory=list)
    #: False means the model came back from live discovery but is absent from catalogue.json.
    metadata_available: bool = True


class ModelSelection(BaseModel):
    provider_id: str
    model_id: str
    base_url: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _custom_requires_base_url(self) -> "ModelSelection":
        if self.provider_id == "custom" and not self.base_url:
            raise ValueError("provider_id 'custom' requires a base_url")
        return self


class ResolvedModel(BaseModel):
    spec: ModelSpec
    base_url: str
    api_key: SecretStr
    params: dict[str, Any] = Field(default_factory=dict)


class Credentials(BaseModel):
    """Keys for one request. BYOK keys live here and nowhere else, for the request's lifetime."""

    byok: dict[str, SecretStr] = Field(default_factory=dict)
    server: dict[str, SecretStr] = Field(default_factory=dict)
