"""Regex detection of system-override and role-hijack phrasing.

Only pattern names are ever reported — the offending text stays out of the logs.
"""

import re

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "ignore_previous": r"\b(?:ignore|forget|bypass)\s+(?:all\s+|any\s+)?"
        r"(?:the\s+|your\s+)?(?:previous|prior|earlier|above)\s+"
        r"(?:instruction|rule|prompt|direction)s?",
        "disregard_above": r"\bdisregard\s+(?:everything\s+)?(?:the\s+)?(?:above|previous|prior)\b",
        "forget_everything": r"\bforget\s+everything\s+(?:you|above|before)\b",
        "role_hijack": r"\byou\s+are\s+now\s+(?:a|an|the|no\s+longer)\b",
        "act_as": r"\b(?:act|behave|respond)\s+as\s+(?:if\s+you\s+are\s+)?"
        r"(?:a|an|the)\s+(?!customer\b)",
        "pretend_to_be": r"\bpretend\s+(?:to\s+be|you\s+are)\b",
        "developer_mode": r"\bdeveloper\s+mode\b",
        "dan_jailbreak": r"\bDAN\b|\bdo\s+anything\s+now\b",
        "system_prompt_probe": r"\bsystem\s+(?:prompt|message|instruction)s?\b",
        "reveal_instructions": r"\b(?:reveal|show|repeat|output|display|tell\s+me)\s+"
        r"(?:me\s+)?(?:your|the)\s+(?:full\s+|original\s+|initial\s+)?"
        r"(?:instruction|prompt|rule|configuration)s?",
        "print_prompt": r"\bprint\s+(?:your|the)\s+prompt\b",
        "new_instructions": r"\b(?:new|updated|revised)\s+instructions\s*:",
        "override_rules": r"\boverride\s+(?:your|the|all)\s+"
        r"(?:rule|restriction|guardrail|safety)s?",
        "jailbreak": r"\bjailbreak\b",
        "unrestricted_mode": r"\b(?:no|without)\s+(?:restrictions|filters|limitations)\b",
    }.items()
}


def detect(text: str) -> list[str]:
    """Return the names of every injection pattern the text matches."""
    return [name for name, pattern in INJECTION_PATTERNS.items() if pattern.search(text)]
