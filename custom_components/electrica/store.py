"""Persistent store for locally recorded meter readings.

Electrica publishes an official reading only every two to three months, and its
self-reading (PAC) window opens for a few days once a month. That caps how much
detail the consumption graph can ever have.

To get past that, every press of the *Submit reading* button records the index
**locally**, whichever day it happens. Those local readings are merged with the
official ones when building the Energy Dashboard series, so the graph gains a
datapoint each time the meter is actually read — without depending on Electrica
storing it.

Submission to Electrica is tracked separately: at most one per PAC window, keyed
by the window's end date, so pressing the button repeatedly never re-sends.

The merge/validation helpers are pure so they can be unit-tested without Home
Assistant; ``Store`` is imported lazily inside the class.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from .const import STORAGE_KEY_READINGS, STORAGE_VERSION
from .models import Reading, to_date, to_float

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Marks a reading this integration recorded, as opposed to one Electrica
# published. Surfaced in attributes so the two are always distinguishable.
LOCAL_READING_TYPE = "Citire locală (Home Assistant)"


def merge_readings(
    official: list[Reading], local: list[dict[str, Any]]
) -> list[Reading]:
    """Combine official and locally recorded readings into one sorted series.

    Official readings win on a date collision: once Electrica publishes a value
    for a day, that is authoritative and the local estimate for the same day is
    dropped. The result is sorted oldest-first, as the statistics importer
    expects.
    """
    by_date: dict[date, Reading] = {}

    for entry in local:
        when = to_date(entry.get("date"))
        index = to_float(entry.get("index"))
        if when is None or index is None:
            continue
        by_date[when] = Reading(
            reading_date=when,
            index=index,
            register=entry.get("register"),
            description=None,
            reading_type=LOCAL_READING_TYPE,
        )

    # Applied second so official values overwrite any local one on that date.
    for reading in official:
        if reading.reading_date and reading.index is not None:
            by_date[reading.reading_date] = reading

    return [by_date[key] for key in sorted(by_date)]


def validate_new_index(
    index: float, readings: list[Reading]
) -> tuple[bool, str | None]:
    """Check an index against history. Returns ``(ok, error)``.

    A mechanical meter cannot run backwards, so anything below the last known
    value is a typo — and submitting one to Electrica would produce a wrong bill.
    """
    if index <= 0:
        return False, "The index must be greater than zero"

    dated = [r for r in readings if r.index is not None]
    if not dated:
        return True, None

    last = max(dated, key=lambda r: (r.reading_date is not None, r.reading_date))
    if last.index is not None and index < last.index:
        return (
            False,
            f"Index {index:g} is below the last known reading ({last.index:g}) — "
            "a meter cannot run backwards",
        )
    return True, None


class ElectricaReadingStore:
    """On-disk record of local readings and per-window submissions, by NLC."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        from homeassistant.helpers.storage import Store

        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_READINGS}_{entry_id}"
        )
        self._data: dict[str, Any] = {}
        self._loaded = False

    async def async_load(self) -> None:
        if not self._loaded:
            self._data = await self._store.async_load() or {}
            self._loaded = True

    def _bucket(self, nlc: str) -> dict[str, Any]:
        return self._data.setdefault(nlc, {"local": [], "submitted": {}})

    # ── Local readings ──────────────────────────────────────────────────────
    def local_readings(self, nlc: str) -> list[dict[str, Any]]:
        return self._bucket(nlc).get("local", [])

    def record_local(self, nlc: str, index: float, when: date) -> None:
        """Store a reading taken today, replacing any earlier one for that day."""
        bucket = self._bucket(nlc)
        entries = [e for e in bucket.get("local", []) if e.get("date") != when.isoformat()]
        entries.append({"date": when.isoformat(), "index": float(index)})
        entries.sort(key=lambda e: e["date"])
        bucket["local"] = entries

    # ── Submission tracking ─────────────────────────────────────────────────
    @staticmethod
    def window_key(window_end: date | None) -> str | None:
        """Identify a PAC window by its end date."""
        return window_end.isoformat() if window_end else None

    def already_submitted(self, nlc: str, window_end: date | None) -> bool:
        key = self.window_key(window_end)
        if key is None:
            return False
        return key in (self._bucket(nlc).get("submitted") or {})

    def mark_submitted(
        self, nlc: str, window_end: date | None, index: float, when: str
    ) -> None:
        key = self.window_key(window_end)
        if key is None:
            return
        self._bucket(nlc).setdefault("submitted", {})[key] = {
            "index": float(index),
            "at": when,
        }

    def last_submission(self, nlc: str) -> dict[str, Any] | None:
        submitted = self._bucket(nlc).get("submitted") or {}
        if not submitted:
            return None
        latest = max(submitted)
        return {"window_end": latest, **submitted[latest]}

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    async def async_remove(self) -> None:
        await self._store.async_remove()
