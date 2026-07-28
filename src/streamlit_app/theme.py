"""The visual layer: design tokens, the stylesheet, and the HTML fragments the page injects.

Kept free of Streamlit so every fragment can be asserted directly. Anything interpolated here may
carry service text — a drafted reply, a tool summary — so it is escaped on the way in. The page
renders these with `unsafe_allow_html`, which makes an unescaped `<` a script-injection vector.
"""

from html import escape
from typing import Any

#: Exact palette and type choices from `.ai/inspiration/DeskFleet Redesign.dc.html`.
TOKENS: dict[str, str] = {
    "--color-bg": "#f5f5f3",
    "--color-surface": "#ffffff",
    "--color-surface-muted": "#f7f7f5",
    "--color-text": "#121212",
    "--color-text-soft": "#84847e",
    "--color-text-faint": "#a9a9a3",
    "--color-divider": "#e7e7e3",
    "--color-accent": "#d9840d",
    "--color-accent-bright": "#f7b733",
    "--color-accent-focus": "#f5c518",
    "--color-accent-ink": "#8a6400",
    "--color-accent-soft": "#fff6dc",
    "--color-danger": "#ff4a1a",
    "--color-danger-ink": "#c9370a",
    "--color-danger-soft": "#ffe9df",
    "--color-success": "#4e7a3b",
    "--color-success-muted": "#5e7f4a",
    "--color-success-dot": "#3c9a46",
    "--color-success-ink": "#355a28",
    "--color-success-soft": "#eaf1e5",
    "--color-neutral-soft": "#efefec",
    "--color-neutral-dot": "#8c8c86",
    "--color-neutral-ink": "#57574f",
    "--font-heading": "'Poppins', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
    "--font-body": "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, sans-serif",
    "--mono": "ui-monospace, 'SF Mono', Menlo, monospace",
}

#: `decision` (as the service spells it) → the banner's colour set.
DECISION_COLOURS: dict[str, dict[str, str]] = {
    "resolved": {
        "bg": "var(--color-success-soft)",
        "dot": "var(--color-success)",
        "ink": "var(--color-success-ink)",
        "sub": "reply drafted and approved",
    },
    "escalate": {
        "bg": "var(--color-danger-soft)",
        "dot": "var(--color-danger)",
        "ink": "var(--color-danger-ink)",
        "sub": "handed to a human with the full trail",
    },
    "refuse": {
        "bg": "var(--color-neutral-soft)",
        "dot": "var(--color-neutral-dot)",
        "ink": "var(--color-neutral-ink)",
        "sub": "outside scope or unsafe to answer",
    },
}

UNKNOWN_COLOURS = {
    "bg": "var(--color-neutral-soft)",
    "dot": "var(--color-neutral-dot)",
    "ink": "var(--color-neutral-ink)",
    "sub": "the service returned no decision",
}

#: Progress dot per node state. `active` is the only one that animates.
NODE_DOTS: dict[str, dict[str, str]] = {
    "done": {"fill": "var(--color-success-dot)", "ring": "none", "anim": "none", "ink": "1"},
    "active": {
        "fill": "var(--color-accent-bright)",
        "ring": "0 0 0 4px var(--color-accent-soft)",
        "anim": "df-pulse 1.2s ease-in-out infinite",
        "ink": "1",
    },
    "pending": {
        "fill": "var(--color-divider)",
        "ring": "none",
        "anim": "none",
        "ink": ".58",
    },
}


def _vars() -> str:
    return "".join(f"{name}:{value};" for name, value in TOKENS.items())


CSS = f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@600;700;800&display=swap');
:root {{ {_vars()} }}

@keyframes df-pulse {{
  0%,100% {{ opacity:1; transform:scale(1) }}
  50% {{ opacity:.35; transform:scale(.7) }}
}}
@keyframes df-in {{
  from {{ opacity:0; transform:translateY(4px) }}
  to {{ opacity:1; transform:none }}
}}
@keyframes df-loading {{
  0% {{ left:-30%; }}
  100% {{ left:100%; }}
}}

.stApp {{ background: var(--color-bg); color: var(--color-text); font-family: var(--font-body); }}
header[data-testid="stHeader"] {{ display:none; }}
[data-testid="stMainBlockContainer"] {{
  padding: 0 48px 90px;
  max-width: 1276px;
}}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{ gap:0; }}

