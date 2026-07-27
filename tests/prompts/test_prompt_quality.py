from __future__ import annotations

import importlib
import re

PROMPT_MODULES = (
    "deskfleet.agents.classifier",
    "deskfleet.agents.researcher",
    "deskfleet.agents.responder",
    "deskfleet.agents.reviewer",
)

PROMPT_CONSTANTS = ("SYSTEM", "RULES", "REMINDER")

KEY_SHAPES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\blsv2_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
)

BANNED_LITERALS = (
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "LANGCHAIN_API_KEY",
    "DATABASE_URL",
    "GRAFANA_CLOUD_PROM_KEY",
)

MAX_PROMPT_LENGTH = 4_000


def _prompt_texts() -> list[tuple[str, str, str]]:
    collected: list[tuple[str, str, str]] = []
    for module_name in PROMPT_MODULES:
        module = importlib.import_module(module_name)
        for attr_name in PROMPT_CONSTANTS:
            value = getattr(module, attr_name, None)
            if isinstance(value, str):
                collected.append((module_name, attr_name, value))
    return collected


def test_prompt_constants_are_short_enough() -> None:
    offenders = [
        (module_name, attr_name, len(value))
        for module_name, attr_name, value in _prompt_texts()
        if len(value) > MAX_PROMPT_LENGTH
    ]

    assert offenders == []


def test_prompt_constants_do_not_contain_secret_shapes() -> None:
    offenders: list[tuple[str, str, str]] = []
    for module_name, attr_name, value in _prompt_texts():
        for pattern in KEY_SHAPES:
            match = pattern.search(value)
            if match:
                offenders.append((module_name, attr_name, match.group(0)))

    assert offenders == []


def test_prompt_constants_do_not_contain_banned_secret_names() -> None:
    offenders: list[tuple[str, str, str]] = []
    for module_name, attr_name, value in _prompt_texts():
        for token in BANNED_LITERALS:
            if token in value:
                offenders.append((module_name, attr_name, token))

    assert offenders == []
