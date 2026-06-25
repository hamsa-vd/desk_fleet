"""PII redaction. Placeholders keep the meaning so the model still knows something was there."""

import re

from deskfleet.config import constants

_EMAIL = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
# Candidate card runs; every hit is Luhn-checked before it is redacted.
_CARD = re.compile(r"(?<![\w.])(?:\d[ -]?){12,18}\d(?![\w.])")
# At least ten digits, and never mid-word — that is what keeps tracking numbers and order ids out.
_PHONE = re.compile(r"(?<![\w+])\+?\d(?:[\d\s().-]{7,}?)\d(?![\w])")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return the redacted text and a count per PII class."""
    found: dict[str, int] = {}

    def _replace(pattern: re.Pattern[str], placeholder: str, label: str, subject: str) -> str:
        def _sub(match: re.Match[str]) -> str:
            found[label] = found.get(label, 0) + 1
            return placeholder

        return pattern.sub(_sub, subject)

    def _sub_card(match: re.Match[str]) -> str:
        digits = _digits(match.group())
        if not (13 <= len(digits) <= 19 and _luhn_valid(digits)):
            return match.group()
        found["card"] = found.get("card", 0) + 1
        return constants.CARD_PLACEHOLDER

    def _sub_phone(match: re.Match[str]) -> str:
        digits = _digits(match.group())
        if not 10 <= len(digits) <= 15:
            return match.group()
        found["phone"] = found.get("phone", 0) + 1
        return constants.PHONE_PLACEHOLDER

    redacted = _replace(_EMAIL, constants.EMAIL_PLACEHOLDER, "email", text)
    redacted = _replace(_SSN, constants.SSN_PLACEHOLDER, "ssn", redacted)
    redacted = _CARD.sub(_sub_card, redacted)
    redacted = _PHONE.sub(_sub_phone, redacted)
    return redacted, found
