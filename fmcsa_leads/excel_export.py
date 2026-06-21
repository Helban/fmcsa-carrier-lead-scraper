"""Export carrier leads to an Excel workbook with a QA summary sheet."""
from __future__ import annotations

import logging
from collections import Counter

import pandas as pd

from .leads import CarrierLead

logger = logging.getLogger(__name__)


def export_leads(leads: list[CarrierLead], output_path: str) -> None:
    """Write a Leads sheet and a QA Summary sheet to ``output_path`` (.xlsx)."""
    lead_columns = {
        "DOT#": [lead.dot_number for lead in leads],
        "Company": [lead.legal_name for lead in leads],
        "Phone": [lead.phone for lead in leads],
        "Street": [lead.street for lead in leads],
        "City": [lead.city for lead in leads],
        "State": [lead.state for lead in leads],
        "ZIP": [lead.zip_code for lead in leads],
        "Power units": [lead.power_units for lead in leads],
        "Trucks": [lead.truck_units for lead in leads],
        "Drivers": [lead.total_drivers for lead in leads],
        "Cargo": [lead.cargo for lead in leads],
    }
    if _was_enriched(leads):
        lead_columns["Website"] = [lead.website for lead in leads]
        lead_columns["Email"] = [lead.email for lead in leads]
    leads_frame = pd.DataFrame(lead_columns)
    qa_frame = _build_qa_summary(leads)
    with pd.ExcelWriter(output_path, engine="openpyxl") as workbook:
        leads_frame.to_excel(workbook, sheet_name="Leads", index=False)
        qa_frame.to_excel(workbook, sheet_name="QA Summary", index=False)
    logger.info("Wrote %d leads to %s", len(leads), output_path)


def _was_enriched(leads: list[CarrierLead]) -> bool:
    return any(lead.website or lead.email for lead in leads)


def _build_qa_summary(leads: list[CarrierLead]) -> pd.DataFrame:
    """Build a metric/value table the client can sanity-check the list against."""
    lead_count = len(leads)
    with_phone = sum(1 for lead in leads if lead.phone)
    by_state = Counter(lead.state for lead in leads)
    phone_coverage = round(100 * with_phone / lead_count, 1) if lead_count else 0.0
    top_state, top_state_count = by_state.most_common(1)[0] if by_state else ("", 0)
    qa_metrics = [
        ("Total leads", lead_count),
        ("With phone", with_phone),
        ("Phone coverage %", phone_coverage),
        ("Distinct states", len(by_state)),
        ("Largest state", f"{top_state} ({top_state_count})"),
    ]
    if _was_enriched(leads):
        with_email = sum(1 for lead in leads if lead.email)
        email_coverage = round(100 * with_email / lead_count, 1) if lead_count else 0.0
        qa_metrics.append(("With email", with_email))
        qa_metrics.append(("Email coverage %", email_coverage))
    return pd.DataFrame(qa_metrics, columns=["Metric", "Value"])
