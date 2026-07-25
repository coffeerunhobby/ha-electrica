"""Diagnostics for the Electrica România integration.

Everything that identifies the customer or the metering point is redacted: NLC,
client code, contract account, names, addresses, phone numbers and meter serials
are all personal data under GDPR.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, CONF_USERNAME
from .coordinator import ElectricaConfigEntry

TO_REDACT_ENTRY = {CONF_USERNAME, CONF_PASSWORD}

TO_REDACT_DATA = {
    "nlc",
    "client_code",
    "contract_account",
    "ContractAccount",
    "address",
    "City",
    "Street",
    "HouseNumber",
    "Building",
    "Entrance",
    "Floor",
    "RoomNumber",
    "PostCode",
    "ClientName",
    "Telephone",
    "meter_serial",
    "SerieContor",
    "fiscal_number",
    "invoice_id",
    "invoice_number",
    "pdf_url",
}


def _plain(value: Any) -> Any:
    """Convert dataclasses/dates into JSON-friendly structures."""
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ElectricaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics with personal data removed."""
    coordinator = entry.runtime_data
    points = _plain(coordinator.data or {})

    return {
        "entry": {
            "title": "<redacted>",
            "data": async_redact_data(dict(entry.data), TO_REDACT_ENTRY),
        },
        "coordinator": {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "point_count": len(coordinator.data or {}),
            # Keyed by NLC, so redact the keys as well as the values.
            "points": [
                async_redact_data(point, TO_REDACT_DATA)
                for point in points.values()
            ],
        },
    }
