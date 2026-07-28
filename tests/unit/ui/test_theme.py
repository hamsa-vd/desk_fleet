"""The page renders every fragment here with `unsafe_allow_html`, so escaping is load-bearing."""

import re

import pytest

from streamlit_app import theme

HOSTILE = '<script>alert("xss")</script>'


def test_the_accent_ramp_matches_the_design() -> None:
    assert theme.TOKENS["--color-accent"] == "#ff684e"
    assert theme.TOKENS["--color-accent-100"] == "#ffe9e3"


def test_every_token_the_stylesheet_names_is_defined() -> None:
    """A `var(--x)` with no `--x` silently renders as nothing — invisible text, not a crash."""
    referenced = set(re.findall(r"var\((--[a-z0-9-]+)\)", theme.CSS))

    assert referenced <= set(theme.TOKENS)


@pytest.mark.parametrize(
    "fragment",
    [
        theme.draft_html(HOSTILE, approved=True),
        theme.banner_html("resolved", HOSTILE, HOSTILE),
        theme.progress_row_html(HOSTILE, "done", HOSTILE, HOSTILE),
        theme.tool_line_html({"Tool": HOSTILE, "Status": "ok", "Latency": HOSTILE}),
        theme.meta_html(HOSTILE, HOSTILE),
        theme.model_row_html(HOSTILE),
        theme.section_label_html(HOSTILE),
    ],
)
def test_service_text_is_escaped_before_it_reaches_the_page(fragment: str) -> None:
    assert "<script>" not in fragment
    assert "&lt;script&gt;" in fragment


def test_a_drafted_reply_survives_escaping_intact() -> None:
    reply = "Your order 1042 ships Tuesday & arrives by 30 July."

    assert "Your order 1042 ships Tuesday &amp; arrives by 30 July." in theme.draft_html(
        reply, approved=True
    )


@pytest.mark.parametrize("decision", ["resolved", "escalate", "refuse"])
def test_each_decision_gets_its_own_banner_colours(decision: str) -> None:
    colours = theme.DECISION_COLOURS[decision]
    rendered = theme.banner_html(decision, decision.upper(), "")

    assert colours["bg"] in rendered
    assert colours["sub"] in rendered


def test_an_unrecognised_decision_still_renders_a_banner() -> None:
    rendered = theme.banner_html("something-new", "UNKNOWN", "")

    assert theme.UNKNOWN_COLOURS["bg"] in rendered
    assert "UNKNOWN" in rendered


def test_an_escalated_draft_is_tinted_differently_from_an_approved_one() -> None:
    """A reviewer must never read an unapproved draft as something the crew was willing to send."""
    approved = theme.draft_html("body", approved=True)
    unapproved = theme.draft_html("body", approved=False)

    assert approved != unapproved
    assert "var(--color-accent-2-500)" in approved
    assert "var(--color-accent)" in unapproved


def test_only_the_running_node_animates() -> None:
    active = theme.progress_row_html("Researcher", "active", "working")
    done = theme.progress_row_html("Researcher", "done", "8 facts gathered")
    pending = theme.progress_row_html("Researcher", "pending", "")

    assert "df-pulse" in active
    assert "df-pulse" not in done
    assert "df-pulse" not in pending


def test_an_unknown_node_state_falls_back_to_pending() -> None:
    rendered = theme.progress_row_html("Researcher", "not-a-state", "")

    assert theme.NODE_DOTS["pending"]["fill"] in rendered


def test_a_completed_node_with_detail_has_a_hover_and_keyboard_tooltip() -> None:
    rendered = theme.progress_row_html(
        "Researcher", "done", "2 facts gathered", "Facts:\n• product.name: Oak desk lamp"
    )

    assert "df-has-detail" in rendered
    assert 'tabindex="0"' in rendered
    assert 'role="tooltip"' in rendered
    assert "product.name: Oak desk lamp" in rendered
    assert ".df-progress-row.df-has-detail:hover .df-progress-tip" in theme.CSS
    assert ".df-progress-row.df-has-detail:focus .df-progress-tip" in theme.CSS


def test_a_blocked_tool_call_is_coloured_apart_from_a_successful_one() -> None:
    blocked = theme.tool_line_html(
        {"Tool": "drop_tables", "Status": "🛑 blocked", "Latency": "0 ms"}
    )
    ok = theme.tool_line_html({"Tool": "get_order_status", "Status": "✅ ok", "Latency": "26 ms"})

    assert "var(--color-accent-700)" in blocked
    assert "var(--color-accent-2-700)" in ok


def test_a_tool_row_missing_every_field_still_renders() -> None:
    assert theme.tool_line_html({}).startswith("<div")


def test_the_model_row_keeps_the_summary_readable() -> None:
    """The picker tests read this line as text; splitting it for styling must not lose the dot."""
    rendered = re.sub(r"<[^>]+>", "", theme.model_row_html("Classifier · server default"))

    assert rendered == "Classifier · server default"


def test_a_model_summary_without_a_separator_is_left_alone() -> None:
    rendered = re.sub(r"<[^>]+>", "", theme.model_row_html("Classifier"))

    assert rendered == "Classifier"
