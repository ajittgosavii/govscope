"""
data_client.py — API calls and cached fallback for contract data.

All network I/O and filesystem access lives here.
No business logic; records are returned as-is from the API.
"""

import json
import pathlib
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_URL = "https://open.canada.ca/data/api/3/action/datastore_search"
_RESOURCE_ID = "fac950c0-00d5-4ec1-a4d3-9cbebf98a305"
_FIELDS = (
    "vendor_name,contract_value,original_value,amendment_value,"
    "contract_date,solicitation_procedure,limited_tendering_reason,"
    "number_of_bids,vendor_postal_code,commodity_type,"
    "description_en,owner_org,owner_org_title,reference_number,"
    "procurement_id,reporting_period"
)
_PAGE_SIZE = 1000
_TIMEOUT = 30  # seconds

_SAMPLE_DIR = pathlib.Path(__file__).parent / "sample_data"

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Allowed owner_org slugs (validated before any network call)
# ---------------------------------------------------------------------------

# This set is populated lazily by callers that have access to the full
# DEPARTMENTS dict (app.py).  When empty, all slugs are permitted so that
# tests and standalone use of data_client continue to work without importing
# app.py here.
_ALLOWED_ORGS: set[str] = set()


def register_allowed_orgs(slugs: set[str]) -> None:
    """Register the set of permitted owner_org slugs.

    Call once at startup (e.g. in app.py) with ``set(DEPARTMENTS.keys())``.
    When registered, ``fetch_contracts`` will reject unknown slugs with a
    ``ValueError`` before making any network request.
    """
    _ALLOWED_ORGS.update(slugs)


def fetch_contracts(
    owner_org: str,
    max_rows: int = 3000,
) -> tuple[list[dict[str, Any]], bool, int]:
    """Fetch contract records for *owner_org* from the Proactive Disclosure API.

    Pages through the datastore_search endpoint (up to *max_rows* records),
    deduplicates amendment rows, and returns the results.

    The Proactive Disclosure dataset adds a new row every time a contract is
    amended; each row repeats the full cumulative ``contract_value``.
    ``dedupe_amendments`` keeps only the most recent row per procurement_id.

    Parameters
    ----------
    owner_org:
        The ``owner_org`` slug to filter on (e.g. ``"ssc-spc"``).
    max_rows:
        Maximum number of records to retrieve across all pages.

    Returns
    -------
    tuple[list[dict], bool, int]
        ``(records, is_cached, raw_count)`` where:
        - *records* is the deduplicated list
        - *is_cached* is ``True`` only when loaded from the local fallback
        - *raw_count* is the number of rows **before** deduplication
          (``raw_count - len(records)`` = rows removed)

    Raises
    ------
    ValueError
        When *owner_org* is not in the registered set of allowed slugs (only
        raised once ``register_allowed_orgs`` has been called with a non-empty
        set).
    RuntimeError
        When the API is unreachable **and** no fallback file exists for the
        requested ``owner_org``.
    """
    if _ALLOWED_ORGS and owner_org not in _ALLOWED_ORGS:
        raise ValueError(
            f"Unknown owner_org slug {owner_org!r}. "
            f"Allowed values: {sorted(_ALLOWED_ORGS)}"
        )

    from analytics import dedupe_amendments  # local import avoids circular dep at module level

    try:
        raw = _paginate(owner_org, max_rows)
        is_cached = False
    except requests.RequestException as exc:
        raw, is_cached = _fallback(owner_org, original_error=exc)

    raw_count = len(raw)
    records, _ = dedupe_amendments(raw)
    return records, is_cached, raw_count


def load_code_labels() -> dict[str, dict[str, str]]:
    """Load human-readable labels for coded fields from sample_data/code_labels.json.

    Returns a dict with up to three keys — ``solicitation_procedure``,
    ``limited_tendering_reason``, and ``commodity_type`` — each mapping a
    code string to its English label string.  Missing or unreadable file
    returns a dict of empty sub-dicts so callers never need to guard against
    ``KeyError``.

    Example return value::

        {
            "solicitation_procedure": {"TN": "Traditional/Non-competitive", ...},
            "limited_tendering_reason": {"02": "National security", ...},
            "commodity_type": {"G": "Goods", "S": "Services"},
        }
    """
    code_file = _SAMPLE_DIR / "code_labels.json"
    empty: dict[str, dict[str, str]] = {
        "solicitation_procedure": {},
        "limited_tendering_reason": {},
        "commodity_type": {},
    }

    if not code_file.exists():
        return empty

    try:
        with code_file.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return empty

    # Merge whatever keys are present; fall back to empty dict per missing key.
    return {
        "solicitation_procedure":   dict(data.get("solicitation_procedure", {})),
        "limited_tendering_reason": dict(data.get("limited_tendering_reason", {})),
        "commodity_type":           dict(data.get("commodity_type", {})),
    }


