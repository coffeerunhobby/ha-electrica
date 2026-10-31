"""Behaviour asked for in the HACS default-store review, and the 1.0.0 fixes.

All values are SYNTHETIC; only the HTTP client is stubbed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

pytest.importorskip("homeassistant")

from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.electrica.const import DOMAIN  # noqa: E402

from .test_integration_setup import NLC, entry, loaded  # noqa: E402,F401


async def test_no_invoice_link_in_state_attributes(hass: HomeAssistant, loaded):
    """State attributes land in the recorder and are visible to every user."""
    attrs = hass.states.get(f"sensor.{DOMAIN}_{NLC}_amount_due").attributes
    assert "pdf_url" not in attrs
    assert all("pdf_url" not in row for row in attrs.get("history", []))


async def test_the_button_still_finds_a_renamed_reading_entity(hass: HomeAssistant, loaded):
    registry = er.async_get(hass)
    old_id = f"number.{DOMAIN}_{NLC}_reading_to_submit"
    registry.async_update_entity(old_id, new_entity_id="number.my_meter_reading")
    await hass.async_block_till_done()

    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.my_meter_reading", "value": 800}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{DOMAIN}_{NLC}_submit_reading"}, blocking=True
    )

    store = loaded.runtime_data.reading_store
    assert [r["index"] for r in store.local_readings(NLC)] == [800.0]


async def test_a_failed_update_retries_soon_then_the_interval_returns(
    hass: HomeAssistant, loaded
):
    coordinator = loaded.runtime_data
    normal = coordinator.update_interval
    assert normal == timedelta(hours=6)

    async def down(*_args, **_kwargs):
        from custom_components.electrica.api import ElectricaConnectionError

        raise ElectricaConnectionError("Electrica did not answer in time")

    api = coordinator.api
    original = api.async_get_hierarchy
    api.async_get_hierarchy = down
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.update_interval == timedelta(minutes=15)

    api.async_get_hierarchy = original
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.update_interval == normal


def test_statistics_metadata_declares_the_unit_class_where_known():
    """Sent on Home Assistant 2025.11+, withheld where older releases would reject it."""
    from homeassistant.components.recorder.models import StatisticMetaData

    from custom_components.electrica.statistics import _metadata

    metadata = _metadata("electrica:consumption_x", "x")
    if "unit_class" in StatisticMetaData.__annotations__:
        assert metadata["unit_class"] == "energy"
    else:
        assert "unit_class" not in metadata
