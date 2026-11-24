"""
branding.py — CSS injection, animated SVG logo, and enterprise header.

Call apply_styles() once immediately after st.set_page_config().
Then call render_header() (main app) or render_login_page() (login page).
No business logic; no data access; no external images or files.
"""

import streamlit as st

# ---------------------------------------------------------------------------
# App identity
# ---------------------------------------------------------------------------

APP_TITLE   = "Procurement Health Check"
APP_CAPTION = "Government of Canada open data"

LEGAL_FOOTER = (
    "Independent tool using Government of Canada open data. "
    "Not affiliated with or endorsed by the Government of Canada. "
    "Contains information licensed under the "
    '<a href="https://open.canada.ca/en/open-government-licence-canada" '
    'target="_blank" rel="noopener noreferrer" '
    'style="color:#525252;">Open Government Licence\u00a0–\u00a0Canada</a>.'
)

# ---------------------------------------------------------------------------
# SVG logo helpers
# ---------------------------------------------------------------------------

def logo_html(size: int = 32) -> str:
    """Return the animated 'procurement health' logo as inline HTML/SVG.

    A rounded blue tile with three ascending bars (spending) and a
    heartbeat line across them (health check). The heartbeat line redraws
    every few seconds; animation is disabled for prefers-reduced-motion.
    """
    uid = f"phc-logo-{size}"
    return f"""<span style="display:inline-flex;align-items:center;flex:0 0 auto;">
<style>
@keyframes {uid}-beat {{
  0%   {{ stroke-dashoffset: 140; opacity: .2; }}
  45%  {{ stroke-dashoffset: 0;   opacity: 1; }}
  80%  {{ stroke-dashoffset: 0;   opacity: 1; }}
  100% {{ stroke-dashoffset: 0;   opacity: .2; }}
}}
@keyframes {uid}-glow {{ 0%,100% {{ r: 3.2; }} 50% {{ r: 4.6; }} }}
.{uid}-ecg {{ stroke-dasharray: 140; animation: {uid}-beat 3.2s ease-in-out infinite; }}
.{uid}-dot {{ animation: {uid}-glow 1.6s ease-in-out infinite; }}
@media (prefers-reduced-motion: reduce) {{
  .{uid}-ecg, .{uid}-dot {{ animation: none !important; stroke-dashoffset: 0; opacity: 1; }}
}}
</style>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"
     width="{size}" height="{size}" role="img" aria-label="{APP_TITLE} logo">
  <title>{APP_TITLE}</title>
  <defs>
    <linearGradient id="{uid}-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4589FF"/>
      <stop offset="1" stop-color="#0043CE"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="14" fill="url(#{uid}-bg)"/>
  <rect x="2.5" y="2.5" width="59" height="59" rx="13.5" fill="none"
        stroke="#FFFFFF" stroke-opacity=".18"/>
  <rect x="14" y="36" width="8" height="14" rx="2" fill="#FFFFFF" fill-opacity=".45"/>
  <rect x="28" y="28" width="8" height="22" rx="2" fill="#FFFFFF" fill-opacity=".65"/>
  <rect x="42" y="20" width="8" height="30" rx="2" fill="#FFFFFF" fill-opacity=".85"/>
  <path class="{uid}-ecg" d="M8 31 H20 L24 22 L30 40 L35 16 L40 31 H56"
        fill="none" stroke="#FFFFFF" stroke-width="3.2"
        stroke-linecap="round" stroke-linejoin="round"/>
  <circle class="{uid}-dot" cx="56" cy="31" r="3.2" fill="#FFFFFF"/>
</svg>
</span>"""


# Maple leaf inline SVG (Canadian red, no official wordmark)
_MAPLE_LEAF_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 100 100" '
    'aria-hidden="true" style="vertical-align:middle;margin-right:4px;">'
    '<path fill="#D52B1E" d="M50 5 l8 22 24-4-14 18 6 2-8 20-16-6v18h-1v-18l-16 6-8-20 '
    '6-2L17 23l24 4z"/>'
    '</svg>'
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
<style>
/* ── 1. Hide default Streamlit chrome ─────────────────────────────────── */
#MainMenu,
footer,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stDeployButton"] {
    display: none !important;
}

