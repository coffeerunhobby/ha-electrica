"""Tests for the Electrica config flow: setup, re-auth and reconfigure.

Only the HTTP client is stubbed; validation, storage encryption and the
entry bookkeeping are the real code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries  # noqa: E402
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
)

from custom_components.electrica.api import ElectricaAuthError  # noqa: E402
from custom_components.electrica.const import (  # noqa: E402
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.electrica.crypto import is_encrypted  # noqa: E402

_HIERARCHY = {
    "error": False,
    "details": [
        {
            "ClientCode": "1234567890",
            "to_ContContract": [
                {
                    "ContractAccount": "000000000001",
                    "to_LocConsum": [{"IdLocConsum": "1234567890"}],
                }
            ],
        }
    ],
}


def _mock_api() -> AsyncMock:
    api = AsyncMock()
    api.async_login.return_value = "synthetic-token"
    api.async_get_hierarchy.return_value = _HIERARCHY
    return api


def _patch_api(api: AsyncMock):
    # extract_points is a classmethod on the real class, so the patched class
    # must delegate to it rather than mock it away.
    from custom_components.electrica.api import ElectricaApiClient

    factory = lambda *a, **kw: api  # noqa: E731
    factory.extract_points = ElectricaApiClient.extract_points
    return patch(
        "custom_components.electrica.config_flow.ElectricaApiClient",
        new=factory,
    )


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Electrica — user@example.com",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "old-password",
            CONF_UPDATE_INTERVAL: 6,
        },
    )


async def test_user_flow_creates_an_entry(hass: HomeAssistant) -> None:
    with _patch_api(_mock_api()), patch(
        "custom_components.electrica.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "secret",
                CONF_UPDATE_INTERVAL: 6,
            },
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "user@example.com"
    # The password must never be persisted as the user typed it.
    assert result["data"][CONF_PASSWORD] != "secret"
    assert is_encrypted(result["data"][CONF_PASSWORD])


async def test_user_flow_rejects_bad_credentials(hass: HomeAssistant) -> None:
    api = _mock_api()
    api.async_login.side_effect = ElectricaAuthError("bad")
    with _patch_api(api):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "wrong"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_form_asks_only_for_the_password(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert {str(k) for k in result["data_schema"].schema} == {CONF_PASSWORD}


async def test_reauth_replaces_the_stored_password(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)

    with _patch_api(_mock_api()), patch(
        "custom_components.electrica.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-password"}
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] != "new-password"
    assert is_encrypted(entry.data[CONF_PASSWORD])
    assert entry.data[CONF_USERNAME] == "user@example.com"


async def test_reconfigure_form_is_available_without_a_failure(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert {str(k) for k in result["data_schema"].schema} == {CONF_PASSWORD}


async def test_reconfigure_updates_the_entry_in_place(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    entry_id = entry.entry_id

    result = await entry.start_reconfigure_flow(hass)

    with _patch_api(_mock_api()), patch(
        "custom_components.electrica.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "rotated"}
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.entry_id == entry_id
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert is_encrypted(entry.data[CONF_PASSWORD])
    # Settings the form does not ask about must survive.
    assert entry.data[CONF_UPDATE_INTERVAL] == 6


async def test_reconfigure_redisplays_its_own_form_on_bad_password(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)

    api = _mock_api()
    api.async_login.side_effect = ElectricaAuthError("bad")
    with _patch_api(api):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "wrong"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "invalid_auth"}
    # The stored (encrypted or old) password is untouched.
    assert entry.data[CONF_PASSWORD] == "old-password"
