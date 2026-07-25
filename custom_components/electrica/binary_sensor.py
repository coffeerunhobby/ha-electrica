"""Binary sensor platform for the Electrica România integration.

Exposes states that Home Assistant can render natively. A device-class
``problem`` entity is shown in red when it is ``on`` (with ``state_color: true``
on a card), which is the only way an integration can signal urgency — text
colour is a frontend concern and cannot be set from here.

The equivalent ``sensor.*`` entities are kept unchanged so existing templates
and automations keep working.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import ElectricaConfigEntry, ElectricaCoordinator
from .models import PointData

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ElectricaBinaryDescription(BinarySensorEntityDescription):
    """Describes a binary sensor on a consumption-point device."""

    value_fn: Callable[[PointData], bool | None]
    attrs_fn: Callable[[PointData], dict[str, Any]] | None = None


BINARY_SENSORS: tuple[ElectricaBinaryDescription, ...] = (
    ElectricaBinaryDescription(
        key="overdue",
        translation_key="overdue",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda p: bool(p.unpaid_invoices),
        attrs_fn=lambda p: {
            "amount_due": p.amount_due,
            "unpaid_invoices": len(p.unpaid_invoices),
            "due_date": (
                p.latest_invoice.due_date.isoformat()
                if p.latest_invoice and p.latest_invoice.due_date
                else None
            ),
        },
    ),
    ElectricaBinaryDescription(
        key="self_reading_open",
        translation_key="self_reading_open",
        icon="mdi:calendar-check",
        value_fn=lambda p: p.self_read_open(dt_util.now().date()),
        attrs_fn=lambda p: {
            "window_start": p.pac_start.isoformat() if p.pac_start else None,
            "window_end": p.pac_end.isoformat() if p.pac_end else None,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ElectricaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors for each consumption point."""
    coordinator = config_entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        entities: list[BinarySensorEntity] = []
        for nlc in (coordinator.data or {}):
            if nlc in known:
                continue
            known.add(nlc)
            entities.extend(
                ElectricaBinarySensor(coordinator, config_entry, nlc, description)
                for description in BINARY_SENSORS
            )
        if entities:
            async_add_entities(entities)

    _add_new()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new))


class ElectricaBinarySensor(
    CoordinatorEntity[ElectricaCoordinator], BinarySensorEntity
):
    """A binary sensor on a consumption-point device."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    entity_description: ElectricaBinaryDescription

    def __init__(
        self,
        coordinator: ElectricaCoordinator,
        config_entry: ElectricaConfigEntry,
        nlc: str,
        description: ElectricaBinaryDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._nlc = nlc
        self._device_id = f"{config_entry.entry_id}_{nlc}"
        self._attr_unique_id = f"{self._device_id}_{description.key}_binary"
        self.entity_id = f"binary_sensor.{DOMAIN}_{nlc}_{description.key}"

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
    def is_on(self) -> bool | None:
        point = self._point
        return self.entity_description.value_fn(point) if point else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        point = self._point
        if point is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(point)
