import re
from pathlib import Path

import pytest

from deskfleet.policy import PolicyError, Rule, loader, policy_text, reload, rule, rules, rules_for

VALID = """# Policy

## Refunds

- **POL-001** Refunds within 30 days.

## Tone

- **POL-060** Be plain and warm.
"""

DUPLICATE_ID = """# Policy

## Refunds

- **POL-001** Refunds within 30 days.
- **POL-001** Refunds within 90 days.
"""

UNPREFIXED_BULLET = """# Policy

## Refunds

- Refunds are fine whenever, honestly.
"""

RULE_WITHOUT_HEADING = """# Policy

- **POL-001** Refunds within 30 days.
"""


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    reload()
    yield
    reload()


@pytest.fixture
def policy_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def _write(markdown: str) -> Path:
        path = tmp_path / "policy.md"
        path.write_text(markdown, encoding="utf-8")
        monkeypatch.setattr(loader, "POLICY_PATH", path)
        reload()
        return path

    return _write


def test_valid_policy_parses_into_rules(policy_file) -> None:
    policy_file(VALID)

    assert rules() == [
        Rule(id="POL-001", text="Refunds within 30 days.", category="refund"),
        Rule(id="POL-060", text="Be plain and warm.", category="tone"),
    ]


def test_duplicate_id_fails_and_names_the_id(policy_file) -> None:
    policy_file(DUPLICATE_ID)

    with pytest.raises(PolicyError, match="duplicate rule id POL-001"):
        rules()


def test_unprefixed_bullet_fails_and_names_the_line(policy_file) -> None:
    policy_file(UNPREFIXED_BULLET)

    with pytest.raises(PolicyError, match="Refunds are fine whenever"):
        rules()


def test_rule_outside_any_heading_fails(policy_file) -> None:
    policy_file(RULE_WITHOUT_HEADING)

    with pytest.raises(PolicyError, match="outside any heading"):
        rules()


def test_empty_policy_fails(policy_file) -> None:
    policy_file("# Policy\n\nNothing here yet.\n")

    with pytest.raises(PolicyError, match="no rules"):
        rules()


def test_unreadable_policy_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(loader, "POLICY_PATH", tmp_path / "missing.md")
    reload()

    with pytest.raises(PolicyError, match="could not read"):
        policy_text()


def test_the_file_is_read_once_per_process(
    policy_file, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = policy_file(VALID)
    reads: list[Path] = []
    original = Path.read_text

    def counting_read(self: Path, *args: object, **kwargs: object) -> str:
        reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read)

    policy_text()
    policy_text()
    rules()
    rules()

    assert reads.count(path) == 1


def test_the_committed_policy_parses_cleanly() -> None:
    parsed = rules()
    ids = [r.id for r in parsed]

    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"POL-\d{3}", rule_id) for rule_id in ids)
    assert set(loader.CATEGORIES.values()) == {r.category for r in parsed}


def test_lookup_by_id() -> None:
    assert rule("POL-001") is not None
    assert rule("POL-999") is None


def test_lookup_by_category() -> None:
    refund_rules = rules_for("refund")

    assert refund_rules
    assert all(r.category == "refund" for r in refund_rules)


def test_policy_text_is_the_file_verbatim() -> None:
    assert policy_text() == loader.POLICY_PATH.read_text(encoding="utf-8")


def test_proposed_rules_are_visibly_marked() -> None:
    assert "(proposed" in policy_text()
