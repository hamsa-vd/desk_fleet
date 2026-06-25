"""The sandwich defence: rules above, untrusted data inside tags, reminder below."""

import re

RULES_TAG = "rules"
DATA_TAG = "user_query"
REMINDER_TAG = "reminder"

# Stripping the delimiters a user might close early neutralises most syntax injection.
_DELIMITERS = re.compile(
    rf"</?\s*(?:{RULES_TAG}|{DATA_TAG}|{REMINDER_TAG})\s*/?>",
    re.IGNORECASE,
)


def strip_delimiters(untrusted: str) -> str:
    return _DELIMITERS.sub("", untrusted)


def harden(system_rules: str, untrusted: str, reminder: str) -> str:
    return (
        f"<{RULES_TAG}>\n{system_rules}\n</{RULES_TAG}>\n"
        f"<{DATA_TAG}>\n{strip_delimiters(untrusted)}\n</{DATA_TAG}>\n"
        f"<{REMINDER_TAG}>\n{reminder}\n</{REMINDER_TAG}>"
    )
