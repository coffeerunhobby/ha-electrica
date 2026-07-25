"""Tests for the native-signalling entities (problem class, relative due date).

An integration cannot set frontend colours, so urgency is signalled through
device classes and icons instead. All data here is SYNTHETIC.
"""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.binary_sensor import (  # noqa: E402
    BinarySensorDeviceClass,
)

from custom_components.electrica.binary_sensor import BINARY_SENSORS  # noqa: E402
from custom_components.electrica.models import Invoice, PointData  # noqa: E402
from custom_components.electrica.sensor import (  # noqa: E402
    SENSORS,
    _due_datetime,
    _due_icon,
)

NLC = "1234567890"


def _point(*, unpaid: float = 0.0, due: date | None = date(2026, 7, 29)) -> PointData:
    point = PointData(nlc=NLC, client_code=NLC)
    point.invoices = [
        Invoice(
            invoice_id="900000001",
            fiscal_number="FF-0001",
            issue_date=date(2026, 7, 14),
            due_date=due,
            total=15.15,
            unpaid=unpaid,
            status="neachitat" if unpaid else "achitat",
        )
    ]
    return point


def _binary(key: str):
    return next(d for d in BINARY_SENSORS if d.key == key)


# ── Overdue signalling ──────────────────────────────────────────────────────
def test_overdue_uses_the_problem_device_class():
    # device_class "problem" is what makes Home Assistant render it red.
    assert _binary("overdue").device_class is BinarySensorDeviceClass.PROBLEM


def test_overdue_reflects_unpaid_invoices():
    assert _binary("overdue").value_fn(_point(unpaid=15.15)) is True
    assert _binary("overdue").value_fn(_point(unpaid=0.0)) is False


def test_overdue_attributes_carry_the_amount():
    attrs = _binary("overdue").attrs_fn(_point(unpaid=15.15))
    assert attrs["amount_due"] == 15.15
    assert attrs["unpaid_invoices"] == 1
    assert attrs["due_date"] == "2026-07-29"


# ── Self-reading window ─────────────────────────────────────────────────────
def test_self_reading_window_is_not_a_problem_class():
    # An open window is useful, not a fault — it must not render as an alert.
    assert _binary("self_reading_open").device_class is None


# ── Relative due date ───────────────────────────────────────────────────────
def test_due_date_timestamp_is_timezone_aware():
    value = _due_datetime(_point())
    assert value is not None
    assert value.tzinfo is not None  # HA requires tz-aware timestamps
    assert (value.year, value.month, value.day) == (2026, 7, 29)


def test_due_date_timestamp_handles_missing_dates():
    assert _due_datetime(_point(due=None)) is None
    assert _due_datetime(PointData(nlc=NLC, client_code=NLC)) is None


def test_due_icon_flags_an_unpaid_invoice():
    assert _due_icon(_point(unpaid=15.15)) == "mdi:calendar-alert"
    assert _due_icon(_point(unpaid=0.0)) == "mdi:calendar-clock"


def test_plain_due_date_sensor_is_unchanged_for_backwards_compatibility():
    # Templates relying on the ISO text must keep working; the timestamp form
    # is a separate entity.
    plain = next(d for d in SENSORS if d.key == "due_date")
    assert plain.device_class is None
    assert plain.value_fn(_point()) == "2026-07-29"
