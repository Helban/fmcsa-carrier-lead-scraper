"""Turn raw census records into clean, deduplicated carrier leads."""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_NON_DIGITS = re.compile(r"\D")


@dataclass(frozen=True)
class CarrierLead:
    """One trucking carrier as a sales lead."""

    dot_number: str
    legal_name: str
    phone: str
    street: str
    city: str
    state: str
    zip_code: str
    power_units: int
    truck_units: int
    total_drivers: int
    cargo: str
    website: str = ""  # filled by optional email enrichment, empty otherwise
    email: str = ""


def normalize_phone(raw_phone: str | None) -> str:
    """Return a 10-digit US phone as ``(XXX) XXX-XXXX``, or '' if unusable."""
    if not raw_phone:
        return ""
    digits = _NON_DIGITS.sub("", raw_phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]  # drop the US country code
    if len(digits) != 10:
        return ""
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def _to_int(raw_count: str | None) -> int:
    """Parse a census count that may arrive as '' or a float-like string."""
    if raw_count in (None, ""):
        return 0
    try:
        return int(float(raw_count))
    except (TypeError, ValueError):
        return 0


def build_leads(
    carrier_records: Iterable[dict[str, str]],
    min_power_units: int | None = None,
) -> list[CarrierLead]:
    """Deduplicate on DOT number, normalize fields, drop carriers below fleet size."""
    leads_by_dot: dict[str, CarrierLead] = {}
    below_fleet_threshold = 0
    for carrier in carrier_records:
        dot_number = (carrier.get("dot_number") or "").strip()
        if not dot_number or dot_number in leads_by_dot:
            continue
        power_units = _to_int(carrier.get("power_units"))
        if min_power_units is not None and power_units < min_power_units:
            below_fleet_threshold += 1
            continue
        leads_by_dot[dot_number] = CarrierLead(
            dot_number=dot_number,
            legal_name=(carrier.get("legal_name") or "").strip(),
            phone=normalize_phone(carrier.get("phone")),
            street=(carrier.get("phy_street") or "").strip(),
            city=(carrier.get("phy_city") or "").strip(),
            state=(carrier.get("phy_state") or "").strip(),
            zip_code=(carrier.get("phy_zip") or "").strip(),
            power_units=power_units,
            truck_units=_to_int(carrier.get("truck_units")),
            total_drivers=_to_int(carrier.get("total_drivers")),
            cargo=(carrier.get("crgo_cargoothr_desc") or "").strip(),
        )
    logger.info(
        "Built %d unique leads (%d dropped below fleet threshold)",
        len(leads_by_dot),
        below_fleet_threshold,
    )
    return list(leads_by_dot.values())