def fetch_many(
    owner_orgs: list[str],
    max_rows_each: int = 1000,
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch contracts for multiple departments and concatenate the results.

    Calls ``fetch_contracts`` for each slug in *owner_orgs* and returns a
    single flat list of all records together with an ``is_cached`` flag that
    is ``True`` if **any** individual department fell back to cached data.
    Each department's records are already deduplicated by ``fetch_contracts``.

    Parameters
    ----------
    owner_orgs:
        List of ``owner_org`` slugs to query.
    max_rows_each:
        Maximum records to retrieve per department (passed to
        ``fetch_contracts`` as *max_rows*).

    Returns
    -------
    tuple[list[dict], bool]
        ``(records, is_cached)`` with the combined deduplicated record list.

    Raises
    ------
    RuntimeError
        Propagated from ``fetch_contracts`` if any department fails and has no
        fallback file.
    """
    all_records: list[dict[str, Any]] = []
    any_cached = False

    for org in owner_orgs:
        records, is_cached, _raw_count = fetch_contracts(org, max_rows=max_rows_each)
        all_records.extend(records)
        if is_cached:
            any_cached = True

    return all_records, any_cached


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _paginate(owner_org: str, max_rows: int) -> list[dict[str, Any]]:
    """Collect all pages for *owner_org* up to *max_rows* records.

    Raises ``requests.RequestException`` on any network or HTTP failure so the
    caller can decide whether to fall back.
    """
    records: list[dict[str, Any]] = []
    offset = 0

    while len(records) < max_rows:
        limit = min(_PAGE_SIZE, max_rows - len(records))
        params = {
            "resource_id": _RESOURCE_ID,
            "filters": json.dumps({"owner_org": owner_org}),
            "sort": "contract_date desc",
            "fields": _FIELDS,
            "limit": limit,
            "offset": offset,
        }

        response = requests.get(_API_URL, params=params, timeout=_TIMEOUT)
        response.raise_for_status()

        payload = response.json()
        if not payload.get("success"):
            raise requests.RequestException(
                f"API returned success=false for owner_org={owner_org!r}: "
                f"{payload.get('error', {})}"
            )

        result = payload["result"]
        page = result.get("records", [])
        records.extend(page)

        # Stop if the API has no more records to give.
        if len(page) < limit or len(records) >= result.get("total", 0):
            break

        offset += len(page)

    return records


def _fallback(
    owner_org: str,
    original_error: Exception,
) -> tuple[list[dict[str, Any]], bool]:  # returns (raw_records, is_cached) — NOT yet deduped
    """Attempt to load a local sample file for *owner_org*.

    Only ``ssc-spc`` has a bundled sample file.  For any other slug the
    original network error is re-raised as a ``RuntimeError`` with a clear
    message.

    Parameters
    ----------
    owner_org:
        The slug that was requested.
    original_error:
        The ``requests.RequestException`` that triggered the fallback.
    """
    sample_file = _SAMPLE_DIR / f"{owner_org}_latest1000.json"

    if not sample_file.exists():
        raise RuntimeError(
            f"Could not fetch contracts for {owner_org!r} from the API "
            f"({original_error}) and no local fallback file was found at "
            f"{sample_file}."
        ) from original_error

    try:
        with sample_file.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as file_exc:
        raise RuntimeError(
            f"Could not fetch contracts for {owner_org!r} from the API "
            f"({original_error}) and the local fallback file at {sample_file} "
            f"could not be read ({file_exc})."
        ) from file_exc

    # Accept either the raw API envelope or a plain list of records.
    if isinstance(payload, list):
        records = payload
    else:
        records = payload.get("result", {}).get("records", [])

    return records, True
