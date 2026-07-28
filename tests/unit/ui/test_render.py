from streamlit_app import render

RESOLVED = {
    "decision": "resolved",
    "reply": "Your order 1042 ships tomorrow.",
    "best_draft": None,
    "langsmith_trace_url": "https://smith.langchain.com/o/x/r/abc",
    "tokens_in": 1200,
    "tokens_out": 340,
    "usd": 0.0031,
    "latency_ms": 8400,
}

ESCALATED = {
    "decision": "escalate",
    "reply": None,
    "best_draft": "I think it arrives Tuesday.",
    "escalation_reason": "low_confidence",
    "escalation_detail": "the reviewer rejected three drafts",
    "langsmith_trace_url": None,
}

REFUSED = {
    "decision": "refuse",
    "reply": None,
    "escalation_reason": "injection_detected",
    "langsmith_trace_url": None,
}


# --- decision badges ---------------------------------------------------------------------


def test_each_decision_gets_its_own_badge() -> None:
    labels = {d: render.badge_for(d).label for d in ("resolved", "escalate", "refuse")}

    assert labels == {"resolved": "RESOLVED", "escalate": "ESCALATE", "refuse": "REFUSE"}


def test_the_three_badges_are_visually_distinct() -> None:
    badges = [render.badge_for(d) for d in ("resolved", "escalate", "refuse")]

    assert len({b.icon for b in badges}) == 3
    assert len({b.tone for b in badges}) == 3


def test_an_unexpected_decision_still_renders_something() -> None:
    assert render.badge_for("something-new").label == "UNKNOWN"
    assert render.badge_for(None).label == "UNKNOWN"


# --- reasons -----------------------------------------------------------------------------


def test_a_known_reason_is_explained_in_plain_words() -> None:
    assert "override" in render.explain_reason("injection_detected")


def test_an_unknown_reason_is_shown_rather_than_swallowed() -> None:
    assert render.explain_reason("some_new_reason") == "some new reason"


def test_no_reason_renders_as_nothing() -> None:
    assert render.explain_reason(None) == ""
    assert render.explain_reason("") == ""


# --- the reply panel ---------------------------------------------------------------------


def test_a_resolved_run_shows_the_reply_as_approved() -> None:
    heading, body, approved = render.reply_panel(RESOLVED)

    assert heading == "Reply"
    assert body == RESOLVED["reply"]
    assert approved is True


def test_an_escalated_run_shows_the_best_draft_labelled_unapproved() -> None:
    heading, body, approved = render.reply_panel(ESCALATED)

    assert "unapproved" in heading.lower()
    assert "not sent" in heading.lower()
    assert body == ESCALATED["best_draft"]
    assert approved is False


def test_a_refused_run_shows_no_reply_at_all() -> None:
    heading, body, approved = render.reply_panel(REFUSED)

    assert heading == "No reply"
    assert body == ""
    assert approved is False


def test_an_escalation_with_no_draft_does_not_invent_one() -> None:
    heading, body, _ = render.reply_panel({"decision": "escalate"})

    assert "unapproved" in heading.lower()
    assert body == ""


# --- the trace link ----------------------------------------------------------------------


def test_a_trace_url_becomes_a_clickable_link() -> None:
    label, url = render.trace_label(RESOLVED["langsmith_trace_url"])

    assert url == RESOLVED["langsmith_trace_url"]
    assert label != render.TRACING_DISABLED


def test_a_missing_trace_url_reads_as_disabled_not_broken() -> None:
    assert render.trace_label(None) == (render.TRACING_DISABLED, None)
    assert render.trace_label("") == (render.TRACING_DISABLED, None)


# --- tool rows ---------------------------------------------------------------------------


def test_a_successful_call_reads_as_ok() -> None:
    row = render.tool_row({"name": "get_order_status", "ok": True, "latency_ms": 42})

    assert row["Tool"] == "get_order_status"
    assert "ok" in row["Status"]
    assert row["Latency"] == "42 ms"


