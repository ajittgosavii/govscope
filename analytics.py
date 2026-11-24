"""
analytics.py — advanced pure analytics functions for contract concentration.

No Streamlit, no network calls, no file I/O.
All money fields arrive as strings; blank/unparsable/negative values are 0.
Reuses _parse_value and normalize_vendor from concentration.py.
"""

from __future__ import annotations

import datetime
from typing import Any, NamedTuple

from concentration import _parse_value, normalize_vendor, hhi, noncompetitive_share, vendor_shares, top_vendor, TopVendor

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_COMPETITIVE_PROCEDURES = {"TC", "OB", "ST"}


def text(rec: dict[str, Any], field: str) -> str:
    """Return (rec.get(field) or "").strip() — safe against None values.

    API records sometimes include fields that are present but set to None
    rather than absent or "". This helper normalises all three cases to an
    empty string before any further string operations.

    >>> text({"a": None}, "a")
    ''
    >>> text({"a": "  TN  "}, "a")
    'TN'
    >>> text({}, "a")
    ''
    """
    return (rec.get(field) or "").strip()


def _parse_date(raw: str) -> datetime.date | None:
    """Parse YYYY-MM-DD string; return None on failure."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _parse_int(raw) -> int | None:
    """Parse a string or integer to int; return None on failure or blank.

    Accepts both ``str`` and ``int`` inputs because CKAN API responses
    sometimes return numeric fields as Python integers rather than strings.
    """
    if isinstance(raw, int):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 1. value_vs_count_share
# ---------------------------------------------------------------------------

class VendorShareRow(NamedTuple):
    vendor: str
    value_share_pct: float   # share of total contract value
    count_share_pct: float   # share of number of contracts


def value_vs_count_share(records: list[dict[str, Any]]) -> list[VendorShareRow]:
    """For each vendor return share of total value and share of contract count.

    Returns rows sorted descending by value share.
    """
    value_totals: dict[str, float] = {}
    counts: dict[str, int] = {}

    for rec in records:
        vendor = normalize_vendor(rec.get("vendor_name", ""))
        if not vendor:
            continue
        value = _parse_value(rec.get("contract_value", ""))
        value_totals[vendor] = value_totals.get(vendor, 0.0) + value
        counts[vendor] = counts.get(vendor, 0) + 1

    grand_value = sum(value_totals.values())
    grand_count = sum(counts.values())

    if grand_value == 0.0 or grand_count == 0:
        return []

    rows = [
        VendorShareRow(
            vendor=v,
            value_share_pct=round(value_totals[v] / grand_value * 100.0, 4),
            count_share_pct=round(counts[v] / grand_count * 100.0, 4),
        )
        for v in value_totals
    ]
    return sorted(rows, key=lambda r: r.value_share_pct, reverse=True)


# ---------------------------------------------------------------------------
# 2. largest_contract_share
# ---------------------------------------------------------------------------

class LargestContract(NamedTuple):
    vendor: str
    description: str
    value: float
    share_pct: float          # percent of total value


def largest_contract_share(records: list[dict[str, Any]]) -> LargestContract:
    """Return the single biggest contract as a percent of total spend."""
    if not records:
        return LargestContract("", "", 0.0, 0.0)

    best_rec = max(records, key=lambda r: _parse_value(r.get("contract_value", "")))
    best_val = _parse_value(best_rec.get("contract_value", ""))
    total = sum(_parse_value(r.get("contract_value", "")) for r in records)

    return LargestContract(
        vendor=normalize_vendor(best_rec.get("vendor_name", "")),
        description=(best_rec.get("description_en") or "").strip(),
        value=best_val,
        share_pct=round(best_val / total * 100.0, 4) if total else 0.0,
    )


# ---------------------------------------------------------------------------
# 3. competition_breakdown
# ---------------------------------------------------------------------------

class CompetitionBreakdown(NamedTuple):
    by_solicitation: list[dict[str, Any]]       # [{label, value, count}, …]
    by_tendering_reason: list[dict[str, Any]]   # [{label, value, count}, …], code "00" excluded
    single_bid_competitive: dict[str, Any]      # {count, value}


def competition_breakdown(
    records: list[dict[str, Any]],
    labels: dict[str, dict[str, str]],
) -> CompetitionBreakdown:
    """Breakdown of contract value and count by solicitation and tendering reason.

    *labels* is the dict returned by ``data_client.load_code_labels()``.
    ``limited_tendering_reason`` code ``"00"`` is excluded from the tendering
    breakdown.  Contracts with a competitive procedure (TC, OB, ST) but
    ``number_of_bids == 1`` are counted separately.
    """
    sol_labels = labels.get("solicitation_procedure", {})
    ltr_labels = labels.get("limited_tendering_reason", {})

    sol_value: dict[str, float] = {}
    sol_count: dict[str, int] = {}
    ltr_value: dict[str, float] = {}
    ltr_count: dict[str, int] = {}
    single_bid_count = 0
    single_bid_value = 0.0

    for rec in records:
        value = _parse_value(rec.get("contract_value", ""))
        sol_code = (rec.get("solicitation_procedure") or "").strip().upper()
        ltr_code = (rec.get("limited_tendering_reason") or "").strip()
        bids = _parse_int(rec.get("number_of_bids", ""))

        # Solicitation breakdown
        sol_key = sol_labels.get(sol_code, sol_code) if sol_code else "Unknown"
        sol_value[sol_key] = sol_value.get(sol_key, 0.0) + value
        sol_count[sol_key] = sol_count.get(sol_key, 0) + 1

        # Tendering reason breakdown (exclude "00")
        if ltr_code and ltr_code != "00":
            ltr_key = ltr_labels.get(ltr_code, ltr_code)
            ltr_value[ltr_key] = ltr_value.get(ltr_key, 0.0) + value
            ltr_count[ltr_key] = ltr_count.get(ltr_key, 0) + 1

        # Competitive but single-bid
        if sol_code in _COMPETITIVE_PROCEDURES and bids == 1:
            single_bid_count += 1
            single_bid_value += value

    by_sol = sorted(
        [{"label": k, "value": v, "count": sol_count[k]} for k, v in sol_value.items()],
        key=lambda x: x["value"],
        reverse=True,
    )
    by_ltr = sorted(
        [{"label": k, "value": v, "count": ltr_count[k]} for k, v in ltr_value.items()],
        key=lambda x: x["value"],
        reverse=True,
    )

    return CompetitionBreakdown(
        by_solicitation=by_sol,
        by_tendering_reason=by_ltr,
        single_bid_competitive={"count": single_bid_count, "value": single_bid_value},
    )


# ---------------------------------------------------------------------------
# 4. split_purchase_clusters
# ---------------------------------------------------------------------------

class SplitCluster(NamedTuple):
    vendor: str
    contract_count: int
    total_value: float
    date_range: str    # "YYYY-MM-DD – YYYY-MM-DD"


def split_purchase_clusters(
    records: list[dict[str, Any]],
    threshold: float = 25_000.0,
    window_days: int = 30,
) -> list[SplitCluster]:
    """Detect potential split-purchase patterns.

    For each vendor, find groups of two or more contracts whose value is in
    [threshold * 0.9, threshold) and whose contract_dates all fall within
    *window_days* of one another.  Returns one ``SplitCluster`` per group.

    Contracts valued exactly at *threshold* or above are excluded.
    Contracts below ``threshold * 0.9`` are excluded.
    """
    lower = threshold * 0.9

    # Group candidate records by vendor
    by_vendor: dict[str, list[tuple[datetime.date, float]]] = {}
    for rec in records:
        value = _parse_value(rec.get("contract_value", ""))
        if not (lower <= value < threshold):
            continue
        date = _parse_date(rec.get("contract_date", ""))
        if date is None:
            continue
        vendor = normalize_vendor(rec.get("vendor_name", ""))
        if not vendor:
            continue
        by_vendor.setdefault(vendor, []).append((date, value))

    clusters: list[SplitCluster] = []
    window = datetime.timedelta(days=window_days)

    for vendor, entries in by_vendor.items():
        # Sort by date and use a sliding window to find clusters
        entries_sorted = sorted(entries, key=lambda x: x[0])
        n = len(entries_sorted)
        used = [False] * n

        for i in range(n):
            if used[i]:
                continue
            group_dates = [entries_sorted[i][0]]
            group_values = [entries_sorted[i][1]]
            group_indices = [i]

            for j in range(i + 1, n):
                if used[j]:
                    continue
                # All dates in the growing cluster must span <= window_days
                candidate_dates = group_dates + [entries_sorted[j][0]]
                span = max(candidate_dates) - min(candidate_dates)
                if span <= window:
                    group_dates.append(entries_sorted[j][0])
                    group_values.append(entries_sorted[j][1])
                    group_indices.append(j)

            if len(group_indices) >= 2:
                for idx in group_indices:
                    used[idx] = True
                min_date = min(group_dates)
                max_date = max(group_dates)
                clusters.append(SplitCluster(
                    vendor=vendor,
                    contract_count=len(group_indices),
                    total_value=round(sum(group_values), 2),
                    date_range=(
                        f"{min_date.isoformat()} – {max_date.isoformat()}"
                        if min_date != max_date
                        else min_date.isoformat()
                    ),
                ))

    return sorted(clusters, key=lambda c: c.total_value, reverse=True)


# ---------------------------------------------------------------------------
# 5. amendment_flags
# ---------------------------------------------------------------------------

def amendment_flags(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return contracts where amendment is large relative to original value.

    Included when BOTH:
    - ``amendment_value`` >= 100 000
    - ``amendment_value`` > 50 % of ``original_value``
    """
    result = []
    for rec in records:
        orig = _parse_value(rec.get("original_value", ""))
        amend = _parse_value(rec.get("amendment_value", ""))
        if amend >= 100_000.0 and orig > 0.0 and amend > orig * 0.5:
            result.append(rec)
    return result


