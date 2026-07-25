"""Button platform: submit the staged meter index to Electrica.

This is the integration's only write. It is deliberately conservative — a wrong
index reaches the real utility account and can produce a wrong bill — so the
submission is refused unless:

* the self-reading (PAC) window is currently open,
* a meter serial and register code are known,
* a value has been staged on the "Reading to submit" number entity, and
* that value is at least the last known index (a meter cannot run backwards).
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import ElectricaConfigEntry, ElectricaCoordinator
from .models import PointData

_LOGGER = logging.getLogger(__name__)

# OBIS register for total active energy; used when the meter list does not
# report one explicitly.
DEFAULT_REGISTER_CODE = "1.8.0"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ElectricaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        entities = []
        for nlc in (coordinator.data or {}):
            if nlc in known:
                continue
            known.add(nlc)
            entities.append(ElectricaSubmitReadingButton(coordinator, config_entry, nlc))
        if entities:
            async_add_entities(entities)

    _add_new()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new))


class ElectricaSubmitReadingButton(ButtonEntity):
    """Submits the staged index as a self-reading."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_translation_key = "submit_reading"
    _attr_icon = "mdi:send-clock"
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: ElectricaCoordinator,
        config_entry: ElectricaConfigEntry,
        nlc: str,
    ) -> None:
        self._coordinator = coordinator
        self._nlc = nlc
        self._device_id = f"{config_entry.entry_id}_{nlc}"
        self._attr_unique_id = f"{self._device_id}_submit_reading"
        self.entity_id = f"button.{DOMAIN}_{nlc}_submit_reading"

    @property
    def _point(self) -> PointData | None:
        return (self._coordinator.data or {}).get(self._nlc)

    @property
    def available(self) -> bool:
        """Only offered while the self-reading window is open."""
        point = self._point
        return point is not None and point.self_read_open(dt_util.now().date())

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

    async def async_press(self) -> None:
        point = self._point
        if point is None:
            raise HomeAssistantError("Consumption point is not available")

        today = dt_util.now().date()
        if not point.self_read_open(today):
            raise HomeAssistantError(
                "The self-reading window is closed "
                f"({point.pac_start} → {point.pac_end}); Electrica will reject this."
            )

        if not point.meter_serial:
            raise HomeAssistantError("Meter serial is unknown — cannot submit")

        state = self.hass.states.get(f"number.{DOMAIN}_{self._nlc}_reading_to_submit")
        try:
            index = float(state.state) if state else None
        except (TypeError, ValueError):
            index = None
        if not index:
            raise HomeAssistantError(
                "Set the index on the 'Reading to submit' entity first"
            )

        last = point.latest_reading
        if last and last.index is not None and index < last.index:
            raise HomeAssistantError(
                f"Index {index:g} is below the last known reading "
                f"({last.index:g}) — a meter cannot run backwards"
            )

        register = (last.register if last and last.register else None) or DEFAULT_REGISTER_CODE
        api = self._coordinator.api
        if api is None:
            raise HomeAssistantError("Electrica API client is not ready")

        # Submit as an integer: Electrica records whole kWh for self-reads.
        await api.async_set_index(self._nlc, point.meter_serial, register, int(index))
        _LOGGER.info("Submitted self-read index for NLC %s", self._nlc)
        await self._coordinator.async_request_refresh()
