"""
app.py — Streamlit UI for the Procurement Health Check tool.

UI-only: all business logic lives in concentration.py, analytics.py, and data_client.py.
Tab structure:
  Overview | Concentration | Competition | Red flags | Trends | Vendors & regions | AI audit brief
"""

import io
import csv
import datetime

import altair as alt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from auth import require_login, render_signout_button
from branding import apply_styles, render_header, render_legal_footer
from data_client import fetch_contracts, fetch_many, load_code_labels, register_allowed_orgs
from ai_brief import generate_brief, brief_to_html, is_watsonx_available
from concentration import (
    vendor_shares,
    hhi,
    band,
    top_vendor,
    noncompetitive_share,
    flags,
    normalize_vendor,
    _parse_value,
)
from analytics import (
    value_vs_count_share,
    largest_contract_share,
    competition_breakdown,
    split_purchase_clusters,
    amendment_flags,
    monthly_trend,
    province_from_postal,
    health_score,
    health_band,
    compare_departments,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEPARTMENTS: dict[str, str] = {
    "ssc-spc":   "Shared Services Canada",
    "dnd-mdn":   "National Defence",
    "cra-arc":   "Canada Revenue Agency",
    "esdc-edsc": "Employment and Social Development Canada",
    "rcmp-grc":  "Royal Canadian Mounted Police",
    "tc":         "Transport Canada",
    "hc-sc":     "Health Canada",
    "tbs-sct":   "Treasury Board of Canada Secretariat",
    # Added 2026-11-24 — owner_org codes verified against the live dataset
    "pwgsc-tpsgc": "Public Services and Procurement Canada",
    "ic":          "Innovation, Science and Economic Development Canada",
    "statcan":     "Statistics Canada",
    "cic":         "Immigration, Refugees and Citizenship Canada",
    "cbsa-asfc":   "Canada Border Services Agency",
    "ec":          "Environment and Climate Change Canada",
    "dfo-mpo":     "Fisheries and Oceans Canada",
    "csc-scc":     "Correctional Service of Canada",
    "nrcan-rncan": "Natural Resources Canada",
    "aafc-aac":    "Agriculture and Agri-Food Canada",
    "pco-bcp":     "Privy Council Office",
    "ps-sp":       "Public Safety Canada",
}

# Register permitted slugs so data_client rejects arbitrary owner_org values
register_allowed_orgs(set(DEPARTMENTS.keys()))

CACHED_DATA_DATE = "2026-11-24"

BADGE_CSS = {
    "Low":      "background:#1a7f37;color:#fff;padding:4px 14px;border-radius:12px;font-weight:600;font-size:1.05rem;",
    "Moderate": "background:#bf8700;color:#fff;padding:4px 14px;border-radius:12px;font-weight:600;font-size:1.05rem;",
    "High":     "background:#cf222e;color:#fff;padding:4px 14px;border-radius:12px;font-weight:600;font-size:1.05rem;",
}

FOOTER_TEXT = (
    "**Data source:** "
    "[Open Government Portal — Proactive Disclosure of Contracts]"
    "(https://open.canada.ca/data/en/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b)  \n"
    "**HHI bands** (Low < 1 000, Moderate 1 000–1 800, High > 1 800) are adapted from the "
    "[2023 US DOJ/FTC Merger Guidelines](https://www.justice.gov/atr/2023-merger-guidelines) "
    "and are **indicators only** — they do not constitute findings of wrongdoing."
)

def _render_app_footer() -> None:
    """Render the data-source/HHI note followed by the legal footer."""
    st.divider()
    st.markdown(FOOTER_TEXT)
    render_legal_footer()


TAB_GUIDE = [
    ("📊 Overview", "A 0–100 health score built from concentration, competition, "
     "vendor diversity and red flags, with the key findings in plain English."),
    ("🏢 Concentration", "Shows whether spending is spread across many vendors or "
     "locked into a few. HHI above 1,800 means highly concentrated."),
    ("⚖️ Competition", "Shows how contracts were awarded, why some were not competed, "
     "and how many competitions attracted only one bid."),
    ("🚩 Red flags", "Contracts that merit a closer look: possible split purchases just "
     "under a threshold, large amendments, and single-bid competitions."),
    ("📈 Trends", "How spending, concentration and competition change month by month."),
    ("🔎 Vendors & regions", f"Look up any vendor across all {len(DEPARTMENTS)} departments "
     "and see where suppliers are located by province."),
    ("✨ AI audit brief", "IBM watsonx.ai, hosted in Toronto, drafts an audit brief from "
     "the computed facts only. Review before use."),
]


def _render_about(show_tab_guide: bool = False) -> None:
    """Bordered 'About this application' box for first-time users."""
    with st.container(border=True):
        st.markdown("#### ℹ️ About this application")
        st.markdown(
            "**Procurement Health Check** gives auditors, procurement officers, "
            "journalists and citizens a one-click health check of a federal "
            "department's contracting, using the Government of Canada's "
            "[Proactive Disclosure of Contracts]"
            "(https://open.canada.ca/data/en/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b) "
            "data. It measures how concentrated spending is, how much was bought "
            "without competition, which contracts deserve a closer look, and how "
            "this is changing over time, then drafts an audit brief with IBM "
            "watsonx.ai. **Results are indicators for review, not findings of "
            "wrongdoing.**"
        )
        st.markdown(
            "**How to use:**\n"
            "1. Pick a department in the sidebar.\n"
            "2. Optionally filter by keyword.\n"
            "3. Click **Check**, then explore the tabs and generate the AI brief."
        )
        if show_tab_guide:
            st.markdown("**What each tab does:**")
            st.markdown("\n".join(f"- **{name}** — {desc}" for name, desc in TAB_GUIDE))

# ---------------------------------------------------------------------------
# Page config — must be the very first Streamlit call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Procurement Health Check",
    page_icon="🇨🇦",
    layout="wide",
)
apply_styles()
require_login()
render_header()

# ---------------------------------------------------------------------------
# Cached data fetch
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def _cached_fetch(owner_org: str) -> tuple[list[dict], bool, int]:
    return fetch_contracts(owner_org)


@st.cache_data(ttl=86400)
def _cached_labels() -> dict:
    return load_code_labels()


# ---------------------------------------------------------------------------
# Pure UI helpers
# ---------------------------------------------------------------------------

def _filter_records(records: list[dict], keyword: str) -> list[dict]:
    if not keyword.strip():
        return records
    kw = keyword.strip().lower()
    return [r for r in records if kw in (r.get("description_en") or "").lower()]


def _build_csv(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _vendor_table_rows(shares: dict[str, float], records: list[dict]) -> list[dict]:
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for rec in records:
        vendor = normalize_vendor(rec.get("vendor_name", ""))
        value = _parse_value(rec.get("contract_value", ""))
        if vendor:
            totals[vendor] = totals.get(vendor, 0.0) + value
            counts[vendor] = counts.get(vendor, 0) + 1
    return [
        {
            "Vendor": v,
            "Total Value (CAD)": round(totals.get(v, 0.0), 2),
            "Share (%)": round(share, 2),
            "# Contracts": counts.get(v, 0),
        }
        for v, share in sorted(shares.items(), key=lambda x: x[1], reverse=True)
    ]


def _fmt_money(value: float) -> str:
    """Format a dollar value as $1.2B, $1.2M, $12K, or $1,234 for readability."""
    if value >= 1e9:
        return f"${value/1e9:.1f}B"
    if value >= 1e6:
        return f"${value/1e6:.1f}M"
    if value >= 1e3:
        return f"${value/1e3:.0f}K"
    return f"${value:,.0f}"


def _truncate(text: str, n: int = 30) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


# ---------------------------------------------------------------------------
# Plotly semicircle gauge
# ---------------------------------------------------------------------------

def _gauge_chart(score: int) -> go.Figure:
    if score >= 75:
        bar_color = "#1a7f37"
    elif score >= 50:
        bar_color = "#bf8700"
    else:
        bar_color = "#cf222e"

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"font": {"size": 48, "color": "#161616"}, "suffix": ""},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#6e6e6e",
                     "tickvals": [0, 25, 50, 75, 100]},
            "bar": {"color": bar_color, "thickness": 0.3},
            "bgcolor": "#f4f4f4",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 50],  "color": "#fff0f0"},
                {"range": [50, 75], "color": "#fff8e6"},
                {"range": [75, 100],"color": "#f0fff4"},
            ],
            "threshold": {
                "line": {"color": bar_color, "width": 3},
                "thickness": 0.75,
                "value": score,
            },
        },
    ))
    fig.update_layout(
        height=240,
        margin={"t": 20, "b": 0, "l": 20, "r": 20},
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "system-ui, sans-serif"},
    )
    return fig