/* ── 2. Max content width ─────────────────────────────────────────────── */
[data-testid="stAppViewContainer"] > .main .block-container,
[data-testid="stMainBlockContainer"] {
    max-width: 1280px;
    padding-top: 4rem;
}
.phc-header { border-radius: 10px; }
.phc-header-text h1 { padding: 0 !important; }
.phc-header-text .caption { margin-top: 2px !important; }
.phc-header-tag {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: .78rem;
    color: #D0E2FF;
    padding: 6px 12px;
    border: 1px solid rgba(208,226,255,.28);
    border-radius: 999px;
    white-space: nowrap;
}
.phc-header-tag b { color: #FFFFFF; font-weight: 600; }
@media (max-width: 900px) { .phc-header-tag { display: none; } }

/* ── 3. Dark navy top header bar ──────────────────────────────────────── */
.phc-header {
    background: #0B1F3A;
    color: #FFFFFF;
    padding: 14px 32px;
    margin-bottom: 24px;
    width: 100%;
    display: flex;
    align-items: center;
    gap: 14px;
}
.phc-header-text h1 {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
    letter-spacing: .01em;
    color: #FFFFFF;
    line-height: 1.3;
}
.phc-header-text .caption {
    margin: 2px 0 0;
    font-size: .72rem;
    color: #A8C4E0;
    letter-spacing: .04em;
    text-transform: uppercase;
}

/* ── 4. Metric cards ──────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid #DDE1E6;
    border-radius: 8px;
    padding: 16px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,.08);
}
[data-testid="stMetricLabel"] {
    font-size: .78rem;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: #525252;
}
[data-testid="stMetricValue"] {
    font-size: 2rem;
    font-weight: 600;
    color: #161616;
}

/* ── 5. Buttons ───────────────────────────────────────────────────────── */
[data-testid="stButton"] > button,
[data-testid="stDownloadButton"] > button {
    background: #0F62FE !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 4px !important;
    font-weight: 500 !important;
    padding: 10px 20px !important;
    transition: background .15s ease;
}
[data-testid="stButton"] > button:hover,
[data-testid="stDownloadButton"] > button:hover {
    background: #0353E9 !important;
}
[data-testid="stButton"] > button:focus,
[data-testid="stDownloadButton"] > button:focus {
    outline: 3px solid #0F62FE !important;
    outline-offset: 2px !important;
}

/* ── 6. Login page — hide sidebar entirely ────────────────────────────── */
.phc-login-active [data-testid="stSidebar"],
.phc-login-active [data-testid="collapsedControl"] {
    display: none !important;
}

/* ── 7. Login two-column layout ───────────────────────────────────────── */
.phc-login-wrap {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 80vh;
    padding: 24px 16px;
    box-sizing: border-box;
}
.phc-login-inner {
    display: flex;
    gap: 0;
    max-width: 1100px;
    width: 100%;
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,.18);
}

