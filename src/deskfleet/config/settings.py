"""Typed environment parsing. Built once at startup; nothing else calls os.getenv."""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from deskfleet.config.constants import KNOWN_LANGCHAIN_ENDPOINTS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM providers
    openai_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None

    # API access — shared secret; None means the server key is unguarded (dev only).
    api_key: SecretStr | None = None

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_endpoint: str = "https://api.smith.langchain.com"
    langchain_api_key: SecretStr | None = None
    langchain_project: str = "deskfleet"

    # Upstream data APIs
    order_api_base_url: str = "http://localhost:8081"
    product_api_base_url: str = "http://localhost:8081"

    # Storage
    database_url: SecretStr | None = None

    # Metrics push (deployed only)
    grafana_cloud_prom_url: str | None = None
    grafana_cloud_prom_user: str | None = None
    grafana_cloud_prom_key: SecretStr | None = None

    # Behaviour
    max_iters: int = Field(default=3, ge=1, le=10)
    recursion_limit: int = Field(default=8, ge=2, le=50)
    token_budget_per_ticket: int = Field(default=20_000, ge=1)
    log_level: str = "INFO"

    # Cloud Run injects $PORT; binding a hardcoded port is the classic deploy failure.
    port: int = 8080

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def langchain_endpoint_is_known(self) -> bool:
        return self.langchain_endpoint.rstrip("/") in KNOWN_LANGCHAIN_ENDPOINTS


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
