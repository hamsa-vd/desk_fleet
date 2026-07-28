"""The page renders every fragment here with `unsafe_allow_html`, so escaping is load-bearing."""

import re

import pytest

from streamlit_app import theme

HOSTILE = '<script>alert("xss")</script>'


def test_the_accent_ramp_matches_the_design() -> None:
    assert theme.TOKENS["--color-accent"] == "#d9840d"
    assert theme.TOKENS["--color-accent-bright"] == "#f7b733"


def test_the_header_matches_the_iconless_reference_copy() -> None:
    rendered = theme.header_html()

    assert "df-brand-mark" not in rendered
    assert "DeskFleet" in rendered
    assert "LIVE DEMO" in rendered
    assert "Classifier → Researcher → Responder → Reviewer" in rendered


def test_the_intro_eyebrow_uses_the_reference_copy() -> None:
    assert '<span class="df-eyebrow">RESOLVE A TICKET</span>' in theme.intro_html()


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
        theme.tool_table_html(
            [
                {
                    "Tool": HOSTILE,
                    "Status": HOSTILE,
                    "Latency": HOSTILE,
                    "Arguments": HOSTILE,
                    "Detail": HOSTILE,
                }
            ]
        ),
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
    assert "var(--color-success)" in approved
    assert "var(--color-danger)" in unapproved


def test_only_the_running_node_animates() -> None:
    active = theme.progress_row_html("Researcher", "active", "working")
    done = theme.progress_row_html("Researcher", "done", "8 facts gathered")
    pending = theme.progress_row_html("Researcher", "pending", "")

    assert "df-pulse" in active
    assert "df-pulse" not in done
    assert "df-pulse" not in pending
    assert "df-state-active" in active
    assert "df-state-done" in done
    assert "df-state-pending" in pending


def test_running_action_matches_the_reference_treatment() -> None:
    # The running button gets a fresh numbered key per node (df-running, df-running-1, …), so the
    # selector must match on a prefix rather than the exact "df-running" key.
    assert '[class*="st-key-df-running"] {' in theme.CSS
    assert "background:linear-gradient(135deg,#f7ce73,#e0a845) !important;" in theme.CSS
    assert "cursor:default !important; opacity:1 !important;" in theme.CSS
    assert "width:max-content !important; min-width:max-content !important;" in theme.CSS


def test_result_stack_uses_explicit_source_spacing_without_streamlit_heading_wrappers() -> None:
    rendered = theme.result_stack_html(
        [
            theme.result_heading_html("Reply"),
            theme.draft_html("body", approved=True),
            theme.result_heading_html("Tool calls"),
            theme.result_empty_html("No tools were called."),
            theme.result_footer_space_html(),
        ]
    )

    assert 'class="df-result-stack"' in rendered
    assert rendered.count('class="df-result-heading"') == 2
    assert 'class="df-result-draft"' in rendered
    assert 'class="df-result-empty"' in rendered
    assert 'class="df-result-footer-space"' in rendered
    assert "margin:36px 0 14px !important;" in theme.CSS
    assert ".df-result-heading a { display:none !important; }" in theme.CSS


def test_tool_table_removes_streamlit_spacing_and_compacts_long_detail() -> None:
    detail = "x" * 140
    rendered = theme.tool_table_html(
        [
            {
                "Tool": "get_order_status",
                "Status": "✅ ok",
                "Latency": "17 ms",
                "Arguments": "order_id=1077",
                "Detail": detail,
            }
        ]
    )

    assert "● ok" in rendered
    assert f'title="{detail}"' in rendered
    assert f"{'x' * 93}...</td>" in rendered
    assert "margin:0 !important;" in theme.CSS
    assert "border:0 !important;" in theme.CSS