/* Left panel */
.phc-left {
    flex: 55;
    background: linear-gradient(145deg, #0B1F3A 0%, #12306B 100%);
    padding: 48px;
    color: #FFFFFF;
    display: flex;
    flex-direction: column;
    gap: 0;
    min-width: 0;
}
.phc-left-title {
    font-size: 1.75rem;
    font-weight: 700;
    color: #FFFFFF;
    margin: 20px 0 10px;
    line-height: 1.25;
}
.phc-left-tagline {
    font-size: .95rem;
    color: #A8C4E0;
    margin: 0 0 32px;
    line-height: 1.55;
}
.phc-feature {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    margin-bottom: 14px;
}
.phc-feature-icon {
    font-size: 1.1rem;
    flex-shrink: 0;
    margin-top: 1px;
}
.phc-feature-text {
    font-size: .88rem;
    color: #D0E2FF;
    line-height: 1.45;
}
.phc-left-footer {
    margin-top: auto;
    padding-top: 32px;
    font-size: .78rem;
    color: #78A9FF;
    display: flex;
    align-items: center;
    gap: 4px;
}

/* Right panel */
.phc-right {
    flex: 45;
    background: #FFFFFF;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 40px;
    min-width: 0;
}
.phc-card {
    width: 100%;
    max-width: 380px;
}
.phc-card-heading {
    font-size: 1.5rem;
    font-weight: 700;
    color: #161616;
    margin: 0 0 4px;
}
.phc-card-sub {
    font-size: .88rem;
    color: #525252;
    margin: 0 0 28px;
}

/* ── 8. Login page legal footer ───────────────────────────────────────── */
.phc-legal-footer {
    text-align: center;
    max-width: 1100px;
    margin: 20px auto 0;
    padding: 0 16px;
    font-size: .75rem;
    color: #6e6e6e;
    line-height: 1.6;
}

/* ── 9. Responsive: stack below 900 px ───────────────────────────────── */
@media (max-width: 900px) {
    .phc-login-inner {
        flex-direction: column;
        border-radius: 12px;
    }
    .phc-left  { padding: 32px 24px; }
    .phc-right { padding: 32px 24px; justify-content: flex-start; }
}
</style>
"""

_CHECK_SVG = (
    '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">'
    '<path fill="none" stroke="#78A9FF" stroke-width="2.2" stroke-linecap="round" '
    'stroke-linejoin="round" d="M3 8.5l3.2 3L13 4.5"/></svg>'
)

# Injected only while the login page is shown.
_LOGIN_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
[data-testid="stAppViewContainer"], [data-testid="stMain"] { background: #F2F4F8 !important; }
.stApp, [data-testid="stApp"] { background: #F2F4F8 !important; }
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stMainBlockContainer"], .block-container {
    max-width: 1000px !important; padding-top: 9vh !important; padding-bottom: 2rem !important;
}
/* The two columns become one card */
[data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"],
.block-container [data-testid="stHorizontalBlock"] {
    gap: 0 !important; background: #FFFFFF; border-radius: 14px; overflow: hidden;
    box-shadow: 0 1px 2px rgba(16,24,40,.06), 0 12px 32px rgba(16,24,40,.12);
    align-items: stretch !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
[data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {
    background: linear-gradient(150deg, #0B1F3A 0%, #102A5C 60%, #153A80 100%);
    padding: 44px 44px 36px !important;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child,
[data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {
    padding: 48px 48px 40px !important; display: flex; flex-direction: column;
    justify-content: center;
}
.phc-l { color: #FFFFFF; }
.phc-l-brand { display: flex; align-items: center; gap: 12px; font-weight: 600;
    font-size: 1.05rem; letter-spacing: .01em; color: #FFFFFF; }
.phc-l-head { font-size: 1.6rem; font-weight: 600; line-height: 1.3; margin: 34px 0 10px;
    color: #FFFFFF; }
.phc-l-sub { font-size: .9rem; line-height: 1.55; color: #A8C4E0; margin-bottom: 26px; }
.phc-feats { display: flex; flex-direction: column; gap: 12px; margin-bottom: 30px; }
.phc-feat { display: flex; align-items: center; gap: 12px; font-size: .9rem; color: #E0EBFF; }
.phc-feat-ico { display: inline-flex; align-items: center; justify-content: center;
    width: 26px; height: 26px; flex: 0 0 26px; border-radius: 6px;
    background: rgba(120,169,255,.16); }
.phc-stats { display: flex; gap: 0; border-top: 1px solid rgba(255,255,255,.14);
    border-bottom: 1px solid rgba(255,255,255,.14); padding: 14px 0; margin-bottom: 22px; }
.phc-stats > div { flex: 1; display: flex; flex-direction: column; }
.phc-stats > div + div { padding-left: 16px; border-left: 1px solid rgba(255,255,255,.14); }
.phc-stats b { font-size: 1.15rem; font-weight: 600; color: #FFFFFF; }
.phc-stats span { font-size: .72rem; color: #A8C4E0; text-transform: uppercase;
    letter-spacing: .05em; }
.phc-badges { display: flex; flex-wrap: wrap; gap: 6px; }
.phc-badge { display: inline-flex; align-items: center; gap: 5px; font-size: .7rem;
    color: #D0E2FF; padding: 4px 9px; border-radius: 999px; white-space: nowrap;
    border: 1px solid rgba(208,226,255,.28); background: rgba(255,255,255,.04); }
.phc-badge svg { margin: 0 !important; }
.phc-signin-eyebrow { font-size: .75rem; font-weight: 600; letter-spacing: .08em;
    text-transform: uppercase; color: #0F62FE; margin-bottom: 6px; }
.phc-signin-title { font-size: 1.6rem; font-weight: 600; color: #161616; margin: 0 0 6px; }
.phc-signin-sub { font-size: .88rem; color: #525252; margin: 0 0 22px; line-height: 1.5; }
.phc-signin-note { font-size: .78rem; color: #6F6F6F; margin-top: 14px; line-height: 1.5; }
.phc-legal-footer { max-width: 1000px; margin: 18px auto 0; }
@media (max-width: 900px) {
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  [data-testid="stHorizontalBlock"] > [data-testid="column"] { padding: 28px 24px !important; }
}
</style>
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_styles() -> None:
    """Inject enterprise CSS. Call once immediately after st.set_page_config()."""
    st.markdown(_CSS, unsafe_allow_html=True)


def render_header() -> None:
    """Render the navy header bar with the small (32 px) animated logo."""
    logo = logo_html(size=32)
    html = f"""
<div class="phc-header">
  {logo}
  <div class="phc-header-text">
    <h1>{APP_TITLE}</h1>
    <p class="caption">{APP_CAPTION}</p>
  </div>
  <div class="phc-header-tag">
    {_MAPLE_LEAF_SVG}Built with <b>IBM Bob</b>&nbsp;·&nbsp;Powered by <b>IBM watsonx.ai</b> (Toronto)
  </div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


def render_legal_footer() -> None:
    """Render the centred legal footer (use in both login page and main app)."""
    st.markdown(
        f'<div class="phc-legal-footer">{LEGAL_FOOTER}</div>',
        unsafe_allow_html=True,
    )


def render_login_page(
    lockout_message: str | None,
    form_html_placeholder: str,
) -> None:
    """Render the full enterprise two-column login layout.

    This function outputs the structural HTML.  The actual ``st.form`` widgets
    must be rendered by the caller (auth.py) using Streamlit's native form API
    *after* this function returns, targeting a Streamlit column returned by
    ``_login_right_col()``.

    Because Streamlit's layout model does not allow HTML-injected containers to
    host native widgets, the two-column approach works as follows:

    - The LEFT panel is pure HTML injected via ``st.markdown``.
    - The RIGHT panel reuses a real ``st.columns`` split that visually matches
      the HTML proportions.

    ``render_login_page`` is therefore a *coordinator*: it draws the left panel
    via HTML, then returns the right Streamlit column so ``auth.py`` can place
    the form there.
    """
    # Login-only styles: grey page, one centred card built from the two
    # Streamlit columns (navy left column, white right column).
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    logo = logo_html(size=56)
    features = "".join(
        f'<div class="phc-feat"><span class="phc-feat-ico">{_CHECK_SVG}</span>'
        f'<span>{feat_text}</span></div>'
        for feat_text in (
            "Real Government of Canada contract data, 20 federal departments",
            "Health score, red flags, competition and trends",
            "AI audit brief by IBM watsonx.ai, hosted in Canada",
        )
    )
    left_html = f"""
<div class="phc-l">
  <div class="phc-l-brand">{logo}<span>{APP_TITLE}</span></div>
  <div class="phc-l-head">Know how healthy a federal department's buying is — in one click.</div>
  <div class="phc-l-sub">Concentration, competition and red-flag indicators from
    the Proactive Disclosure of Contracts, with an AI-drafted audit brief.</div>
  <div class="phc-feats">{features}</div>
  <div class="phc-stats">
    <div><b>20</b><span>departments</span></div>
    <div><b>1.3M+</b><span>contracts</span></div>
    <div><b>Hourly</b><span>data refresh</span></div>
  </div>
  <div class="phc-badges">
    <span class="phc-badge">{_MAPLE_LEAF_SVG}Canadian open data</span>
    <span class="phc-badge">Built with IBM Bob · IBM watsonx.ai</span>
  </div>
</div>"""

    left_col, right_col = st.columns([11, 10], gap=None)
    with left_col:
        st.markdown(left_html, unsafe_allow_html=True)
    return right_col


# Keep old name as alias so any code that imports render_login_logo still works
def render_login_logo() -> None:  # pragma: no cover
    logo = logo_html(size=120)
    st.markdown(
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'gap:12px;padding:32px 0 20px 0;">{logo}</div>',
        unsafe_allow_html=True,
    )