# ---------------------------------------------------------------------------
# Altair horizontal bar chart — top 10 vendors
# ---------------------------------------------------------------------------

def _vendor_bar_chart(table_rows: list[dict]) -> alt.Chart:
    top10 = table_rows[:10]
    df = pd.DataFrame([
        {
            "Vendor": r["Vendor"],
            "Label": _truncate(r["Vendor"], 30),
            "Share": r["Share (%)"],
            "Total": _fmt_money(r["Total Value (CAD)"]),
        }
        for r in top10
    ])
    # Sort order: descending share → largest at top
    sort_order = df.sort_values("Share", ascending=False)["Label"].tolist()

    base = alt.Chart(df).encode(
        y=alt.Y("Label:N", sort=sort_order, title=None,
                axis=alt.Axis(labelLimit=220, labelFontSize=12)),
        tooltip=[
            alt.Tooltip("Vendor:N", title="Vendor"),
            alt.Tooltip("Total:N", title="Total Value"),
            alt.Tooltip("Share:Q", title="Share (%)", format=".2f"),
        ],
    )

    bars = base.mark_bar(color="#0F62FE", cornerRadiusTopRight=3,
                         cornerRadiusBottomRight=3).encode(
        x=alt.X("Share:Q", title="Share of total value (%)",
                axis=alt.Axis(grid=False, format=".1f")),
    )

    text = base.mark_text(align="left", dx=4, fontSize=11, color="#161616").encode(
        x=alt.X("Share:Q"),
        text=alt.Text("Share:Q", format=".1f"),
    )

    return (bars + text).properties(height=max(200, len(top10) * 32)).configure_view(
        strokeWidth=0
    ).configure_axis(
        labelColor="#525252", titleColor="#525252", domainColor="#dde1e6"
    )


# ---------------------------------------------------------------------------
# Key-findings bullet generator
# ---------------------------------------------------------------------------

def _key_findings(
    records: list[dict],
    shares: dict[str, float],
    hhi_score: float,
    nc_pct: float,
    labels: dict,
) -> list[str]:
    findings: list[str] = []

    # Largest single contract
    lc = largest_contract_share(records)
    if lc.share_pct >= 50:
        findings.append(
            f"One contract ({lc.vendor}, {_fmt_money(lc.value)}) represents "
            f"**{lc.share_pct:.1f}%** of all spending in this result set."
        )

    # Single-bid competitive
    cb = competition_breakdown(records, labels)
    sb = cb.single_bid_competitive["count"]
    if sb > 0:
        findings.append(
            f"**{sb}** competitive contract{'s' if sb != 1 else ''} received "
            f"only one bid, suggesting limited market response."
        )

    # Split-purchase clusters
    clusters = split_purchase_clusters(records)
    if clusters:
        total_in_clusters = sum(c.contract_count for c in clusters)
        findings.append(
            f"**{len(clusters)}** potential split-purchase cluster{'s' if len(clusters) != 1 else ''} "
            f"detected ({total_in_clusters} contracts near the $25 k sole-source threshold)."
        )

    # Large amendments
    afs = amendment_flags(records)
    if afs:
        findings.append(
            f"**{len(afs)}** contract{'s' if len(afs) != 1 else ''} "
            f"{'have' if len(afs) != 1 else 'has'} an amendment exceeding "
            f"50% of the original value and over $100 k."
        )

    # Non-competitive share
    if nc_pct > 50:
        findings.append(
            f"**{nc_pct:.1f}%** of total contract value was awarded non-competitively (sole-source)."
        )

    # HHI
    if hhi_score >= 2500:
        findings.append(
            f"HHI of **{hhi_score:,.0f}** indicates a highly concentrated vendor market."
        )
    elif hhi_score >= 1800:
        findings.append(
            f"HHI of **{hhi_score:,.0f}** indicates moderate-to-high vendor concentration."
        )

    return findings[:5]  # cap at 5


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Analysis settings")

    dept_name = st.selectbox(
        "Department",
        options=list(DEPARTMENTS.keys()),
        format_func=lambda k: DEPARTMENTS[k],
    )

    keyword = st.text_input(
        "Keyword filter (description_en)",
        placeholder="e.g. software, consulting …",
    )

    check = st.button("Check", type="primary", width="stretch")

    st.divider()

    with st.expander("ℹ️ How to use"):
        st.markdown(
            "1. **Pick a department** from the dropdown above.\n"
            "2. Optionally type a **keyword** to filter contracts by description.\n"
            "3. Click **Check** — data loads once and all tabs update instantly.\n"
            "4. Explore the tabs, adjust the split-purchase threshold in **Red flags**, "
            "and generate the **AI audit brief** on the last tab."
        )

    with st.expander("📖 Glossary"):
        st.markdown(
            "**HHI (Herfindahl–Hirschman Index):** Sum of squared vendor-share "
            "percentages. Range 0–10 000. Higher = more concentrated spending. "
            "< 1 000 Low · 1 000–1 800 Moderate · > 1 800 High "
            "(adapted from 2023 US DOJ/FTC Merger Guidelines).\n\n"
            "**Non-competitive (TN):** Contracts with solicitation procedure "
            "code TN (\"Non-Competitive\") — awarded without a competitive "
            "bidding process.\n\n"
            "**Limited tendering reason:** The official reason code a department "
            "reports when a contract is not competed (e.g. exclusive rights, "
            "extreme urgency, no response to a bid solicitation).\n\n"
            "**Single-bid competition:** A contract tendered competitively (TC, OB, "
            "or ST procedure) that received only one bid. The process was open but "
            "the market did not respond.\n\n"
            "**Split purchase:** Two or more contracts to the same vendor, each just "
            "below a threshold, within a short window. This pattern merits review "
            "to confirm the requirement was not divided to avoid competition.\n\n"
            "**Amendment:** A formal change to a contract after it was awarded, "
            "typically increasing the value or extending the term. A large amendment "
            "relative to the original value may indicate poor scope definition."
        )

    st.divider()
    render_signout_button()
    st.divider()
    st.caption(
        "Results reflect Proactive Disclosure data from the "
        "Open Government Portal. Refresh rate: 1 hour."
    )

# ---------------------------------------------------------------------------
# Fetch + store in session_state so tab switches don't re-fetch
# ---------------------------------------------------------------------------

if check:
    with st.spinner(f"Fetching contracts for {DEPARTMENTS.get(dept_name, dept_name)} …"):
        try:
            raw, cached, raw_count = _cached_fetch(dept_name)
            st.session_state["records"]    = raw
            st.session_state["is_cached"]  = cached
            st.session_state["raw_count"]  = raw_count
            st.session_state["dept_name"]  = dept_name
            st.session_state["keyword"]    = keyword
        except RuntimeError as exc:
            st.error(f"**Could not load data.** {exc}")
            st.stop()

# Guard against displaying one department's data under a different department's
# name: if the user has changed the selector without clicking Check, the live
# keyword value must only filter the data that was actually fetched.
_loaded_dept = st.session_state.get("dept_name")
if _loaded_dept and _loaded_dept != dept_name:
    # Different department selected but not yet fetched — ignore the sidebar
    # keyword so it cannot silently filter the wrong department's records.
    keyword = st.session_state.get("keyword", "")

# Guard: nothing shown until at least one successful fetch
if "records" not in st.session_state:
    st.info("👈 Select a department in the sidebar and click **Check** to load results.")
    _render_about(show_tab_guide=True)
    _render_app_footer()
    st.stop()

