"""Diagnostics must never disclose credentials or personal data.

A diagnostics download is the artefact users attach to issue reports, so this is
the one output where a redaction gap is actively harmful. These tests assert on
the *rendered* result rather than on the redaction constants, so a refactor that
drops a name still fails here even if the module keeps importing.

All values below are SYNTHETIC.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME  # noqa: E402

from custom_components.electrica.diagnostics import (  # noqa: E402
    TO_REDACT_ENTRY,
    async_get_config_entry_diagnostics,
)
from custom_components.electrica.models import (  # noqa: E402
    Invoice,
    PointData,
    Reading,
)

NLC = "1234567890"


def _entry() -> SimpleNamespace:
    point = PointData(
        nlc="canary-nlc-value",
        client_code="canary-client-code",
        address="canary-street-address",
        meter_serial="canary-meter-serial",
    )
    point.readings = [
        Reading(
            reading_date=date(2026, 7, 3),
            index=728.0,
            register="1.8.0",
            description=None,
            reading_type="utility",
        )
    ]
    point.invoices = [
        Invoice(
            invoice_id="canary-invoice-id",
            fiscal_number="canary-fiscal-number",
            issue_date=date(2026, 7, 14),
            due_date=date(2026, 7, 29),
            total=15.15,
            unpaid=15.15,
            status="neachitat",
            pdf_url="https://example.com/canary-pdf",
        )
    ]
    return SimpleNamespace(
        title="Electrica — canary-user@example.com",
        entry_id="entry_one",
        data={
            CONF_USERNAME: "canary-user@example.com",
            CONF_PASSWORD: "enc:v1:canary-encrypted-password",
            "update_interval": 6,
        },
        runtime_data=SimpleNamespace(last_update_success=True, data={NLC: point}),
    )


async def _render() -> str:
    return json.dumps(await async_get_config_entry_diagnostics(None, _entry()), default=str)


async def test_credentials_never_appear_in_diagnostics():
    rendered = await _render()
    assert "canary-user@example.com" not in rendered
    # Even the ciphertext stays out: it is still the stored secret.
    assert "canary-encrypted-password" not in rendered


async def test_customer_and_metering_identifiers_are_redacted():
    rendered = await _render()
    for marker in (
        "canary-nlc-value",
        "canary-client-code",
        "canary-street-address",
        "canary-meter-serial",
        "canary-fiscal-number",
        "canary-invoice-id",
        "canary-pdf",
    ):
        assert marker not in rendered, f"{marker} leaked into diagnostics"


async def test_diagnostics_still_carry_useful_non_sensitive_context():
    result = await async_get_config_entry_diagnostics(None, _entry())
    assert result["coordinator"]["last_update_success"] is True
    assert result["coordinator"]["point_count"] == 1
    assert "update_interval" in result["entry"]["data"]


def test_credentials_are_listed_in_the_redaction_set():
    assert CONF_USERNAME in TO_REDACT_ENTRY
    assert CONF_PASSWORD in TO_REDACT_ENTRY