h1, h2, h3, h4 {{
  font-family: var(--font-heading) !important;
  font-weight: 800 !important;
  letter-spacing: -.02em !important;
  color: var(--color-text) !important;
  padding:0 !important;
}}
p, label, input, textarea, button {{ font-family:var(--font-body) !important; }}

.df-header {{
  position:relative; left:50%; width:100vw; margin-left:-50vw;
  box-sizing:border-box; display:flex; align-items:center; justify-content:space-between;
  min-height:77px; padding:22px 48px; border-bottom:1px solid var(--color-divider);
  background:var(--color-surface); font-family:var(--font-body); line-height:normal;
}}
.df-brand {{ display:flex; align-items:center; gap:12px; }}
.df-wordmark {{
  font-family:var(--font-heading); font-weight:800; font-size:19px; line-height:normal;
}}
.df-live-badge {{
  padding:4px 10px; border:1px solid var(--color-divider); border-radius:999px;
  color:var(--color-text-soft); font-size:11px; font-weight:700; letter-spacing:.04em;
  line-height:normal;
}}
.df-crew-line {{
  font-family:var(--font-body); font-size:12px; line-height:normal;
  color:var(--color-text-faint); font-weight:600;
}}
.df-intro {{ padding:64px 0 12px; }}

/* Secondary actions and presets use the compact pill treatment from the reference. */
.stButton > button {{
  font-size:13px; font-weight:600; border-radius:999px;
  border:1px solid var(--color-divider); background:var(--color-surface-muted);
  color:var(--color-text); padding:9px 16px; transition:.16s ease;
  white-space:nowrap; box-shadow:none;
}}
.stButton > button p {{ white-space: nowrap; }}
.stButton > button:hover:not(:disabled) {{
  border-color:var(--color-accent); background:var(--color-accent-soft); color:var(--color-text);
}}
.stButton > button[kind="primary"] {{
  background:linear-gradient(135deg,var(--color-accent-bright),var(--color-accent));
  border-color:transparent; color:var(--color-accent-soft);
  border-radius:10px; padding:12px 26px; font-size:14px; font-weight:800;
}}
.stButton > button[kind="primary"]:hover:not(:disabled) {{
  filter:brightness(.96); border-color:transparent; color:var(--color-accent-soft);
}}
.stButton > button:disabled {{ opacity: .45; }}
.st-key-df-presets .stButton > button {{
  height:35px; min-height:35px; padding:0 16px;
  font-family:Arial,sans-serif !important; font-size:13px; font-weight:600;
  transition:none;
}}
.st-key-df-presets {{ gap:10px !important; }}
.df-composer-label {{
  margin:0 0 14px; color:var(--color-text-faint); font-family:'Inter',sans-serif !important;
  font-size:11px; font-weight:800; letter-spacing:.08em; line-height:normal;
  text-transform:uppercase;
}}
.st-key-df-presets .stButton > button p {{
  font-family:Arial,sans-serif !important; font-size:13px !important;
  line-height:normal !important; font-weight:600 !important;
}}
.st-key-df-presets .stButton > button {{ line-height:normal !important; }}
.st-key-df-presets .stButton > button:hover:not(:disabled) {{
  border-color:var(--color-divider) !important;
  background:var(--color-surface-muted) !important;
  color:var(--color-text) !important; filter:none;
}}
.st-key-df-presets .stButton > button[kind="primary"] {{
  border-radius:999px; padding:0 16px; font-size:13px; font-weight:600;
  background-color:var(--color-accent-bright) !important;
  background-image:
    linear-gradient(135deg,var(--color-accent-bright),var(--color-accent)) !important;
  border-color:var(--color-accent) !important;
  color:var(--color-accent-soft) !important;
}}
.st-key-df-presets .stButton > button[kind="primary"]:hover:not(:disabled) {{
  background-color:var(--color-accent-bright) !important;
  background-image:
    linear-gradient(135deg,var(--color-accent-bright),var(--color-accent)) !important;
  border-color:var(--color-accent) !important;
  color:var(--color-accent-soft) !important; filter:none;
}}
.st-key-df-resolve button {{
  height:40px; min-height:40px; padding:0 26px;
  font-family:Arial,sans-serif !important;
}}
.st-key-df-resolve button p {{
  font-family:Arial,sans-serif !important; font-size:14px !important;
  line-height:normal !important; font-weight:800 !important;
}}
.st-key-df-resolve button:hover:not(:disabled) {{
  background-image:
    linear-gradient(135deg,var(--color-accent-bright),var(--color-accent)) !important;
  color:var(--color-accent-soft) !important; filter:none;
}}
/* One numbered key per node the run advances to (df-running, df-running-1, df-running-2, …), so
   the class selector must match on a prefix rather than the exact "df-running" key. */