# Pull from session state (tab switches keep these values)
raw_records = st.session_state["records"]
is_cached   = st.session_state["is_cached"]
raw_count   = st.session_state.get("raw_count", len(raw_records))
active_dept = st.session_state["dept_name"]
# Use the sidebar keyword live (allows re-filter without re-fetching)
records = _filter_records(raw_records, keyword)

# Cached-data banner
if is_cached:
    st.warning(
        f"⚠️ Showing **cached real data from {CACHED_DATA_DATE}** "
        "(live API was unreachable).",
        icon="📦",
    )

# No-records guard
if not records:
    if keyword.strip():
        st.info(
            f"No contracts for **{DEPARTMENTS.get(active_dept, active_dept)}** matched the keyword "
            f'**\"{keyword.strip()}\"**. Try a different term or leave the field blank.'
        )
    else:
        st.info(
            f"No contract records found for **{DEPARTMENTS.get(active_dept, active_dept)}**. "
            "The department may not appear in the dataset yet."
        )
    _render_app_footer()
    st.stop()

# ---------------------------------------------------------------------------
# Pre-compute analytics (once, shared across all tabs)
# ---------------------------------------------------------------------------

labels       = _cached_labels()
shares       = vendor_shares(records)
hhi_score    = hhi(shares)
conc_band    = band(hhi_score)
tv           = top_vendor(shares)
nc_pct       = noncompetitive_share(records)
risk_flags   = flags(shares, records)
table_rows   = _vendor_table_rows(shares, records)
clusters     = split_purchase_clusters(records)
amd_flags    = amendment_flags(records)
total_value  = sum(_parse_value(r.get("contract_value", "")) for r in records)
n_vendors    = len(shares)

flagged_count    = sum(c.contract_count for c in clusters) + len(amd_flags)
flagged_pct      = (flagged_count / len(records) * 100) if records else 0.0
hs               = health_score(hhi_score, nc_pct, tv.share, flagged_pct)
hb               = health_band(hs.score)

# Extra values used by the AI brief facts dict
lc_global        = largest_contract_share(records)
cb_global        = competition_breakdown(records, labels)
sb_count_global  = cb_global.single_bid_competitive["count"]

# Date range from monthly trend (drop "unknown" rows)
_trend_months    = [t.month for t in monthly_trend(records) if t.month != "unknown"]
_date_range      = (
    f"{min(_trend_months)} to {max(_trend_months)}"
    if _trend_months else "—"
)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

(
    tab_overview,
    tab_conc,
    tab_comp,
    tab_red,
    tab_trends,
    tab_vendors,
    tab_ai,
    tab_compare,
) = st.tabs([
    "📊 Overview",
    "🏭 Concentration",
    "⚖️ Competition",
    "🚩 Red flags",
    "📈 Trends",
    "🗺️ Vendors & regions",
    "✨ AI audit brief",
    "🔀 Compare departments",
])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1 — Overview
# ═══════════════════════════════════════════════════════════════════════════

