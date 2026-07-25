"""Config and options flow for the Electrica România integration.

Electrica does not use two-factor authentication, so setup is a single step:
validate the credentials, then confirm at least one consumption point exists.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    ElectricaApiClient,
    ElectricaAuthError,
    ElectricaConnectionError,
    ElectricaError,
)
from .const import (
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    MAX_UPDATE_INTERVAL_HOURS,
    MIN_UPDATE_INTERVAL_HOURS,
)
from .coordinator import ElectricaConfigEntry
from .crypto import ElectricaCipher

_LOGGER = logging.getLogger(__name__)

_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_UPDATE_INTERVAL_HOURS,
        max=MAX_UPDATE_INTERVAL_HOURS,
        step=1,
        mode=NumberSelectorMode.BOX,
    )
)


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=defaults.get(
                    CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS
                ),
            ): _INTERVAL_SELECTOR,
        }
    )


async def _store_password(hass, password: str) -> str:
    """Encrypt the password for storage, falling back to plaintext.

    Home Assistant persists config entries as plaintext JSON, so this protects
    against partial exposure (a shared `core.config_entries`, a single-file
    backup) rather than against full filesystem access — see crypto.py.
    """
    cipher = await ElectricaCipher.async_load(hass)
    return cipher.encrypt(password) if cipher else password


async def _validate(hass, username: str, password: str) -> int:
    """Log in and return the number of consumption points found."""
    client = ElectricaApiClient(
        username, password, session=async_get_clientsession(hass)
    )
    try:
        await client.async_login()
        hierarchy = await client.async_get_hierarchy()
        return len(ElectricaApiClient.extract_points(hierarchy))
    finally:
        await client.close()


class ElectricaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            try:
                points = await _validate(
                    self.hass, username, user_input[CONF_PASSWORD]
                )
            except ElectricaAuthError:
                errors["base"] = "invalid_auth"
            except ElectricaConnectionError:
                errors["base"] = "cannot_connect"
            except ElectricaError:
                errors["base"] = "unknown"
            else:
                if not points:
                    errors["base"] = "no_points"
                else:
                    return self.async_create_entry(
                        title=f"Electrica — {username}",
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: await _store_password(
                                self.hass, user_input[CONF_PASSWORD]
                            ),
                            CONF_UPDATE_INTERVAL: int(
                                user_input.get(
                                    CONF_UPDATE_INTERVAL,
                                    DEFAULT_UPDATE_INTERVAL_HOURS,
                                )
                            ),
                        },
                    )

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(user_input), errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            username = entry.data[CONF_USERNAME]
            try:
                await _validate(self.hass, username, user_input[CONF_PASSWORD])
            except ElectricaAuthError:
                errors["base"] = "invalid_auth"
            except ElectricaConnectionError:
                errors["base"] = "cannot_connect"
            except ElectricaError:
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_PASSWORD: await _store_password(
                            self.hass, user_input[CONF_PASSWORD]
                        ),
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ElectricaConfigEntry,
    ) -> ElectricaOptionsFlow:
        return ElectricaOptionsFlow()


class ElectricaOptionsFlow(OptionsFlow):
    """Allow changing the update interval without re-adding the integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                },
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=entry.data.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS
                        ),
                    ): _INTERVAL_SELECTOR
                }
            ),
        )
