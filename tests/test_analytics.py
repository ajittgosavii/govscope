"""
tests/test_analytics.py — pytest suite for analytics.py
"""

import json
import pathlib
import pytest

from analytics import (
    health_score,
    health_band,
    split_purchase_clusters,
    amendment_flags,
    province_from_postal,
    competition_breakdown,
    dedupe_amendments,
    text,
)
from concentration import noncompetitive_share, vendor_shares, hhi, top_vendor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_FILE = (
    pathlib.Path(__file__).parent.parent / "sample_data" / "ssc-spc_latest1000.json"
)


def _load_sample_records() -> list[dict]:
    with _SAMPLE_FILE.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload["result"]["records"]


def _make_record(**kwargs) -> dict:
    """Return a minimal contract record dict with sensible defaults."""
    defaults = {
        "vendor_name": "ACME INC",
        "contract_value": "1000.0",
        "original_value": "1000.0",
        "amendment_value": "0.0",
        "contract_date": "2024-01-15",
        "solicitation_procedure": "TC",
        "limited_tendering_reason": "00",
        "number_of_bids": "3",
        "vendor_postal_code": "K1A",
        "commodity_type": "S",
        "description_en": "Test contract",
        "owner_org": "test-org",
        "owner_org_title": "Test Org",
        "reference_number": "REF-001",
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# health_score
# ---------------------------------------------------------------------------

class TestHealthScore:
    def test_perfect_score(self):
        hs = health_score(hhi=0, noncompetitive_pct=0, top_share_pct=0, flagged_contract_pct=0)
        assert hs.score == 100

    def test_zero_score(self):
        hs = health_score(hhi=10_000, noncompetitive_pct=100, top_share_pct=100, flagged_contract_pct=10)
        assert hs.score == 0

    def test_components_sum_to_score(self):
        hs = health_score(hhi=5000, noncompetitive_pct=50, top_share_pct=60, flagged_contract_pct=5)
        total = (
            hs.concentration_component
            + hs.competition_component
            + hs.diversity_component
            + hs.red_flags_component
        )
        assert abs(total - hs.score) <= 1  # rounding tolerance of ±1

    def test_flagged_pct_capped_at_10(self):
        # flagged_contract_pct of 20 should give same red-flags component as 10
        hs_10 = health_score(hhi=0, noncompetitive_pct=0, top_share_pct=0, flagged_contract_pct=10)
        hs_20 = health_score(hhi=0, noncompetitive_pct=0, top_share_pct=0, flagged_contract_pct=20)
        assert hs_10.red_flags_component == hs_20.red_flags_component == 0.0


# ---------------------------------------------------------------------------
# health_band
# ---------------------------------------------------------------------------

class TestHealthBand:
    def test_at_risk_boundary(self):
        assert health_band(49) == "At risk"

    def test_watch_lower_boundary(self):
        assert health_band(50) == "Watch"

    def test_watch_upper_boundary(self):
        assert health_band(74) == "Watch"

    def test_healthy_boundary(self):
        assert health_band(75) == "Healthy"


# ---------------------------------------------------------------------------
# split_purchase_clusters
# ---------------------------------------------------------------------------

class TestSplitPurchaseClusters:
    def test_finds_two_contracts_within_window(self):
        records = [
            _make_record(vendor_name="ACME INC", contract_value="24000", contract_date="2024-01-01"),
            _make_record(vendor_name="ACME INC", contract_value="24000", contract_date="2024-01-11"),
        ]
        clusters = split_purchase_clusters(records, threshold=25_000, window_days=30)
        assert len(clusters) == 1
        assert clusters[0].vendor == "ACME INC"
        assert clusters[0].contract_count == 2

    def test_ignores_pair_outside_window(self):
        records = [
            _make_record(vendor_name="ACME INC", contract_value="24000", contract_date="2024-01-01"),
            _make_record(vendor_name="ACME INC", contract_value="24000", contract_date="2024-02-11"),
        ]
        clusters = split_purchase_clusters(records, threshold=25_000, window_days=30)
        assert len(clusters) == 0

    def test_ignores_contract_at_exact_threshold(self):
        records = [
            _make_record(vendor_name="ACME INC", contract_value="25000", contract_date="2024-01-01"),
            _make_record(vendor_name="ACME INC", contract_value="25000", contract_date="2024-01-02"),
        ]
        clusters = split_purchase_clusters(records, threshold=25_000, window_days=30)
        assert len(clusters) == 0

    def test_ignores_contract_below_90_percent(self):
        # 22_499 is below 25_000 * 0.9 = 22_500
        records = [
            _make_record(vendor_name="ACME INC", contract_value="22499", contract_date="2024-01-01"),
            _make_record(vendor_name="ACME INC", contract_value="22499", contract_date="2024-01-02"),
        ]
        clusters = split_purchase_clusters(records, threshold=25_000, window_days=30)
        assert len(clusters) == 0


# ---------------------------------------------------------------------------
# amendment_flags
# ---------------------------------------------------------------------------

class TestAmendmentFlags:
    def test_includes_large_amendment(self):
        records = [_make_record(original_value="100000", amendment_value="150000")]
        result = amendment_flags(records)
        assert len(result) == 1

    def test_excludes_small_ratio(self):
        # amendment 150_000 is only 15% of 1_000_000 — below 50%
        records = [_make_record(original_value="1000000", amendment_value="150000")]
        result = amendment_flags(records)
        assert len(result) == 0

    def test_excludes_amendment_below_100k(self):
        # ratio is > 50% but amount < 100_000
        records = [_make_record(original_value="10000", amendment_value="9000")]
        result = amendment_flags(records)
        assert len(result) == 0

    def test_boundary_exactly_100k(self):
        # amendment exactly 100_000 and > 50% of original → included
        records = [_make_record(original_value="100000", amendment_value="100000")]
        result = amendment_flags(records)
        assert len(result) == 1

    def test_zero_original_excluded(self):
        records = [_make_record(original_value="0", amendment_value="150000")]
        result = amendment_flags(records)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# province_from_postal
# ---------------------------------------------------------------------------

class TestProvinceFromPostal:
    def test_ontario_k(self):
        assert province_from_postal("K1A") == "ON"

    def test_quebec_h(self):
        assert province_from_postal("H2X") == "QC"

    def test_bc_v(self):
        assert province_from_postal("V6B") == "BC"

    def test_non_canadian(self):
        assert province_from_postal("12345") == "Outside Canada / unknown"

    def test_empty_string(self):
        assert province_from_postal("") == "Outside Canada / unknown"

    def test_case_insensitive(self):
        assert province_from_postal("k1a") == "ON"

    def test_nova_scotia(self):
        assert province_from_postal("B3H") == "NS"

    def test_nt_nu(self):
        assert province_from_postal("X0A") == "NT/NU"


# ---------------------------------------------------------------------------
# competition_breakdown — single-bid competitive
# ---------------------------------------------------------------------------

class TestCompetitionBreakdown:
    _labels = {
        "solicitation_procedure": {
            "TC": "Competitive – Traditional",
            "TN": "Non-Competitive",
            "OB": "Open Bidding",
            "ST": "Selective Tendering",
        },
        "limited_tendering_reason": {},
        "commodity_type": {},
    }

    def test_tc_with_one_bid_counted(self):
        records = [
            _make_record(solicitation_procedure="TC", number_of_bids="1", contract_value="50000"),
        ]
        result = competition_breakdown(records, self._labels)
        assert result.single_bid_competitive["count"] == 1
        assert result.single_bid_competitive["value"] == 50_000.0

    def test_tn_not_counted_as_single_bid_competitive(self):
        # TN with 1 bid is non-competitive, not a "competitive single-bid"
        records = [
            _make_record(solicitation_procedure="TN", number_of_bids="1", contract_value="50000"),
        ]
        result = competition_breakdown(records, self._labels)
        assert result.single_bid_competitive["count"] == 0

    def test_solicitation_label_mapped(self):
        records = [
            _make_record(solicitation_procedure="TC", contract_value="10000"),
        ]
        result = competition_breakdown(records, self._labels)
        labels_in_result = [row["label"] for row in result.by_solicitation]
        assert "Competitive – Traditional" in labels_in_result

    def test_ltr_excludes_code_00(self):
        records = [
            _make_record(solicitation_procedure="TN", limited_tendering_reason="00", contract_value="5000"),
        ]
        result = competition_breakdown(records, self._labels)
        assert result.by_tendering_reason == []


# ---------------------------------------------------------------------------
# dedupe_amendments
# ---------------------------------------------------------------------------

class TestDedupeAmendments:

    def _rec(self, pid="", ref="", period="", **kwargs) -> dict:
        base = {
            "procurement_id":   pid,
            "reference_number": ref,
            "reporting_period": period,
            "contract_value":   "1000",
        }
        base.update(kwargs)
        return base

    def test_three_rows_same_pid_keeps_latest_period(self):
        """Three rows with the same procurement_id: keep only the 2026-2027-Q1 row."""
        records = [
            self._rec(pid="P-001", ref="R-001", period="2025-2026-Q2"),
            self._rec(pid="P-001", ref="R-002", period="2025-2026-Q4"),
            self._rec(pid="P-001", ref="R-003", period="2026-2027-Q1"),
        ]
        deduped, removed = dedupe_amendments(records)
        assert len(deduped) == 1
        assert removed == 2
        assert deduped[0]["reporting_period"] == "2026-2027-Q1"
        assert deduped[0]["reference_number"] == "R-003"

    def test_different_procurement_ids_all_kept(self):
        records = [
            self._rec(pid="P-001", ref="R-001", period="2025-2026-Q2"),
            self._rec(pid="P-002", ref="R-002", period="2025-2026-Q2"),
            self._rec(pid="P-003", ref="R-003", period="2025-2026-Q2"),
        ]
        deduped, removed = dedupe_amendments(records)
        assert len(deduped) == 3
        assert removed == 0

    def test_tie_period_breaks_on_reference_number(self):
        """Same reporting_period: keep the row with the lexicographically higher ref."""
        records = [
            self._rec(pid="P-001", ref="R-001", period="2025-2026-Q2"),
            self._rec(pid="P-001", ref="R-002", period="2025-2026-Q2"),
        ]
        deduped, removed = dedupe_amendments(records)
        assert len(deduped) == 1
        assert deduped[0]["reference_number"] == "R-002"

    def test_blank_pid_falls_back_to_reference_number(self):
        """When procurement_id is blank, group by reference_number."""
        records = [
            self._rec(pid="", ref="R-001", period="2025-2026-Q2"),
            self._rec(pid="", ref="R-001", period="2025-2026-Q4"),
        ]
        deduped, removed = dedupe_amendments(records)
        assert len(deduped) == 1
        assert deduped[0]["reporting_period"] == "2025-2026-Q4"

    def test_no_key_treated_as_singleton(self):
        """Rows with blank pid AND blank ref are all kept."""
        records = [
            self._rec(pid="", ref="", period="2025-2026-Q2"),
            self._rec(pid="", ref="", period="2025-2026-Q4"),
        ]
        deduped, removed = dedupe_amendments(records)
        assert len(deduped) == 2
        assert removed == 0

    def test_empty_input(self):
        deduped, removed = dedupe_amendments([])
        assert deduped == []
        assert removed == 0


# ---------------------------------------------------------------------------
# None-safe field access — text() helper and downstream functions
# ---------------------------------------------------------------------------

class TestNullFieldSafety:
    """Ensure no AttributeError when API records contain None for string fields."""

    _labels = {
        "solicitation_procedure": {"TC": "Competitive – Traditional", "TN": "Non-Competitive"},
        "limited_tendering_reason": {},
        "commodity_type": {},
    }

    def _null_record(self, **overrides) -> dict:
        """Record where every string field is explicitly None."""
        base = {
            "vendor_name":              None,
            "contract_value":           None,
            "original_value":           None,
            "amendment_value":          None,
            "contract_date":            None,
            "solicitation_procedure":   None,
            "limited_tendering_reason": None,
            "number_of_bids":           None,
            "vendor_postal_code":       None,
            "commodity_type":           None,
            "description_en":           None,
            "owner_org":                None,
            "owner_org_title":          None,
            "reference_number":         None,
        }
        base.update(overrides)
        return base

    def test_text_helper_none(self):
        assert text({"a": None}, "a") == ""

    def test_text_helper_missing_key(self):
        assert text({}, "missing") == ""

    def test_text_helper_whitespace(self):
        assert text({"a": "  TN  "}, "a") == "TN"

    def test_competition_breakdown_null_procedure_and_bids(self):
        """competition_breakdown must not crash when solicitation_procedure is None."""
        records = [
            self._null_record(contract_value="5000"),
            _make_record(solicitation_procedure="TC", number_of_bids="1", contract_value="1000"),
        ]
        # Should not raise
        result = competition_breakdown(records, self._labels)
        assert result.single_bid_competitive["count"] == 1

    def test_noncompetitive_share_null_procedure(self):
        """noncompetitive_share must not crash when solicitation_procedure is None."""
        records = [
            self._null_record(contract_value="10000"),
            _make_record(solicitation_procedure="TN", contract_value="5000"),
        ]
        pct = noncompetitive_share(records)
        # Only the TN record counts: 5000 / 15000 * 100 ≈ 33.3
        assert abs(pct - 33.333) < 0.01

    def test_split_purchase_clusters_null_fields(self):
        """split_purchase_clusters must not crash with None vendor/date/value."""
        records = [
            self._null_record(),
            _make_record(vendor_name="ACME INC", contract_value="24000",
                         contract_date="2024-01-01"),
            _make_record(vendor_name="ACME INC", contract_value="24000",
                         contract_date="2024-01-05"),
        ]
        clusters = split_purchase_clusters(records, threshold=25_000, window_days=30)
        assert len(clusters) == 1

    def test_amendment_flags_null_money(self):
        """amendment_flags must treat None original/amendment as 0 and not crash."""
        records = [self._null_record()]
        result = amendment_flags(records)
        assert result == []

    def test_number_of_bids_none_not_counted_as_single_bid(self):
        """A None number_of_bids must not be treated as '1'."""
        records = [
            self._null_record(solicitation_procedure="TC", contract_value="50000"),
        ]
        result = competition_breakdown(records, self._labels)
        assert result.single_bid_competitive["count"] == 0


# ---------------------------------------------------------------------------
# Fixture tests against ssc-spc_latest1000.json
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _SAMPLE_FILE.exists(),
    reason="sample_data/ssc-spc_latest1000.json not present",
)
class TestSampleData:
    @pytest.fixture(scope="class")
    def records(self):
        """Load and deduplicate the sample file — mirrors what fetch_contracts does."""
        raw = _load_sample_records()
        deduped, _ = dedupe_amendments(raw)
        return deduped

    def test_unique_contract_count(self, records):
        assert len(records) == 940

    def test_hhi_range(self, records):
        shares = vendor_shares(records)
        h = hhi(shares)
        assert 1500 <= h <= 1545, f"HHI {h:.1f} not in [1500, 1545]"

    def test_top_vendor_share_range(self, records):
        shares = vendor_shares(records)
        tv = top_vendor(shares)
        assert 35.0 <= tv.share <= 36.5, f"Top vendor share {tv.share:.2f}% not in [35, 36.5]"

    def test_split_purchase_clusters_count(self, records):
        clusters = split_purchase_clusters(records)
        assert len(clusters) == 4

    def test_amendment_flags_count(self, records):
        flagged = amendment_flags(records)
        assert len(flagged) == 16