with tab_overview:
    st.subheader(f"Overview — {DEPARTMENTS.get(active_dept, active_dept)}")
    _removed = raw_count - len(raw_records)
    st.caption(
        f"{raw_count:,} rows from the API, "
        f"**{len(raw_records):,} unique contracts** after removing "
        f"{_removed:,} amendment duplicate{'s' if _removed != 1 else ''}."
    )

    # ── About this application (bordered box, shown before results) ─────
    _render_about()

    st.caption(
        "A 0–100 health score built from concentration, competition, vendor diversity "
        "and red flags, with the key findings in plain English. "
        "Not an official Government of Canada rating — not a finding of wrongdoing."
    )

    # ── Gauge + component bars ──────────────────────────────────────────
    g_col, bars_col = st.columns([2, 3], gap="large")

    with g_col:
        badge_style = BADGE_CSS[conc_band]
        st.markdown(
            f"<p style='font-size:0.85rem;color:#525252;margin-bottom:4px;'>"
            f"Concentration band &nbsp;"
            f"<span style='{badge_style}'>{conc_band}</span></p>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(_gauge_chart(hs.score), config={"displayModeBar": False})
        st.markdown(
            f"<p style='text-align:center;font-size:1.1rem;font-weight:600;"
            f"color:#161616;margin-top:-12px;'>{hb}</p>",
            unsafe_allow_html=True,
        )

    with bars_col:
        st.markdown("**Score components**")
        components = [
            ("Concentration", hs.concentration_component, 40),
            ("Competition",   hs.competition_component,   30),
            ("Diversity",     hs.diversity_component,     15),
            ("Red flags",     hs.red_flags_component,     15),
        ]
        for label, val, max_val in components:
            pct = val / max_val * 100 if max_val else 0
            st.markdown(
                f"<div style='margin-bottom:10px;'>"
                f"<div style='display:flex;justify-content:space-between;"
                f"font-size:0.82rem;color:#525252;'>"
                f"<span>{label}</span>"
                f"<span>{val:.1f} / {max_val}</span></div>"
                f"<div style='background:#e0e0e0;border-radius:4px;height:10px;'>"
                f"<div style='background:#0F62FE;width:{pct:.1f}%;height:10px;"
                f"border-radius:4px;'></div></div></div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # ── KPI row ─────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Value",        _fmt_money(total_value),
              help="Sum of all contract_value fields in the filtered result set.")
    k2.metric("Contracts",          f"{len(records):,}",
              help="Total number of contract records returned for this department and filter.")
    k3.metric("Vendors",            f"{n_vendors:,}",
              help="Count of distinct normalised vendor names (uppercased, trimmed).")
    k4.metric("HHI",                f"{hhi_score:,.0f}",
              help="Herfindahl–Hirschman Index (0–10 000). Higher = more concentrated. "
                   "< 1 000 = Low · 1 000–1 800 = Moderate · > 1 800 = High.")
    k5.metric("Non-competitive %",  f"{nc_pct:.1f}%",
              help="Percentage of total contract value awarded without competitive bidding "
                   "(solicitation procedure code TN — sole-source).")

    st.divider()

    # ── Key findings ────────────────────────────────────────────────────
    st.subheader("Key findings")
    findings = _key_findings(records, shares, hhi_score, nc_pct, labels)
    if findings:
        for f in findings:
            st.markdown(f"- {f}")
    else:
        st.markdown("- No significant concentration concerns detected in this result set.")

    for flag in risk_flags:
        st.warning(f"⚠️ **Flag:** {flag.capitalize()}", icon="🚩")

    st.divider()

    # ── About this data expander ─────────────────────────────────────────
    with st.expander("ℹ️ About this data"):
        st.markdown(f"""
**Source:** [Open Government Portal — Proactive Disclosure of Contracts](https://open.canada.ca/data/en/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b)

**API endpoint:** `https://open.canada.ca/data/api/3/action/datastore_search`

**Resource ID:** `fac950c0-00d5-4ec1-a4d3-9cbebf98a305`

**Fields used:** `vendor_name`, `contract_value`, `original_value`, `amendment_value`,
`contract_date`, `solicitation_procedure`, `limited_tendering_reason`, `number_of_bids`,
`vendor_postal_code`, `commodity_type`, `description_en`, `owner_org`, `owner_org_title`,
`reference_number`

**Refresh rate:** Results are cached for 1 hour. Click **Check** again after the cache expires to fetch the latest data.

**Coverage:** Up to 3 000 most recent records per department, sorted by `contract_date desc`.
Contracts predating the department's disclosure threshold or below the reporting floor may not appear.

**Limitations:**
- Vendor names are normalised (uppercased, trimmed) but not deduplicated across spelling variants.
- `contract_value` reflects the value at disclosure time and may differ from final settled amounts.
- HHI bands are adapted from the 2023 US DOJ/FTC Merger Guidelines and are **indicators only**.
- This tool does not access classified, Cabinet-confidential, or below-threshold contracts.
        """)

    _render_app_footer()

# ═══════════════════════════════════════════════════════════════════════════
# TAB 2 — Concentration
# ═══════════════════════════════════════════════════════════════════════════

with tab_conc:
    st.subheader("Vendor concentration")
    st.caption(
        "Shows whether spending is spread across many vendors or locked into a few. "
        "HHI above 1\u202f800 means highly concentrated."
    )
    badge_style = BADGE_CSS[conc_band]
    st.markdown(
        f"Concentration risk &nbsp;"
        f"<span style='{badge_style}'>{conc_band}</span> &nbsp;"
        f"&nbsp; HHI = **{hhi_score:,.0f}**",
        unsafe_allow_html=True,
    )
    st.caption(
        "HHI < 1 000 = Low · 1 000–1 800 = Moderate · > 1 800 = High  "
        "(adapted from 2023 US DOJ/FTC Merger Guidelines — indicator only)"
    )

    # Metrics row
    c1, c2, c3 = st.columns(3)
    c1.metric("HHI Score",         f"{hhi_score:,.0f}",
              help="Herfindahl–Hirschman Index: sum of squared vendor share percentages. "
                   "Range 0–10 000. Higher values indicate greater vendor concentration.")
    c2.metric("Top Vendor Share",  f"{tv.share:.1f}%",
              help=f"The single vendor with the largest share of total contract value: {tv.name}.")
    c3.metric("Non-competitive %", f"{nc_pct:.1f}%",
              help="Percentage of total contract value awarded via sole-source (TN) — "
                   "no competitive bidding process was held.")

    for flag in risk_flags:
        st.warning(f"⚠️ **Flag:** {flag.capitalize()}", icon="🚩")

    st.divider()

    # Altair bar chart + value-vs-count table side by side
    if table_rows:
        chart_col, tbl_col = st.columns([3, 2], gap="large")
        with chart_col:
            st.markdown("**Top 10 vendors by value share**")
            st.altair_chart(_vendor_bar_chart(table_rows))

        with tbl_col:
            st.markdown("**Value share vs. contract count share**")
            vc_rows = value_vs_count_share(records)
            df_vc = pd.DataFrame([
                {
                    "Vendor": _truncate(r.vendor, 28),
                    "Value %": f"{r.value_share_pct:.1f}",
                    "Count %": f"{r.count_share_pct:.1f}",
                }
                for r in vc_rows[:10]
            ])
            st.dataframe(df_vc, hide_index=True)

    st.divider()

    # Full vendor table
    st.subheader(f"All vendors — {DEPARTMENTS[active_dept]}")
    if keyword.strip():
        st.caption(f'Filtered to records containing **\"{keyword.strip()}\"** in description.')

    df_full = pd.DataFrame(table_rows)
    df_full["Total Value (CAD)"] = df_full["Total Value (CAD)"].map("${:,.2f}".format)
    st.dataframe(df_full, hide_index=True)

    csv_bytes = _build_csv(table_rows)
    st.download_button(
        label="⬇️ Download vendor table as CSV",
        data=csv_bytes,
        file_name=f"{active_dept}_concentration.csv",
        mime="text/csv",
    )

    _render_app_footer()

# ═══════════════════════════════════════════════════════════════════════════
# TAB 3 — Competition
# ═══════════════════════════════════════════════════════════════════════════

with tab_comp:
    st.subheader("Competition analysis")
    st.caption(
        "Shows how contracts were awarded, why some were not competed, "
        "and how many competitions attracted only one bid."
    )
    cb = competition_breakdown(records, labels)
    sb_count = cb.single_bid_competitive["count"]
    sb_value = cb.single_bid_competitive["value"]

    # ── Metrics row ─────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    c1.metric("Non-competitive share",     f"{nc_pct:.1f}%",
              help="Share of total contract value awarded via sole-source (TN solicitation). "
                   "A high percentage means most spending bypassed competitive bidding.")
    c2.metric("Competed but only one bid", f"{sb_count:,}",
              help=f"Contracts with a competitive procedure (TC, OB, or ST) that received "
                   f"only 1 bid — total value {_fmt_money(sb_value)}. May indicate limited "
                   f"market engagement or restrictive specifications.")
    c3.metric("Unique solicitation types", str(len(cb.by_solicitation)),
              help="Number of distinct solicitation procedure codes used across all contracts "
                   "in this result set.")

    st.divider()

    # ── Donut chart of value by solicitation procedure ───────────────────
    st.markdown("**Contract value by solicitation procedure**")
    st.caption("Percentage of total value awarded under each solicitation type. Hover for dollar amounts.")
    if cb.by_solicitation:
        sol_labels_list = [row["label"] for row in cb.by_solicitation]
        sol_values_list = [row["value"] for row in cb.by_solicitation]
        donut_fig = go.Figure(go.Pie(
            labels=sol_labels_list,
            values=sol_values_list,
            hole=0.55,
            textinfo="percent",
            hovertemplate="<b>%{label}</b><br>%{value:$,.0f}<br>%{percent}<extra></extra>",
            marker=dict(colors=[
                "#0F62FE", "#4589FF", "#78A9FF", "#A6C8FF", "#D0E2FF",
                "#08BDBA", "#6FDC8C", "#BAE6FF",
            ]),
        ))
        donut_fig.update_layout(
            title={"text": "Solicitation procedure mix", "font": {"size": 13}, "x": 0.01},
            height=340,
            margin={"t": 40, "b": 20, "l": 20, "r": 20},
            paper_bgcolor="rgba(0,0,0,0)",
            legend={"font": {"size": 12}, "orientation": "v"},
            font={"family": "system-ui, sans-serif", "color": "#161616"},
        )
        st.plotly_chart(donut_fig, config={"displayModeBar": False})
    else:
        st.caption("No solicitation data available.")

    st.divider()

    # ── Horizontal bar: non-competitive (limited-tendering) reasons ──────
    st.markdown('**Non-competitive reasons** *(limited-tendering, excluding "None" / code 00)*')
    # Filter out the "None" label produced when code is "00"
    ltr_filtered = [
        row for row in cb.by_tendering_reason
        if row["label"].lower() not in ("none", "not applicable")
    ]
    if ltr_filtered:
        df_ltr_bar = pd.DataFrame([
            {
                "Reason": _truncate(row["label"], 40),
                "Full Reason": row["label"],
                "Value": row["value"],
                "Contracts": row["count"],
                "Value Fmt": _fmt_money(row["value"]),
            }
            for row in ltr_filtered
        ])
        sort_ltr = (
            df_ltr_bar.sort_values("Value", ascending=False)["Reason"].tolist()
        )
        ltr_base = alt.Chart(df_ltr_bar).encode(
            y=alt.Y("Reason:N", sort=sort_ltr, title=None,
                    axis=alt.Axis(labelLimit=280, labelFontSize=11)),
            tooltip=[
                alt.Tooltip("Full Reason:N", title="Reason"),
                alt.Tooltip("Value Fmt:N",   title="Total Value"),
                alt.Tooltip("Contracts:Q",   title="# Contracts"),
            ],
        )
        ltr_bars = ltr_base.mark_bar(
            color="#cf222e", cornerRadiusTopRight=3, cornerRadiusBottomRight=3
        ).encode(
            x=alt.X("Value:Q", title="Contract value (CAD)",
                    axis=alt.Axis(grid=False, format="$,.0f")),
        )
        ltr_text = ltr_base.mark_text(
            align="left", dx=4, fontSize=10, color="#161616"
        ).encode(
            x=alt.X("Value:Q"),
            text=alt.Text("Value Fmt:N"),
        )
        st.altair_chart(
            (ltr_bars + ltr_text)
            .properties(height=max(140, len(ltr_filtered) * 32))
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor="#525252", domainColor="#dde1e6"),
        )
    else:
        st.caption("No non-competitive limited-tendering reasons found (or all coded 00).")

    st.divider()

    # ── Competed but single-bid expander ────────────────────────────────
    st.markdown(
        f"**Competed but only one bid** &nbsp;"
        f"<span style='background:#bf8700;color:#fff;padding:2px 10px;"
        f"border-radius:10px;font-size:0.85rem;'>{sb_count}</span>",
        unsafe_allow_html=True,
    )
    sb_records = [
        r for r in records
        if (r.get("solicitation_procedure") or "").strip().upper() in {"TC", "OB", "ST"}
        and str(r.get("number_of_bids") or "").strip() == "1"
    ]
    if sb_records:
        with st.expander(f"Show {len(sb_records)} single-bid contracts ({_fmt_money(sb_value)} total)"):
            df_sb = pd.DataFrame([
                {
                    "Ref #":       r.get("reference_number", ""),
                    "Vendor":      normalize_vendor(r.get("vendor_name", "")),
                    "Date":        r.get("contract_date", ""),
                    "Value":       f"${_parse_value(r.get('contract_value', '')):,.0f}",
                    "Procedure":   r.get("solicitation_procedure", ""),
                    "Description": (r.get("description_en") or "")[:60],
                }
                for r in sorted(
                    sb_records,
                    key=lambda x: _parse_value(x.get("contract_value", "")),
                    reverse=True,
                )
            ])
            st.dataframe(df_sb, hide_index=True)
    else:
        st.caption("No single-bid competitive contracts found.")

    _render_app_footer()

