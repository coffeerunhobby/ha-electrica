"""Sensor platform for the Electrica România integration.

Layout mirrors the account → devices model: the config entry is the Electrica
account (titled by e-mail) and each consumption point (NLC) is its own device,
named by its address. Entity ids use the NLC — never the address text.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, CURRENCY_RON, DOMAIN, MANUFACTURER, MODEL
from .coordinator import ElectricaConfigEntry, ElectricaCoordinator
from .models import PointData

_LOGGER = logging.getLogger(__name__)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


@dataclass(frozen=True, kw_only=True)
class ElectricaSensorDescription(SensorEntityDescription):
    """Describes a sensor on a consumption-point device."""

    value_fn: Callable[[PointData], Any]
    attrs_fn: Callable[[PointData], dict[str, Any]] | None = None
    # Optional per-state icon, e.g. to flag an overdue due date.
    icon_fn: Callable[[PointData], str | None] | None = None


def _due_datetime(point: PointData) -> datetime | None:
    """The latest invoice's due date as a timezone-aware datetime.

    Reported as a ``timestamp`` sensor so Home Assistant renders it as
    "in 3 days" / "5 days ago" — an overdue invoice then reads at a glance
    without any frontend styling, which an integration cannot control.
    """
    invoice = point.latest_invoice
    if invoice is None or invoice.due_date is None:
        return None
    return datetime.combine(invoice.due_date, time.min).replace(
        tzinfo=dt_util.DEFAULT_TIME_ZONE
    )


def _due_icon(point: PointData) -> str:
    return "mdi:calendar-alert" if point.unpaid_invoices else "mdi:calendar-clock"


def _invoice_attrs(point: PointData) -> dict[str, Any]:
    latest = point.latest_invoice
    return {
        "address": point.address,
        "client_code": point.client_code,
        "invoice_number": latest.fiscal_number if latest else None,
        "issue_date": _iso(latest.issue_date) if latest else None,
        "due_date": _iso(latest.due_date) if latest else None,
        "status": latest.status if latest else None,
        "pdf_url": latest.pdf_url if latest else None,
        "unpaid_invoices": len(point.unpaid_invoices),
        "history": [
            {
                "invoice_number": inv.fiscal_number,
                "issue_date": _iso(inv.issue_date),
                "due_date": _iso(inv.due_date),
                "total": inv.total,
                "unpaid": inv.unpaid,
                "status": inv.status,
            }
            for inv in point.invoices[:12]
        ],
    }


def _reading_attrs(point: PointData) -> dict[str, Any]:
    latest = point.latest_reading
    return {
        "reading_date": _iso(latest.reading_date) if latest else None,
        "reading_type": latest.reading_type if latest else None,
        "self_read": latest.self_read if latest else None,
        "register": latest.register if latest else None,
        # Raw readings are kept visible: the Energy Dashboard series is
        # interpolated between these points, so this is the metered truth.
        "readings": [
            {
                "date": _iso(r.reading_date),
                "index": r.index,
                "self_read": r.self_read,
            }
            for r in point.readings
        ],
    }


def _self_read_attrs(point: PointData) -> dict[str, Any]:
    return {
        "window_start": _iso(point.pac_start),
        "window_end": _iso(point.pac_end),
        "self_reading_available": point.pac_available,
        "meter_serial": point.meter_serial,
    }


SENSORS: tuple[ElectricaSensorDescription, ...] = (
    ElectricaSensorDescription(
        key="amount_due",
        translation_key="amount_due",
        icon="mdi:cash-multiple",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_RON,
        value_fn=lambda p: p.amount_due,
        attrs_fn=_invoice_attrs,
    ),
    ElectricaSensorDescription(
        key="last_invoice",
        translation_key="last_invoice",
        icon="mdi:file-document-outline",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_RON,
        value_fn=lambda p: (p.latest_invoice.total if p.latest_invoice else None),
    ),
    ElectricaSensorDescription(
        key="due_date",
        translation_key="due_date",
        icon="mdi:calendar-clock",
        # Plain ISO text, kept stable for templates and automations.
        value_fn=lambda p: _iso(p.latest_invoice.due_date) if p.latest_invoice else None,
        icon_fn=_due_icon,
    ),
    ElectricaSensorDescription(
        key="due_date_timestamp",
        translation_key="due_date_timestamp",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_due_datetime,
        icon_fn=_due_icon,
    ),
    ElectricaSensorDescription(
        key="overdue",
        translation_key="overdue",
        icon="mdi:alert-circle-outline",
        value_fn=lambda p: "yes" if p.unpaid_invoices else "no",
    ),
    ElectricaSensorDescription(
        key="meter_index",
        translation_key="meter_index",
        icon="mdi:counter",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda p: (p.latest_reading.index if p.latest_reading else None),
        attrs_fn=_reading_attrs,
    ),
    ElectricaSensorDescription(
        key="self_reading",
        translation_key="self_reading",
        icon="mdi:calendar-check",
        value_fn=lambda p: "open" if p.self_read_open(dt_util.now().date()) else "closed",
        attrs_fn=_self_read_attrs,
    ),
    ElectricaSensorDescription(
        key="annual_convention",
        translation_key="annual_convention",
        icon="mdi:chart-bell-curve",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda p: round(sum(p.convention.values()), 2) if p.convention else None,
        attrs_fn=lambda p: {"monthly_kwh": {str(k): v for k, v in sorted(p.convention.items())}},
    ),
    ElectricaSensorDescription(
        key="last_payment",
        translation_key="last_payment",
        icon="mdi:cash-check",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_RON,
        value_fn=lambda p: (p.payments[0].amount if p.payments else None),
        attrs_fn=lambda p: {
            "payment_date": _iso(p.payments[0].payment_date) if p.payments else None,
            "source": p.payments[0].source if p.payments else None,
            "history": [
                {
                    "date": _iso(pay.payment_date),
                    "amount": pay.amount,
                    "source": pay.source,
                }
                for pay in p.payments[:12]
            ],
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ElectricaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one device per consumption point, each with its sensors."""
    coordinator = config_entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        entities: list[SensorEntity] = []
        for nlc in (coordinator.data or {}):
            if nlc in known:
                continue
            known.add(nlc)
            entities.extend(
                ElectricaSensor(coordinator, config_entry, nlc, description)
                for description in SENSORS
            )
        if entities:
            async_add_entities(entities)

    _add_new()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new))