[class*="st-key-df-running"] {{
  width:max-content !important; min-width:max-content !important;
  margin-left:auto; overflow:visible !important;
}}
[class*="st-key-df-running"] button {{
  width:max-content !important; min-width:max-content !important;
  height:40px; min-height:40px; padding:0 26px;
  background:linear-gradient(135deg,#f7ce73,#e0a845) !important;
  border:0 !important; border-radius:10px !important;
  color:var(--color-accent-soft) !important;
  cursor:default !important; opacity:1 !important;
  font-family:Arial,sans-serif !important;
}}
[class*="st-key-df-running"] button p {{
  font-family:Arial,sans-serif !important; font-size:14px !important;
  line-height:normal !important; font-weight:800 !important;
}}

/* Streamlit puts the visibility toggle *inside* the input's root element, so bordering the inner
   <input> draws a second box that stops short of the eye — password fields then read as narrower
   than text fields. The border belongs to the root; the input itself is transparent. */
[data-testid="stTextInputRootElement"],
.stTextArea [data-baseweb="base-input"],
.stSelectbox div[data-baseweb="select"] > div {{
  background:var(--color-surface-muted) !important;
  border-radius:10px !important; border:1px solid var(--color-divider) !important;
  box-shadow:none !important;
}}
[data-testid="stTextInputRootElement"]:focus-within,
.stTextArea [data-baseweb="base-input"]:focus-within {{
  border-color:var(--color-accent-focus) !important;
}}
.st-key-order_id [data-testid="stTextInputRootElement"] {{
  height:40px; min-height:40px;
}}
.st-key-order_id input {{ height:38px; }}
.stTextArea {{ margin-bottom:-2px; }}
.stTextInput input, .stTextArea textarea {{
  background:transparent !important; border:none !important;
  color:var(--color-text) !important; font-family:var(--font-body);
}}
[data-testid="stTextInputRootElement"] button {{ background: transparent !important; }}
.st-key-api_key [data-testid="stTextInputRootElement"] button,
.st-key-openai_key [data-testid="stTextInputRootElement"] button {{ display:none; }}
.stTextInput input {{ font-size:13px; }}
.stTextArea textarea {{ font-size:14px; line-height:1.5; padding:14px; }}
div[data-testid="stElementContainer"].st-key-ticket {{
  overflow:unset !important;
}}
.st-key-ticket,
.st-key-ticket [data-testid="stTextArea"],
.st-key-ticket [data-testid="stTextAreaRootElement"] {{
  width:100% !important; max-width:none !important;
}}
.st-key-ticket [data-testid="stTextArea"] {{
  width:100% !important;
  height:138px !important; min-height:138px !important; max-height:138px !important;
  margin-bottom:-11px !important;
}}
.st-key-ticket [data-testid="stTextAreaRootElement"] {{
  width:100% !important;
  height:112px; min-height:112px; box-sizing:border-box;
  background:var(--color-surface-muted) !important;
  border:1px solid var(--color-divider) !important;
  border-radius:12px !important; box-shadow:none !important;
  overflow:hidden !important;
}}
.st-key-ticket textarea {{
  width:100% !important; height:110px !important; box-sizing:border-box;
  background:transparent !important; border:none !important;
  color:var(--color-text) !important; font-family:var(--font-body) !important;
  font-size:14px !important; line-height:21px !important; padding:14px !important;
  overflow:hidden !important; overflow-y:hidden !important; overflow-x:hidden !important;
  resize:vertical !important;
}}
.st-key-ticket [data-testid="stWidgetLabel"],
.st-key-order_id [data-testid="stWidgetLabel"] {{ align-items:flex-start; }}
.st-key-ticket [data-testid="stWidgetLabel"] p {{
  position:relative; top:6px; line-height:normal !important;
}}
.st-key-order_id [data-testid="stWidgetLabel"] p {{
  position:relative; top:5.5px; line-height:normal !important;
}}
.stTextInput label p, .stTextArea label p, .stSelectbox label p {{
  color:var(--color-text) !important; font-size:12px !important; font-weight:700 !important;
}}
[data-testid="stCaptionContainer"] p {{
  color:var(--color-text-soft) !important; font-size:12px !important; line-height:1.5 !important;
}}

[data-testid="stTabs"] [role="tablist"] {{
  align-items:flex-start; gap:22px; height:30px; min-height:30px;
  border-bottom:1px solid var(--color-divider);
}}
[data-testid="stTabs"] [role="tab"] {{
  align-items:flex-start; justify-content:flex-start;
  height:30px; min-height:30px; padding:0 0 12px;
  font-family:var(--font-body); font-size:13px; line-height:normal; font-weight:700;
  color:var(--color-text-faint);
}}
[data-testid="stTabs"] [role="tab"] p {{
  position:relative; top:.5px;
  font-family:var(--font-body) !important; font-size:13px !important;
  line-height:normal !important; font-weight:700 !important; color:inherit !important;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{ color:var(--color-text); }}
[data-testid="stTabs"] .react-aria-SelectionIndicator {{
  background:var(--color-accent-focus) !important; height:2px !important;
}}
[data-testid="stTabPanel"] {{
  padding-top:18px;
}}
[data-testid="stTabPanel"] > [data-testid="stVerticalBlock"] {{ gap:0; }}
[data-testid="stTabPanel"]
  [data-testid="stElementContainer"]:has([data-testid="stCaptionContainer"]) {{
  margin-bottom:18px;
}}
.st-key-toggle-api-key,
.st-key-toggle-openai-key {{
  display:flex; justify-content:flex-end; width:100% !important;
  height:20px; min-height:20px;
}}
.st-key-toggle-api-key {{
  margin:4px 0 16px;
}}
.st-key-toggle-openai-key {{
  margin:4px 0 0;
}}
.st-key-toggle-api-key .stButton,
.st-key-toggle-openai-key .stButton {{
  display:flex; align-items:center; width:auto !important;
  height:20px; min-height:20px;
}}
.st-key-toggle-api-key button,
.st-key-toggle-openai-key button {{
  width:auto !important; min-width:0 !important; min-height:14px; height:14px;
  padding:0; border:none;
  background:transparent; color:var(--color-accent-ink); font-size:11px;
  transform:translateY(2px);
}}
.st-key-toggle-api-key button p,
.st-key-toggle-openai-key button p {{
  font-family:var(--font-body) !important; font-size:11px !important;
  line-height:normal !important; font-weight:600 !important; color:inherit !important;
}}
.st-key-toggle-api-key button:hover,
.st-key-toggle-openai-key button:hover {{
  border:none; background:transparent; color:var(--color-accent);
}}

.st-key-base_url {{ margin-bottom:16px; }}
.st-key-api_key,
.st-key-openai_key {{ margin-bottom:0; }}
.st-key-base_url [data-testid="stTextInputRootElement"],
.st-key-api_key [data-testid="stTextInputRootElement"],
.st-key-openai_key [data-testid="stTextInputRootElement"] {{
  height:37px; min-height:37px;
}}
.st-key-base_url [data-testid="stWidgetLabel"],
.st-key-api_key [data-testid="stWidgetLabel"],
.st-key-openai_key [data-testid="stWidgetLabel"] {{
  align-items:flex-start; height:15px; min-height:15px;
  margin:0 0 8px; padding:0;
}}
.st-key-base_url input,
.st-key-api_key input,
.st-key-openai_key input {{
  font-family:Arial,sans-serif !important; font-size:13px !important;
}}
.st-key-base_url [data-testid="InputInstructions"],
.st-key-api_key [data-testid="InputInstructions"],
.st-key-openai_key [data-testid="InputInstructions"] {{ display:none; }}
.st-key-base_url label p,
.st-key-api_key label p,
.st-key-openai_key label p {{
  font-family:var(--font-body) !important; font-size:12px !important;
  line-height:normal !important; font-weight:700 !important;
}}

/* Every primary column is a white card with the reference's 20px radius and subtle lift.
   Streamlit 1.60 represents a bordered container as a layout wrapper whose direct child carries
   the actual border, so target that stable relationship instead of an old generated wrapper. */
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]
  > [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] {{
  border:1px solid var(--color-divider) !important; border-radius:20px !important;
  background:var(--color-surface) !important; padding:24px !important;
  box-shadow:0 2px 10px rgba(23,20,15,.04) !important;
}}
.st-key-df-run-panel {{ min-height:266px; }}

.df-model-row {{
  display:flex; flex-direction:column; justify-content:flex-start;
  height:30.5px; min-height:30.5px; line-height:normal;
}}
.df-model-row b {{
  font-family:var(--font-body); font-size:13px; line-height:15.5px; font-weight:700;
}}
.df-model-selection {{
  margin-top:2px; color:var(--color-text-faint);
  font-family:var(--font-body); font-size:11px; line-height:13px;
}}
.st-key-model-row-classifier,
.st-key-model-row-researcher,
.st-key-model-row-responder,
.st-key-model-row-reviewer {{
  height:30.5px; min-height:30.5px; margin-bottom:16px;
}}
.st-key-model-row-classifier [data-testid="stHorizontalBlock"],
.st-key-model-row-researcher [data-testid="stHorizontalBlock"],
.st-key-model-row-responder [data-testid="stHorizontalBlock"],
.st-key-model-row-reviewer [data-testid="stHorizontalBlock"] {{
  align-items:center; gap:0; height:30.5px; min-height:30.5px;
}}
.st-key-model-row-classifier [data-testid="stColumn"]:first-child,
.st-key-model-row-researcher [data-testid="stColumn"]:first-child,
.st-key-model-row-responder [data-testid="stColumn"]:first-child,
.st-key-model-row-reviewer [data-testid="stColumn"]:first-child {{
  align-self:flex-start; margin-top:0 !important; margin-bottom:0 !important;
}}
.st-key-open-classifier button,
.st-key-open-researcher button,
.st-key-open-responder button,
.st-key-open-reviewer button {{
  width:74px; min-width:74px; height:28px; min-height:28px;
  padding:6px 14px; border:1px solid var(--color-text);
  border-radius:999px; background:transparent; color:var(--color-text);
  font-family:Arial,sans-serif !important; font-size:12px; line-height:normal; font-weight:700;
}}
.st-key-open-classifier button p,
.st-key-open-researcher button p,
.st-key-open-responder button p,
.st-key-open-reviewer button p {{
  font-family:Arial,sans-serif !important; font-size:12px !important;
  line-height:normal !important; font-weight:700 !important;
}}
.st-key-open-classifier button:hover,
.st-key-open-researcher button:hover,
.st-key-open-responder button:hover,
.st-key-open-reviewer button:hover {{
  border-color:var(--color-text); background:var(--color-surface-muted);
}}
/* Apply, in the model dialog, stays put on hover. It is the only primary action on screen at that
   point, so the brightness shift signalled nothing and just read as a wobble. */
.st-key-picker-apply button:hover:not(:disabled) {{
  filter:none;
  background:linear-gradient(135deg,var(--color-accent-bright),var(--color-accent));
  border-color:transparent; color:var(--color-accent-soft);
}}
.df-sr-only {{
  position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden;
  clip:rect(0,0,0,0); white-space:nowrap; border:0;
}}
.df-eyebrow {{
  display:block; margin-bottom:14px;
  font-family:var(--font-body); font-size:12px; line-height:normal;
  letter-spacing:.08em;
  font-weight:800; color:var(--color-accent-ink);
}}
.df-quiet {{ color:var(--color-text-soft); }}
.df-mono {{ font-family:var(--mono); font-size:12px; }}
.df-progress-row {{ position:relative; }}
.df-progress-row:first-child {{ margin-top:1px; }}
.df-progress-name {{
  display:block; color:var(--color-text); font-family:var(--font-body);
  font-size:13px;
  font-weight:700; line-height:16px;
}}
.df-progress-row.df-state-pending .df-progress-name {{
  color:var(--color-text-faint); font-weight:500;
}}
.df-progress-note {{
  display:block; margin-top:2px; font-family:var(--font-body);
  font-size:11px; line-height:normal;
}}
.df-progress-row.df-has-detail {{ cursor:default; }}
.df-progress-row.df-has-detail .df-progress-name {{
  text-decoration:underline dotted var(--color-text-faint); text-underline-offset:4px;
}}
.df-progress-tip {{
  visibility:hidden; opacity:0; pointer-events:none;
  position:absolute; z-index:20; top:100%; left:0;
  width:min(260px,calc(100vw - 88px)); max-height:220px; overflow:auto;
  margin-top:6px; padding:14px 16px; border:1px solid var(--color-divider);
  border-radius:12px; background:var(--color-surface); color:#3a3a36;
  box-shadow:0 10px 30px rgba(0,0,0,.12);
  font-family:var(--font-body); font-size:12px; line-height:1.55;
  white-space:pre-line; transition:opacity .12s ease;
}}
.df-progress-row.df-has-detail:hover .df-progress-tip,
.df-progress-row.df-has-detail:focus .df-progress-tip,
.df-progress-row.df-has-detail:focus-within .df-progress-tip {{
  visibility:visible; opacity:1; pointer-events:auto;
}}
.df-loading {{
  position:fixed; left:0; right:0; bottom:0; height:3px;
  background:#edede8; z-index:999; overflow:hidden;
}}
.df-loading span {{
  position:absolute; top:0; bottom:0; width:30%;
  background:linear-gradient(90deg,var(--color-accent-bright),var(--color-accent-focus));
  animation:df-loading 1.1s ease-in-out infinite;
}}

.st-key-df-output {{ margin-top:20px; }}
.st-key-df-output [data-testid="stAlertContainer"] {{
  min-height:56px; box-sizing:border-box; border-radius:8px;
}}
.st-key-df-output [data-testid="stAlertContainer"] p {{
  font-family:var(--font-body) !important; font-size:16px !important; line-height:24px !important;
}}
.st-key-df-result {{ margin-top:0; }}
.df-result-stack {{ font-family:var(--font-body); }}
.df-result-banner {{
  min-height:56px; box-sizing:border-box;
  font-family:var(--font-body); line-height:normal;
}}
.df-result-heading {{
  margin:36px 0 14px !important; padding:0 !important;
  font-family:var(--font-heading) !important; font-size:26px !important;
  font-weight:800 !important; line-height:normal !important;
  letter-spacing:-.02em !important; color:var(--color-text) !important;
}}
.df-result-heading a {{ display:none !important; }}
.df-result-caption {{
  margin:10px 22px 0; color:var(--color-text-faint);
  font-family:var(--font-body); font-size:13px; line-height:1.5;
}}
.df-result-stack blockquote.df-result-draft {{
  margin:0 !important; padding:18px 22px !important;
  border-radius:0 12px 12px 0 !important;
  background:var(--color-surface-muted) !important; color:#2e2a22 !important;
  font-family:var(--font-body) !important; font-size:14px !important;
  line-height:1.6 !important;
}}
.df-result-empty {{
  margin:0; color:var(--color-text-faint);
  font-family:var(--font-body); font-size:13px; line-height:1.5;
}}
.df-result-footer-space {{ height:32px; }}

.df-tool-table {{
  width:100%; overflow:hidden; border:1px solid var(--color-divider);
  border-radius:16px; background:var(--color-surface); font-family:var(--font-body);
}}
.df-tool-table table {{
  width:100%; border-collapse:collapse; font-family:var(--font-body);
  font-size:13px; line-height:normal; margin:0 !important;
}}
.df-tool-table th {{
  padding:12px 16px; background:var(--color-surface-muted); text-align:left;
  color:var(--color-text-soft); font-size:11px; font-weight:700; letter-spacing:.04em;
  line-height:13.5px; border:0 !important;
}}
.df-tool-table tr {{ border:0 !important; }}
.df-tool-table tbody tr {{
  border-top:1px solid var(--color-divider) !important;
}}
.df-tool-table td {{
  padding:12px 16px; border:0 !important; line-height:16px;
}}
.df-tool-table .df-mono {{
  font-family:'SF Mono',monospace !important; font-size:13px !important;
}}
.df-tool-table .df-ok {{ color:var(--color-success); font-weight:700; }}
.df-tool-table .df-blocked, .df-tool-table .df-failed {{
  color:var(--color-danger-ink); font-weight:700;
}}
.df-tool-table .df-soft {{ color:var(--color-text-soft); }}

.stLinkButton a {{
  min-height:auto; padding:12px 22px; border:none; border-radius:999px;
  background:var(--color-text); color:#fff; font-size:13px; font-weight:700;
}}
.stLinkButton a:hover {{ background:#2b2b2b; color:#fff; border:none; }}
.st-key-df-result .stLinkButton a,
.st-key-df-result .stLinkButton a p {{
  font-family:Arial,sans-serif !important; font-size:13px !important;
  line-height:normal !important; font-weight:700 !important;
}}

[data-testid="stDialog"] [role="dialog"] {{
  border-radius:20px; box-shadow:0 20px 60px rgba(0,0,0,.25);
}}

/* The global h1-h4 rule near the top of this sheet zeroes padding with !important, which also
   strips Streamlit's own dialog-title padding — that is why the title ends up flush against the
   modal edge while the body below keeps its inset. Put it back so "Classifier model" lines up
   with "Provider" underneath. */
[data-testid="stDialog"] h2 {{
  padding:1.5rem 1.5rem .75rem !important;
}}

@media (max-width: 900px) {{
  [data-testid="stMainBlockContainer"] {{ padding:0 24px 64px; }}
  .df-header {{ padding:18px 24px; }}
  .df-crew-line {{ display:none; }}
  .df-intro {{ padding:48px 0 12px; }}
}}
@media (max-width: 560px) {{
  [data-testid="stMainBlockContainer"] {{ padding:0 16px 48px; }}
  .df-header {{ padding:16px; }}
  .df-live-badge {{ display:none; }}
  .df-intro h1 {{ font-size:34px !important; }}
}}
</style>"""


def header_html() -> str:
    """Full-width product bar from the selected redesign."""
    return (
        '<div class="df-header">'
        '<div class="df-brand">'
        '<span class="df-wordmark">DeskFleet</span>'
        '<span class="df-live-badge">LIVE DEMO</span>'
        "</div>"
        '<span class="df-crew-line">Classifier → Researcher → Responder → Reviewer</span>'
        "</div>"
    )


def intro_html() -> str:
    return (
        '<div class="df-intro">'
        '<span class="df-eyebrow">RESOLVE A TICKET</span>'
        '<h1 style="font-size:clamp(34px,3.4vw,44px);line-height:1.05;margin:0 0 14px;">'
        "Hand the crew a support ticket.</h1>"
        '<p style="font-size:15px;line-height:1.6;max-width:640px;margin:0 0 36px;" '
        'class="df-quiet">Pick a preset or write your own, then resolve it and watch each node '
        "work in real time. Every run goes to the service you point at below.</p></div>"
    )


def section_label_html(text: str, top: int = 0, bottom: int = 10) -> str:
    return (
        '<div style="font-family:var(--font-body);font-size:11px;font-weight:800;'
        "line-height:normal;letter-spacing:.08em;text-transform:uppercase;"
        f'margin:{top}px 0 {bottom}px;color:var(--color-text-faint);">{escape(text)}</div>'
    )


def divider_html(top: int = 12, bottom: int = 16) -> str:
    return (
        f'<div style="height:1px;background:var(--color-divider);margin:{top}px 0 {bottom}px">'
        "</div>"
    )


def quiet_text_html(text: str) -> str:
    return (
        '<div style="font-family:var(--font-body);font-size:12px;line-height:normal;'
        'color:var(--color-text-faint);">'
        f"{escape(text)}</div>"
    )


def model_row_html(summary: str) -> str:
    """Render the node name and its selection on separate lines like the redesign."""
    node, sep, selection = summary.partition("·")
    if not sep:
        return f'<div class="df-model-row"><span>{escape(summary)}</span></div>'
    return (
        f'<div class="df-model-row"><b>{escape(node.strip())}</b>'
        '<span class="df-sr-only"> · </span>'
        f'<span class="df-model-selection">{escape(selection.strip())}</span></div>'
    )


def progress_row_html(label: str, state: str, note: str, detail: str = "") -> str:
    """One node's line: dot, name, and whatever the node reported when it finished."""
    resolved_state = state if state in NODE_DOTS else "pending"
    dot = NODE_DOTS[resolved_state]
    note = note.strip()
    detail = detail.strip()
    if resolved_state == "active" and not detail:
        detail = f"{label} is currently working."
    row_classes = ["df-progress-row", f"df-state-{resolved_state}"]
    if detail:
        row_classes.append("df-has-detail")
    row_class = " ".join(row_classes)
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
        'gap:10px;margin-bottom:14px;">'
        f'<span style="flex:none;margin-top:3px;width:9px;height:9px;border-radius:50%;'
        f'background:{dot["fill"]};box-shadow:{dot["ring"]};animation:{dot["anim"]};"></span>'
        '<span style="flex:1;min-width:0;">'
        f'<span class="df-progress-name">{escape(label)}</span>'
        f'<span class="df-progress-note df-quiet">{escape(note)}</span></span>'
        f"{tooltip}"
        "</div>"
    )


def tool_line_html(row: dict[str, Any]) -> str:
    """The live feed's compact form. The table with the detail column comes after the run."""
    status = str(row.get("Status", ""))
    colour = (
        "var(--color-danger-ink)"
        if "blocked" in status
        else "var(--color-success-muted)"
        if "ok" in status
        else "var(--color-text-faint)"
    )
    return (
        '<div style="margin-bottom:10px;">'
        f'<div class="df-mono" style="font-weight:600;color:var(--color-text);">'
        f"{escape(str(row.get('Tool', '')))}</div>"
        f'<div style="font-size:11px;margin-top:2px;font-weight:600;color:{colour};">'
        f"{escape(status)} · {escape(str(row.get('Latency', '')))}</div>"
        "</div>"
    )


def banner_html(decision: str | None, label: str, reason: str) -> str:
    colours = DECISION_COLOURS.get((decision or "").lower(), UNKNOWN_COLOURS)
    tail = f" — {escape(reason)}" if reason else ""
    return (
        f'<div class="df-result-banner" style="display:flex;align-items:center;'
        f"flex-wrap:wrap;gap:14px;"
        f"padding:18px 22px;border-radius:16px;background:{colours['bg']};"
        f'animation:df-in .35s ease;">'
        f'<span style="flex:none;width:9px;height:9px;border-radius:50%;'
        f'background:{colours["dot"]};"></span>'
        f'<span style="font-size:13px;font-weight:800;letter-spacing:.03em;'
        f'color:{colours["ink"]};">{escape(label)}</span>'
        f'<span style="font-size:13px;color:#5b5346;">{escape(colours["sub"])}{tail}</span>'
        "</div>"
    )


def draft_html(body: str, approved: bool) -> str:
    """An unapproved draft is tinted differently so it cannot be mistaken for a sent reply."""
    edge = "var(--color-success)" if approved else "var(--color-danger)"
    return (
        f'<blockquote class="df-result-draft" style="border-left:3px solid {edge};">'
        f"{escape(body)}</blockquote>"
    )


def result_heading_html(text: str) -> str:
    return f'<h2 class="df-result-heading">{escape(text)}</h2>'


def result_caption_html(text: str) -> str:
    return f'<p class="df-result-caption">{escape(text)}</p>'


def result_empty_html(text: str) -> str:
    return f'<p class="df-result-empty">{escape(text)}</p>'


def result_footer_space_html() -> str:
    return '<div class="df-result-footer-space" aria-hidden="true"></div>'


def result_stack_html(blocks: list[str]) -> str:
    return '<div class="df-result-stack">' + "".join(blocks) + "</div>"


def meta_html(cost_line: str, ticket_id: str) -> str:
    return (
        '<div style="display:flex;flex-wrap:wrap;gap:8px 22px;align-items:center;'
        'font-size:12px;margin-top:6px;color:var(--color-text-faint);">'
        f'<span class="df-mono">{escape(cost_line)}</span>'
        f'<span>Ticket <span class="df-mono">{escape(ticket_id)}</span></span>'
        "</div>"
    )


def loading_html() -> str:
    """Fixed progress rail used while the streamed run is waiting or advancing."""
    return (
        '<div class="df-loading" role="status" aria-label="Resolving your ticket">'
        "<span></span></div>"
    )


def tool_table_html(rows: list[dict[str, Any]]) -> str:
    """Accessible, responsive table matching the selected design."""
    cells = []
    for row in rows:
        status = str(row.get("Status", ""))
        tone = "df-blocked" if "blocked" in status else "df-ok" if "ok" in status else "df-failed"
        if "blocked" in status:
            display_status = "● blocked"
        elif "ok" in status:
            display_status = "● ok"
        elif "failed" in status:
            display_status = "● failed"
        else:
            display_status = status
        full_detail = str(row.get("Detail", ""))
        compact_detail = (
            full_detail if len(full_detail) <= 96 else full_detail[:93].rstrip() + "..."
        )
        cells.append(
            "<tr>"
            f'<td class="df-mono">{escape(str(row.get("Tool", "")))}</td>'
            f'<td class="{tone}">{escape(display_status)}</td>'
            f'<td class="df-soft">{escape(str(row.get("Latency", "")))}</td>'
            f'<td class="df-mono df-soft">{escape(str(row.get("Arguments", "")))}</td>'
            f'<td class="df-soft" title="{escape(full_detail, quote=True)}">'
            f"{escape(compact_detail)}</td>"
            "</tr>"
        )
    return (
        '<div class="df-tool-table"><table><thead><tr>'
        "<th>TOOL</th><th>STATUS</th><th>LATENCY</th><th>ARGUMENTS</th><th>DETAIL</th>"
        "</tr></thead><tbody>" + "".join(cells) + "</tbody></table></div>"
    )
