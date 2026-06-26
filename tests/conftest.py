import json
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
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
        #: Repeated once the script runs out, so a re-entered node keeps behaving the same way.
        self.last = responses[-1] if responses else ""

    @property
    def call_count(self) -> int:
        return len(self.prompts)

    def invoke(self, prompt: Any, **_: Any) -> FakeMessage:
        self.prompts.append(str(prompt))
        if self.responses:
            self.last = self.responses.pop(0)
        return FakeMessage(self.last, self.tokens_in, self.tokens_out)


@pytest.fixture
def classifier_says() -> Callable[..., FakeChatModel]:
    def _factory(
        category: str = "order", rationale: str = "asks about a delivery"
    ) -> FakeChatModel:
        return FakeChatModel(json.dumps({"category": category, "rationale": rationale}))

    return _factory


DEFAULT_DRAFT = "Your order is on its way and the tracking number is in your account."


def responder_says(draft: str = DEFAULT_DRAFT, **kwargs: Any) -> FakeChatModel:
    return FakeChatModel(json.dumps({"draft": draft}), **kwargs)


@pytest.fixture
def repository(monkeypatch: pytest.MonkeyPatch) -> InMemoryRepository:
    """Swap the store module's write functions for the in-memory double."""
    from deskfleet.runner import run as runner_module

    repo = InMemoryRepository()
    monkeypatch.setattr(runner_module, "write_ticket", repo.write_ticket)
    monkeypatch.setattr(runner_module, "write_tool_calls", repo.write_tool_calls)
    return repo


class FakeToolCallingModel(BaseChatModel):
    """A chat model scripted to request specific tool calls, then to answer.

    `bind_tools` is a no-op: the script decides what is requested, which is what makes the
    Researcher's dispatch and rejection paths testable without a provider.
    """

    script: list[list[dict[str, Any]]] = []
    answer: str = "here is what I found"
    always: bool = False
    tokens_in: int = 0
    tokens_out: int = 0

    turns: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "FakeToolCallingModel":
        return self

    def _generate(self, messages: list[Any], stop: Any = None, **kwargs: Any) -> ChatResult:
        turn = self.turns
        self.turns += 1
        if self.always and self.script:
            requested = self.script[turn % len(self.script)]
        else:
            requested = self.script[turn] if turn < len(self.script) else []
        message = AIMessage(
            content="" if requested else self.answer,
            tool_calls=[
                {"name": call["name"], "args": call["args"], "id": f"call-{turn}-{index}"}
                for index, call in enumerate(requested)
            ],
            usage_metadata={
                "input_tokens": self.tokens_in,
                "output_tokens": self.tokens_out,
                "total_tokens": self.tokens_in + self.tokens_out,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def researcher_calling(*turns: list[dict[str, Any]], **kwargs: Any) -> FakeToolCallingModel:
    return FakeToolCallingModel(script=list(turns), **kwargs)


@pytest.fixture
def client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., FakeChatModel]:
    """Make the runner use the given fakes instead of real provider clients.

    Nodes without an explicit fake get a silent default that reports no tokens, so token
    assertions stay exact as nodes are added to the graph.
    """
    from deskfleet.runner import run as runner_module

    def _default(node: str) -> Any:
        if node == "responder":
            return responder_says(tokens_in=0, tokens_out=0)
        return researcher_calling(answer="no tools were needed")

    def _install(model: Any, **per_node: Any) -> Any:
        clients: dict[str, Any] = {"classifier": model, **per_node}

        def build_clients(_req: Any, _creds: Any) -> dict[str, Any]:
            return {node: clients.get(node) or _default(node) for node in runner_module.NODES}

        monkeypatch.setattr(runner_module, "_build_clients", build_clients)
        return model

    return _install