# ---------------------------------------------------------------------------
# 6. monthly_trend
# ---------------------------------------------------------------------------

class MonthlyRow(NamedTuple):
    month: str            # "YYYY-MM"
    total_value: float
    contract_count: int
    hhi_score: float
    noncompetitive_pct: float


def monthly_trend(records: list[dict[str, Any]]) -> list[MonthlyRow]:
    """Per-month total value, contract count, HHI, and non-competitive share.

    Rows are sorted ascending by month.  Records with unparsable dates are
    grouped under the key ``"unknown"``.
    """
    by_month: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        date = _parse_date(rec.get("contract_date", ""))
        key = date.strftime("%Y-%m") if date else "unknown"
        by_month.setdefault(key, []).append(rec)

    rows = []
    for month in sorted(by_month):
        month_recs = by_month[month]
        shares = vendor_shares(month_recs)
        rows.append(MonthlyRow(
            month=month,
            total_value=round(sum(_parse_value(r.get("contract_value", "")) for r in month_recs), 2),
            contract_count=len(month_recs),
            hhi_score=round(hhi(shares), 2),
            noncompetitive_pct=round(noncompetitive_share(month_recs), 4),
        ))
    return rows


# ---------------------------------------------------------------------------
# 7. province_from_postal
# ---------------------------------------------------------------------------