def test_pending_progress_matches_the_reference_typography_and_rhythm() -> None:
    assert "color:var(--color-text-faint); font-weight:500;" in theme.CSS
    assert "font-family:var(--font-body);" in theme.CSS
    assert "font-weight:700; line-height:16px;" in theme.CSS
    assert ".df-progress-row:first-child { margin-top:1px; }" in theme.CSS
    assert ".st-key-df-run-panel { min-height:266px; }" in theme.CSS
    assert "margin-top:3px;width:9px;height:9px" in theme.progress_row_html(
        "Classifier", "pending", ""
    )


def test_the_active_node_exposes_its_current_progress_on_hover() -> None:
    rendered = theme.progress_row_html("Researcher", "active", "Working…")

    assert "df-has-detail" in rendered
    assert ".df-progress-row.df-has-detail { cursor:default; }" in theme.CSS
    assert 'tabindex="0"' in rendered
    assert 'role="tooltip"' in rendered
    assert "Researcher is currently working." in rendered


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

    assert "var(--color-danger-ink)" in blocked
    assert "var(--color-success-muted)" in ok


def test_a_tool_row_missing_every_field_still_renders() -> None:
    assert theme.tool_line_html({}).startswith("<div")


def test_the_model_row_keeps_the_summary_readable() -> None:
    """The redesign stacks the values while preserving their accessible reading order."""
    rendered = re.sub(r"<[^>]+>", "", theme.model_row_html("Classifier · server default"))

    assert rendered == "Classifier · server default"


def test_the_model_panel_uses_the_reference_tab_and_action_geometry() -> None:
    assert "height:30px; min-height:30px; padding:0 0 12px" in theme.CSS
    assert "height:30.5px; min-height:30.5px; margin-bottom:16px" in theme.CSS
    assert "width:74px; min-width:74px; height:28px; min-height:28px" in theme.CSS


def test_the_service_panel_uses_the_reference_field_rhythm() -> None:
    assert "align-items:flex-start; height:15px; min-height:15px;" in theme.CSS
    assert ".st-key-base_url { margin-bottom:16px; }" in theme.CSS
    assert "height:20px; min-height:20px;" in theme.CSS


def test_the_ticket_box_disables_internal_scrolling_and_can_grow_vertically() -> None:
    assert 'div[data-testid="stElementContainer"].st-key-ticket {' in theme.CSS
    assert "overflow:unset !important;" in theme.CSS
    assert "width:calc(100% + 11px) !important;" not in theme.CSS
    assert '.st-key-ticket [data-testid="stTextAreaRootElement"]' in theme.CSS
    assert "overflow:hidden !important;" in theme.CSS
    assert "overflow-y:hidden !important; overflow-x:hidden !important;" in theme.CSS
    assert "resize:vertical !important;" in theme.CSS


def test_the_right_rail_uses_the_reference_spacing() -> None:
    assert "margin:0px 0 16px" in theme.section_label_html("Progress", bottom=16)
    assert "margin:0px 0 12px" in theme.section_label_html("Live tool calls", bottom=12)
    assert "height:1px;background:var(--color-divider);margin:12px 0 16px" in theme.divider_html()
    assert "height:1px;background:var(--color-divider);margin:0px 0 16px" in theme.divider_html(
        top=0
    )
    assert (
        "font-family:var(--font-body);font-size:12px;line-height:normal;"
        in theme.quiet_text_html("No tool calls yet.")
    )


def test_a_model_summary_without_a_separator_is_left_alone() -> None:
    rendered = re.sub(r"<[^>]+>", "", theme.model_row_html("Classifier"))

    assert rendered == "Classifier"


def test_the_loading_rail_is_accessible() -> None:
    rendered = theme.loading_html()

    assert 'role="status"' in rendered
    assert "Resolving your ticket" in rendered


def test_output_region_keeps_source_spacing_and_alert_dimensions() -> None:
    assert ".st-key-df-output { margin-top:20px; }" in theme.CSS
    assert '.st-key-df-output [data-testid="stAlertContainer"] {' in theme.CSS
    assert "min-height:56px; box-sizing:border-box; border-radius:8px;" in theme.CSS
    assert ".st-key-df-result { margin-top:0; }" in theme.CSS