# ═══════════════════════════════════════════════════════════════════════════
# TAB 4 — Red flags
# ═══════════════════════════════════════════════════════════════════════════

with tab_red:
    st.subheader("Red flag analysis")
    st.caption(
        "Contracts that merit a closer look: possible split purchases just under a threshold, "
        "large amendments, and single-bid competitions. "
        "**Indicator for review — not evidence of wrongdoing.**"
    )

    # ── Threshold slider for split-purchase detection ────────────────────
    split_threshold = st.slider(
        "Split-purchase sole-source threshold (CAD)",
        min_value=10_000,
        max_value=100_000,
        value=25_000,
        step=5_000,
        format="$%d",
        help=(
            "Contracts within 90%–100% of this value awarded to the same vendor "
            "within 30 days are flagged as potential split purchases."
        ),
    )
    # Re-run split detection with the slider value (live, no re-fetch needed)
    clusters_rf = split_purchase_clusters(records, threshold=float(split_threshold))

    # ── Single-bid records (reused from competition tab logic) ───────────
    sb_records_rf = [
        r for r in records
        if (r.get("solicitation_procedure") or "").strip().upper() in {"TC", "OB", "ST"}
        and str(r.get("number_of_bids") or "").strip() == "1"
    ]

    # ── Summary badges ───────────────────────────────────────────────────
    b1, b2, b3 = st.columns(3)
    b1.metric("Possible split purchases",  f"{len(clusters_rf):,}",
              help=f"Groups of 2+ contracts to the same vendor, each valued between "
                   f"90%–100% of ${split_threshold:,}, within 30 days of each other.")
    b2.metric("Large amendments",          f"{len(amd_flags):,}",
              help="Contracts where the amendment value is ≥ $100 k AND exceeds "
                   "50% of the original contract value.")
    b3.metric("Single-bid competitions",   f"{len(sb_records_rf):,}",
              help="Competitive solicitations (TC, OB, or ST procedure) that attracted "
                   "only one bidder — the market may not have been effectively engaged.")

    st.divider()

    # ── Helper: standard flag table ──────────────────────────────────────
    def _flag_table(flag_records: list[dict], value_col: str = "contract_value") -> None:
        df = pd.DataFrame([
            {
                "Ref #":       r.get("reference_number", ""),
                "Vendor":      normalize_vendor(r.get("vendor_name", "")),
                "Date":        r.get("contract_date", ""),
                "Value":       f"${_parse_value(r.get(value_col, '')):,.0f}",
                "Description": (r.get("description_en") or "")[:70],
            }
            for r in sorted(
                flag_records,
                key=lambda x: _parse_value(x.get(value_col, "")),
                reverse=True,
            )
        ])
        st.dataframe(df, hide_index=True)

    # ── Section 1: Possible split purchases ─────────────────────────────
    st.markdown(
        f"#### Possible split purchases &nbsp;"
        f"<span style='background:#cf222e;color:#fff;padding:2px 10px;"
        f"border-radius:10px;font-size:0.85rem;'>{len(clusters_rf)}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "Splitting a contract into smaller pieces to stay below a sole-source "
        "threshold can circumvent competitive bidding requirements."
    )
    st.caption("Indicator for review — not evidence of wrongdoing.")
    if clusters_rf:
        # Expand clusters into individual flat records for the table
        split_detail_recs: list[dict] = []
        lower_rf = float(split_threshold) * 0.9
        for rec in records:
            val = _parse_value(rec.get("contract_value", ""))
            if lower_rf <= val < float(split_threshold):
                split_detail_recs.append(rec)
        _flag_table(split_detail_recs)
    else:
        st.caption(f"No clusters found near ${split_threshold:,} threshold.")

    st.divider()

    # ── Section 2: Large amendments ──────────────────────────────────────
    st.markdown(
        f"#### Large amendments &nbsp;"
        f"<span style='background:#cf222e;color:#fff;padding:2px 10px;"
        f"border-radius:10px;font-size:0.85rem;'>{len(amd_flags)}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "An amendment that substantially increases the original contract value "
        "may indicate scope was not properly defined at award, or that competitive "
        "requirements were sidestepped."
    )
    st.caption("Indicator for review — not evidence of wrongdoing.")
    if amd_flags:
        df_am2 = pd.DataFrame([
            {
                "Ref #":       r.get("reference_number", ""),
                "Vendor":      normalize_vendor(r.get("vendor_name", "")),
                "Date":        r.get("contract_date", ""),
                "Original":    f"${_parse_value(r.get('original_value', '')):,.0f}",
                "Amendment":   f"${_parse_value(r.get('amendment_value', '')):,.0f}",
                "Description": (r.get("description_en") or "")[:70],
            }
            for r in sorted(
                amd_flags,
                key=lambda x: _parse_value(x.get("amendment_value", "")),
                reverse=True,
            )
        ])
        st.dataframe(df_am2, hide_index=True)
    else:
        st.caption("No large-amendment contracts detected.")

    st.divider()

    # ── Section 3: Single-bid competitions ───────────────────────────────
    st.markdown(
        f"#### Single-bid competitions &nbsp;"
        f"<span style='background:#bf8700;color:#fff;padding:2px 10px;"
        f"border-radius:10px;font-size:0.85rem;'>{len(sb_records_rf)}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "A competitive solicitation that attracts only one bidder may indicate "
        "specifications were written to favour a particular vendor, or that the "
        "market was not effectively engaged."
    )
    st.caption("Indicator for review — not evidence of wrongdoing.")
    if sb_records_rf:
        _flag_table(sb_records_rf)
    else:
        st.caption("No single-bid competitive contracts found.")

    st.divider()

    # ── Combined CSV download ────────────────────────────────────────────
    # Flatten split-purchase individual records
    lower_rf2 = float(split_threshold) * 0.9
    split_flat = [
        r for r in records
        if lower_rf2 <= _parse_value(r.get("contract_value", "")) < float(split_threshold)
    ] if clusters_rf else []

    all_flag_rows: list[dict] = []
    for r in split_flat:
        all_flag_rows.append({
            "flag_type":        "possible_split_purchase",
            "reference_number": r.get("reference_number", ""),
            "vendor":           normalize_vendor(r.get("vendor_name", "")),
            "contract_date":    r.get("contract_date", ""),
            "contract_value":   r.get("contract_value", ""),
            "description":      (r.get("description_en") or "")[:120],
        })
    for r in amd_flags:
        all_flag_rows.append({
            "flag_type":        "large_amendment",
            "reference_number": r.get("reference_number", ""),
            "vendor":           normalize_vendor(r.get("vendor_name", "")),
            "contract_date":    r.get("contract_date", ""),
            "contract_value":   r.get("contract_value", ""),
            "description":      (r.get("description_en") or "")[:120],
        })
    for r in sb_records_rf:
        all_flag_rows.append({
            "flag_type":        "single_bid_competition",
            "reference_number": r.get("reference_number", ""),
            "vendor":           normalize_vendor(r.get("vendor_name", "")),
            "contract_date":    r.get("contract_date", ""),
            "contract_value":   r.get("contract_value", ""),
            "description":      (r.get("description_en") or "")[:120],
        })

    flags_csv = _build_csv(all_flag_rows)
    st.download_button(
        label="⬇️ Download all flags as CSV",
        data=flags_csv,
        file_name=f"{active_dept}_red_flags.csv",
        mime="text/csv",
        disabled=not all_flag_rows,
    )

    _render_app_footer()