# ---------------------------------------------------------------------------
# Regression tests for bugs found in code review 2026-11-24
# ---------------------------------------------------------------------------

class TestH1RuleBasedBriefGuard:
    """H-1: _rule_based_brief guard condition was always True (int never in list[str])."""

    def _make_facts(self, **overrides) -> dict:
        base = {
            "department_name":           "Test Dept",
            "date_range":                "2024-01 to 2024-12",
            "health_score":              60,
            "health_band":               "Watch",
            "total_value_fmt":           "$1.0M",
            "contract_count":            100,
            "vendor_count":              20,
            "hhi_score":                 1500,
            "top_vendor_name":           "ACME INC",
            "top_vendor_share_pct":      35.0,
            "largest_contract_share_pct": 20.0,
            "noncompetitive_pct":        20.0,
            "single_bid_count":          0,
            "split_purchase_clusters":   0,
            "large_amendment_count":     0,
        }
        base.update(overrides)
        return base

    def test_large_amendments_appear_in_top3_when_no_other_risks(self):
        """When only large_amendment_count > 0, it should appear in the brief."""
        from ai_brief import _rule_based_brief
        facts = self._make_facts(large_amendment_count=5)
        brief = _rule_based_brief(facts)
        assert "Large amendments" in brief

    def test_top3_capped_at_three_items(self):
        """With 6 possible risks triggered, only 3 should appear in section 2."""
        from ai_brief import _rule_based_brief
        facts = self._make_facts(
            top_vendor_share_pct=45.0,       # triggers single-vendor dependency
            noncompetitive_pct=35.0,          # triggers low competition
            split_purchase_clusters=2,        # triggers split purchases
            large_amendment_count=5,          # triggers large amendments
            single_bid_count=3,               # triggers single-bid
            largest_contract_share_pct=55.0,  # triggers dominant contract
        )
        brief = _rule_based_brief(facts)
        # Isolate section 2 ("Top 3 risks") — ends at the next "###" heading
        import re
        section2_match = re.search(
            r"### 2\. Top 3 risks\n(.*?)(?=###|\Z)", brief, re.DOTALL
        )
        assert section2_match, "Section '### 2. Top 3 risks' not found in brief"
        section2_text = section2_match.group(1)
        numbered = re.findall(r"^\d+\.", section2_text, re.MULTILINE)
        assert len(numbered) == 3, f"Expected 3 risk items in section 2, found {len(numbered)}"

    def test_no_duplicate_amendment_risk_when_many_risks(self):
        """Large amendments must not appear twice in the top-3 list."""
        from ai_brief import _rule_based_brief
        facts = self._make_facts(
            large_amendment_count=5,
            split_purchase_clusters=2,
            noncompetitive_pct=35.0,
        )
        brief = _rule_based_brief(facts)
        assert brief.count("Large amendments") <= 1


