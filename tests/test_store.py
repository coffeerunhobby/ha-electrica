"""Tests for local reading storage, merging and index validation.

Pure logic — no Home Assistant needed. All data is SYNTHETIC.
"""

from __future__ import annotations

from datetime import date

from ._loader import load

models = load("models")
store = load("store")

Reading = models.Reading


def _official(day: date, index: float) -> "Reading":
    return Reading(
        reading_date=day,
        index=index,
        register="1.8.0",
        description="ENERGIE ACTIVA",
        reading_type="Citire contor de comp.utilitati - SAP",
    )


def _local(day: date, index: float) -> dict:
    return {"date": day.isoformat(), "index": index}


# ── Merging ─────────────────────────────────────────────────────────────────
def test_merge_sorts_oldest_first():
    merged = store.merge_readings(
        [_official(date(2026, 7, 3), 728)],
        [_local(date(2026, 5, 1), 690), _local(date(2026, 8, 1), 745)],
    )
    assert [r.reading_date for r in merged] == [
        date(2026, 5, 1),
        date(2026, 7, 3),
        date(2026, 8, 1),
    ]


def test_official_reading_wins_on_the_same_day():
    # Once Electrica publishes a value, it is authoritative over our estimate.
    merged = store.merge_readings(
        [_official(date(2026, 7, 3), 728)], [_local(date(2026, 7, 3), 999)]
    )
    assert len(merged) == 1
    assert merged[0].index == 728
    assert "SAP" in merged[0].reading_type


def test_local_readings_are_labelled():
    merged = store.merge_readings([], [_local(date(2026, 7, 25), 750)])
    assert merged[0].reading_type == store.LOCAL_READING_TYPE


def test_merge_ignores_malformed_local_entries():
    merged = store.merge_readings(
        [], [{"date": "nonsense", "index": 1}, {"date": "2026-07-25"}]
    )
    assert merged == []


# ── Validation ──────────────────────────────────────────────────────────────
def test_index_must_be_positive():
    ok, error = store.validate_new_index(0, [])
    assert ok is False and "greater than zero" in error


def test_index_below_last_reading_is_rejected():
    ok, error = store.validate_new_index(700, [_official(date(2026, 7, 3), 728)])
    assert ok is False
    assert "backwards" in error


def test_index_at_or_above_last_reading_is_accepted():
    history = [_official(date(2026, 7, 3), 728)]
    assert store.validate_new_index(728, history)[0] is True
    assert store.validate_new_index(750, history)[0] is True


def test_validation_passes_without_history():
    assert store.validate_new_index(500, [])[0] is True


# ── Window bookkeeping (pure helpers) ───────────────────────────────────────
def test_window_key_is_the_window_end_date():
    assert store.ElectricaReadingStore.window_key(date(2026, 7, 30)) == "2026-07-30"
    assert store.ElectricaReadingStore.window_key(None) is None