class ElectricaSensor(CoordinatorEntity[ElectricaCoordinator], SensorEntity):
    """A sensor on a consumption-point device."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    entity_description: ElectricaSensorDescription

    def __init__(
        self,
        coordinator: ElectricaCoordinator,
        config_entry: ElectricaConfigEntry,
        nlc: str,
        description: ElectricaSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._nlc = nlc
        self._device_id = f"{config_entry.entry_id}_{nlc}"
        self._attr_unique_id = f"{self._device_id}_{description.key}"
        # e.g. sensor.electrica_1234567890_amount_due — the NLC is Electrica's
        # own stable id; the address never appears in the entity_id.
        self.entity_id = f"sensor.{DOMAIN}_{nlc}_{description.key}"

    @property
    def _point(self) -> PointData | None:
        return (self.coordinator.data or {}).get(self._nlc)

    @property
    def available(self) -> bool:
        return super().available and self._point is not None

    @property
    def device_info(self) -> DeviceInfo:
        point = self._point
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=(point.address if point and point.address else f"NLC {self._nlc}"),
            manufacturer=MANUFACTURER,
            model=MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Any:
        point = self._point
        return self.entity_description.value_fn(point) if point else None

    @property
    def icon(self) -> str | None:
        """Allow the icon to reflect state (e.g. an overdue due date)."""
        point = self._point
        icon_fn = self.entity_description.icon_fn
        if point is not None and icon_fn is not None:
            return icon_fn(point)
        return super().icon

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        point = self._point
        if point is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(point)