def test_a_failed_call_is_marked_failed() -> None:
    row = render.tool_row({"name": "get_order_status", "ok": False, "latency_ms": 3000})

    assert "failed" in row["Status"]


def test_a_rejected_call_is_distinguished_from_a_mere_failure() -> None:
    """A blocked off-allowlist call is the most persuasive row in the demo."""
    rejected = render.tool_row({"name": "drop_tables", "ok": False, "rejected": True})
    failed = render.tool_row({"name": "get_order_status", "ok": False})

    assert "blocked" in rejected["Status"]
    assert rejected["Status"] != failed["Status"]


def test_a_row_renders_from_a_live_event_and_from_a_persisted_call_alike() -> None:
    live = render.tool_row({"name": "get_order_status", "ok": True, "latency_ms": 42})
    persisted = render.tool_row(
        {
            "name": "get_order_status",
            "ok": True,
            "latency_ms": 42,
            "args": {"order_id": "1042"},
            "result_summary": "order 1042 is in transit",
        }
    )

    assert live.keys() == persisted.keys()
    assert persisted["Arguments"] == "order_id=1042"
    assert persisted["Detail"] == "order 1042 is in transit"
    assert live["Arguments"] == ""


# --- node summaries ----------------------------------------------------------------------


def test_the_classifier_summary_names_the_category() -> None:
    assert "order" in render.node_summary("classifier", {"category": "order"})


def test_the_classifier_summary_flags_an_injection() -> None:
    summary = render.node_summary("classifier", {"category": "other", "injection_detected": True})

    assert "injection" in summary


def test_the_researcher_summary_counts_facts() -> None:
    assert render.node_summary("researcher", {"facts": ["a", "b"]}) == "2 facts gathered"
    assert render.node_summary("researcher", {"facts": ["a"]}) == "1 fact gathered"
    assert render.node_summary("researcher", {"facts": []}) == "0 facts gathered"


def test_the_responder_summary_counts_drafts() -> None:
    assert render.node_summary("responder", {"iterations": 2}) == "draft 2"


def test_the_researcher_detail_lists_fact_values_and_sources() -> None:
    detail = render.node_detail(
        "researcher",
        {
            "facts": [
                {
                    "source": "search_products",
                    "key": "product.name",
                    "value": "Oak desk lamp",
                }
            ]
        },
    )

    assert "product.name: Oak desk lamp" in detail
    assert "search_products" in detail


def test_the_responder_detail_marks_the_draft_as_unreviewed() -> None:
    detail = render.node_detail(
        "responder", {"iterations": 2, "draft": "The oak lamp is in stock."}
    )

    assert "Draft 2" in detail
    assert "awaiting reviewer approval" in detail
    assert "The oak lamp is in stock." in detail


def test_the_reviewer_summary_reports_a_decision_when_it_has_one() -> None:
    assert render.node_summary("reviewer", {"decision": "resolved"}) == "decision: resolved"


def test_the_reviewer_summary_reports_a_rewrite_request_otherwise() -> None:
    summary = render.node_summary("reviewer", {"review_notes": ["POL-003: unsupported date"]})

    assert "rewrite" in summary
    assert "POL-003" in summary


def test_a_summary_never_raises_on_missing_data() -> None:
    for node in ("classifier", "researcher", "responder", "reviewer", "mystery"):
        assert isinstance(render.node_summary(node, None), str)
        assert isinstance(render.node_detail(node, None), str)


# --- the cost line -----------------------------------------------------------------------


def test_the_cost_line_reports_tokens_spend_and_latency() -> None:
    line = render.cost_line(RESOLVED)

    assert "1,540 tokens" in line
    assert "$0.0031" in line
    assert "8.4s" in line


def test_the_cost_line_survives_a_result_with_no_usage() -> None:
    assert render.cost_line({}) == "0 tokens (0 in / 0 out) · $0.0000 · 0.0s"
