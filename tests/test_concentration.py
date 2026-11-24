"""
tests/test_concentration.py — pytest suite for concentration.py

Covers every public function and the _parse_value helper:
  _parse_value, normalize_vendor, vendor_shares, hhi, band,
  top_vendor, noncompetitive_share, flags
"""

import math
import string

import pytest

from concentration import (
    _parse_value,
    normalize_vendor,
    vendor_shares,
    hhi,
    band,
    top_vendor,
    noncompetitive_share,
    flags,
    TopVendor,
)


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _rec(vendor: str = "ACME INC",
         value: str = "1000.00",
         procedure: str = "TC") -> dict:
    """Minimal contract record dict."""
    return {
        "vendor_name":            vendor,
        "contract_value":         value,
        "solicitation_procedure": procedure,
    }


# ===========================================================================
# _parse_value
# ===========================================================================

class TestParseValue:
    # --- happy path ----------------------------------------------------------

    def test_plain_integer_string(self):
        assert _parse_value("1000") == 1000.0

    def test_plain_float_string(self):
        assert _parse_value("1234.56") == 1234.56

    def test_dollar_prefix_stripped(self):
        assert _parse_value("$9500.00") == 9500.0

    def test_comma_separators_stripped(self):
        assert _parse_value("1,234,567.89") == 1234567.89

    def test_dollar_and_commas(self):
        assert _parse_value("$1,000,000.00") == 1_000_000.0

    def test_leading_trailing_whitespace(self):
        assert _parse_value("  500.0  ") == 500.0

    # --- zero / negative -----------------------------------------------------

    def test_zero_string(self):
        assert _parse_value("0") == 0.0

    def test_zero_float_string(self):
        assert _parse_value("0.00") == 0.0

    def test_negative_becomes_zero(self):
        assert _parse_value("-500.00") == 0.0

    def test_negative_with_dollar(self):
        assert _parse_value("$-100") == 0.0

    # --- blank / None / non-string ------------------------------------------

    def test_empty_string(self):
        assert _parse_value("") == 0.0

    def test_whitespace_only(self):
        assert _parse_value("   ") == 0.0

    def test_none_input(self):
        assert _parse_value(None) == 0.0

    def test_integer_input(self):
        assert _parse_value(42) == 0.0

    def test_float_input(self):
        assert _parse_value(3.14) == 0.0

    def test_list_input(self):
        assert _parse_value([]) == 0.0

    # --- unparsable strings --------------------------------------------------

    def test_alphabetic_string(self):
        assert _parse_value("N/A") == 0.0

    def test_mixed_garbage(self):
        assert _parse_value("abc123xyz") == 0.0

    def test_only_dollar_sign(self):
        assert _parse_value("$") == 0.0

    def test_only_commas(self):
        assert _parse_value(",,,") == 0.0


# ===========================================================================
# normalize_vendor
# ===========================================================================

class TestNormalizeVendor:
    # --- happy path ----------------------------------------------------------

    def test_uppercases(self):
        assert normalize_vendor("acme inc") == "ACME INC"

    def test_strips_whitespace(self):
        assert normalize_vendor("  Acme Corp  ") == "ACME CORP"

    def test_removes_trailing_period(self):
        assert normalize_vendor("Acme Corp.") == "ACME CORP"

    def test_removes_trailing_comma(self):
        assert normalize_vendor("Acme Corp,") == "ACME CORP"

    def test_removes_trailing_multiple_punctuation(self):
        # rstrip removes all trailing punctuation chars one by one
        assert normalize_vendor("ACME!!") == "ACME"

    def test_already_normalised(self):
        assert normalize_vendor("ACME INC") == "ACME INC"

    def test_internal_punctuation_preserved(self):
        # Punctuation in the middle of a name is kept
        assert normalize_vendor("I.B.M. CANADA") == "I.B.M. CANADA"

    def test_mixed_case_with_numbers(self):
        assert normalize_vendor("  Bell Canada 2024.  ") == "BELL CANADA 2024"

    # --- None / non-string ---------------------------------------------------

    def test_none_returns_empty(self):
        assert normalize_vendor(None) == ""

    def test_integer_returns_empty(self):
        assert normalize_vendor(42) == ""

    def test_list_returns_empty(self):
        assert normalize_vendor(["acme"]) == ""

    def test_empty_string_returns_empty(self):
        assert normalize_vendor("") == ""

    def test_whitespace_only_returns_empty(self):
        # strip() makes it empty; upper() of "" is ""; rstrip of "" is ""
        assert normalize_vendor("   ") == ""

    def test_punctuation_only_returns_empty(self):
        # After upper() and rstrip(punctuation), nothing remains
        assert normalize_vendor("...") == ""


