"""End-to-end setup inside a real Home Assistant instance.

Boots the integration the way Home Assistant does — config entry, coordinator,
all four platforms — and asserts on the entities and states that actually reach
the UI. Only the HTTP client is stubbed, so the real parser, coordinator and
entity code all run.

Payload shapes mirror what api.myelectrica.ro returns. All values are SYNTHETIC.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
)

from custom_components.electrica.api import ElectricaApiClient  # noqa: E402
from custom_components.electrica.const import (  # noqa: E402
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

NLC = "1234567890"
CLIENT = "1234567890"


def _wrap(payload):
    return {"status": "OK", "httpCode": "200", "body": {"response": payload}}


HIERARCHY = {
    "error": False,
    "details": [
        {
            "ClientCode": CLIENT,
            "ClientType": "PF",
            "ClientName": "ION POPESCU",
            "to_ContContract": [
                {
                    "ContractAccount": "000000000001",
                    "Balance": "15.15",
                    "City": "ORAS",
                    "Street": "EXEMPLU",
                    "HouseNumber": "10",
                    "to_LocConsum": [
                        {
                            "IdLocConsum": NLC,
                            "City": "ORAS",
                            "Street": "EXEMPLU",
                            "HouseNumber": "10",
                            "StartDatePAC": "2026-07-25",
                            "EndDatePAC": "2026-07-30",
                        }
                    ],
                }
            ],
        }
    ],
}

READINGS = _wrap(
    [
        {
            "ReadingDate": "2026-04-28",
            "Index": "663",
            "RegisterCode": "1.8.0",
            "MeterReadingType": "Citire contor de comp.utilitati - SAP",
        },
        {
            "ReadingDate": "2026-07-03",
            "Index": "728",
            "RegisterCode": "1.8.0",
            "MeterReadingType": "Citire contor de comp.utilitati - SAP",
        },
    ]
)

INVOICES = _wrap(
    [
        {
            "InvoiceID": "900000001",
            "FiscalNumber": "FF-0001",
            "IssueDate": "2026-07-14",
            "DueDate": "2026-07-29",
            "TotalAmount": "15.15",
            "UnpaidValue": "15.15",
            "InvoiceStatus": "neachitat",
            "nlcField": NLC,
        }
    ]
)


class _StubApi:
    """Stands in for the HTTP client; everything downstream is the real code."""

    # The real point-discovery walker: only transport is stubbed.
    extract_points = ElectricaApiClient.extract_points

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def async_login(self):
        return "synthetic-token"

    async def async_get_hierarchy(self):
        return HIERARCHY

    async def async_get_invoices(self, client_code, **kw):
        return INVOICES

    async def async_get_payments(self, client_code):
        return _wrap([{"PaidValue": "6.05", "PaymentDate": "2026-06-24"}])

    async def async_get_contract(self, nlc):
        return _wrap({"ContractStatus": "activ", "ProductName": "Energie electrica"})

    async def async_get_meter_list(self, nlc):
        return _wrap(
            {
                "PACIndicator": "X",
                "StartDatePAC": "2026-07-25",
                "EndDatePAC": "2026-07-30",
                "to_Contor": [{"SerieContor": "SYNTH-METER", "to_Cadran": []}],
            }
        )

    async def async_get_readings(self, client_code, nlc):
        return READINGS

    async def async_get_convention(self, nlc):
        return _wrap([{"Month": "01", "Quantity": "6", "Area": "U"}])

    async def close(self):
        return None


@pytest.fixture(autouse=True)
def _enable_custom_integration(enable_custom_integrations):
    """Declared directly so it is resolved before hass is built.

    The shared conftest requests it lazily, which is too late for a test that
    actually loads the integration."""
    yield


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Electrica — user@example.com",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "synthetic-password",
            CONF_UPDATE_INTERVAL: 6,
        },
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    with (
        patch("custom_components.electrica.coordinator.ElectricaApiClient", _StubApi),
        # Sync function, and the recorder is not running in these tests.
        patch(
            "custom_components.electrica.coordinator.async_update_consumption_statistics",
            MagicMock(return_value=None),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


@pytest.fixture
async def loaded(hass: HomeAssistant, entry: MockConfigEntry):
    """Set the integration up, and always unload it afterwards.

    Unloading closes the aiohttp session Home Assistant opens during setup;
    leaving it open trips the test harness's lingering-resource check.
    """
    await _setup(hass, entry)
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_the_integration_sets_up(loaded):
    entry = loaded
    assert entry.state is ConfigEntryState.LOADED


async def test_every_platform_produces_its_entities(hass, loaded):
    for entity_id in (
        f"sensor.{DOMAIN}_{NLC}_amount_due",
        f"sensor.{DOMAIN}_{NLC}_due_date",
        f"sensor.{DOMAIN}_{NLC}_due_date_timestamp",
        f"sensor.{DOMAIN}_{NLC}_meter_index",
        f"binary_sensor.{DOMAIN}_{NLC}_overdue",
        f"binary_sensor.{DOMAIN}_{NLC}_self_reading_open",
        f"number.{DOMAIN}_{NLC}_reading_to_submit",
        f"button.{DOMAIN}_{NLC}_submit_reading",
    ):
        assert hass.states.get(entity_id) is not None, f"{entity_id} was not created"


async def test_states_reflect_the_fetched_account(hass, loaded):
    assert hass.states.get(f"sensor.{DOMAIN}_{NLC}_amount_due").state == "15.15"
    assert hass.states.get(f"sensor.{DOMAIN}_{NLC}_meter_index").state == "728.0"
    # The next deadline is the unpaid invoice's due date.
    assert hass.states.get(f"sensor.{DOMAIN}_{NLC}_due_date").state == "2026-07-29"


async def test_overdue_is_a_problem_binary_sensor(hass, loaded):
    state = hass.states.get(f"binary_sensor.{DOMAIN}_{NLC}_overdue")
    assert state.state == "on"
    assert state.attributes["device_class"] == "problem"


async def test_self_reading_window_is_not_flagged_as_a_problem(hass, loaded):
    state = hass.states.get(f"binary_sensor.{DOMAIN}_{NLC}_self_reading_open")
    # An open window is useful, not a fault, so it must not render as an alert.
    assert state.attributes.get("device_class") is None


async def test_all_entities_share_one_device(hass, loaded):
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    entry = loaded
    device_ids = {
        e.device_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.device_id
    }
    assert len(device_ids) == 1, "entities scattered across multiple devices"
    device = dr.async_get(hass).async_get(next(iter(device_ids)))
    assert "EXEMPLU" in device.name


async def test_the_password_is_stored_encrypted(loaded):
    from custom_components.electrica.crypto import is_encrypted

    entry = loaded
    # Setup migrates a plaintext password to ciphertext in place.
    assert is_encrypted(entry.data[CONF_PASSWORD])


async def test_unload_is_clean(hass, loaded):
    assert await hass.config_entries.async_unload(loaded.entry_id)
    await hass.async_block_till_done()
    assert loaded.state is ConfigEntryState.NOT_LOADED
