from collections.abc import Callable

import pytest

from deskfleet.config import Settings, constants, get_settings


def test_defaults_with_empty_environment(settings_factory: Callable[..., Settings]) -> None:
    settings = settings_factory()

    assert settings.openai_api_key is None
    assert settings.api_key is None
    assert settings.langchain_endpoint == "https://aws.api.smith.langchain.com"
    assert settings.langchain_project == "Desk Fleet"
    assert settings.order_api_base_url == "http://localhost:8081"
    assert settings.product_api_base_url == "http://localhost:8081"
    assert settings.max_iters == 3
    assert settings.recursion_limit == 8
    assert settings.token_budget_per_ticket == 20_000
    assert settings.log_level == "INFO"
    assert settings.port == 8080


def test_environment_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_ITERS", "2")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "deskfleet-test")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    settings = Settings(_env_file=None)

    assert settings.max_iters == 2
    assert settings.langchain_project == "deskfleet-test"
    assert settings.log_level == "DEBUG"


def test_port_reads_cloud_run_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9999")

    assert Settings(_env_file=None).port == 9999


def test_secrets_are_masked_in_repr_and_str(settings_factory: Callable[..., Settings]) -> None:
    settings = settings_factory(
        openai_api_key="sk-abc123def456",
        database_url="postgresql://user:hunter2@host/db",
    )

    assert "sk-abc123def456" not in repr(settings)
    assert "sk-abc123def456" not in str(settings)
    assert "hunter2" not in repr(settings)
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-abc123def456"


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("endpoint", "known"),
    [
        ("https://api.smith.langchain.com", True),
        ("https://eu.api.smith.langchain.com", True),
        ("https://api.smith.langchain.com/", True),
        ("https://smith.example.com", False),
    ],
)
def test_langchain_endpoint_recognition(
    settings_factory: Callable[..., Settings], endpoint: str, known: bool
) -> None:
    assert settings_factory(langchain_endpoint=endpoint).langchain_endpoint_is_known is known


def test_constants_match_the_architecture() -> None:
    assert constants.MAX_ITERS == 3
    assert constants.RECURSION_LIMIT == 8
