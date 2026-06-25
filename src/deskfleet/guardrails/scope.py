"""The domain-scope pre-filter. Deliberately permissive — the Classifier makes the real call."""

import re

_DOMAIN_TERMS = frozenset(
    {
        "basket",
        "cancel",
        "cancelled",
        "cart",
        "charge",
        "checkout",
        "courier",
        "damaged",
        "deliver",
        "delivered",
        "delivery",
        "dispatch",
        "eta",
        "exchange",
        "faulty",
        "invoice",
        "item",
        "items",
        "order",
        "ordered",
        "package",
        "parcel",
        "payment",
        "postage",
        "price",
        "product",
        "purchase",
        "receipt",
        "refund",
        "refunded",
        "replacement",
        "return",
        "returned",
        "shipment",
        "shipped",
        "shipping",
        "size",
        "stock",
        "tracking",
        "warranty",
    }
)

_OFF_TOPIC = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bwrite\s+(?:me\s+)?(?:a|an|some)\s+(?:poem|song|essay|story|script|joke)",
        r"\b(?:python|javascript|java|sql|rust|c\+\+)\s+(?:code|function|script|program)\b",
        r"\brecipe\s+for\b",
        r"\btranslate\s+(?:this|the\s+following)\b",
        r"\bwho\s+(?:won|is\s+the\s+president|is\s+the\s+prime\s+minister)\b",
        r"\bwhat(?:'s|\s+is)\s+the\s+(?:weather|capital\s+of)\b",
        r"\b(?:medical|legal|investment|tax)\s+advice\b",
        r"\bhomework\b",
        r"\bsolve\s+this\s+equation\b",
    )
)

_WORD = re.compile(r"[a-z']+")


def is_in_scope(text: str) -> bool:
    words = set(_WORD.findall(text.lower()))
    if words & _DOMAIN_TERMS:
        return True
    return not any(pattern.search(text) for pattern in _OFF_TOPIC)