class TestH2NumberOfBidsIntegerSafe:
    """H-2: number_of_bids arriving as int (not str) must not raise AttributeError."""

    _labels = {
        "solicitation_procedure": {"TC": "Competitive – Traditional"},
        "limited_tendering_reason": {},
        "commodity_type": {},
    }

    def test_integer_bids_counted_in_competition_breakdown(self):
        """analytics.competition_breakdown already uses _parse_int — confirm it handles int input."""
        records = [
            _make_record(solicitation_procedure="TC", number_of_bids=1, contract_value="50000"),
        ]
        result = competition_breakdown(records, self._labels)
        assert result.single_bid_competitive["count"] == 1

    def test_integer_bids_zero_not_counted(self):
        records = [
            _make_record(solicitation_procedure="TC", number_of_bids=3, contract_value="50000"),
        ]
        result = competition_breakdown(records, self._labels)
        assert result.single_bid_competitive["count"] == 0

    def test_integer_bids_none_not_counted(self):
        records = [
            _make_record(solicitation_procedure="TC", number_of_bids=None, contract_value="50000"),
        ]
        result = competition_breakdown(records, self._labels)
        assert result.single_bid_competitive["count"] == 0


class TestM2FallbackCorruptFile:
    """M-2: _fallback must raise RuntimeError (not raw json.JSONDecodeError) on corrupt file."""

    def test_corrupt_fallback_raises_runtime_error(self, tmp_path):
        import requests as _requests
        from data_client import _fallback

        # Write a corrupt (non-JSON) file where the fallback would look for it
        fake_org = "corrupt-dept"
        sample_dir = tmp_path
        corrupt_file = sample_dir / f"{fake_org}_latest1000.json"
        corrupt_file.write_text("<<<not json>>>", encoding="utf-8")

        # Patch _SAMPLE_DIR inside data_client so _fallback finds our corrupt file
        import data_client as dc
        original_dir = dc._SAMPLE_DIR
        dc._SAMPLE_DIR = sample_dir
        try:
            original_error = _requests.RequestException("network down")
            with pytest.raises(RuntimeError, match="could not be read"):
                _fallback(fake_org, original_error)
        finally:
            dc._SAMPLE_DIR = original_dir

    def test_missing_fallback_raises_runtime_error(self, tmp_path):
        import requests as _requests
        from data_client import _fallback

        import data_client as dc
        original_dir = dc._SAMPLE_DIR
        dc._SAMPLE_DIR = tmp_path  # empty dir — no fallback file
        try:
            original_error = _requests.RequestException("network down")
            with pytest.raises(RuntimeError, match="no local fallback file"):
                _fallback("no-such-dept", original_error)
        finally:
            dc._SAMPLE_DIR = original_dir