# ===========================================================================
# vendor_shares
# ===========================================================================

class TestVendorShares:
    # --- happy path ----------------------------------------------------------

    def test_single_vendor_gets_100_pct(self):
        records = [_rec("ACME", "500"), _rec("ACME", "500")]
        shares = vendor_shares(records)
        assert shares == {"ACME": 100.0}

    def test_two_equal_vendors(self):
        records = [_rec("ACME", "500"), _rec("BETA", "500")]
        shares = vendor_shares(records)
        assert abs(shares["ACME"] - 50.0) < 1e-9
        assert abs(shares["BETA"] - 50.0) < 1e-9

    def test_proportional_shares(self):
        records = [_rec("BIG", "7500"), _rec("SML", "2500")]
        shares = vendor_shares(records)
        assert abs(shares["BIG"] - 75.0) < 1e-9
        assert abs(shares["SML"] - 25.0) < 1e-9

    def test_shares_sum_to_100(self):
        records = [
            _rec("A", "1000"),
            _rec("B", "2000"),
            _rec("C", "3000"),
            _rec("D", "4000"),
        ]
        total = sum(vendor_shares(records).values())
        assert abs(total - 100.0) < 1e-9

    def test_vendor_name_normalised(self):
        # "acme inc." and "ACME INC" should collapse to the same key
        records = [_rec("acme inc.", "500"), _rec("ACME INC", "500")]
        shares = vendor_shares(records)
        assert len(shares) == 1
        assert "ACME INC" in shares

    # --- zero / blank values -------------------------------------------------

    def test_all_zero_values_returns_empty(self):
        records = [_rec("ACME", "0"), _rec("BETA", "0.00")]
        assert vendor_shares(records) == {}

    def test_blank_vendor_excluded(self):
        records = [
            {"vendor_name": "", "contract_value": "1000"},
            _rec("ACME", "2000"),
        ]
        shares = vendor_shares(records)
        assert "" not in shares
        assert "ACME" in shares

    def test_none_vendor_excluded(self):
        records = [
            {"vendor_name": None, "contract_value": "1000"},
            _rec("ACME", "500"),
        ]
        shares = vendor_shares(records)
        assert "" not in shares
        assert "ACME" in shares

    def test_missing_vendor_key_excluded(self):
        records = [
            {"contract_value": "1000"},   # no vendor_name key
            _rec("ACME", "500"),
        ]
        shares = vendor_shares(records)
        assert "ACME" in shares

    def test_zero_value_record_included_vendor_at_zero_share(self):
        # Zero-value record contributes 0 to totals but vendor entry still
        # created with 0 — grand_total driven by other records
        records = [_rec("ACME", "0"), _rec("BETA", "1000")]
        shares = vendor_shares(records)
        # ACME has 0 value: share is 0 but should still be in dict (0 / 1000)
        assert "ACME" in shares
        assert shares["ACME"] == 0.0
        assert shares["BETA"] == 100.0

    def test_empty_records_list(self):
        assert vendor_shares([]) == {}

    # --- None / missing contract_value ---------------------------------------

    def test_none_contract_value_treated_as_zero(self):
        records = [
            {"vendor_name": "ACME", "contract_value": None},
            _rec("BETA", "1000"),
        ]
        shares = vendor_shares(records)
        assert "BETA" in shares
        assert abs(shares["BETA"] - 100.0) < 1e-9


# ===========================================================================
# hhi
# ===========================================================================

