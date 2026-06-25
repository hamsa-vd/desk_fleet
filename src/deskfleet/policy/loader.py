"""Read policy.md and expose it as prompt text plus a structured rule list.

The policy is trusted text from this repo, not untrusted ticket text — it needs no F-05 hardening.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from deskfleet.config import get_logger

logger = get_logger(__name__)

# policy.md lives at the repo root so a non-engineer can edit it without opening src/.
POLICY_PATH = Path(__file__).resolve().parents[3] / "policy.md"

CATEGORIES: dict[str, str] = {
    "refunds": "refund",
    "delivery": "delivery",
    "compensation": "compensation",
    "disclosure": "disclosure",
    "commitments": "commitments",
    "cancellation": "cancellation",
    "tone": "tone",
    "escalation": "escalation",
}

_HEADING = re.compile(r"^##\s+(.*?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_RULE = re.compile(r"^\*\*(POL-\d{3})\*\*\s+(.+)$")


class PolicyError(RuntimeError):
    """A malformed policy would make the Reviewer quietly permissive. Fail at startup instead."""


@dataclass(frozen=True)
class Rule:
    id: str
    text: str
    category: str


def parse(markdown: str) -> list[Rule]:
    parsed: list[Rule] = []
    seen: dict[str, int] = {}
    category: str | None = None
    in_rule_section = False

    for number, line in enumerate(markdown.splitlines(), start=1):
        heading = _HEADING.match(line)
        if heading:
            category = CATEGORIES.get(heading.group(1).strip().lower())
            in_rule_section = category is not None
            continue

        bullet = _BULLET.match(line)
        if not bullet:
            continue
        if category is None:
            raise PolicyError(f"policy.md line {number}: rule bullet outside any heading: {line!r}")
        if not in_rule_section:
            continue

        rule_match = _RULE.match(bullet.group(1).strip())
        if not rule_match:
            raise PolicyError(f"policy.md line {number}: bullet has no POL-nnn prefix: {line!r}")

        rule_id, text = rule_match.group(1), rule_match.group(2).strip()
        if rule_id in seen:
            raise PolicyError(
                f"policy.md line {number}: duplicate rule id {rule_id} "
                f"(first seen on line {seen[rule_id]})"
            )
        seen[rule_id] = number
        parsed.append(Rule(id=rule_id, text=text, category=category))

    if not parsed:
        raise PolicyError(f"{POLICY_PATH} contains no rules")
    return parsed


@lru_cache(maxsize=1)
def policy_text() -> str:
    try:
        return POLICY_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"could not read {POLICY_PATH}: {exc}") from exc


@lru_cache(maxsize=1)
def rules() -> list[Rule]:
    parsed = parse(policy_text())
    logger.info("policy_loaded", extra={"rules": len(parsed)})
    return parsed


def rule(rule_id: str) -> Rule | None:
    return next((r for r in rules() if r.id == rule_id), None)


def rules_for(category: str) -> list[Rule]:
    return [r for r in rules() if r.category == category]


def reload() -> None:
    policy_text.cache_clear()
    rules.cache_clear()