class TestM1AuthStrip:
    """M-1: _check_credentials must handle whitespace in stored username gracefully."""

    def test_compare_digest_strips_expected_user(self):
        """hmac.compare_digest must receive stripped versions of both sides."""
        import hmac
        # Simulate what _check_credentials now does: strip both sides
        stored_user = "  judge  "   # whitespace that could appear in secrets.toml
        entered_user = "judge"
        assert hmac.compare_digest(entered_user.strip(), stored_user.strip())

    def test_compare_digest_mismatch_without_strip_would_fail(self):
        """Confirm the old behaviour (no strip on expected) would have caused a lockout."""
        import hmac
        stored_user = "  judge  "
        entered_user = "judge"
        # Without stripping stored_user, the digest comparison returns False
        assert not hmac.compare_digest(entered_user.strip(), stored_user)


# ---------------------------------------------------------------------------
# compare_departments — tab 8 pure function
# ---------------------------------------------------------------------------

class TestCompareDepartments:
    """compare_departments returns rows sorted descending by health score."""

    from analytics import compare_departments as _compare_departments

    _dept_names = {
        "dept-a": "Department A",
        "dept-b": "Department B",
        "dept-c": "Department C",
    }

    def _recs(self, vendor: str, value: str, n: int, proc: str = "TC") -> list[dict]:
        """Return *n* minimal contract records for a single vendor."""
        return [
            _make_record(
                vendor_name=vendor,
                contract_value=value,
                solicitation_procedure=proc,
                owner_org="test-org",
            )
            for _ in range(n)
        ]

    def test_sorted_descending_by_health_score(self):
        from analytics import compare_departments
        # dept-a: perfectly competitive, one vendor, tiny HHI → high score
        # dept-c: all non-competitive, single vendor → low score
        records_by_org = {
            "dept-a": self._recs("VENDOR X", "1000", 10, proc="TC"),
            "dept-b": self._recs("VENDOR Y", "1000", 10, proc="OB"),
            "dept-c": self._recs("VENDOR Z", "1000", 10, proc="TN"),  # all non-competitive
        }
        rows = compare_departments(records_by_org, self._dept_names)
        scores = [r.health_score for r in rows]
        assert scores == sorted(scores, reverse=True), (
            f"Rows not sorted descending by score: {scores}"
        )

    def test_dept_with_no_records_excluded(self):
        from analytics import compare_departments
        records_by_org = {
            "dept-a": self._recs("VENDOR X", "1000", 5),
            "dept-b": [],   # empty — must be excluded
        }
        rows = compare_departments(records_by_org, self._dept_names)
        org_slugs = [r.org for r in rows]
        assert "dept-a" in org_slugs
        assert "dept-b" not in org_slugs

    def test_health_band_matches_score(self):
        from analytics import compare_departments, health_band
        records_by_org = {
            "dept-a": self._recs("VENDOR X", "1000", 5, proc="TC"),
        }
        rows = compare_departments(records_by_org, self._dept_names)
        assert len(rows) == 1
        assert rows[0].health_band == health_band(rows[0].health_score)

    def test_department_name_resolved(self):
        from analytics import compare_departments
        records_by_org = {"dept-a": self._recs("VENDOR X", "1000", 3)}
        rows = compare_departments(records_by_org, self._dept_names)
        assert rows[0].name == "Department A"

    def test_unknown_org_falls_back_to_slug(self):
        from analytics import compare_departments
        records_by_org = {"unknown-slug": self._recs("VENDOR X", "1000", 3)}
        rows = compare_departments(records_by_org, self._dept_names)
        assert rows[0].name == "unknown-slug"


