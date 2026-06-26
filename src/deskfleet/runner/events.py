"""The vocabulary both transports speak: one run's input, its result, and the events in between.

These live here rather than in `api/` because nothing may import `api`. `api/contracts.py`
re-exports `ResolveRequest` and `TicketResult` so the HTTP layer still owns its own naming.
"""

from typing import Literal

from pydantic import BaseModel, Field

from deskfleet.agents.schemas import Category, Decision, ToolCall
from deskfleet.models import ModelSelection


class ResolveRequest(BaseModel):
    ticket: str = Field(min_length=1)
    order_id: str | None = None
    #: Per-node overrides keyed by node name; absent means every node uses its configured default.
    models: dict[str, ModelSelection] | None = None


class TicketResult(BaseModel):
    ticket_id: str
    decision: Decision
    reply: str | None = None
    category: Category | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    #: Carries the terminal reason for both ESCALATE and REFUSE.
    escalation_reason: str | None = None
    escalation_detail: str | None = None
    langsmith_trace_url: str | None = None
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0


class EventNode(BaseModel):
    type: Literal["node"] = "node"
    node: str
    status: Literal["start", "end"]
    data: dict = Field(default_factory=dict)


class EventTool(BaseModel):
    type: Literal["tool"] = "tool"
    name: str
    ok: bool
    latency_ms: int
    rejected: bool = False


class EventDone(BaseModel):
    type: Literal["done"] = "done"
    result: TicketResult


class EventError(BaseModel):
    type: Literal["error"] = "error"
    message: str


Event = EventNode | EventTool | EventDone | EventError
