"""Pure presentation decisions, kept out of `main.py` so they can be tested without Streamlit."""

from dataclasses import dataclass
from typing import Any

REASON_LABELS = {
    "no_facts_found": "the researcher found nothing to ground a reply on",
    "low_confidence": "the reviewer could not approve a draft",
    "max_iters_exhausted": "the review loop ran out of attempts",
    "policy_violation": "the draft could not be brought within policy",
    "tool_failure": "a required upstream call failed",
    "refund_over_limit": "the refund exceeds what the policy allows without a human",
    "injection_detected": "the ticket tried to override the agent's instructions",
    "out_of_scope": "the ticket is outside what this service handles",
}

TRACING_DISABLED = "tracing disabled"


@dataclass(frozen=True)
class Badge:
    label: str
    icon: str
    tone: str  # maps to st.success / st.error / st.warning


BADGES = {
    "resolved": Badge("RESOLVED", "✅", "success"),
    "escalate": Badge("ESCALATE", "⚠️", "warning"),
    "refuse": Badge("REFUSE", "🚫", "error"),
}

UNKNOWN_BADGE = Badge("UNKNOWN", "❔", "warning")


def badge_for(decision: str | None) -> Badge:
    return BADGES.get((decision or "").lower(), UNKNOWN_BADGE)


def explain_reason(reason: str | None) -> str:
    if not reason:
        return ""
    return REASON_LABELS.get(reason, reason.replace("_", " "))


def node_summary(node: str, data: dict[str, Any] | None) -> str:
    """One line per node, in the vocabulary a reviewer watching the demo already has."""
    data = data or {}
    if node == "classifier":
        parts = [str(data[k]) for k in ("category", "intent") if data.get(k)]
        if data.get("injection_detected"):
            parts.append("injection detected")
        return " · ".join(parts)
    if node == "researcher":
        facts = data.get("facts")
        count = len(facts) if isinstance(facts, list) else 0
        return f"{count} fact{'' if count == 1 else 's'} gathered"
    if node == "responder":
        iterations = data.get("iterations")
        return f"draft {iterations}" if iterations else "draft written"
    if node == "reviewer":
        if data.get("decision"):
            return f"decision: {data['decision']}"
        notes = data.get("review_notes")
        if isinstance(notes, list) and notes:
            return f"rewrite requested — {notes[-1]}"
        return "reviewed"
    return ""


def tool_row(event: dict[str, Any]) -> dict[str, Any]:
    """A rejected off-allowlist call is the most persuasive row in the table — never hide it."""
    rejected = bool(event.get("rejected"))
    ok = bool(event.get("ok"))
    if rejected:
        status = "🛑 blocked"
    elif ok:
        status = "✅ ok"
    else:
        status = "❌ failed"

    # Live `tool` events carry no summary; the result's tool_calls do. One shape, both sources.
    return {
        "Tool": event.get("name", ""),
        "Status": status,
        "Latency": f"{event.get('latency_ms', 0)} ms",
        "Arguments": ", ".join(f"{k}={v}" for k, v in (event.get("args") or {}).items()),
        "Detail": event.get("result_summary") or "",
    }


def trace_label(url: str | None) -> tuple[str, str | None]:
    """`(label, url)`. A null URL must read as a deliberate state, not a broken link."""
    if not url:
        return TRACING_DISABLED, None
    return "Open the LangSmith trace", url


def cost_line(result: dict[str, Any]) -> str:
    tokens_in = result.get("tokens_in") or 0
    tokens_out = result.get("tokens_out") or 0
    parts = [f"{tokens_in + tokens_out:,} tokens ({tokens_in:,} in / {tokens_out:,} out)"]
    parts.append(f"${result.get('usd') or 0.0:.4f}")
    parts.append(f"{(result.get('latency_ms') or 0) / 1000:.1f}s")
    return " · ".join(parts)


def reply_panel(result: dict[str, Any]) -> tuple[str, str, bool]:
    """`(heading, body, approved)`.

    An escalated run still has a draft, and showing it is useful — but a reviewer must never mistake
    an unapproved draft for something the crew was willing to send.
    """
    decision = (result.get("decision") or "").lower()
    if decision == "refuse":
        return "No reply", "", False
    if decision == "escalate":
        draft = result.get("best_draft") or result.get("reply") or ""
        return "Best draft (unapproved — not sent)", draft, False
    return "Reply", result.get("reply") or "", True
