import ast
from pathlib import Path

import pytest

from streamlit_app.examples import EXAMPLES

APP = Path(__file__).resolve().parents[3] / "src" / "streamlit_app"

SOURCES = sorted(APP.glob("*.py"))


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_the_demo_client_never_imports_the_service(path: Path) -> None:
    """Sharing types would let logic drift into the least-tested part of the codebase."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not [name for name in imported if name.split(".")[0] == "deskfleet"]


def test_the_examples_cover_more_than_the_happy_path() -> None:
    labels = " ".join(e.label.lower() for e in EXAMPLES)

    assert len(EXAMPLES) >= 4
    assert "injection" in labels
    assert "delayed" in labels


def test_the_delayed_example_uses_the_seeded_order() -> None:
    delayed = next(e for e in EXAMPLES if "delayed" in e.label.lower())

    assert delayed.order_id == "1077"


def test_the_injection_example_carries_an_actual_override_attempt() -> None:
    injection = next(e for e in EXAMPLES if "injection" in e.label.lower())

    assert "ignore all previous instructions" in injection.ticket.lower()


def test_every_example_has_a_ticket() -> None:
    assert all(e.ticket.strip() for e in EXAMPLES)
