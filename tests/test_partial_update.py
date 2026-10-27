"""One consumption point failing must not take the whole account down.

Runs the real coordinator inside Home Assistant with a two-point account whose
second point stops answering. All values are SYNTHETIC.
"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.electrica.api import ElectricaConnectionError  # noqa: E402
from custom_components.electrica.const import DOMAIN  # noqa: E402

from .test_integration_setup import HIERARCHY, NLC, _StubApi, entry  # noqa: E402,F401

SECOND_NLC = "1111111111"

TWO_POINTS = copy.deepcopy(HIERARCHY)
_contract = TWO_POINTS["details"][0]["to_ContContract"][0]
_contract["to_LocConsum"].append({**_contract["to_LocConsum"][0], "IdLocConsum": SECOND_NLC})


class _FlakyApi(_StubApi):
    """The second point times out whenever ``failing`` is set."""

    failing = False
    everything_down = False

    async def async_get_hierarchy(self):
        return TWO_POINTS

    async def async_get_meter_list(self, nlc):
        if _FlakyApi.everything_down or (_FlakyApi.failing and nlc == SECOND_NLC):
            raise ElectricaConnectionError("Electrica did not answer in time")
        return await super().async_get_meter_list(nlc)


@pytest.fixture(autouse=True)
def _reset():
    _FlakyApi.failing = False
    _FlakyApi.everything_down = False
    yield


@pytest.fixture
async def coordinator(hass: HomeAssistant, entry, enable_custom_integrations):
    entry.add_to_hass(hass)
    with (
        patch("custom_components.electrica.coordinator.ElectricaApiClient", _FlakyApi),
        patch(
            "custom_components.electrica.coordinator.async_update_consumption_statistics",
            MagicMock(return_value=None),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry.runtime_data
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()


async def test_both_points_load(coordinator):
    assert set(coordinator.data) == {NLC, SECOND_NLC}


async def test_a_failing_point_keeps_its_last_data_and_the_rest_refresh(
    hass: HomeAssistant, coordinator
):
    before = coordinator.data[SECOND_NLC]
    _FlakyApi.failing = True

    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.data[SECOND_NLC] is before  # last good data, not dropped
    assert coordinator.data[NLC] is not None
    state = hass.states.get(f"sensor.{DOMAIN}_{SECOND_NLC}_amount_due")
    assert state is not None and state.state != "unavailable"


async def test_the_update_fails_only_when_no_point_refreshed(coordinator):
    _FlakyApi.everything_down = True

    await coordinator.async_refresh()

    assert not coordinator.last_update_success
