"""Number platform: the meter index staged for submission.

Holds the value the "Submit reading" button will send. Kept local (nothing is
sent to Electrica when this changes) so the reading can be typed in, checked,
and only then submitted deliberately.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import ElectricaConfigEntry, ElectricaCoordinator
from .entity import ElectricaPointEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ElectricaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        entities = [
            ElectricaReadingNumber(coordinator, config_entry, nlc)
            for nlc in (coordinator.data or {})
            if nlc not in known and not known.add(nlc)  # type: ignore[func-returns-value]
        ]
        if entities:
            async_add_entities(entities)

    _add_new()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new))


class ElectricaReadingNumber(ElectricaPointEntity, RestoreEntity, NumberEntity):
    """The index value staged for the next self-reading submission."""

    _attr_translation_key = "reading_to_submit"
    _attr_icon = "mdi:numeric"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 99_999_999
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: ElectricaCoordinator,
        config_entry: ElectricaConfigEntry,
        nlc: str,
    ) -> None:
        self._init_point(coordinator, config_entry, nlc)
        self._attr_unique_id = f"{self._device_id}_reading_to_submit"
        self.entity_id = self._build_entity_id("number", "reading_to_submit")
        self._value: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            try:
                self._value = float(last.state)
            except (TypeError, ValueError):
                self._value = None
        if self._value is None:
            # Seed with the last known meter index so the user edits from a
            # sensible starting point rather than zero.
            point = (self._coordinator.data or {}).get(self._nlc)
            if point and point.latest_reading and point.latest_reading.index:
                self._value = float(point.latest_reading.index)


    @property
    def native_value(self) -> float | None:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = value
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        point = (self._coordinator.data or {}).get(self._nlc)
        last = point.latest_reading if point else None
        return {
            "last_known_index": last.index if last else None,
            "note": "Press the Submit reading button to send this to Electrica.",
        }