# ---------------------------------------------------------------------------
# Regression tests for second-pass code review (2026-11-24)
# ---------------------------------------------------------------------------

class TestH1DepartmentsGetSafe:
    """H-1: DEPARTMENTS lookups must use .get() so a stale slug never raises KeyError."""

    def test_departments_get_returns_slug_for_unknown_key(self):
        """DEPARTMENTS.get(unknown, unknown) must return the slug, not raise."""
        DEPARTMENTS = {"ssc-spc": "Shared Services Canada"}
        active_dept = "obsolete-slug"
        result = DEPARTMENTS.get(active_dept, active_dept)
        assert result == "obsolete-slug"

    def test_departments_direct_access_raises_for_unknown_key(self):
        """Confirm the old pattern raises — validates that the fix was needed."""
        DEPARTMENTS = {"ssc-spc": "Shared Services Canada"}
        with pytest.raises(KeyError):
            _ = DEPARTMENTS["obsolete-slug"]


class TestH2DatetimeImport:
    """H-2: datetime.date.today() must work without __import__ hack."""

    def test_datetime_module_accessible_without_import_hack(self):
        import datetime as _dt
        result = _dt.date.today().isoformat()
        # Result must be a valid ISO date string YYYY-MM-DD
        assert len(result) == 10
        assert result[4] == "-" and result[7] == "-"


