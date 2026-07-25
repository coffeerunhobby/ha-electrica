"""The Electrica România integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD
from .coordinator import ElectricaConfigEntry, ElectricaCoordinator
from .crypto import ElectricaCipher, is_encrypted

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.BUTTON]


async def _async_migrate_password(
    hass: HomeAssistant, entry: ElectricaConfigEntry
) -> None:
    """Encrypt a password stored in the clear by an earlier version.

    Rewrites the entry in place; this does not change any tunable setting, so it
    does not trigger a reload loop via the update listener.
    """
    stored = entry.data.get(CONF_PASSWORD)
    if not stored or is_encrypted(stored):
        return
    cipher = await ElectricaCipher.async_load(hass)
    if cipher is None:
        return
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_PASSWORD: cipher.encrypt(stored)}
    )
    _LOGGER.debug("Encrypted the stored Electrica password at rest")


async def async_setup_entry(hass: HomeAssistant, entry: ElectricaConfigEntry) -> bool:
    """Set up Electrica from a config entry."""
    await _async_migrate_password(hass, entry)
    coordinator = ElectricaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ElectricaConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and (coordinator := entry.runtime_data) is not None:
        await coordinator.async_shutdown()
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ElectricaConfigEntry) -> None:
    """Reload only when the tunable settings actually changed."""
    coordinator = entry.runtime_data
    if coordinator is None or coordinator.settings_changed():
        await hass.config_entries.async_reload(entry.entry_id)