# ═══════════════════════════════════════════════════════════════════════════
# TAB 5 — Trends
# ═══════════════════════════════════════════════════════════════════════════

with tab_trends:
    st.subheader("Monthly spending trends")
    st.caption(
        "How spending, concentration and competition change month by month."
    )
    trend = [t for t in monthly_trend(records) if t.month != "unknown"]

    if not trend:
        st.caption("Not enough dated records to build a trend.")
    else:
        df_trend = pd.DataFrame([
            {
                "Month":             t.month,
                "Total Value":       t.total_value,
                "Contracts":         t.contract_count,
                "HHI":               t.hhi_score,
                "Non-competitive %": t.noncompetitive_pct,
            }
            for t in trend
        ])

        date_min = df_trend["Month"].min()
        date_max = df_trend["Month"].max()
        st.caption(
            f"Date range covered: **{date_min}** to **{date_max}** "
            f"({len(df_trend)} months)"
        )

        # ── Chart 1: monthly contract value ─────────────────────────────
        st.markdown("**Monthly contract value (CAD)**")
        st.caption("Total value of contracts awarded each month. X-axis: YYYY-MM. Y-axis: CAD.")
        st.line_chart(
            df_trend.set_index("Month")[["Total Value"]],
            height=240,
            color="#0F62FE",
            x_label="Month (YYYY-MM)",
            y_label="Contract Value (CAD)",
        )

        st.divider()

        # ── Chart 2: monthly HHI and non-competitive share ───────────────
        st.markdown("**Monthly HHI and non-competitive share**")
        st.caption(
            "HHI (left concept) and Non-competitive % (right concept) are plotted "
            "on their own natural scales. High HHI or high non-competitive % in a "
            "given month warrants closer review."
        )
        # Altair dual-series line chart with two y-axes via layering
        df_dual = df_trend[["Month", "HHI", "Non-competitive %"]].copy()

        base_dual = alt.Chart(df_dual).encode(
            x=alt.X("Month:O", title="Month (YYYY-MM)", axis=alt.Axis(labelAngle=-45))
        )
        hhi_line = base_dual.mark_line(
            color="#0F62FE", strokeWidth=2, point=alt.OverlayMarkDef(color="#0F62FE", size=40)
        ).encode(
            y=alt.Y("HHI:Q", title="HHI", axis=alt.Axis(titleColor="#0F62FE")),
            tooltip=[alt.Tooltip("Month:O"), alt.Tooltip("HHI:Q", format=".0f")],
        )
        nc_line = base_dual.mark_line(
            color="#cf222e", strokeWidth=2, strokeDash=[4, 2],
            point=alt.OverlayMarkDef(color="#cf222e", size=40)
        ).encode(
            y=alt.Y("Non-competitive %:Q", title="Non-competitive %",
                    axis=alt.Axis(titleColor="#cf222e")),
            tooltip=[alt.Tooltip("Month:O"),
                     alt.Tooltip("Non-competitive %:Q", format=".1f")],
        )
        st.altair_chart(
            alt.layer(hhi_line, nc_line).resolve_scale(y="independent")
            .properties(height=240)
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor="#525252", domainColor="#dde1e6"),
        )

        st.divider()

        # ── Detail table ─────────────────────────────────────────────────
        df_disp = df_trend.copy()
        df_disp["Total Value"] = df_disp["Total Value"].map("${:,.0f}".format)
        df_disp["HHI"]         = df_disp["HHI"].map("{:,.0f}".format)
        df_disp["Non-competitive %"] = df_disp["Non-competitive %"].map("{:.1f}%".format)
        st.dataframe(df_disp, hide_index=True)

    _render_app_footer()

# ═══════════════════════════════════════════════════════════════════════════
# TAB 6 — Vendors & regions
# ═══════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_all_departments() -> tuple[list[dict], bool, list[str]]:
    """Fetch up to 1 000 records per department across all departments.

    Departments are fetched in parallel (6 at a time). A department that fails
    is skipped and reported rather than aborting the whole search.
    Returns (records, any_cached, skipped_department_names).
    """
    from concurrent.futures import ThreadPoolExecutor

    def _one(org: str):
        try:
            recs, cached = fetch_many([org], max_rows_each=1000)
            return org, recs, cached, None
        except Exception as exc:  # noqa: BLE001 — report, don't abort
            return org, [], False, str(exc)

    all_recs: list[dict] = []
    any_cached = False
    skipped: list[str] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for org, recs, cached, err in pool.map(_one, list(DEPARTMENTS.keys())):
            if err:
                skipped.append(DEPARTMENTS[org])
                continue
            all_recs.extend(recs)
            any_cached = any_cached or cached
    return all_recs, any_cached, skipped


