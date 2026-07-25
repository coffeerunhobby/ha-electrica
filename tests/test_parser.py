"""Unit tests for the Electrica payload parser (no Home Assistant required).

All data here is SYNTHETIC — never real account data.
"""

from __future__ import annotations

from datetime import date

from ._loader import load

models = load("models")
parser = load("parser")

NLC = "1234567890"
CLIENT = "1234567890"


def _wrap(payload):
    """Mimic the API's {status, httpCode, body:{response: …}} envelope."""
    return {"status": "OK", "httpCode": "200", "body": {"response": payload}}


# ── Scalars ─────────────────────────────────────────────────────────────────
def test_to_float_handles_api_string_numbers():
    assert models.to_float("15.15") == 15.15
    assert models.to_float("1.234,56") == 1234.56
    assert models.to_float("7") == 7.0
    assert models.to_float("") is None
    assert models.to_float(None) is None
    assert models.to_float("abc") is None


def test_to_date_variants():
    assert models.to_date("2026-07-25") == date(2026, 7, 25)
    assert models.to_date("25.07.2026") == date(2026, 7, 25)
    assert models.to_date("") is None
    assert models.to_date("nonsense") is None


# ── Readings ────────────────────────────────────────────────────────────────
READINGS = _wrap(
    [
        {
            "ReadingDate": "2026-04-28",
            "Index": "663",
            "RegisterCode": "1.8.0",
            "MeterReadingType": "Citire contor de comp.utilitati - SAP",
        },
        {
            "ReadingDate": "2026-02-25",
            "Index": "603",
            "RegisterCode": "1.8.0",
            "MeterReadingType": "Citire contor de catre client - SAP",
        },
    ]
)


def test_parse_readings_sorted_and_typed():
    readings = parser.parse_readings(READINGS)
    assert len(readings) == 2
    # Sorted oldest-first regardless of API order.
    assert [r.reading_date for r in readings] == [date(2026, 2, 25), date(2026, 4, 28)]
    assert readings[-1].index == 663.0
    # "de catre client" marks a customer self-read.
    assert readings[0].self_read is True
    assert readings[1].self_read is False


def test_parse_readings_drops_incomplete_rows():
    assert parser.parse_readings(_wrap([{"Index": "5"}, {"ReadingDate": "2026-01-01"}])) == []


# ── Invoices / payments ─────────────────────────────────────────────────────
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
        },
        {
            "InvoiceID": "900000000",
            "FiscalNumber": "FF-0000",
            "IssueDate": "2026-06-14",
            "DueDate": "2026-06-29",
            "TotalAmount": "6.05",
            "UnpaidValue": "0",
            "InvoiceStatus": "achitat",
            "nlcField": NLC,
        },
    ]
)


def test_parse_invoices_newest_first_and_unpaid_flag():
    invoices = parser.parse_invoices(INVOICES)
    assert [i.issue_date for i in invoices] == [date(2026, 7, 14), date(2026, 6, 14)]
    assert invoices[0].is_unpaid is True
    assert invoices[1].is_unpaid is False
    assert invoices[0].total == 15.15


def test_parse_payments():
    payments = parser.parse_payments(
        _wrap([{"PaidValue": "6.05", "PaymentDate": "2026-06-24", "PaymentSource": "Banci"}])
    )
    assert payments[0].amount == 6.05
    assert payments[0].payment_date == date(2026, 6, 24)


# ── Convention / meter ──────────────────────────────────────────────────────
def test_parse_convention_builds_month_profile():
    profile = parser.parse_convention(
        _wrap([{"Month": "01", "Quantity": "6"}, {"Month": "12", "Quantity": "21"}])
    )
    assert profile == {1: 6.0, 12: 21.0}


def test_parse_convention_ignores_bad_months():
    assert parser.parse_convention(_wrap([{"Month": "13", "Quantity": "5"}])) == {}


def test_parse_meter_extracts_serial_and_pac_window():
    meter = parser.parse_meter(
        _wrap(
            {
                "PACIndicator": "X",
                "StartDatePAC": "2026-07-25",
                "EndDatePAC": "2026-07-30",
                "to_Contor": [{"SerieContor": "SYNTH-METER", "to_Cadran": []}],
            }
        )
    )
    assert meter["meter_serial"] == "SYNTH-METER"
    assert meter["pac_start"] == date(2026, 7, 25)
    assert meter["pac_available"] is True


# ── Hierarchy ───────────────────────────────────────────────────────────────
HIERARCHY = {
    "error": False,
    "details": [
        {
            "ClientCode": CLIENT,
            "to_ContContract": [
                {
                    "Balance": "15.15",
                    "to_LocConsum": [
                        {
                            "IdLocConsum": NLC,
                            "Street": "EXEMPLU",
                            "HouseNumber": "1",
                            "City": "ORAS",
                            "StartDatePAC": "2026-07-25",
                            "EndDatePAC": "2026-07-30",
                        }
                    ],
                }
            ],
        }
    ],
}


def test_balance_is_pushed_down_to_each_nlc():
    assert parser.balances_by_nlc(HIERARCHY) == {NLC: 15.15}


def test_apply_hierarchy_fills_balance_and_window():
    point = models.PointData(nlc=NLC, client_code=CLIENT)
    parser.apply_hierarchy(point, HIERARCHY)
    assert point.balance == 15.15
    assert point.pac_start == date(2026, 7, 25)


# ── PointData behaviour ─────────────────────────────────────────────────────
def test_amount_due_prefers_balance_then_falls_back_to_unpaid():
    point = models.PointData(nlc=NLC, client_code=CLIENT, balance=15.15)
    assert point.amount_due == 15.15

    without_balance = models.PointData(nlc=NLC, client_code=CLIENT)
    without_balance.invoices = parser.parse_invoices(INVOICES)
    assert without_balance.amount_due == 15.15  # sums only the unpaid one


def test_self_read_window_boundaries():
    point = models.PointData(
        nlc=NLC,
        client_code=CLIENT,
        pac_available=True,
        pac_start=date(2026, 7, 25),
        pac_end=date(2026, 7, 30),
    )
    assert point.self_read_open(date(2026, 7, 25)) is True   # first day
    assert point.self_read_open(date(2026, 7, 30)) is True   # last day
    assert point.self_read_open(date(2026, 7, 24)) is False
    assert point.self_read_open(date(2026, 7, 31)) is False


def test_self_read_closed_when_unavailable():
    point = models.PointData(
        nlc=NLC,
        client_code=CLIENT,
        pac_available=False,
        pac_start=date(2026, 7, 25),
        pac_end=date(2026, 7, 30),
    )
    assert point.self_read_open(date(2026, 7, 26)) is False