class TestHhi:
    def test_monopoly_gives_10000(self):
        assert hhi({"ACME": 100.0}) == pytest.approx(10_000.0)

    def test_two_equal_vendors(self):
        # (50^2 + 50^2) = 5000
        assert hhi({"A": 50.0, "B": 50.0}) == pytest.approx(5000.0)

    def test_perfectly_distributed_10_vendors(self):
        shares = {str(i): 10.0 for i in range(10)}
        assert hhi(shares) == pytest.approx(1000.0)

    def test_empty_shares_gives_zero(self):
        assert hhi({}) == 0.0

    def test_result_range_0_to_10000(self):
        shares = {"A": 60.0, "B": 25.0, "C": 15.0}
        result = hhi(shares)
        assert 0.0 <= result <= 10_000.0

    def test_known_value(self):
        # (60^2 + 40^2) = 3600 + 1600 = 5200
        assert hhi({"X": 60.0, "Y": 40.0}) == pytest.approx(5200.0)


# ===========================================================================
# band
# ===========================================================================

class TestBand:
    # --- exact boundaries ----------------------------------------------------

    def test_zero_is_low(self):
        assert band(0.0) == "Low"

    def test_just_below_1000_is_low(self):
        assert band(999.99) == "Low"

    def test_exactly_1000_is_moderate(self):
        assert band(1000.0) == "Moderate"

    def test_mid_moderate(self):
        assert band(1400.0) == "Moderate"

    def test_exactly_1800_is_moderate(self):
        assert band(1800.0) == "Moderate"

    def test_just_above_1800_is_high(self):
        assert band(1800.01) == "High"

    def test_monopoly_hhi_is_high(self):
        assert band(10_000.0) == "High"

    # --- return type ---------------------------------------------------------

    def test_returns_string(self):
        assert isinstance(band(500.0), str)


# ===========================================================================
# top_vendor
# ===========================================================================

class TestTopVendor:
    def test_single_vendor(self):
        tv = top_vendor({"ACME": 100.0})
        assert tv.name == "ACME"
        assert tv.share == pytest.approx(100.0)

    def test_picks_highest_share(self):
        shares = {"SMALL": 10.0, "BIG": 70.0, "MED": 20.0}
        tv = top_vendor(shares)
        assert tv.name == "BIG"
        assert tv.share == pytest.approx(70.0)

    def test_two_equal_vendors_returns_one(self):
        # max() picks the first found in dict iteration; just ensure it returns
        # a TopVendor with the correct share
        shares = {"A": 50.0, "B": 50.0}
        tv = top_vendor(shares)
        assert tv.share == pytest.approx(50.0)
        assert tv.name in ("A", "B")

    def test_empty_shares_returns_sentinel(self):
        tv = top_vendor({})
        assert tv == TopVendor("", 0.0)
        assert tv.name == ""
        assert tv.share == 0.0

    def test_returns_namedtuple(self):
        tv = top_vendor({"ACME": 55.0})
        assert isinstance(tv, TopVendor)

    def test_name_and_share_accessible_by_attribute(self):
        tv = top_vendor({"CORP": 33.3})
        assert tv.name == "CORP"
        assert tv.share == pytest.approx(33.3)


# ===========================================================================
# noncompetitive_share
# ===========================================================================

class TestNoncompetitiveShare:
    # --- happy path ----------------------------------------------------------

    def test_all_tn_gives_100(self):
        records = [_rec("A", "1000", "TN"), _rec("B", "500", "TN")]
        assert noncompetitive_share(records) == pytest.approx(100.0)

    def test_no_tn_gives_zero(self):
        records = [_rec("A", "1000", "TC"), _rec("B", "500", "OB")]
        assert noncompetitive_share(records) == pytest.approx(0.0)

    def test_half_tn(self):
        records = [_rec("A", "1000", "TN"), _rec("B", "1000", "TC")]
        assert noncompetitive_share(records) == pytest.approx(50.0)

    def test_proportional(self):
        records = [_rec("A", "3000", "TN"), _rec("B", "7000", "TC")]
        assert noncompetitive_share(records) == pytest.approx(30.0)

    # --- case insensitivity --------------------------------------------------

    def test_tn_lowercase(self):
        records = [{"vendor_name": "A", "contract_value": "500",
                    "solicitation_procedure": "tn"}]
        assert noncompetitive_share(records) == pytest.approx(100.0)

    def test_tn_with_whitespace(self):
        records = [{"vendor_name": "A", "contract_value": "500",
                    "solicitation_procedure": "  TN  "}]
        assert noncompetitive_share(records) == pytest.approx(100.0)

    # --- None / blank / missing fields ---------------------------------------

    def test_none_procedure_not_counted_as_tn(self):
        records = [{"vendor_name": "A", "contract_value": "1000",
                    "solicitation_procedure": None}]
        assert noncompetitive_share(records) == pytest.approx(0.0)

    def test_missing_procedure_key_not_counted(self):
        records = [{"vendor_name": "A", "contract_value": "1000"}]
        assert noncompetitive_share(records) == pytest.approx(0.0)

    def test_blank_procedure_not_counted_as_tn(self):
        records = [{"vendor_name": "A", "contract_value": "1000",
                    "solicitation_procedure": ""}]
        assert noncompetitive_share(records) == pytest.approx(0.0)

    def test_all_zero_values_returns_zero(self):
        records = [_rec("A", "0", "TN"), _rec("B", "0", "TN")]
        assert noncompetitive_share(records) == 0.0

    def test_empty_list_returns_zero(self):
        assert noncompetitive_share([]) == 0.0

    def test_none_contract_value_treated_as_zero(self):
        records = [
            {"vendor_name": "A", "contract_value": None, "solicitation_procedure": "TN"},
            _rec("B", "1000", "TC"),
        ]
        # TN value is 0; total is 1000 → 0 / 1000 = 0 %
        assert noncompetitive_share(records) == pytest.approx(0.0)


