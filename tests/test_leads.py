"""Tests for lead normalization and deduplication (no network needed)."""
from __future__ import annotations

import pytest

from fmcsa_leads.census import build_where_clause
from fmcsa_leads.cli import _parse_state_codes
from fmcsa_leads.leads import build_leads, normalize_phone


def test_normalize_phone_formats_ten_digits() -> None:
    assert normalize_phone("5125551234") == "(512) 555-1234"


def test_normalize_phone_strips_country_code_and_punctuation() -> None:
    assert normalize_phone("+1 (512) 555-1234") == "(512) 555-1234"


def test_normalize_phone_rejects_short_numbers() -> None:
    assert normalize_phone("555-1234") == ""
    assert normalize_phone(None) == ""


def test_build_leads_dedupes_on_dot_number() -> None:
    duplicate_records = [
        {"dot_number": "111", "legal_name": "Acme Freight", "power_units": "5"},
        {"dot_number": "111", "legal_name": "Acme Freight (dup)", "power_units": "5"},
    ]
    leads = build_leads(duplicate_records)
    assert len(leads) == 1
    assert leads[0].legal_name == "Acme Freight"


def test_build_leads_filters_below_fleet_threshold() -> None:
    carrier_records = [
        {"dot_number": "1", "power_units": "2"},
        {"dot_number": "2", "power_units": "10"},
    ]
    leads = build_leads(carrier_records, min_power_units=5)
    assert [lead.dot_number for lead in leads] == ["2"]


def test_build_where_clause_single_state() -> None:
    assert build_where_clause(["tx"], active_only=True) == "phy_state IN ('TX') AND status_code='A'"


def test_build_where_clause_multiple_states() -> None:
    assert build_where_clause(["TX", "ca"], active_only=False) == "phy_state IN ('TX','CA')"


def test_build_where_clause_accepts_canadian_province() -> None:
    assert build_where_clause(["on"], active_only=False) == "phy_state IN ('ON')"


def test_build_where_clause_rejects_bad_state() -> None:
    with pytest.raises(ValueError):
        build_where_clause(["Texas"], active_only=True)


def test_parse_state_codes_normalizes_and_trims() -> None:
    assert _parse_state_codes("tx, ca ,fl") == ["TX", "CA", "FL"]


def test_parse_state_codes_rejects_typo() -> None:
    with pytest.raises(ValueError):
        _parse_state_codes("TX,CZ,FL")