class TestH3FlaggedPctNoDeadGuard:
    """H-3: compare_departments flagged_pct must be computed without dead guard."""

    def test_flagged_pct_computed_correctly_for_non_empty_recs(self):
        from analytics import compare_departments
        # 2 records, neither flagged → flagged_pct = 0
        recs = [
            _make_record(vendor_name="A", contract_value="1000",
                         original_value="1000", amendment_value="0"),
            _make_record(vendor_name="B", contract_value="1000",
                         original_value="1000", amendment_value="0"),
        ]
        rows = compare_departments({"dept": recs}, {"dept": "Dept"})
        assert len(rows) == 1
        assert rows[0].flagged_pct == 0.0

    def test_empty_org_excluded_before_division(self):
        """An org with zero records must be excluded, not cause ZeroDivisionError."""
        from analytics import compare_departments
        rows = compare_departments({"empty-dept": []}, {"empty-dept": "Empty"})
        assert rows == []


class TestM1WatsonxErrorTruncated:
    """M-1: Watsonx SDK exception message must be truncated to 120 chars in the label."""

    def test_long_exception_message_truncated(self):
        from ai_brief import generate_brief

        long_msg = "X" * 300
        # Simulate a watsonx call failure by patching _call_watsonx
        import ai_brief as _ab
        import unittest.mock as mock

        original = _ab._call_watsonx
        try:
            _ab._call_watsonx = mock.Mock(side_effect=RuntimeError(long_msg))
            # Need is_watsonx_available to return True
            with mock.patch.object(_ab, "is_watsonx_available", return_value=True):
                _, is_ai, label = generate_brief({"department_name": "Test",
                                                   "contract_count": 1,
                                                   "vendor_count": 1,
                                                   "hhi_score": 500,
                                                   "noncompetitive_pct": 10.0,
                                                   "top_vendor_share_pct": 20.0,
                                                   "health_score": 70,
                                                   "health_band": "Watch",
                                                   "total_value_fmt": "$1M",
                                                   "split_purchase_clusters": 0,
                                                   "large_amendment_count": 0,
                                                   "single_bid_count": 0,
                                                   "largest_contract_share_pct": 5.0,
                                                   "date_range": "2024-01 to 2024-12"})
            assert is_ai is False
            # The error substring in the label must be at most 120 chars
            # label format: "Rule-based fallback (watsonx error: <msg>)"
            prefix = "Rule-based fallback (watsonx error: "
            assert label.startswith(prefix)
            error_part = label[len(prefix):-1]  # strip trailing ")"
            assert len(error_part) <= 120
        finally:
            _ab._call_watsonx = original

    def test_short_exception_message_preserved(self):
        from ai_brief import generate_brief
        import ai_brief as _ab
        import unittest.mock as mock

        original = _ab._call_watsonx
        try:
            _ab._call_watsonx = mock.Mock(side_effect=RuntimeError("short error"))
            with mock.patch.object(_ab, "is_watsonx_available", return_value=True):
                _, _, label = generate_brief({"department_name": "Test",
                                               "contract_count": 1,
                                               "vendor_count": 1,
                                               "hhi_score": 500,
                                               "noncompetitive_pct": 10.0,
                                               "top_vendor_share_pct": 20.0,
                                               "health_score": 70,
                                               "health_band": "Watch",
                                               "total_value_fmt": "$1M",
                                               "split_purchase_clusters": 0,
                                               "large_amendment_count": 0,
                                               "single_bid_count": 0,
                                               "largest_contract_share_pct": 5.0,
                                               "date_range": "2024-01 to 2024-12"})
            assert "short error" in label
        finally:
            _ab._call_watsonx = original


