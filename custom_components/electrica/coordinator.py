"""Data update coordinator for the Electrica România integration."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    ElectricaApiClient,
    ElectricaAuthError,
    ElectricaConnectionError,
    ElectricaError,
)
from .const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)
from .crypto import ElectricaCipher, is_encrypted
from .models import PointData
from .statistics import async_update_consumption_statistics
from .store import ElectricaReadingStore, merge_readings
from .parser import (
    apply_hierarchy,
    parse_contract,
    parse_convention,
    parse_invoices,
    parse_meter,
    parse_payments,
    parse_readings,
)

_LOGGER = logging.getLogger(__name__)

type ElectricaConfigEntry = ConfigEntry["ElectricaCoordinator"]


class ElectricaCoordinator(DataUpdateCoordinator[dict[str, PointData]]):
    """Fetches the Electrica account and exposes it keyed by NLC."""

    config_entry: ElectricaConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        hours = int(
            config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=hours),
            config_entry=config_entry,
        )
        self._interval_hours = hours
        self.api: ElectricaApiClient | None = None
        # Locally recorded readings + which PAC windows were submitted.
        self.reading_store: ElectricaReadingStore | None = None

    def settings_changed(self) -> bool:
        current = int(
            self.config_entry.data.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS
            )
        )
        return current != self._interval_hours

    async def _async_password(self) -> str:
        """Return the account password, decrypting it when stored encrypted."""
        stored = self.config_entry.data[CONF_PASSWORD]
        if not is_encrypted(stored):
            return stored
        cipher = await ElectricaCipher.async_load(self.hass)
        if cipher is None:
            raise ConfigEntryAuthFailed(
                "The stored password is encrypted but cryptography is unavailable"
            )
        try:
            return cipher.decrypt(stored)
        except ValueError as err:
            # Typically a restored backup without the matching key file — send
            # the user through reauth rather than failing forever.
            raise ConfigEntryAuthFailed(str(err)) from err

    async def _async_ensure_api(self) -> ElectricaApiClient:
        if self.api is None:
            self.api = ElectricaApiClient(
                self.config_entry.data[CONF_USERNAME],
                await self._async_password(),
                session=async_get_clientsession(self.hass),
            )
        return self.api

    async def async_shutdown(self) -> None:
        if self.api is not None:
            await self.api.close()
            self.api = None
        await super().async_shutdown()

    async def _async_update_data(self) -> dict[str, PointData]:
        api = await self._async_ensure_api()
        try:
            return await self._fetch(api)
        except ElectricaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (ElectricaConnectionError, ElectricaError) as err:
            raise UpdateFailed(str(err)) from err

    async def _ensure_store(self) -> ElectricaReadingStore:
        if self.reading_store is None:
            self.reading_store = ElectricaReadingStore(
                self.hass, self.config_entry.entry_id
            )
            await self.reading_store.async_load()
        return self.reading_store

    def async_update_statistics(self, nlc: str) -> None:
        """Re-import the statistics for one point (after a local reading)."""
        point = (self.data or {}).get(nlc)
        if point is None or self.reading_store is None:
            return
        async_update_consumption_statistics(
            self.hass,
            nlc,
            point.address or nlc,
            merge_readings(point.readings, self.reading_store.local_readings(nlc)),
        )

    async def _fetch(self, api: ElectricaApiClient) -> dict[str, PointData]:
        store = await self._ensure_store()
        hierarchy = await api.async_get_hierarchy()
        points = api.extract_points(hierarchy)
        if not points:
            raise UpdateFailed("No consumption points (NLC) found on this account")

        # Invoices/payments are per client code — fetch each once and share it
        # across the NLCs beneath it rather than re-requesting per point.
        client_codes = {p.client_code for p in points}
        invoices_by_client: dict[str, Any] = {}
        payments_by_client: dict[str, Any] = {}
        for code in client_codes:
            invoices_by_client[code] = parse_invoices(
                await api.async_get_invoices(code)
            )
            payments_by_client[code] = parse_payments(
                await api.async_get_payments(code)
            )

        result: dict[str, PointData] = {}
        for point in points:
            data = PointData(
                nlc=point.nlc,
                client_code=point.client_code,
                address=point.address,
            )
            apply_hierarchy(data, hierarchy)

            data.contract = parse_contract(await api.async_get_contract(point.nlc))
            meter = parse_meter(await api.async_get_meter_list(point.nlc))
            data.meter_serial = meter.get("meter_serial")
            # meter-list is authoritative for the PAC window; the hierarchy is
            # only a fallback (applied above).
            data.pac_start = meter.get("pac_start") or data.pac_start
            data.pac_end = meter.get("pac_end") or data.pac_end
            data.pac_available = bool(meter.get("pac_available"))

            data.readings = parse_readings(
                await api.async_get_readings(point.client_code, point.nlc)
            )
            data.convention = parse_convention(
                await api.async_get_convention(point.nlc)
            )

            all_invoices = invoices_by_client.get(point.client_code) or []
            # Invoices carry the NLC they belong to; when several NLCs share a
            # client code, keep only this point's (fall back to all if unset).
            own = [i for i in all_invoices if i.nlc and str(i.nlc) == point.nlc]
            data.invoices = own or all_invoices
            data.payments = payments_by_client.get(point.client_code) or []

            # Meter index → Energy Dashboard (interpolated to daily points).
            async_update_consumption_statistics(
                self.hass,
                point.nlc,
                data.address or point.nlc,
                merge_readings(data.readings, store.local_readings(point.nlc)),
            )

            result[point.nlc] = data

        return result

    @property
    def today(self) -> date:
        return dt_util.now().date()