with tab_vendors:
    st.subheader("Vendors & regional distribution")
    st.caption(
        f"Look up any vendor across all {len(DEPARTMENTS)} departments and see where "
        "suppliers are located by province."
    )

    # ── Vendor search ────────────────────────────────────────────────────
    st.markdown("**Vendor lookup — current department**")
    vendor_query = st.text_input(
        "Search vendor name (case-insensitive contains)",
        placeholder="e.g. IBM, Deloitte, Bell …",
        key="vendor_search",
    )

    if vendor_query.strip():
        vq = vendor_query.strip().upper()
        # Match against normalised names
        matched_vendors = {
            v: share for v, share in shares.items()
            if vq in v
        }
        if not matched_vendors:
            st.info(f"No vendor matching **\"{vendor_query.strip()}\"** found in {DEPARTMENTS[active_dept]}.")
        else:
            for vname, vshare in sorted(matched_vendors.items(),
                                        key=lambda x: x[1], reverse=True):
                # Gather this vendor's records
                v_recs = [
                    r for r in records
                    if normalize_vendor(r.get("vendor_name", "")) == vname
                ]
                v_total = sum(_parse_value(r.get("contract_value", "")) for r in v_recs)
                v_tn    = sum(
                    _parse_value(r.get("contract_value", "")) for r in v_recs
                    if (r.get("solicitation_procedure") or "").strip().upper() == "TN"
                )
                v_nc_pct = (v_tn / v_total * 100) if v_total else 0.0
                v_dates  = sorted(
                    r.get("contract_date", "") for r in v_recs
                    if r.get("contract_date", "")
                )
                v_first  = v_dates[0]  if v_dates else "—"
                v_last   = v_dates[-1] if v_dates else "—"

                with st.expander(f"{vname}  ·  {_fmt_money(v_total)}  ·  {len(v_recs)} contracts",
                                 expanded=True):
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Total Value",        _fmt_money(v_total))
                    m2.metric("Contracts",          str(len(v_recs)))
                    m3.metric("Non-competitive %",  f"{v_nc_pct:.1f}%")
                    m4.metric("Active period",      f"{v_first} – {v_last}",
                              help="First and last contract date in this dataset")

                    df_v = pd.DataFrame([
                        {
                            "Ref #":       r.get("reference_number", ""),
                            "Date":        r.get("contract_date", ""),
                            "Value":       f"${_parse_value(r.get('contract_value','')):,.0f}",
                            "Procedure":   r.get("solicitation_procedure", ""),
                            "Description": (r.get("description_en") or "")[:70],
                        }
                        for r in sorted(v_recs,
                                        key=lambda x: x.get("contract_date", ""),
                                        reverse=True)
                    ])
                    st.dataframe(df_v, hide_index=True)

        st.divider()

        # ── Cross-department search ──────────────────────────────────────
        st.markdown(f"**Search across all {len(DEPARTMENTS)} departments**")
        if st.button(f"Search across all {len(DEPARTMENTS)} departments", key="search_all_depts"):
            with st.spinner(
                f"Fetching contracts from {len(DEPARTMENTS)} departments "
                "(first time ~15 seconds, then cached for an hour) …"
            ):
                all_recs, all_cached, skipped = _fetch_all_departments()
                st.session_state["all_dept_records"]  = all_recs
                st.session_state["all_dept_cached"]   = all_cached
                st.session_state["all_dept_skipped"]  = skipped

        if st.session_state.get("all_dept_skipped"):
            st.caption(
                "⚠️ Could not load: " + ", ".join(st.session_state["all_dept_skipped"])
                + ". Results cover the other departments."
            )

        if "all_dept_records" in st.session_state and vendor_query.strip():
            all_recs   = st.session_state["all_dept_records"]
            all_cached = st.session_state["all_dept_cached"]
            if all_cached:
                st.caption("⚠️ Some departments used cached fallback data.")

            vq2 = vendor_query.strip().upper()
            # Aggregate value by department for the searched vendor
            dept_value: dict[str, float] = {}
            for r in all_recs:
                if vq2 in normalize_vendor(r.get("vendor_name", "")):
                    org_title = r.get("owner_org_title", r.get("owner_org", "Unknown"))
                    # Use short name from DEPARTMENTS if owner_org is known
                    org_key   = r.get("owner_org", "")
                    label     = DEPARTMENTS.get(org_key, org_title.split("|")[0].strip())
                    val       = _parse_value(r.get("contract_value", ""))
                    dept_value[label] = dept_value.get(label, 0.0) + val

            if dept_value:
                st.markdown(f"**Value by department for vendors matching \"{vendor_query.strip()}\"**")
                df_dept = pd.DataFrame([
                    {"Department": _truncate(k, 35), "Total Value": v}
                    for k, v in sorted(dept_value.items(), key=lambda x: x[1], reverse=True)
                ])
                sort_dept = df_dept.sort_values("Total Value", ascending=False)["Department"].tolist()
                dept_base = alt.Chart(df_dept).encode(
                    y=alt.Y("Department:N", sort=sort_dept, title=None,
                            axis=alt.Axis(labelLimit=240, labelFontSize=11)),
                    tooltip=[
                        alt.Tooltip("Department:N"),
                        alt.Tooltip("Total Value:Q", title="Total Value", format="$,.0f"),
                    ],
                )
                dept_bars = dept_base.mark_bar(
                    color="#0F62FE", cornerRadiusTopRight=3, cornerRadiusBottomRight=3
                ).encode(
                    x=alt.X("Total Value:Q", title="Contract value (CAD)",
                            axis=alt.Axis(grid=False, format="$,.0f")),
                )
                dept_text = dept_base.mark_text(align="left", dx=4, fontSize=10,
                                                 color="#161616").encode(
                    x=alt.X("Total Value:Q"),
                    text=alt.Text("Total Value:Q", format="$,.0f"),
                )
                st.altair_chart(
                    (dept_bars + dept_text)
                    .properties(height=max(140, len(df_dept) * 32))
                    .configure_view(strokeWidth=0)
                    .configure_axis(labelColor="#525252", domainColor="#dde1e6"),
                )
            else:
                st.info(f"No contracts found for vendors matching **\"{vendor_query.strip()}\"** across all departments.")

    st.divider()

    # ── Province / territory bar chart ───────────────────────────────────
    st.markdown("**Contract value by vendor province/territory**")
    prov_value: dict[str, float] = {}
    prov_count: dict[str, int]   = {}
    for rec in records:
        prov = province_from_postal(rec.get("vendor_postal_code", ""))
        val  = _parse_value(rec.get("contract_value", ""))
        prov_value[prov] = prov_value.get(prov, 0.0) + val
        prov_count[prov] = prov_count.get(prov, 0) + 1

    if prov_value:
        df_prov = pd.DataFrame([
            {"Province/Territory": p, "Total Value": v, "Contracts": prov_count[p]}
            for p, v in sorted(prov_value.items(), key=lambda x: x[1], reverse=True)
        ])
        sort_prov = df_prov.sort_values("Total Value", ascending=False)["Province/Territory"].tolist()
        prov_base = alt.Chart(df_prov).encode(
            y=alt.Y("Province/Territory:N", sort=sort_prov, title=None,
                    axis=alt.Axis(labelLimit=100, labelFontSize=11)),
            tooltip=[
                alt.Tooltip("Province/Territory:N"),
                alt.Tooltip("Total Value:Q", title="Total Value", format="$,.0f"),
                alt.Tooltip("Contracts:Q",   title="# Contracts"),
            ],
        )
        prov_bars = prov_base.mark_bar(
            color="#0F62FE", cornerRadiusTopRight=3, cornerRadiusBottomRight=3
        ).encode(
            x=alt.X("Total Value:Q", title="Contract value (CAD)",
                    axis=alt.Axis(grid=False, format="$,.0f")),
        )
        prov_text = prov_base.mark_text(align="left", dx=4, fontSize=10,
                                         color="#161616").encode(
            x=alt.X("Total Value:Q"),
            text=alt.Text("Total Value:Q", format="$,.0f"),
        )
        st.altair_chart(
            (prov_bars + prov_text)
            .properties(height=max(200, len(df_prov) * 30))
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor="#525252", domainColor="#dde1e6"),
        )
        df_prov_display = df_prov.copy()
        df_prov_display["Total Value"] = df_prov_display["Total Value"].map("${:,.0f}".format)
        st.dataframe(df_prov_display, hide_index=True)
    else:
        st.caption("No postal code data available for province mapping.")

    _render_app_footer()

# ═══════════════════════════════════════════════════════════════════════════
# TAB 7 — AI audit brief
# ═══════════════════════════════════════════════════════════════════════════