# ===========================================================================
# flags
# ===========================================================================

class TestFlags:
    # --- no flags ------------------------------------------------------------

    def test_no_flags_when_healthy(self):
        # top vendor < 40 %, all competitive
        shares  = {"A": 30.0, "B": 40.0, "C": 30.0}  # top = 40 % (not > 40)
        records = [_rec("A", "3000", "TC"), _rec("B", "4000", "TC")]
        result  = flags(shares, records)
        assert result == []

    # --- single-vendor dependency only ---------------------------------------

    def test_single_vendor_flag_above_40(self):
        shares  = {"BIG": 41.0, "SML": 59.0}
        records = [_rec("BIG", "4100", "TC"), _rec("SML", "5900", "TC")]
        result  = flags(shares, records)
        assert "single-vendor dependency" in result
        assert "low competition" not in result

    def test_single_vendor_flag_exactly_40_not_triggered(self):
        # top vendor is exactly 40.0 — the rule is > 40, so no flag
        shares  = {"BIG": 40.0, "SML": 35.0, "TINY": 25.0}
        records = [
            _rec("BIG",  "4000", "TC"),
            _rec("SML",  "3500", "TC"),
            _rec("TINY", "2500", "TC"),
        ]
        result  = flags(shares, records)
        assert "single-vendor dependency" not in result

    def test_single_vendor_flag_at_100_pct(self):
        shares  = {"MONO": 100.0}
        records = [_rec("MONO", "5000", "TC")]
        result  = flags(shares, records)
        assert "single-vendor dependency" in result

    # --- low competition only ------------------------------------------------

    def test_low_competition_flag_above_30(self):
        # 31 % TN, top vendor well below 40 %
        shares  = {"A": 25.0, "B": 25.0, "C": 25.0, "D": 25.0}
        records = [
            _rec("A", "3100", "TN"),
            _rec("B", "2300", "TC"),
            _rec("C", "2300", "TC"),
            _rec("D", "2300", "TC"),
        ]
        result  = flags(shares, records)
        assert "low competition" in result
        assert "single-vendor dependency" not in result

    def test_low_competition_exactly_30_not_triggered(self):
        # 30 % TN is NOT > 30 %
        records = [_rec("A", "3000", "TN"), _rec("B", "7000", "TC")]
        shares  = {"A": 30.0, "B": 70.0}
        result  = flags(shares, records)
        assert "low competition" not in result

    # --- both flags ----------------------------------------------------------

    def test_both_flags_raised(self):
        shares  = {"BIG": 95.0, "SML": 5.0}
        records = [_rec("BIG", "9500", "TN"), _rec("SML", "500", "TN")]
        result  = flags(shares, records)
        assert "single-vendor dependency" in result
        assert "low competition" in result
        assert len(result) == 2

    # --- edge cases ----------------------------------------------------------

    def test_empty_shares_no_flags(self):
        result = flags({}, [])
        assert result == []

    def test_flags_returns_list(self):
        assert isinstance(flags({}, []), list)