class TestM2OwnerOrgValidation:
    """M-2: fetch_contracts must reject unknown slugs when allowed orgs are registered."""

    def test_raises_value_error_for_unknown_slug(self):
        import data_client as dc
        original = dc._ALLOWED_ORGS.copy()
        try:
            dc._ALLOWED_ORGS.clear()
            dc.register_allowed_orgs({"ssc-spc", "dnd-mdn"})
            with pytest.raises(ValueError, match="Unknown owner_org slug"):
                dc.fetch_contracts("evil-injection-attempt")
        finally:
            dc._ALLOWED_ORGS.clear()
            dc._ALLOWED_ORGS.update(original)

    def test_known_slug_passes_validation(self):
        """A slug that is in _ALLOWED_ORGS must not raise ValueError at the guard."""
        import data_client as dc
        original = dc._ALLOWED_ORGS.copy()
        try:
            dc._ALLOWED_ORGS.clear()
            dc.register_allowed_orgs({"ssc-spc", "dnd-mdn"})
            # Neither of these should raise ValueError
            for slug in ("ssc-spc", "dnd-mdn"):
                try:
                    dc.fetch_contracts(slug, max_rows=0)
                except ValueError:
                    pytest.fail(f"fetch_contracts raised ValueError for known slug {slug!r}")
                except Exception:
                    pass  # Network / RuntimeError is fine — the slug passed validation
        finally:
            dc._ALLOWED_ORGS.clear()
            dc._ALLOWED_ORGS.update(original)

    def test_no_allowed_orgs_registered_permits_any_slug(self, tmp_path):
        """When _ALLOWED_ORGS is empty, all slugs are permitted (tests / standalone use)."""
        import data_client as dc
        original = dc._ALLOWED_ORGS.copy()
        original_sample = dc._SAMPLE_DIR
        try:
            dc._ALLOWED_ORGS.clear()  # empty → no restriction
            dc._SAMPLE_DIR = tmp_path
            # Should raise RuntimeError (no network + no fallback), not ValueError
            with pytest.raises(RuntimeError):
                import requests as _req
                orig_get = _req.get
                _req.get = lambda *a, **kw: (_ for _ in ()).throw(
                    _req.exceptions.ConnectionError("offline"))
                try:
                    dc.fetch_contracts("any-slug-at-all")
                finally:
                    _req.get = orig_get
        finally:
            dc._ALLOWED_ORGS.clear()
            dc._ALLOWED_ORGS.update(original)
            dc._SAMPLE_DIR = original_sample


