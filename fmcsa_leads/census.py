"""Fetch motor carrier records from the public FMCSA census.

Source: Socrata SODA API, dataset ``az4n-8mr2`` on data.transportation.gov
(FMCSA Motor Carrier Census). Public US government data, no login required.
An optional Socrata app token only raises the rate limit.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence

import httpx

logger = logging.getLogger(__name__)

CENSUS_RESOURCE_URL = "https://data.transportation.gov/resource/az4n-8mr2.json"

# Socrata serves at most this many rows per response; we walk $offset until a
# page comes back shorter than the page size. This is the same row-cap gotcha
# that silently truncates naive Socrata pulls to 1000 rows.
SOCRATA_PAGE_SIZE = 50_000
REQUEST_TIMEOUT_SECONDS = 60.0

# Census columns we keep. dot_number is the dedup key; the rest feed the lead row.
CENSUS_COLUMNS = (
    "dot_number",
    "legal_name",
    "phone",
    "phy_street",
    "phy_city",
    "phy_state",
    "phy_zip",
    "power_units",
    "truck_units",
    "total_drivers",
    "carrier_operation",
    "status_code",
    "crgo_cargoothr_desc",
)

# status_code 'A' marks an active carrier in the census.
_ACTIVE_STATUS_CODE = "A"

# Physical-location codes that actually occur in the census: US states, DC, US
# territories, and Canadian provinces (FMCSA registers cross-border carriers).
# Validating against this set turns a typo into a clear error instead of a
# silent zero-result query.
VALID_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
        "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
        "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
        "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
        "WI", "WY",
        "DC", "PR", "GU", "VI", "AS", "MP",
        "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
    }
)


def build_where_clause(states: Sequence[str] | None, active_only: bool) -> str:
    """Build the SoQL ``$where`` clause for server-side filtering.

    Fleet-size filtering is deliberately left to the Python side because the
    census stores unit counts as text, which makes numeric SoQL comparisons
    unreliable. Only validated 2-letter state codes and a fixed status literal
    are interpolated here, so there is no injection surface.
    """
    conditions: list[str] = []
    if states:
        quoted_states = ",".join(_quote_validated_state(state) for state in states)
        conditions.append(f"phy_state IN ({quoted_states})")
    if active_only:
        conditions.append(f"status_code='{_ACTIVE_STATUS_CODE}'")
    return " AND ".join(conditions) if conditions else "1=1"


def _quote_validated_state(state: str) -> str:
    normalized_state = state.upper()
    if normalized_state not in VALID_STATE_CODES:
        raise ValueError(f"unrecognized state code: {state!r}")
    return f"'{normalized_state}'"


def fetch_carrier_records(
    where_clause: str,
    app_token: str | None = None,
    page_size: int = SOCRATA_PAGE_SIZE,
) -> Iterator[dict[str, str]]:
    """Yield census records matching ``where_clause``, paging past the row cap."""
    request_headers = {"X-App-Token": app_token} if app_token else {}
    offset = 0
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, headers=request_headers) as client:
        while True:
            query_params = {
                "$select": ",".join(CENSUS_COLUMNS),
                "$where": where_clause,
                "$order": "dot_number",  # stable ordering so paging never repeats/skips
                "$limit": page_size,
                "$offset": offset,
            }
            census_response = client.get(CENSUS_RESOURCE_URL, params=query_params)
            census_response.raise_for_status()
            census_page: list[dict[str, str]] = census_response.json()
            if not census_page:
                break
            logger.info("Fetched %d carriers at offset %d", len(census_page), offset)
            yield from census_page
            if len(census_page) < page_size:
                break
            offset += page_size