_POSTAL_MAP: dict[str, str] = {
    "A": "NL", "B": "NS", "C": "PE", "E": "NB",
    "G": "QC", "H": "QC", "J": "QC",
    "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON",
    "R": "MB", "S": "SK", "T": "AB", "V": "BC",
    "X": "NT/NU", "Y": "YT",
}


def province_from_postal(code: str) -> str:
    """Map the first letter of a postal code to a Canadian province/territory.

    Returns ``"Outside Canada / unknown"`` for unrecognised prefixes or
    non-string input.
    """
    if not isinstance(code, str) or not code.strip():
        return "Outside Canada / unknown"
    first = code.strip()[0].upper()
    return _POSTAL_MAP.get(first, "Outside Canada / unknown")


# ---------------------------------------------------------------------------
# 8. health_score / health_band
# ---------------------------------------------------------------------------

class HealthScore(NamedTuple):
    score: int                    # 0–100, rounded
    concentration_component: float
    competition_component: float
    diversity_component: float
    red_flags_component: float


def health_score(
    hhi: float,
    noncompetitive_pct: float,
    top_share_pct: float,
    flagged_contract_pct: float,
) -> HealthScore:
    """Compute a 0–100 procurement health score.

    Components
    ----------
    concentration (40 pts):  40 × (1 - hhi / 10 000)
    competition   (30 pts):  30 × (1 - noncompetitive_pct / 100)
    diversity     (15 pts):  15 × (1 - top_share_pct / 100)
    red flags     (15 pts):  15 × (1 - min(1, flagged_contract_pct / 10))

    *flagged_contract_pct* = (split-purchase contracts + large-amendment
    contracts) as a percent of all contracts.
    """
    concentration = 40.0 * (1.0 - min(1.0, hhi / 10_000.0))
    competition   = 30.0 * (1.0 - min(1.0, noncompetitive_pct / 100.0))
    diversity     = 15.0 * (1.0 - min(1.0, top_share_pct / 100.0))
    red_flags     = 15.0 * (1.0 - min(1.0, flagged_contract_pct / 10.0))

    total = concentration + competition + diversity + red_flags
    return HealthScore(
        score=round(total),
        concentration_component=round(concentration, 4),
        competition_component=round(competition, 4),
        diversity_component=round(diversity, 4),
        red_flags_component=round(red_flags, 4),
    )


