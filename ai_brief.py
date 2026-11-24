"""
ai_brief.py — IBM watsonx.ai-powered procurement audit brief generator.

Public API
----------
generate_brief(facts: dict) -> str
    Call with pre-computed analytics facts.
    Returns a Markdown string.
    Falls back to a rule-based brief when watsonx is unavailable.

is_watsonx_available() -> bool
    Returns True when st.secrets["watsonx"] is fully configured.
"""

from __future__ import annotations

import datetime
import textwrap
from typing import Any

# ---------------------------------------------------------------------------
# Watsonx availability probe (lazy — no import-time crash if SDK absent)
# ---------------------------------------------------------------------------

def is_watsonx_available() -> bool:
    """Return True when the watsonx secrets block is present and non-empty."""
    try:
        import streamlit as st
        sec = st.secrets.get("watsonx", {})
        return all(sec.get(k) for k in ("api_key", "project_id", "url", "model_id"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# System and user prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a public-sector procurement audit assistant. "
    "Use only the facts provided. "
    "Do not invent numbers, vendor names, or causes. "
    "Do not allege wrongdoing; describe indicators that merit review. "
    "Write for a deputy head in plain English."
)

_USER_TEMPLATE = """\
Please produce a procurement concentration audit brief for the department below.

## Facts

{facts_table}

## Required output — use exactly these four sections, no others

### 1. Summary (3 sentences)
Summarise the department's overall procurement concentration picture in three sentences.

### 2. Top 3 risks
List the three most significant indicators that warrant review. Include the specific number behind each risk.

### 3. Recommended next steps (for an internal auditor)
List three concrete, actionable next steps.

### 4. Data limitations (one sentence)
Note one important limitation of this analysis.
"""


def _build_facts_table(facts: dict[str, Any]) -> str:
    """Format the facts dict as a Markdown table."""
    rows = [
        ("Department",                    facts.get("department_name", "—")),
        ("Date range",                    facts.get("date_range", "—")),
        ("Health score / band",           f"{facts.get('health_score', '—')} / {facts.get('health_band', '—')}"),
        ("  Concentration component",     f"{facts.get('component_concentration', '—')} / 40"),
        ("  Competition component",       f"{facts.get('component_competition', '—')} / 30"),
        ("  Diversity component",         f"{facts.get('component_diversity', '—')} / 15"),
        ("  Red-flags component",         f"{facts.get('component_red_flags', '—')} / 15"),
        ("Total contract value",          facts.get("total_value_fmt", "—")),
        ("Contract count",                str(facts.get("contract_count", "—"))),
        ("Vendor count",                  str(facts.get("vendor_count", "—"))),
        ("HHI score",                     str(facts.get("hhi_score", "—"))),
        ("Top vendor",                    facts.get("top_vendor_name", "—")),
        ("Top vendor share",              f"{facts.get('top_vendor_share_pct', '—')}%"),
        ("Largest single contract share", f"{facts.get('largest_contract_share_pct', '—')}%"),
        ("Non-competitive share (TN)",    f"{facts.get('noncompetitive_pct', '—')}%"),
        ("Single-bid competitive count",  str(facts.get("single_bid_count", "—"))),
        ("Split-purchase clusters",       str(facts.get("split_purchase_clusters", "—"))),
        ("Large-amendment contracts",     str(facts.get("large_amendment_count", "—"))),
    ]
    header = "| Metric | Value |\n|---|---|\n"
    body   = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return header + body


# ---------------------------------------------------------------------------
# watsonx call
# ---------------------------------------------------------------------------

def _call_watsonx(facts: dict[str, Any]) -> str:
    """Call the watsonx.ai ModelInference chat API and return the brief text."""
    import streamlit as st
    from ibm_watsonx_ai import Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference

    sec = st.secrets["watsonx"]
    credentials = Credentials(url=sec["url"], api_key=sec["api_key"])
    model = ModelInference(
        model_id=sec["model_id"],
        credentials=credentials,
        project_id=sec["project_id"],
    )

    facts_table = _build_facts_table(facts)
    user_message = _USER_TEMPLATE.format(facts_table=facts_table)

    response = model.chat(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        params={
            "max_new_tokens": 600,
            "temperature":    0.2,
        },
    )
    # ModelInference.chat returns a dict with choices[0].message.content
    return response["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Rule-based fallback brief
# ---------------------------------------------------------------------------

def _rule_based_brief(facts: dict[str, Any]) -> str:
    """Generate a deterministic brief from the facts dict without any AI call."""
    dept   = facts.get("department_name", "the department")
    hhi_v  = facts.get("hhi_score", 0)
    nc_pct = facts.get("noncompetitive_pct", 0.0)
    tv_pct = facts.get("top_vendor_share_pct", 0.0)
    score  = facts.get("health_score", "—")
    bnd    = facts.get("health_band", "—")
    total  = facts.get("total_value_fmt", "—")
    n_con  = facts.get("contract_count", "—")
    n_ven  = facts.get("vendor_count", "—")
    sp     = facts.get("split_purchase_clusters", 0)
    am     = facts.get("large_amendment_count", 0)
    sb     = facts.get("single_bid_count", 0)
    lc_pct = facts.get("largest_contract_share_pct", 0.0)
    dr     = facts.get("date_range", "—")

    # Determine HHI descriptor
    if hhi_v >= 2500:
        hhi_desc = f"highly concentrated (HHI {hhi_v:,.0f})"
    elif hhi_v >= 1800:
        hhi_desc = f"moderately-to-highly concentrated (HHI {hhi_v:,.0f})"
    elif hhi_v >= 1000:
        hhi_desc = f"moderately concentrated (HHI {hhi_v:,.0f})"
    else:
        hhi_desc = f"relatively competitive (HHI {hhi_v:,.0f})"

    # Build risks
    risks: list[str] = []
    if tv_pct > 40:
        risks.append(
            f"**Single-vendor dependency:** The largest vendor holds {tv_pct:.1f}% "
            f"of total contract value, indicating a material reliance risk."
        )
    if nc_pct > 30:
        risks.append(
            f"**Low competition:** {nc_pct:.1f}% of spending was awarded "
            f"non-competitively (TN solicitation), limiting price discovery."
        )
    if sp > 0:
        risks.append(
            f"**Possible split purchases:** {sp} cluster(s) of contracts near the "
            f"sole-source threshold were detected and merit review."
        )
    if am > 0:
        risks.append(
            f"**Large amendments:** {am} contract(s) had amendments exceeding "
            f"$100 k and 50% of original value, suggesting scope uncertainty at award."
        )
    if sb > 0:
        risks.append(
            f"**Single-bid competitions:** {sb} competitive solicitation(s) received "
            f"only one bid, suggesting limited market engagement."
        )
    if lc_pct >= 50:
        risks.append(
            f"**Dominant single contract:** One contract represents {lc_pct:.1f}% "
            f"of total spending in this dataset."
        )
    top3_risks = risks[:3]

    brief = textwrap.dedent(f"""\
        ### 1. Summary

        {dept} recorded {total} across {n_con:,} contracts with {n_ven:,} unique vendors \
over the period {dr}. The vendor market is {hhi_desc}. \
The overall procurement health score is **{score}/100 ({bnd})**, reflecting the \
combined assessment of concentration, competition, diversity and red-flag indicators.

        ### 2. Top 3 risks

        """)

    if top3_risks:
        for i, r in enumerate(top3_risks, 1):
            brief += f"{i}. {r}\n\n"
    else:
        brief += "No significant risks identified based on the available data.\n\n"

    brief += textwrap.dedent(f"""\
        ### 3. Recommended next steps

        1. Review sole-source justification documentation for the {nc_pct:.1f}% of spending \
awarded non-competitively and confirm that Treasury Board contracting policy \
requirements were met.
        2. Examine the {sp} potential split-purchase cluster(s) to determine whether \
individual contracts were structured to remain below sole-source thresholds.
        3. Assess the {am} large-amendment contract(s) to verify that original \
statements of work adequately defined scope and that amendments were properly authorised.

        ### 4. Data limitations

        This analysis is based on Proactive Disclosure records for the selected period \
({dr}) and may not capture all contracts, sub-contracts, or procurement instruments \
not subject to disclosure requirements.
        """)

    return brief.strip()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

#: Set to a human-readable label to show in the UI when the brief is AI-generated.
WATSONX_LABEL_TEMPLATE = (
    "AI-generated with IBM watsonx.ai (model: {model_id}) — review before use"
)


def generate_brief(facts: dict[str, Any]) -> tuple[str, bool, str]:
    """Generate a procurement audit brief from pre-computed analytics facts.

    Parameters
    ----------
    facts:
        Dict of computed metrics — see ``_build_facts_table`` for expected keys.

    Returns
    -------
    tuple[str, bool, str]
        ``(brief_markdown, is_ai, label)`` where:
        - ``brief_markdown`` is the full brief as a Markdown string
        - ``is_ai`` is True when the brief was produced by watsonx
        - ``label`` is the display label for the source (model ID or fallback tag)
    """
    if is_watsonx_available():
        try:
            import streamlit as st
            model_id = st.secrets["watsonx"].get("model_id", "unknown")
            brief = _call_watsonx(facts)
            label = WATSONX_LABEL_TEMPLATE.format(model_id=model_id)
            return brief, True, label
        except Exception as exc:
            # Fall through to rule-based.  Truncate the error to avoid leaking
            # credential values that IBM SDK exceptions sometimes include.
            safe_msg = str(exc)[:120]
            fallback = _rule_based_brief(facts)
            return fallback, False, f"Rule-based fallback (watsonx error: {safe_msg})"

    fallback = _rule_based_brief(facts)
    return fallback, False, "Rule-based fallback (watsonx not configured)"


# ---------------------------------------------------------------------------
# HTML export helper
# ---------------------------------------------------------------------------

def brief_to_html(brief_md: str, label: str, facts: dict[str, Any]) -> str:
    """Wrap a Markdown brief in a minimal standalone HTML document.

    Includes the department name, generation date and facts table as an appendix.
    """
    import html as _html

    dept      = _html.escape(str(facts.get("department_name", "—")))
    today     = datetime.date.today().isoformat()
    facts_tbl = _build_facts_table(facts)

    # Very light Markdown→HTML: convert ### headings and **bold** only
    def _md_to_html_simple(md: str) -> str:
        lines = []
        for line in md.splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                lines.append(f"<h3>{_html.escape(stripped[4:])}</h3>")
            elif stripped.startswith("## "):
                lines.append(f"<h2>{_html.escape(stripped[3:])}</h2>")
            elif stripped.startswith("# "):
                lines.append(f"<h1>{_html.escape(stripped[2:])}</h1>")
            elif stripped == "---":
                lines.append("<hr>")
            elif stripped == "":
                lines.append("<br>")
            else:
                # Bold
                import re
                escaped = _html.escape(line)
                escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
                lines.append(f"<p>{escaped}</p>")
        return "\n".join(lines)

    facts_rows = "".join(
        f"<tr><td>{_html.escape(k)}</td><td>{_html.escape(str(v))}</td></tr>"
        for k, v in [
            ("Department",     facts.get("department_name", "—")),
            ("Date range",     facts.get("date_range", "—")),
            ("Health score",   f"{facts.get('health_score', '—')} / 100 ({facts.get('health_band', '—')})"),
            ("Total value",    facts.get("total_value_fmt", "—")),
            ("Contracts",      str(facts.get("contract_count", "—"))),
            ("Vendors",        str(facts.get("vendor_count", "—"))),
            ("HHI",            str(facts.get("hhi_score", "—"))),
            ("Non-competitive %", f"{facts.get('noncompetitive_pct', '—')}%"),
        ]
    )

    body_html = _md_to_html_simple(brief_md)
    label_esc = _html.escape(label)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Audit Brief — {dept}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 820px; margin: 40px auto;
         color: #161616; line-height: 1.6; padding: 0 24px; }}
  h1   {{ font-size: 1.4rem; color: #0B1F3A; border-bottom: 2px solid #0F62FE;
         padding-bottom: 8px; }}
  h2   {{ font-size: 1.1rem; color: #0B1F3A; margin-top: 2rem; }}
  h3   {{ font-size: 1rem; color: #0B1F3A; margin-top: 1.5rem; }}
  .label {{ font-size: 0.78rem; color: #525252; border: 1px solid #dde1e6;
            border-radius: 4px; padding: 4px 10px; display: inline-block;
            margin-bottom: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
  td, th {{ border: 1px solid #dde1e6; padding: 6px 10px; font-size: 0.88rem; }}
  th {{ background: #f4f4f4; text-align: left; }}
  .footer {{ font-size: 0.75rem; color: #525252; margin-top: 3rem;
             border-top: 1px solid #dde1e6; padding-top: 8px; }}
</style>
</head>
<body>
<h1>Procurement Audit Brief — {dept}</h1>
<div class="label">{label_esc}</div>
<p style="color:#525252;font-size:0.85rem;">Generated: {today}</p>
{body_html}
<h2>Facts used in this analysis</h2>
<table>
<thead><tr><th>Metric</th><th>Value</th></tr></thead>
<tbody>{facts_rows}</tbody>
</table>
<div class="footer">
  Data source: Open Government Portal — Proactive Disclosure of Contracts.<br>
  This brief is an indicator for review and does not constitute a finding of wrongdoing.
</div>
</body>
</html>"""
