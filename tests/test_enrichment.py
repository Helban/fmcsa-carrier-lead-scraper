"""Tests for the website-matching guard in email enrichment (no network)."""
from __future__ import annotations

from fmcsa_leads.enrichment import _domain_matches_company


def test_domain_match_accepts_real_company_domain() -> None:
    assert _domain_matches_company("https://www.dixonbrosinc.com/", "DIXON BROS INC")


def test_domain_match_rejects_directory_host() -> None:
    assert not _domain_matches_company(
        "https://otrucking.com/carrier/simon-contractors/", "SIMON CONTRACTORS"
    )


def test_domain_match_ignores_generic_words() -> None:
    # "transport" alone is too generic to confirm the domain is the carrier's own
    assert not _domain_matches_company(
        "https://quicktransportsolutions.com/x", "ADMIRAL TRANSPORT CORPORATION"
    )
