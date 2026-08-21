"""Bounded, read-only Garmin calendar provider seams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CalendarMonthResult:
    """A calendar month payload with bounded provider-status metadata."""

    month: str
    data: tuple[Any, ...] = ()
    failed: bool = False
    invalid: bool = False


def get_calendar_month(client: Any, year: int, month: int) -> CalendarMonthResult:
    """Read and bound one calendar month through the pinned Garmin method."""
    month_key = f"{year:04d}-{month:02d}"

    try:
        response = client.get_scheduled_workouts(year, month)
    except Exception:  # noqa: BLE001 - provider boundary must sanitize every exception
        return CalendarMonthResult(month_key, failed=True)

    if response is None:
        return CalendarMonthResult(month_key)
    if type(response) is not dict:
        return CalendarMonthResult(month_key, invalid=True)
    if not response:
        return CalendarMonthResult(month_key)
    if "calendarItems" not in response:
        return CalendarMonthResult(month_key, invalid=True)

    items = response["calendarItems"]
    if items is None:
        return CalendarMonthResult(month_key)
    if type(items) is not list:
        return CalendarMonthResult(month_key, invalid=True)
    return CalendarMonthResult(month_key, tuple(items))


__all__ = ["CalendarMonthResult", "get_calendar_month"]
