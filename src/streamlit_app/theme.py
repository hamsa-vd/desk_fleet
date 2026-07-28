"""The visual layer: design tokens, the stylesheet, and the HTML fragments the page injects.

Kept free of Streamlit so every fragment can be asserted directly. Anything interpolated here may
carry service text — a drafted reply, a tool summary — so it is escaped on the way in. The page
renders these with `unsafe_allow_html`, which makes an unescaped `<` a script-injection vector.
"""

from html import escape
from typing import Any

#: Taken from the design. The accent ramp is given; the neutrals and the second accent are derived
#: from it — the design system's own stylesheet was not shipped with the mockups.
TOKENS: dict[str, str] = {
    "--color-bg": "#f5ead8",
    "--color-surface": "#fdf8ee",
    "--color-text": "#2a2118",
    "--color-divider": "#e2d5bd",
    "--color-accent": "#ff684e",
    "--color-accent-600": "#e5503a",
    "--color-accent-700": "#b23a29",
    "--color-accent-800": "#7d2417",
    "--color-accent-100": "#ffe9e3",
    "--color-accent-200": "#ffd4c9",
    "--color-accent-300": "#ffb4a4",
    "--color-accent-2-100": "#eef1e6",
    "--color-accent-2-300": "#c3cdaa",
    "--color-accent-2-500": "#7a8a5e",
    "--color-accent-2-700": "#566141",
    "--color-accent-2-800": "#3d452e",
    "--color-neutral-200": "#ece3d4",
    "--color-neutral-300": "#ddd0b9",
    "--color-neutral-400": "#b3a795",
    "--color-neutral-500": "#8c8172",
    "--color-neutral-800": "#3a332a",
    "--font-heading": "'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, serif",
    "--font-body": "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, sans-serif",
    "--mono": "ui-monospace, 'SF Mono', Menlo, monospace",
}

#: `decision` (as the service spells it) → the banner's colour set.
DECISION_COLOURS: dict[str, dict[str, str]] = {
    "resolved": {
        "bg": "var(--color-accent-2-100)",
        "border": "var(--color-accent-2-300)",
        "dot": "var(--color-accent-2-500)",
        "ink": "var(--color-accent-2-800)",
        "sub": "reply drafted and approved",
    },
    "escalate": {
        "bg": "var(--color-accent-100)",
        "border": "var(--color-accent-300)",
        "dot": "var(--color-accent)",
        "ink": "var(--color-accent-800)",
        "sub": "handed to a human with the full trail",
    },
    "refuse": {
        "bg": "var(--color-neutral-200)",
        "border": "var(--color-neutral-300)",
        "dot": "var(--color-neutral-500)",
        "ink": "var(--color-neutral-800)",
        "sub": "outside scope or unsafe to answer",
    },
}

UNKNOWN_COLOURS = {
    "bg": "var(--color-neutral-200)",
    "border": "var(--color-neutral-300)",
    "dot": "var(--color-neutral-500)",
    "ink": "var(--color-neutral-800)",
    "sub": "the service returned no decision",
}

#: Progress dot per node state. `active` is the only one that animates.
NODE_DOTS: dict[str, dict[str, str]] = {
    "done": {"fill": "var(--color-accent-2-500)", "ring": "none", "anim": "none", "ink": "1"},
    "active": {
        "fill": "var(--color-accent)",
        "ring": "0 0 0 4px var(--color-accent-100)",
        "anim": "df-pulse 1.2s ease-in-out infinite",
        "ink": "1",
    },
    "pending": {"fill": "var(--color-neutral-400)", "ring": "none", "anim": "none", "ink": ".55"},
}


def _vars() -> str:
    return "".join(f"{name}:{value};" for name, value in TOKENS.items())


