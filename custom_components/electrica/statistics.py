"""Feed Electrica meter readings into Home Assistant long-term statistics.

The meter index (OBIS register 1.8.0) is a cumulative kWh counter, which is
exactly what the Energy Dashboard consumes. The catch is cadence: Electrica
reads the meter every two to three months, so importing the raw points would
show one large spike on each reading day and nothing in between.

Instead, consumption between two consecutive real readings is spread evenly
across the days separating them, producing a smooth cumulative series. The raw
readings remain visible as sensor attributes, so nothing is hidden — but the
per-day split is an interpolation, not metered truth.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .models import Reading

_LOGGER = logging.getLogger(__name__)


def statistic_id(nlc: str) -> str:
    """External statistic id, e.g. ``electrica:consumption_<nlc>``."""
    return f"{DOMAIN}:consumption_{nlc}"


def _metadata(stat_id: str, name: str) -> StatisticMetaData:
    """Sum-only statistic metadata, robust across Home Assistant versions.

    Newer Home Assistant replaced ``has_mean`` with a ``mean_type`` enum; supply
    whichever the running version understands.
    """
    metadata: StatisticMetaData = {
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": stat_id,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    }
    try:
        from homeassistant.components.recorder.models import StatisticMeanType

        metadata["mean_type"] = StatisticMeanType.NONE
    except ImportError:
        metadata["has_mean"] = False
    return metadata


def daily_series(readings: list[Reading]) -> list[tuple[datetime, float]]:
    """Interpolate the cumulative index to one point per day.

    Returns ``(local_midnight, cumulative_kWh)`` pairs covering the first through
    the last reading. Needs at least two dated readings to establish a rate.
    """
    usable = [r for r in readings if r.reading_date and r.index is not None]
    usable.sort(key=lambda r: r.reading_date)  # type: ignore[arg-type,return-value]
    if len(usable) < 2:
        return []

    series: list[tuple[datetime, float]] = []
    first = usable[0]
    series.append(
        (dt_util.start_of_local_day(datetime.combine(first.reading_date, datetime.min.time())), float(first.index))  # type: ignore[arg-type]
    )

    for previous, current in zip(usable, usable[1:]):
        start, end = previous.reading_date, current.reading_date
        span = (end - start).days  # type: ignore[operator]
        if span <= 0:
            continue
        delta = float(current.index) - float(previous.index)  # type: ignore[arg-type]
        # A meter reset/replacement would make this negative; skip rather than
        # emit a decreasing cumulative sum.
        if delta < 0:
            continue
        per_day = delta / span
        for offset in range(1, span + 1):
            day = start + timedelta(days=offset)  # type: ignore[operator]
            value = float(previous.index) + per_day * offset  # type: ignore[arg-type]
            series.append(
                (
                    dt_util.start_of_local_day(
                        datetime.combine(day, datetime.min.time())
                    ),
                    round(value, 3),
                )
            )
    return series


def async_update_consumption_statistics(
    hass: HomeAssistant,
    nlc: str,
    display_name: str,
    readings: list[Reading],
) -> None:
    """Import the interpolated meter series as external statistics."""
    series = daily_series(readings)
    if not series:
        return

    stat_id = statistic_id(nlc)
    points = [
        StatisticData(start=moment, state=value, sum=value) for moment, value in series
    ]
    try:
        async_add_external_statistics(
            hass, _metadata(stat_id, f"Electrica {display_name} consumption"), points
        )
    except Exception:  # noqa: BLE001 — recorder may be unavailable
        _LOGGER.debug("Could not import Electrica statistics", exc_info=True)
