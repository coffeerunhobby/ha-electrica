"""Shared identity and lookup for entities bound to one consumption point.

Every entity in this integration belongs to exactly one NLC, and each of the
four platforms previously repeated the same three things: the device
identifiers, the point lookup through the coordinator, and the entity_id shape.
Three copies that must agree — and if they drift, entities silently split
across two devices.

This is a mixin rather than a base class because the platforms do not share a
parent: the sensors are :class:`CoordinatorEntity` subclasses, while the number
and button are plain entities holding a coordinator reference. The mixin only
needs ``_init_point`` to have been called.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import ElectricaConfigEntry, ElectricaCoordinator
from .models import PointData


class ElectricaPointEntity:
    """Identity for an entity that represents one consumption point (NLC)."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    _coordinator: ElectricaCoordinator
    _nlc: str
    _device_id: str

    def _init_point(
        self,
        coordinator: ElectricaCoordinator,
        config_entry: ElectricaConfigEntry,
        nlc: str,
    ) -> None:
        """Bind this entity to one NLC. Call from ``__init__``."""
        self._coordinator = coordinator
        self._nlc = nlc
        self._device_id = f"{config_entry.entry_id}_{nlc}"

    def _build_entity_id(self, platform: str, key: str) -> str:
        """e.g. ``sensor.electrica_1234567890_amount_due``.

        Keyed on the NLC — Electrica's own stable identifier for the metering
        point — so the address text never appears in an entity_id.
        """
        return f"{platform}.{DOMAIN}_{self._nlc}_{key}"

    @property
    def _point(self) -> PointData | None:
        """This entity's consumption point, if still present in the account."""
        return (self._coordinator.data or {}).get(self._nlc)

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
