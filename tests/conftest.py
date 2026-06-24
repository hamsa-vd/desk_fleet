from collections.abc import Callable

import pytest

from deskfleet.config import Settings

# Every var the settings object reads, so a stray developer .env or shell export
# cannot change what a unit test sees.
_SETTINGS_ENV_VARS = tuple(Settings.model_fields)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    """Build a Settings with arbitrary overrides, ignoring any .env on disk."""

    def _factory(**overrides: object) -> Settings:
        return Settings(_env_file=None, **overrides)

    return _factory
