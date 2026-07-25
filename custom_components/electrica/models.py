"""Data models for the Electrica România integration.

The API returns SAP-shaped payloads with Romanian/CamelCase keys and numbers as
strings; these models are the normalised form the coordinator and entities use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


def to_float(value: Any) -> float | None:
    """Parse a number that the API returns as a string ('15.15', '1.234,56')."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    # Romanian payloads may use ',' as the decimal separator.
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def to_date(value: Any) -> date | None:
    """Parse an ISO-ish date ('2026-07-25'); returns None when absent/invalid."""
    if not value:
        return None
    text = str(value).strip()[:10]
    for sep in ("-", "."):
        parts = text.split(sep)
        if len(parts) == 3:
            try:
                if len(parts[0]) == 4:
                    year, month, day = (int(p) for p in parts)
                else:
                    day, month, year = (int(p) for p in parts)
                return date(year, month, day)
            except ValueError:
                return None
    return None


@dataclass(slots=True)
class Reading:
    """A single meter reading (cumulative index, OBIS register 1.8.0)."""

    reading_date: date | None
    index: float | None
    register: str | None = None
    description: str | None = None
    reading_type: str | None = None

    @property
    def self_read(self) -> bool:
        """True when the customer submitted this reading themselves."""
        return "client" in (self.reading_type or "").lower()


@dataclass(slots=True)
class Invoice:
    """One invoice from the client-code invoice history."""

    invoice_id: str | None
    fiscal_number: str | None
    issue_date: date | None
    due_date: date | None
    total: float | None
    unpaid: float | None
    status: str | None
    invoice_type: str | None = None
    pdf_url: str | None = None
    nlc: str | None = None

    @property
    def is_unpaid(self) -> bool:
        return (self.unpaid or 0) > 0


@dataclass(slots=True)
class Payment:
    """One payment from the client-code payment history."""

    invoice_id: str | None
    fiscal_number: str | None
    payment_date: date | None
    amount: float | None
    source: str | None = None


@dataclass(slots=True)
class PointData:
    """Everything known about a single consumption point (NLC)."""

    nlc: str
    client_code: str
    address: str | None = None
    balance: float | None = None
    # Self-reading ("autocitire") window, when the meter may be self-read.
    pac_start: date | None = None
    pac_end: date | None = None
    pac_available: bool = False
    meter_serial: str | None = None
    contract: dict[str, Any] = field(default_factory=dict)
    readings: list[Reading] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    # Agreed monthly consumption profile: {month_number: kWh}.
    convention: dict[int, float] = field(default_factory=dict)

    @property
    def latest_reading(self) -> Reading | None:
        dated = [r for r in self.readings if r.reading_date]
        return max(dated, key=lambda r: r.reading_date) if dated else None

    @property
    def latest_invoice(self) -> Invoice | None:
        dated = [i for i in self.invoices if i.issue_date]
        return max(dated, key=lambda i: i.issue_date) if dated else None

    @property
    def unpaid_invoices(self) -> list[Invoice]:
        return [i for i in self.invoices if i.is_unpaid]

    @property
    def amount_due(self) -> float:
        """Outstanding total — the balance if given, else the unpaid invoices."""
        if self.balance is not None:
            return round(self.balance, 2)
        return round(sum(i.unpaid or 0 for i in self.unpaid_invoices), 2)

    def self_read_open(self, today: date) -> bool:
        """Whether the self-reading window is open on ``today``."""
        if not self.pac_available or not self.pac_start or not self.pac_end:
            return False
        return self.pac_start <= today <= self.pac_end
