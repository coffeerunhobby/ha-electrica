"""Normalise Electrica's SAP-shaped API payloads into the models.

Kept free of Home Assistant imports so it can be unit-tested standalone.

Most endpoints wrap their useful content as ``{"status": …, "httpCode": …,
"body": {"response": <payload>}}``; :func:`unwrap` peels that off.
"""

from __future__ import annotations

from typing import Any

from .models import Invoice, Payment, PointData, Reading, to_date, to_float


def unwrap(payload: Any) -> Any:
    """Return the meaningful part of an API response.

    Tolerates the endpoints that answer with the bare payload, and the ones
    that nest it under ``body.response`` (or just ``response``/``details``).
    """
    node = payload
    for _ in range(4):  # bounded: the nesting is at most body → response
        if not isinstance(node, dict):
            return node
        for key in ("body", "response", "details", "data"):
            if key in node:
                node = node[key]
                break
        else:
            return node
    return node


def _as_list(payload: Any) -> list[dict[str, Any]]:
    node = unwrap(payload)
    if isinstance(node, list):
        return [item for item in node if isinstance(item, dict)]
    if isinstance(node, dict):
        return [node]
    return []


def _get(node: dict[str, Any], *names: str) -> Any:
    """Case-insensitive lookup across several candidate key spellings."""
    lowered = {k.lower(): v for k, v in node.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def parse_readings(payload: Any) -> list[Reading]:
    """Meter readings, newest last (sorted by date)."""
    readings = [
        Reading(
            reading_date=to_date(_get(row, "ReadingDate", "reading_date")),
            index=to_float(_get(row, "Index", "index")),
            register=_get(row, "RegisterCode", "register_code"),
            description=_get(row, "RegisterDescription", "register_description"),
            reading_type=_get(row, "MeterReadingType", "meter_reading_type"),
        )
        for row in _as_list(payload)
    ]
    readings = [r for r in readings if r.reading_date and r.index is not None]
    readings.sort(key=lambda r: r.reading_date)  # type: ignore[arg-type,return-value]
    return readings


def parse_invoices(payload: Any) -> list[Invoice]:
    """Invoices, newest first."""
    invoices = [
        Invoice(
            invoice_id=_get(row, "InvoiceID", "invoice_id"),
            fiscal_number=_get(row, "FiscalNumber", "fiscal_number"),
            issue_date=to_date(_get(row, "IssueDate", "issue_date")),
            due_date=to_date(_get(row, "DueDate", "due_date")),
            total=to_float(_get(row, "TotalAmount", "total_amount")),
            unpaid=to_float(_get(row, "UnpaidValue", "unpaid_value")) or 0.0,
            status=_get(row, "InvoiceStatus", "invoice_status"),
            invoice_type=_get(row, "InvoiceType", "invoice_type"),
            pdf_url=_get(row, "DownloadPDFUrl", "download_pdf_url"),
            nlc=_get(row, "nlcField", "nlc"),
        )
        for row in _as_list(payload)
    ]
    invoices.sort(key=lambda i: (i.issue_date is not None, i.issue_date), reverse=True)
    return invoices


def parse_payments(payload: Any) -> list[Payment]:
    """Payments, newest first."""
    payments = [
        Payment(
            invoice_id=_get(row, "InvoiceID", "invoice_id"),
            fiscal_number=_get(row, "FiscalNumber", "fiscal_number"),
            payment_date=to_date(_get(row, "PaymentDate", "payment_date")),
            amount=to_float(_get(row, "PaidValue", "paid_value")),
            source=_get(row, "PaymentSource", "payment_source"),
        )
        for row in _as_list(payload)
    ]
    payments.sort(
        key=lambda p: (p.payment_date is not None, p.payment_date), reverse=True
    )
    return payments


def parse_convention(payload: Any) -> dict[int, float]:
    """Agreed monthly consumption profile as {month_number: kWh}."""
    profile: dict[int, float] = {}
    for row in _as_list(payload):
        month = _get(row, "Month", "month")
        quantity = to_float(_get(row, "Quantity", "quantity"))
        try:
            month_no = int(str(month))
        except (TypeError, ValueError):
            continue
        if 1 <= month_no <= 12 and quantity is not None:
            profile[month_no] = quantity
    return profile


def parse_meter(payload: Any) -> dict[str, Any]:
    """Meter serial and the self-reading (PAC) window."""
    node = unwrap(payload)
    if not isinstance(node, dict):
        return {}

    serial = None
    meters = _get(node, "to_Contor", "meters")
    if isinstance(meters, list) and meters and isinstance(meters[0], dict):
        serial = _get(meters[0], "SerieContor", "serie_contor", "serial")

    indicator = str(_get(node, "PACIndicator", "pac_indicator") or "").strip()
    return {
        "meter_serial": serial,
        "pac_start": to_date(_get(node, "StartDatePAC", "start_date_pac")),
        "pac_end": to_date(_get(node, "EndDatePAC", "end_date_pac")),
        # SAP flags this as "X"/"A"/"true" depending on the endpoint.
        "pac_available": indicator.lower() in ("x", "a", "true", "1", "da", "yes"),
    }


def parse_contract(payload: Any) -> dict[str, Any]:
    """Contract details, as a flat dict of scalars."""
    node = unwrap(payload)
    if not isinstance(node, dict):
        return {}
    return {k: v for k, v in node.items() if not isinstance(v, (dict, list))}


def balances_by_nlc(hierarchy: Any) -> dict[str, float]:
    """Map each NLC to the balance on its contract account.

    ``Balance`` lives on the contract-account level of the hierarchy, one level
    above the NLCs it covers, so it is pushed down to each child NLC.
    """
    result: dict[str, float] = {}
    details = hierarchy.get("details") if isinstance(hierarchy, dict) else None
    for client in details or []:
        if not isinstance(client, dict):
            continue
        for account in client.get("to_ContContract") or []:
            if not isinstance(account, dict):
                continue
            balance = to_float(_get(account, "Balance", "balance"))
            for point in account.get("to_LocConsum") or []:
                if isinstance(point, dict):
                    nlc = _get(point, "IdLocConsum", "nlc")
                    if nlc is not None and balance is not None:
                        result[str(nlc)] = balance
    return result


def apply_hierarchy(point: PointData, hierarchy: Any) -> None:
    """Fill balance and the PAC window for ``point`` from the account tree."""
    balances = balances_by_nlc(hierarchy)
    if point.nlc in balances:
        point.balance = balances[point.nlc]

    details = hierarchy.get("details") if isinstance(hierarchy, dict) else None
    for client in details or []:
        if not isinstance(client, dict):
            continue
        for account in client.get("to_ContContract") or []:
            if not isinstance(account, dict):
                continue
            for node in account.get("to_LocConsum") or []:
                if not isinstance(node, dict):
                    continue
                if str(_get(node, "IdLocConsum", "nlc") or "") != point.nlc:
                    continue
                if point.pac_start is None:
                    point.pac_start = to_date(_get(node, "StartDatePAC"))
                if point.pac_end is None:
                    point.pac_end = to_date(_get(node, "EndDatePAC"))