def health_band(score: int) -> str:
    """Classify a health score into a band.

    >= 75  → "Healthy"
    50–74  → "Watch"
    < 50   → "At risk"
    """
    if score >= 75:
        return "Healthy"
    if score >= 50:
        return "Watch"
    return "At risk"


# ---------------------------------------------------------------------------
# 0. Amendment deduplication  (insert before all other analytics)
# ---------------------------------------------------------------------------

def dedupe_amendments(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Keep only the most recent amendment row per contract.

    The Proactive Disclosure dataset appends a new row every time a contract
    is amended, repeating the full cumulative ``contract_value``.  To avoid
    double-counting, we group rows by their procurement identifier and keep
    only the row with the highest ``reporting_period``.  Ties in
    ``reporting_period`` are broken by the highest ``reference_number``.

    Grouping key
    ------------
    ``procurement_id`` when non-blank; otherwise ``reference_number``.
    If both are blank, each row is treated as its own unique contract.

    Parameters
    ----------
    records:
        Raw list of records, possibly containing multiple amendment rows for
        the same contract.

    Returns
    -------
    tuple[list[dict], int]
        ``(deduped, removed_count)`` where *removed_count* is the number of
        rows that were discarded.
    """
    # Assign a stable grouping key to every record
    keyed: dict[str, dict[str, Any]] = {}
    singletons: list[dict[str, Any]] = []   # rows with no usable key

    for rec in records:
        pid = (rec.get("procurement_id") or "").strip()
        ref = (rec.get("reference_number") or "").strip()
        key = pid or ref or None

        if key is None:
            singletons.append(rec)
            continue

        if key not in keyed:
            keyed[key] = rec
        else:
            # Keep the row with the later reporting_period; break ties on reference_number
            existing = keyed[key]
            rp_new  = (rec.get("reporting_period")      or "").strip()
            rp_old  = (existing.get("reporting_period") or "").strip()
            rn_new  = (rec.get("reference_number")      or "").strip()
            rn_old  = (existing.get("reference_number") or "").strip()
            if (rp_new, rn_new) > (rp_old, rn_old):
                keyed[key] = rec

    deduped = list(keyed.values()) + singletons
    removed = len(records) - len(deduped)
    return deduped, removed


# ---------------------------------------------------------------------------
# 9. compare_departments
# ---------------------------------------------------------------------------

class DeptRow(NamedTuple):
    org:                 str    # owner_org slug
    name:                str    # human-readable department name
    contract_count:      int
    total_value:         float
    hhi_score:           float
    noncompetitive_pct:  float
    top_vendor_share:    float
    flagged_pct:         float
    health_score:        int
    health_band:         str


def compare_departments(
    records_by_org: dict[str, list[dict[str, Any]]],
    dept_names: dict[str, str],
) -> list[DeptRow]:
    """Compute per-department procurement metrics for cross-department comparison.

    Parameters
    ----------
    records_by_org:
        Mapping of ``owner_org`` slug → deduplicated list of contract records
        for that department.
    dept_names:
        Mapping of slug → human-readable department name (e.g. ``DEPARTMENTS``
        from ``app.py``).

    Returns
    -------
    list[DeptRow]
        One row per department that has at least one record, sorted descending
        by health score.
    """
    rows: list[DeptRow] = []

    for org, recs in records_by_org.items():
        if not recs:
            continue

        shares       = vendor_shares(recs)
        hhi_val      = hhi(shares)
        nc_pct       = noncompetitive_share(recs)
        tv           = top_vendor(shares) if shares else TopVendor("", 0.0)
        clusters     = split_purchase_clusters(recs)
        amd          = amendment_flags(recs)
        flagged_cnt  = sum(c.contract_count for c in clusters) + len(amd)
        flagged_pct  = flagged_cnt / len(recs) * 100  # recs is non-empty; guarded by continue above
        hs           = health_score(hhi_val, nc_pct, tv.share, flagged_pct)
        hb           = health_band(hs.score)
        total_val    = sum(_parse_value(r.get("contract_value", "")) for r in recs)

        rows.append(DeptRow(
            org=org,
            name=dept_names.get(org, org),
            contract_count=len(recs),
            total_value=round(total_val, 2),
            hhi_score=round(hhi_val, 1),
            noncompetitive_pct=round(nc_pct, 1),
            top_vendor_share=round(tv.share, 1),
            flagged_pct=round(flagged_pct, 1),
            health_score=hs.score,
            health_band=hb,
        ))

    return sorted(rows, key=lambda r: r.health_score, reverse=True)
