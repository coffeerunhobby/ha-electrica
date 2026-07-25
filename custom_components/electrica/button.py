"""Button platform: record a meter reading, and submit it when Electrica allows.

Pressing this always records the staged index **locally**, so the Energy
Dashboard gains a datapoint every time the meter is actually read. Electrica
only accepts a self-reading during its monthly PAC window, and only once per
window, so the API call is made *conditionally*:

* the self-reading window must be open, and
* nothing must have been submitted for that window yet.

Outside those conditions the press is still useful — the reading is kept locally
— it simply is not sent. Pressing repeatedly therefore never re-submits and
never produces a rejected request.

The index is validated before anything happens: a value below the last known
reading is a typo, and sending one to Electrica would produce a wrong bill.
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
from .store import merge_readings, validate_new_index

_LOGGER = logging.getLogger(__name__)

# OBIS register for total active energy; used when the meter list reports none.
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
    """Records the staged index, and forwards it to Electrica when permitted."""

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
        # Deliberately available outside the PAC window: a press still records
        # the reading locally for the consumption graph.
        return self._point is not None

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
    def extra_state_attributes(self) -> dict[str, str | int | bool | None]:
        """Explain what the next press will actually do."""
        point = self._point
        store = self._coordinator.reading_store
        if point is None or store is None:
            return {}

        window_open = point.self_read_open(dt_util.now().date())
        submitted = store.already_submitted(self._nlc, point.pac_end)
        last = store.last_submission(self._nlc)
        return {
            "will_submit_to_electrica": window_open and not submitted,
            "window_open": window_open,
            "already_submitted_this_window": submitted,
            "window_end": point.pac_end.isoformat() if point.pac_end else None,
            "local_readings": len(store.local_readings(self._nlc)),
            "last_submitted_index": last.get("index") if last else None,
            "last_submitted_at": last.get("at") if last else None,
        }

    async def async_press(self) -> None:
        point = self._point
        store = self._coordinator.reading_store
        if point is None or store is None:
            raise HomeAssistantError("Consumption point is not available")

        state = self.hass.states.get(f"number.{DOMAIN}_{self._nlc}_reading_to_submit")
        try:
            index = float(state.state) if state else None
        except (TypeError, ValueError):
            index = None
        if not index:
            raise HomeAssistantError(
                "Set the index on the 'Reading to submit' entity first"
            )

        # Validate against official *and* previously recorded local readings.
        history = merge_readings(point.readings, store.local_readings(self._nlc))
        ok, error = validate_new_index(index, history)
        if not ok:
            raise HomeAssistantError(error or "Invalid index")

        today = dt_util.now().date()

        # 1. Always record locally — this is what feeds the consumption graph.
        store.record_local(self._nlc, index, today)

        # 2. Submit to Electrica only when it will actually be accepted.
        window_open = point.self_read_open(today)
        already = store.already_submitted(self._nlc, point.pac_end)
        submitted = False

        if window_open and not already:
            if not point.meter_serial:
                raise HomeAssistantError("Meter serial is unknown — cannot submit")
            last = point.latest_reading
            register = (
                last.register if last and last.register else None
            ) or DEFAULT_REGISTER_CODE
            api = self._coordinator.api
            if api is None:
                raise HomeAssistantError("Electrica API client is not ready")

            await api.async_set_index(
                self._nlc, point.meter_serial, register, int(index)
            )
            store.mark_submitted(
                self._nlc, point.pac_end, index, dt_util.now().isoformat()
            )
            submitted = True
            _LOGGER.info("Submitted self-read index to Electrica for NLC %s", self._nlc)
        elif already:
            _LOGGER.info(
                "Index recorded locally for NLC %s; already submitted for the "
                "window ending %s",
                self._nlc,
                point.pac_end,
            )
        else:
            _LOGGER.info(
                "Index recorded locally for NLC %s; the self-reading window is "
                "closed so nothing was sent to Electrica",
                self._nlc,
            )

        await store.async_save()
        self.async_write_ha_state()
        if submitted:
            await self._coordinator.async_request_refresh()
        else:
            # Local-only: refresh the statistics so the new point shows up.
            self._coordinator.async_update_statistics(self._nlc)
