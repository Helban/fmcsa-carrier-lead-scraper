"""Command-line entry point: build a filtered FMCSA lead list as Excel."""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .census import VALID_STATE_CODES, build_where_clause, fetch_carrier_records
from .enrichment import enrich_leads
from .excel_export import export_leads
from .leads import build_leads

logger = logging.getLogger(__name__)

_EXIT_OK = 0
_EXIT_NO_MATCHES = 1
_EXIT_BAD_ARGS = 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a filtered FMCSA carrier lead list as an Excel workbook."
    )
    parser.add_argument(
        "--state", help="Comma-separated 2-letter state codes, e.g. TX or TX,CA,FL"
    )
    parser.add_argument(
        "--min-power-units",
        type=int,
        help="Keep only carriers with at least this many power units",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include carriers not marked active in the census",
    )
    parser.add_argument(
        "--all-states",
        action="store_true",
        help="Pull the entire national census when no --state is given (millions of rows)",
    )
    parser.add_argument(
        "--output",
        default="fmcsa_leads.xlsx",
        help="Output .xlsx path (default: fmcsa_leads.xlsx)",
    )
    parser.add_argument(
        "--enrich-email",
        action="store_true",
        help="Find each carrier's website and scrape a contact email (slow, best-effort)",
    )
    parser.add_argument(
        "--enrich-limit",
        type=int,
        default=25,
        help="Cap how many carriers to enrich when --enrich-email is set (default: 25)",
    )
    parser.add_argument(
        "--enrich-delay",
        type=float,
        default=1.0,
        help="Seconds between enrichment requests (default: 1.0)",
    )
    return parser.parse_args(argv)


def _parse_state_codes(raw_states: str | None) -> list[str] | None:
    """Split a comma-separated ``--state`` value into recognized 2-letter codes."""
    if not raw_states:
        return None
    state_codes = [code.strip().upper() for code in raw_states.split(",") if code.strip()]
    unrecognized_codes = [code for code in state_codes if code not in VALID_STATE_CODES]
    if unrecognized_codes:
        raise ValueError(f"unrecognized state code(s): {', '.join(unrecognized_codes)}")
    return state_codes


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    options = _parse_args(argv)
    try:
        state_codes = _parse_state_codes(options.state)
    except ValueError as bad_state_codes:
        logger.error("%s", bad_state_codes)
        return _EXIT_BAD_ARGS

    if state_codes is None and not options.all_states:
        logger.error(
            "No --state given. Pass codes like --state TX,CA or use --all-states "
            "to pull the entire active census (millions of rows)."
        )
        return _EXIT_BAD_ARGS
    if state_codes is None:
        logger.warning("Pulling the entire active census; this is slow and memory-heavy")

    socrata_token = os.environ.get("SOCRATA_APP_TOKEN")
    where_clause = build_where_clause(
        states=state_codes, active_only=not options.include_inactive
    )
    logger.info("Querying FMCSA census where: %s", where_clause)

    carrier_records = fetch_carrier_records(where_clause, app_token=socrata_token)
    leads = build_leads(carrier_records, min_power_units=options.min_power_units)
    if not leads:
        logger.warning("No carriers matched the filters")
        return _EXIT_NO_MATCHES

    if options.enrich_email:
        leads = enrich_leads(
            leads,
            limit=options.enrich_limit,
            request_delay_seconds=options.enrich_delay,
        )

    export_leads(leads, options.output)
    return _EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
