import json

import pytest
from pydantic import BaseModel, ValidationError

from deskfleet.agents.schemas import (
    Category,
    ClassifierOutput,
    Decision,
    EscalationReason,
    Fact,
    NodeOutputError,
    ResearcherOutput,
    ResponderOutput,
    ReviewVerdict,
    ToolCall,
    validate_node_output,
)


class _Retry:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def test_valid_output_never_retries() -> None:
    retry = _Retry()

    result = validate_node_output(
        '{"category": "order", "rationale": "asks about a delivery"}',
        ClassifierOutput,
        retry=retry,
    )

    assert isinstance(result, ClassifierOutput)
    assert result.category is Category.ORDER
    assert retry.prompts == []


def test_invalid_then_valid_retries_exactly_once() -> None:
    retry = _Retry('{"category": "order", "rationale": "fixed"}')

    result = validate_node_output("{not json", ClassifierOutput, retry=retry)

    assert isinstance(result, ClassifierOutput)
    assert len(retry.prompts) == 1


def test_the_retry_prompt_carries_the_validation_error() -> None:
    retry = _Retry('{"category": "order", "rationale": "fixed"}')

    validate_node_output('{"category": "spaceship"}', ClassifierOutput, retry=retry)

    assert "category" in retry.prompts[0]
    assert "validation error" in retry.prompts[0].lower()


def test_invalid_twice_returns_a_structured_failure() -> None:
    retry = _Retry("still not json")

    result = validate_node_output("{not json", ClassifierOutput, retry=retry)

    assert isinstance(result, NodeOutputError)
    assert result.attempts == 2
    assert result.error


def test_a_raising_retry_is_swallowed() -> None:
    def boom(_: str) -> str:
        raise RuntimeError("provider is down")

    result = validate_node_output("{not json", ClassifierOutput, retry=boom)

    assert isinstance(result, NodeOutputError)
    assert "provider is down" in result.error


@pytest.mark.parametrize("enum", [Decision, Category, EscalationReason])
def test_enum_values_are_prometheus_safe(enum: type) -> None:
    for member in enum:
        assert member.value == member.value.lower()
        assert member.value.replace("_", "").isalnum()
        assert json.dumps({"label": member}) == f'{{"label": "{member.value}"}}'


def test_review_score_is_bounded() -> None:
    with pytest.raises(ValidationError):
        ReviewVerdict(approved=True, grounded=True, policy_ok=True, score=11, reasons=[])

    assert ReviewVerdict(approved=True, grounded=True, policy_ok=True, score=10).score == 10


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ClassifierOutput, {"category": "order"}),
        (ResearcherOutput, {"facts": [{"source": "get_order_status"}]}),
        (ResponderOutput, {}),
        (ToolCall, {"name": "get_order_status", "ok": True}),
    ],
)
def test_incomplete_node_output_is_rejected(model: type[BaseModel], payload: dict) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_fact_stays_flat_and_stringly_typed() -> None:
    fact = Fact(source="get_order_status", key="order.status", value="shipped")

    assert fact.model_dump() == {
        "source": "get_order_status",
        "key": "order.status",
        "value": "shipped",
    }