CSS = f"""<style>
:root {{ {_vars()} }}

@keyframes df-pulse {{
  0%,100% {{ opacity:1; transform:scale(1) }}
  50% {{ opacity:.35; transform:scale(.7) }}
}}
@keyframes df-in {{
  from {{ opacity:0; transform:translateY(4px) }}
  to {{ opacity:1; transform:none }}
}}

.stApp {{ background: var(--color-bg); color: var(--color-text); font-family: var(--font-body); }}
header[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 2.2rem; max-width: 1260px; }}

h1, h2, h3, h4 {{ font-family: var(--font-heading) !important; letter-spacing: -.015em; }}

/* Buttons read as pills, primary in the accent. */
.stButton > button {{
  font-family: var(--font-body); font-size: 13.5px; font-weight: 500;
  border-radius: 999px; border: 1px solid var(--color-divider);
  background: var(--color-bg); color: var(--color-text);
  padding: .45rem .9rem; transition: border-color .15s, background .15s;
  /* A narrow column would otherwise break a one-word label across two lines. */
  white-space: nowrap;
}}
.stButton > button p {{ white-space: nowrap; }}
.stButton > button:hover:not(:disabled) {{
  border-color: var(--color-accent); background: var(--color-accent-100); color: var(--color-text);
}}
.stButton > button[kind="primary"] {{
  background: var(--color-accent); border-color: var(--color-accent); color: #fff;
  border-radius: 12px; padding: .6rem 1.6rem; font-size: 15px;
}}
.stButton > button[kind="primary"]:hover:not(:disabled) {{
  background: var(--color-accent-600); border-color: var(--color-accent-600); color: #fff;
}}
.stButton > button:disabled {{ opacity: .45; }}

/* Streamlit puts the visibility toggle *inside* the input's root element, so bordering the inner
   <input> draws a second box that stops short of the eye — password fields then read as narrower
   than text fields. The border belongs to the root; the input itself is transparent. */
[data-testid="stTextInputRootElement"],
.stTextArea [data-baseweb="base-input"],
.stSelectbox div[data-baseweb="select"] > div {{
  background: var(--color-surface) !important;
  border-radius: 12px !important; border: 1px solid var(--color-divider) !important;
}}
[data-testid="stTextInputRootElement"]:focus-within,
.stTextArea [data-baseweb="base-input"]:focus-within {{
  border-color: var(--color-accent) !important;
}}
.stTextInput input, .stTextArea textarea {{
  background: transparent !important; border: none !important;
  color: var(--color-text) !important; font-family: var(--font-body);
}}
[data-testid="stTextInputRootElement"] button {{ background: transparent !important; }}
.stTextArea textarea {{ font-size: 15px; line-height: 1.55; }}

[data-testid="stTabs"] button[role="tab"] {{ font-family: var(--font-heading); font-size: 14px; }}
[data-baseweb="tab-highlight"] {{ background: var(--color-accent) !important; }}

/* The mockup's panels: the config aside and the run panel are the same card. */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
  border: 1px solid var(--color-divider) !important; border-radius: 16px !important;
  background: var(--color-surface); padding: 6px 18px 14px;
}}

/* One model row per node: name and current selection left, the control right, baselines aligned. */
.df-model-row {{
  display: flex; align-items: center; min-height: 34px;
  font-size: 13.5px; line-height: 1.35;
}}
.df-model-row b {{ font-family: var(--font-heading); font-weight: 400; }}
.df-eyebrow {{
  font-size: 12.5px; letter-spacing: .08em; text-transform: uppercase;
  font-weight: 600; color: var(--color-accent-700);
}}
.df-quiet {{ color: color-mix(in srgb, var(--color-text) 62%, transparent); }}
.df-mono {{ font-family: var(--mono); font-size: 12.5px; }}
.df-progress-row {{ position: relative; }}
.df-progress-row.df-has-detail {{ cursor: help; }}
.df-progress-row.df-has-detail .df-progress-name {{
  text-decoration: underline dotted color-mix(in srgb, var(--color-text) 38%, transparent);
  text-underline-offset: 4px;
}}
.df-progress-tip {{
  visibility: hidden; opacity: 0; pointer-events: none;
  position: absolute; z-index: 20; top: calc(100% - 3px); left: 22px;
  width: min(330px, calc(100vw - 88px)); max-height: 220px; overflow: auto;
  padding: 12px 14px; border: 1px solid var(--color-divider); border-radius: 10px;
  background: var(--color-surface); color: var(--color-text);
  box-shadow: 0 10px 28px rgba(58, 51, 42, .16);
  font-family: var(--font-body); font-size: 12.5px; line-height: 1.5;
  white-space: pre-line; transition: opacity .12s ease;
}}
.df-progress-row.df-has-detail:hover .df-progress-tip,
.df-progress-row.df-has-detail:focus .df-progress-tip,
.df-progress-row.df-has-detail:focus-within .df-progress-tip {{
  visibility: visible; opacity: 1; pointer-events: auto;
}}
</style>"""


def header_html() -> str:
    """The wordmark, the check glyph, and the badge saying this talks to a live service."""
    return (
        '<div style="display:flex;align-items:center;gap:11px;'
        'padding-bottom:16px;border-bottom:1px solid var(--color-divider);margin-bottom:22px;">'
        '<span style="width:26px;height:26px;border-radius:8px;background:var(--color-accent);'
        'display:inline-grid;place-content:center;">'
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--color-bg)" '
        'stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 6 9 17l-5-5"/></svg></span>'
        '<span style="font-family:var(--font-heading);font-size:20px;">DeskFleet</span>'
        '<span style="font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;'
        'border:1px solid var(--color-divider);padding:3px 9px;border-radius:999px;" '
        'class="df-quiet">Live demo</span>'
        '<span style="margin-left:auto;font-size:13px;" class="df-quiet">'
        "Classifier → Researcher → Responder → Reviewer</span>"
        "</div>"
    )


