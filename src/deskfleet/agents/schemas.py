"""The output contract for every node.

Pydantic guards the edges; the TypedDict in `graph.state` carries the state between them.
"""

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError

# StrEnum values double as JSON payloads and Prometheus label values, so they stay lowercase
# and drawn from a closed set.


class Decision(StrEnum):
    RESOLVED = "resolved"
    ESCALATE = "escalate"
    REFUSE = "refuse"


class Category(StrEnum):
    ORDER = "order"
    PRODUCT = "product"
    REFUND = "refund"
    OTHER = "other"


class EscalationReason(StrEnum):
    MAX_ITERS_EXHAUSTED = "max_iters_exhausted"
    NO_FACTS_FOUND = "no_facts_found"
    POLICY_VIOLATION = "policy_violation"
    TOOL_FAILURE = "tool_failure"
    OUT_OF_SCOPE = "out_of_scope"


class RefusalReason(StrEnum):
    INJECTION = "injection"
    OUT_OF_SCOPE = "out_of_scope"


class Fact(BaseModel):
    """Flat and stringly-typed: the Reviewer grounds claims against `value` substrings."""

    source: str
    key: str
    value: str


class ToolCall(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)
    ok: bool
    result_summary: str
    latency_ms: int
    rejected: bool = False


class ClassifierOutput(BaseModel):
    category: Category
    rationale: str


class ResearcherOutput(BaseModel):
    facts: list[Fact] = Field(default_factory=list)
    sufficient: bool
    notes: str = ""


class ResponderOutput(BaseModel):
    draft: str


class ReviewVerdict(BaseModel):
    approved: bool
    grounded: bool
    policy_ok: bool
    score: float = Field(ge=0, le=10)
    reasons: list[str] = Field(default_factory=list)


class NodeOutputError(BaseModel):
    """What a node gets back when the model could not produce a valid instance twice running."""

    error: str
    attempts: int


def validate_node_output[T: BaseModel](
    raw: str,
    model: type[T],
    *,
    retry: Callable[[str], str],
) -> T | NodeOutputError:
    """Validate, and on failure feed the error back to the model once before giving up.

    Never raises into the graph — a malformed response degrades the node, not the run.
    """
    try:
        return model.model_validate_json(raw)
    except ValidationError as first_error:
        repair_prompt = (
            "Your previous response did not match the required schema.\n"
            f"Validation error:\n{first_error}\n"
            "Reply with corrected JSON only."
        )
        try:
            return model.model_validate_json(retry(repair_prompt))
        except ValidationError as second_error:
            return NodeOutputError(error=str(second_error), attempts=2)
        except Exception as exc:
            return NodeOutputError(error=f"retry failed: {exc}", attempts=2)