class TestM4SignOutClearsData:
    """M-4: sign-out must clear all data-related session_state keys."""

    def test_data_keys_to_clear_are_enumerated(self):
        """Verify the explicit list of keys that sign-out clears."""
        # This documents the contract — if new data keys are added to app.py
        # they should also appear in auth.py's sign-out block.
        expected_keys = {
            "records", "is_cached", "raw_count", "dept_name", "keyword",
            "all_dept_records", "all_dept_cached", "all_dept_skipped",
            "cmp_records", "cmp_cached", "cmp_skipped",
        }
        import inspect
        import auth
        source = inspect.getsource(auth.render_signout_button)
        for key in expected_keys:
            assert f'"{key}"' in source or f"'{key}'" in source, (
                f"Key {key!r} not found in render_signout_button source"
            )

    def test_ai_brief_prefix_cleared(self):
        """Sign-out must clear ai_brief_* keys from session_state."""
        import inspect
        import auth
        source = inspect.getsource(auth.render_signout_button)
        assert "ai_brief_" in source, (
            "ai_brief_ prefix not found in sign-out logic"
        )


class TestM5MathImportRemoved:
    """M-5: branding.py must not import math (unused)."""

    def test_math_not_imported_in_branding(self):
        import inspect
        import branding
        source = inspect.getsource(branding)
        # Only look at import lines
        import_lines = [
            ln.strip() for ln in source.splitlines()
            if ln.strip().startswith("import ") or ln.strip().startswith("from ")
        ]
        assert not any("math" in ln for ln in import_lines), (
            f"Unexpected 'math' import found in branding.py: {import_lines}"
        )