def intro_html() -> str:
    return (
        '<span class="df-eyebrow">Resolve a ticket</span>'
        '<h1 style="font-size:clamp(28px,3.4vw,38px);line-height:1.1;margin:10px 0 0;">'
        "Hand the crew a support ticket.</h1>"
        '<p style="font-size:15.5px;line-height:1.6;max-width:62ch;margin:12px 0 22px;" '
        'class="df-quiet">Pick a preset or write your own, then resolve it and watch each node '
        "work in real time. Every run goes to the service you point at below.</p>"
    )


def section_label_html(text: str, top: int = 0) -> str:
    return (
        '<div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;'
        f'margin:{top}px 0 10px;" class="df-quiet">{escape(text)}</div>'
    )


def model_row_html(summary: str) -> str:
    """`summary` arrives as "Classifier · server default"; the node name carries the weight."""
    node, sep, selection = summary.partition("·")
    if not sep:
        return f'<div class="df-model-row"><span>{escape(summary)}</span></div>'
    return (
        f'<div class="df-model-row"><span><b>{escape(node.strip())}</b> · '
        f'<span class="df-quiet">{escape(selection.strip())}</span></span></div>'
    )


def progress_row_html(label: str, state: str, note: str, detail: str = "") -> str:
    """One node's line: dot, name, and whatever the node reported when it finished."""
    dot = NODE_DOTS.get(state, NODE_DOTS["pending"])
    detail = detail.strip()
    row_class = "df-progress-row df-has-detail" if detail else "df-progress-row"
    accessibility = (
        f' tabindex="0" aria-label="{escape(f"{label}: {note}. {detail}", quote=True)}"'
        if detail
        else ""
    )
    tooltip = (
        f'<span class="df-progress-tip" role="tooltip">{escape(detail)}</span>' if detail else ""
    )
    return (
        f'<div class="{row_class}"{accessibility} style="display:flex;align-items:flex-start;'
        'gap:12px;padding:10px 0;border-bottom:1px solid var(--color-divider);">'
        f'<span style="flex:none;margin-top:5px;width:11px;height:11px;border-radius:50%;'
        f'background:{dot["fill"]};box-shadow:{dot["ring"]};animation:{dot["anim"]};"></span>'
        f'<span class="df-progress-name" style="min-width:88px;'
        f"font-family:var(--font-heading);font-size:15px;"
        f'opacity:{dot["ink"]};">{escape(label)}</span>'
        f'<span style="font-size:13.5px;line-height:1.45;" class="df-quiet">{escape(note)}</span>'
        f"{tooltip}"
        "</div>"
    )


def tool_line_html(row: dict[str, Any]) -> str:
    """The live feed's compact form. The table with the detail column comes after the run."""
    status = str(row.get("Status", ""))
    colour = (
        "var(--color-accent-700)"
        if "blocked" in status
        else "var(--color-accent-2-700)"
        if "ok" in status
        else "var(--color-neutral-500)"
    )
    return (
        '<div style="display:flex;justify-content:space-between;gap:10px;padding:5px 0;'
        'animation:df-in .3s ease;" class="df-mono">'
        f"<span>{escape(str(row.get('Tool', '')))}</span>"
        f'<span class="df-quiet"><span style="color:{colour};">{escape(status)}</span>'
        f" · {escape(str(row.get('Latency', '')))}</span>"
        "</div>"
    )


def banner_html(decision: str | None, label: str, reason: str) -> str:
    colours = DECISION_COLOURS.get((decision or "").lower(), UNKNOWN_COLOURS)
    tail = f" — {escape(reason)}" if reason else ""
    return (
        f'<div style="display:flex;align-items:center;flex-wrap:wrap;gap:10px 14px;'
        f"padding:15px 20px;border-radius:14px;background:{colours['bg']};"
        f'border:1px solid {colours["border"]};animation:df-in .35s ease;">'
        f'<span style="flex:none;width:11px;height:11px;border-radius:50%;'
        f'background:{colours["dot"]};"></span>'
        f'<span style="font-family:var(--font-heading);font-size:16px;letter-spacing:.02em;'
        f'color:{colours["ink"]};">{escape(label)}</span>'
        f'<span style="font-size:14px;" class="df-quiet">{escape(colours["sub"])}{tail}</span>'
        "</div>"
    )


def draft_html(body: str, approved: bool) -> str:
    """An unapproved draft is tinted differently so it cannot be mistaken for a sent reply."""
    edge = "var(--color-accent-2-500)" if approved else "var(--color-accent)"
    return (
        f'<blockquote style="margin:0;padding:18px 22px;border-left:3px solid {edge};'
        f"border-radius:0 12px 12px 0;background:var(--color-surface);font-size:15.5px;"
        f'line-height:1.65;">{escape(body)}</blockquote>'
    )


def meta_html(cost_line: str, ticket_id: str) -> str:
    return (
        '<div style="display:flex;flex-wrap:wrap;gap:8px 22px;align-items:center;'
        'font-size:13px;margin-top:6px;" class="df-quiet">'
        f'<span class="df-mono">{escape(cost_line)}</span>'
        f'<span>Ticket <span class="df-mono">{escape(ticket_id)}</span></span>'
        "</div>"
    )