with tab_ai:
    st.subheader("AI audit brief")
    st.caption(
        "IBM watsonx.ai, hosted in Toronto, drafts an audit brief from the computed facts only. "
        "Review before use."
    )

    # Build the facts dict once — same keys every time, regardless of AI or fallback
    _facts: dict = {
        "department_name":           DEPARTMENTS.get(active_dept, active_dept),
        "date_range":                _date_range,
        "health_score":              hs.score,
        "health_band":               hb,
        "component_concentration":   round(hs.concentration_component, 1),
        "component_competition":     round(hs.competition_component, 1),
        "component_diversity":       round(hs.diversity_component, 1),
        "component_red_flags":       round(hs.red_flags_component, 1),
        "total_value_fmt":           _fmt_money(total_value),
        "contract_count":            len(records),
        "vendor_count":              n_vendors,
        "hhi_score":                 round(hhi_score, 0),
        "top_vendor_name":           tv.name,
        "top_vendor_share_pct":      round(tv.share, 1),
        "largest_contract_share_pct": round(lc_global.share_pct, 1),
        "noncompetitive_pct":        round(nc_pct, 1),
        "single_bid_count":          sb_count_global,
        "split_purchase_clusters":   len(clusters),
        "large_amendment_count":     len(amd_flags),
    }

    # Cache key: department + record count so stale cache auto-invalidates on new fetch
    _brief_cache_key = f"ai_brief_{active_dept}_{len(records)}"

    if not is_watsonx_available():
        st.info(
            "IBM watsonx.ai is not configured. Add `[watsonx]` with `api_key`, "
            "`project_id`, `url`, and `model_id` to `.streamlit/secrets.toml` to "
            "enable AI generation. A rule-based brief is available below.",
            icon="ℹ️",
        )

    # Generate button (skipped if already cached for this dept+count)
    if _brief_cache_key not in st.session_state:
        if st.button("Generate brief with IBM watsonx.ai", type="primary"):
            with st.spinner("Generating audit brief …"):
                brief_md, is_ai, label = generate_brief(_facts)
                st.session_state[_brief_cache_key] = (brief_md, is_ai, label)
                if not is_ai:
                    st.info(
                        f"watsonx.ai was not used. {label}",
                        icon="ℹ️",
                    )
    else:
        st.caption("Brief loaded from session cache. Click **Clear** to regenerate.")
        if st.button("Clear cached brief", key="clear_brief"):
            del st.session_state[_brief_cache_key]
            st.rerun()

    # Display brief if available
    if _brief_cache_key in st.session_state:
        brief_md, is_ai, label = st.session_state[_brief_cache_key]

        # Labelled bordered container
        label_color = "#0F62FE" if is_ai else "#525252"
        st.markdown(
            f"<div style='border:1px solid #dde1e6;border-radius:6px;"
            f"padding:4px 14px 2px 14px;margin-bottom:12px;"
            f"font-size:0.78rem;color:{label_color};'>"
            f"{'✨ ' if is_ai else 'ℹ️ '}{label}</div>",
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            st.markdown(brief_md)

        st.divider()

        # Download buttons
        dl1, dl2 = st.columns(2)

        # Markdown download
        md_full = (
            f"# Procurement Audit Brief — {DEPARTMENTS.get(active_dept, active_dept)}\n\n"
            f"*{label}*  \n"
            f"Generated: {datetime.date.today().isoformat()}\n\n"
            f"---\n\n"
            f"{brief_md}\n\n"
            f"---\n\n"
            f"**Data source:** Open Government Portal — Proactive Disclosure of Contracts.  \n"
            f"This brief is an indicator for review and does not constitute a finding of wrongdoing.\n"
        )
        dl1.download_button(
            label="⬇️ Download as Markdown (.md)",
            data=md_full.encode("utf-8"),
            file_name=f"{active_dept}_audit_brief.md",
            mime="text/markdown",
        )

        # HTML download
        html_content = brief_to_html(brief_md, label, _facts)
        dl2.download_button(
            label="⬇️ Download as HTML (.html)",
            data=html_content.encode("utf-8"),
            file_name=f"{active_dept}_audit_brief.html",
            mime="text/html",
        )

    _render_app_footer()

# ═══════════════════════════════════════════════════════════════════════════
# TAB 8 — Compare departments
# ═══════════════════════════════════════════════════════════════════════════

def _compare_bar_chart(rows: list) -> alt.Chart:
    """Horizontal bar chart of health score per department, coloured by band."""
    band_colours = {"Healthy": "#1a7f37", "Watch": "#bf8700", "At risk": "#cf222e"}
    df = pd.DataFrame([
        {
            "Department": _truncate(r.name, 40),
            "Score":      r.health_score,
            "Band":       r.health_band,
            "Colour":     band_colours.get(r.health_band, "#525252"),
        }
        for r in rows
    ])
    # Sort descending by score (highest at top)
    sort_order = df.sort_values("Score", ascending=False)["Department"].tolist()

    base = alt.Chart(df).encode(
        y=alt.Y("Department:N", sort=sort_order, title=None,
                axis=alt.Axis(labelLimit=260, labelFontSize=12)),
        tooltip=[
            alt.Tooltip("Department:N"),
            alt.Tooltip("Score:Q", title="Health score"),
            alt.Tooltip("Band:N",  title="Band"),
        ],
    )
    bars = base.mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3).encode(
        x=alt.X("Score:Q", title="Health score (0–100)",
                scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(grid=False)),
        color=alt.Color(
            "Band:N",
            scale=alt.Scale(
                domain=["Healthy", "Watch", "At risk"],
                range=["#1a7f37", "#bf8700", "#cf222e"],
            ),
            legend=alt.Legend(title="Band", orient="bottom"),
        ),
    )
    text = base.mark_text(align="left", dx=4, fontSize=11, color="#161616").encode(
        x=alt.X("Score:Q"),
        text=alt.Text("Score:Q", format="d"),
    )
    return (bars + text).properties(
        height=max(260, len(rows) * 32)
    ).configure_view(strokeWidth=0).configure_axis(
        labelColor="#525252", titleColor="#525252", domainColor="#dde1e6"
    )


with tab_compare:
    st.subheader("Compare departments")
    st.caption(
        "Side-by-side procurement health indicators across all departments. "
        "Indicators for review, not findings of wrongdoing. "
        "Based on the latest 1,000 contracts per department."
    )

    if st.button(
        f"Load all {len(DEPARTMENTS)} departments",
        key="compare_load",
        type="primary",
    ):
        with st.spinner(
            f"Fetching up to 1,000 contracts from each of the "
            f"{len(DEPARTMENTS)} departments — first run may take ~15 s …"
        ):
            _cmp_recs, _cmp_cached, _cmp_skipped = _fetch_all_departments()
            st.session_state["cmp_records"] = _cmp_recs
            st.session_state["cmp_cached"]  = _cmp_cached
            st.session_state["cmp_skipped"] = _cmp_skipped

    if "cmp_records" not in st.session_state:
        st.info("👆 Click the button above to load all departments.")
        _render_app_footer()
    else:
        _cmp_all   = st.session_state["cmp_records"]
        _cmp_cache = st.session_state["cmp_cached"]
        _cmp_skip  = st.session_state.get("cmp_skipped", [])

        if _cmp_cache:
            st.warning("⚠️ One or more departments used cached fallback data.", icon="📦")
        if _cmp_skip:
            st.warning(f"⚠️ Could not load: {', '.join(_cmp_skip)}. Results cover other departments.")

        # Group records by owner_org and run compare_departments
        _recs_by_org: dict[str, list[dict]] = {org: [] for org in DEPARTMENTS}
        for _r in _cmp_all:
            _org_key = (_r.get("owner_org") or "").strip()
            if _org_key in _recs_by_org:
                _recs_by_org[_org_key].append(_r)

        _cmp_rows = compare_departments(_recs_by_org, DEPARTMENTS)

        if not _cmp_rows:
            st.info("No data returned for any department.")
            _render_app_footer()

    # ── Summary KPIs ─────────────────────────────────────────────────────
        if _cmp_rows:
            _n_healthy  = sum(1 for r in _cmp_rows if r.health_band == "Healthy")
            _n_watch    = sum(1 for r in _cmp_rows if r.health_band == "Watch")
            _n_at_risk  = sum(1 for r in _cmp_rows if r.health_band == "At risk")
            _avg_score  = round(sum(r.health_score for r in _cmp_rows) / len(_cmp_rows))

            kc1, kc2, kc3, kc4 = st.columns(4)
            kc1.metric("Departments loaded", len(_cmp_rows))
            kc2.metric("🟢 Healthy (≥ 75)",  _n_healthy)
            kc3.metric("🟡 Watch (50–74)",    _n_watch)
            kc4.metric("🔴 At risk (< 50)",   _n_at_risk)

            st.divider()

            # ── Horizontal bar chart ──────────────────────────────────────────────
            st.markdown("#### Health score by department")
            st.altair_chart(_compare_bar_chart(_cmp_rows))

            st.divider()

            # ── Sortable table ────────────────────────────────────────────────────
            st.markdown("#### Full metrics table")

            _BAND_ICON = {"Healthy": "🟢", "Watch": "🟡", "At risk": "🔴"}
            _df_cmp = pd.DataFrame([
                {
                    "Department":        r.name,
                    "Score":             r.health_score,
                    "Band":              f"{_BAND_ICON.get(r.health_band, '')} {r.health_band}",
                    "Contracts":         r.contract_count,
                    "Total Value (CAD)": round(r.total_value, 0),
                    "HHI":               round(r.hhi_score, 0),
                    "Non-comp %":        f"{r.noncompetitive_pct:.1f}%",
                    "Top vendor %":      f"{r.top_vendor_share:.1f}%",
                    "Flagged %":         f"{r.flagged_pct:.1f}%",
                }
                for r in _cmp_rows   # already sorted descending by score
            ])
            st.dataframe(
                _df_cmp,
                hide_index=True,
                column_config={
                    "Score":             st.column_config.NumberColumn("Score", format="%d"),
                    "Total Value (CAD)": st.column_config.NumberColumn("Total Value (CAD)", format="$%,.0f"),
                    "HHI":               st.column_config.NumberColumn("HHI", format="%,.0f"),
                },
            )

            st.caption(
                "**Score** 0–100 procurement health (higher = healthier). "
                "**HHI** < 1,000 Low · 1,000–1,800 Moderate · > 1,800 High. "
                "**Non-comp %** share of spend awarded without competition (TN). "
                "**Flagged %** share of contracts with split-purchase or large-amendment indicators. "
                "Indicators for review, not findings of wrongdoing. "
                "Based on the latest 1,000 contracts per department."
            )

        _render_app_footer()
