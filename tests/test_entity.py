"""Entity identity must stay stable across all four platforms.

entity_id and unique_id are a contract with the user: they appear in dashboards,
automations and recorded history, so a refactor that changes them silently
breaks working setups. Every platform must also land on the *same* device, or
the entities scatter across duplicates in the UI.

All values below are SYNTHETIC.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.electrica.binary_sensor import (  # noqa: E402
    BINARY_SENSORS,
    ElectricaBinarySensor,
)
from custom_components.electrica.button import (  # noqa: E402
    ElectricaSubmitReadingButton,
)
from custom_components.electrica.const import DOMAIN  # noqa: E402
from custom_components.electrica.models import PointData  # noqa: E402
from custom_components.electrica.number import ElectricaReadingNumber  # noqa: E402
from custom_components.electrica.sensor import SENSORS, ElectricaSensor  # noqa: E402

NLC = "1234567890"
ENTRY_ID = "entry_one"


def _coordinator(address: str | None = "Strada Exemplu 1") -> SimpleNamespace:
    point = PointData(nlc=NLC, client_code=NLC, address=address)
    return SimpleNamespace(data={NLC: point}, last_update_success=True)


def _entry() -> SimpleNamespace:
    return SimpleNamespace(entry_id=ENTRY_ID, data={})


def _all_entities(coordinator=None):
    coordinator = coordinator or _coordinator()
    entry = _entry()
    return {
        "sensor": ElectricaSensor(coordinator, entry, NLC, SENSORS[0]),
        "binary_sensor": ElectricaBinarySensor(
            coordinator, entry, NLC, BINARY_SENSORS[0]
        ),
        "number": ElectricaReadingNumber(coordinator, entry, NLC),
        "button": ElectricaSubmitReadingButton(coordinator, entry, NLC),
    }


def test_entity_ids_are_unchanged():
    entities = _all_entities()
    assert entities["sensor"].entity_id == f"sensor.{DOMAIN}_{NLC}_amount_due"
    assert entities["binary_sensor"].entity_id == f"binary_sensor.{DOMAIN}_{NLC}_overdue"
    assert entities["number"].entity_id == f"number.{DOMAIN}_{NLC}_reading_to_submit"
    assert entities["button"].entity_id == f"button.{DOMAIN}_{NLC}_submit_reading"


def test_unique_ids_are_unchanged():
    entities = _all_entities()
    assert entities["sensor"].unique_id == f"{ENTRY_ID}_{NLC}_amount_due"
    assert entities["binary_sensor"].unique_id == f"{ENTRY_ID}_{NLC}_overdue_binary"
    assert entities["number"].unique_id == f"{ENTRY_ID}_{NLC}_reading_to_submit"
    assert entities["button"].unique_id == f"{ENTRY_ID}_{NLC}_submit_reading"


def test_every_platform_lands_on_one_device():
    identifiers = {
        next(iter(entity.device_info["identifiers"]))
        for entity in _all_entities().values()
    }
    assert identifiers == {(DOMAIN, f"{ENTRY_ID}_{NLC}")}


def test_device_is_named_by_address():
    for entity in _all_entities().values():
        assert entity.device_info["name"] == "Strada Exemplu 1"


def test_device_falls_back_to_the_nlc_without_an_address():
    for entity in _all_entities(_coordinator(address=None)).values():
        assert entity.device_info["name"] == f"NLC {NLC}"


def test_the_address_never_appears_in_an_entity_id():
    # The address is the device name, not part of any entity_id.
    for entity in _all_entities().values():
        assert "strada" not in entity.entity_id.lower()
