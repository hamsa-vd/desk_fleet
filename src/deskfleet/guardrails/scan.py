"""The façade the runner calls. Reports what it found; the decision to refuse is made elsewhere."""

from dataclasses import dataclass, field

from deskfleet.guardrails import injection, pii


@dataclass(frozen=True)
class ScanResult:
    clean_text: str
    injection_detected: bool = False
    matched_patterns: list[str] = field(default_factory=list)
    pii_found: dict[str, int] = field(default_factory=dict)


def scan_input(text: str) -> ScanResult:
    matched = injection.detect(text)
    clean_text, pii_found = pii.redact(text)
    return ScanResult(
        clean_text=clean_text,
        injection_detected=bool(matched),
        matched_patterns=matched,
        pii_found=pii_found,
    )


def scan_output(text: str) -> ScanResult:
    """Output scanning is redaction only — the model's own draft is not an attack vector."""
    clean_text, pii_found = pii.redact(text)
    return ScanResult(clean_text=clean_text, pii_found=pii_found)
