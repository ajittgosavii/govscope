"""
concentration.py — pure scoring functions for contract concentration analysis.

No I/O, no network calls, no Streamlit imports.
Each record is expected to be a dict with string fields:
  vendor_name, contract_value, solicitation_procedure
"""

import string
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_value(raw: str) -> float:
    """Return a non-negative float from a raw contract_value string.

    Blank or unparsable values become 0.  Negative values are treated as 0.
    """
    if not isinstance(raw, str) or not raw.strip():
        return 0.0
    # Remove currency symbols, commas, and surrounding whitespace.
    cleaned = raw.strip().lstrip("$").replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return 0.0
    return value if value >= 0 else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_vendor(name: str) -> str:
    """Return an uppercased, whitespace-trimmed name with trailing punctuation removed.

    >>> normalize_vendor("  Acme Corp.  ")
    'ACME CORP'
    """
    if not isinstance(name, str):
        return ""
    # Strip surrounding whitespace, uppercase, then remove trailing punctuation.
    normalized = name.strip().upper()
    normalized = normalized.rstrip(string.punctuation)
    return normalized


def vendor_shares(records: list[dict]) -> dict[str, float]:
    """Return a mapping of normalized vendor name → percent of total contract value.

    Records with zero or negative contract_value are included in the vendor
    aggregation only if they contribute a positive amount; they otherwise do
    not change the totals.  Returns an empty dict when total spend is zero.
    """
    totals: dict[str, float] = {}
    for rec in records:
        vendor = normalize_vendor(rec.get("vendor_name", ""))
        value = _parse_value(rec.get("contract_value", ""))
        if vendor:
            totals[vendor] = totals.get(vendor, 0.0) + value

    grand_total = sum(totals.values())
    if grand_total == 0.0:
        return {}

    return {vendor: (amount / grand_total) * 100.0 for vendor, amount in totals.items()}


def hhi(shares: dict[str, float]) -> float:
    """Return the Herfindahl–Hirschman Index: sum of squared percentage shares.

    Result is in the range 0–10 000.  An empty input returns 0.
    """
    return sum(s ** 2 for s in shares.values())


def band(hhi_score: float) -> str:
    """Classify an HHI score into a concentration band.

    < 1000       → "Low"
    1000–1800    → "Moderate"
    > 1800       → "High"
    """
    if hhi_score < 1000:
        return "Low"
    if hhi_score <= 1800:
        return "Moderate"
    return "High"


class TopVendor(NamedTuple):
    name: str
    share: float


def top_vendor(shares: dict[str, float]) -> TopVendor:
    """Return the name and percentage share of the highest-spending vendor.

    Returns TopVendor("", 0.0) when shares is empty.
    """
    if not shares:
        return TopVendor("", 0.0)
    name = max(shares, key=lambda v: shares[v])
    return TopVendor(name, shares[name])


def noncompetitive_share(records: list[dict]) -> float:
    """Return the percent of total contract value where solicitation_procedure is "TN".

    Returns 0.0 when total spend is zero or records is empty.
    """
    total = 0.0
    tn_total = 0.0
    for rec in records:
        value = _parse_value(rec.get("contract_value", ""))
        total += value
        if (rec.get("solicitation_procedure") or "").strip().upper() == "TN":
            tn_total += value

    if total == 0.0:
        return 0.0
    return (tn_total / total) * 100.0


def flags(shares: dict[str, float], records: list[dict]) -> list[str]:
    """Return a list of human-readable concentration flag strings.

    Rules:
      "single-vendor dependency"  when the top vendor share > 40 %
      "low competition"           when the non-competitive share > 30 %

    The returned list may contain zero, one, or both flags.
    """
    result: list[str] = []
    tv = top_vendor(shares)
    if tv.share > 40.0:
        result.append("single-vendor dependency")
    if noncompetitive_share(records) > 30.0:
        result.append("low competition")
    return result
