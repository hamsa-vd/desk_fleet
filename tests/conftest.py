import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from prometheus_client import CollectorRegistry

from deskfleet.config import Settings, get_settings
from deskfleet.observability import use_registry
from deskfleet.store import InMemoryRepository

# Every var the settings object reads, so a stray developer .env or shell export
# cannot change what a unit test sees.
_SETTINGS_ENV_VARS = tuple(Settings.model_fields)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name.upper(), raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    """Build a Settings with arbitrary overrides, ignoring any .env on disk."""

    def _factory(**overrides: object) -> Settings:
        return Settings(_env_file=None, **overrides)

    return _factory


@pytest.fixture
def fresh_registry() -> CollectorRegistry:
    """A per-test Prometheus registry so counter values never leak between cases."""
    registry = CollectorRegistry()
    use_registry(registry)
    return registry


class FakeMessage:
    def __init__(self, content: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self.content = content
        self.usage_metadata = {"input_tokens": tokens_in, "output_tokens": tokens_out}


class FakeChatModel:
    """Returns scripted responses and counts calls. The call count is the point in safety tests."""

    def __init__(self, *responses: str, tokens_in: int = 120, tokens_out: int = 30) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out

    @property
    def call_count(self) -> int:
        return len(self.prompts)

    def invoke(self, prompt: Any, **_: Any) -> FakeMessage:
        self.prompts.append(str(prompt))
        content = self.responses.pop(0) if self.responses else self.responses_exhausted()
        return FakeMessage(content, self.tokens_in, self.tokens_out)

    def responses_exhausted(self) -> str:
        return json.dumps({"category": "order", "rationale": "fallback"})


@pytest.fixture
def classifier_says() -> Callable[..., FakeChatModel]:
    def _factory(
        category: str = "order", rationale: str = "asks about a delivery"
    ) -> FakeChatModel:
        return FakeChatModel(json.dumps({"category": category, "rationale": rationale}))

    return _factory


@pytest.fixture
def repository(monkeypatch: pytest.MonkeyPatch) -> InMemoryRepository:
    """Swap the store module's write functions for the in-memory double."""
    from deskfleet.runner import run as runner_module

    repo = InMemoryRepository()
    monkeypatch.setattr(runner_module, "write_ticket", repo.write_ticket)
    return repo


@pytest.fixture
def client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[FakeChatModel], Iterator[None]]:
    """Make the runner build the given fake chat model instead of a real provider client."""
    from deskfleet.runner import run as runner_module

    def _install(model: FakeChatModel) -> FakeChatModel:
        monkeypatch.setattr(runner_module, "build_client", lambda _resolved: model)
        return model

    return _install
