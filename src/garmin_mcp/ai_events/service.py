"""Pure normalization primitives for Garmin target events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite

DEFAULT_LOOKAHEAD_DAYS = 180
MAX_LOOKAHEAD_DAYS = 366
MAX_EVENTS = 100
MAX_TITLE_LENGTH = 256
MAX_LOCATION_LENGTH = 256
MAX_TIME_ZONE_LENGTH = 128
_MAX_UUID_LENGTH = 256


@dataclass(frozen=True)
class EventFacts:
    """Normalized facts from one Garmin calendar event."""

    title: str
    date: date
    is_race: bool | None
    primary_event: bool | None
    distance_km: float | None
    start_time_local: str | None
    time_zone: str | None
    location: str | None
    source_uuid: str | None

    def to_public_dict(self, today: date) -> dict[str, object]:
        """Project facts into the public target-event representation."""
        return {
            "title": self.title,
            "date": self.date.isoformat(),
            "days_until": (self.date - today).days,
            "is_race": self.is_race,
            "primary_event": self.primary_event,
            "distance_km": self.distance_km,
            "start_time_local": self.start_time_local,
            "time_zone": self.time_zone,
            "location": self.location,
        }


def event_months(start: date, end: date) -> tuple[tuple[int, int], ...]:
    """Return every calendar month touched by the inclusive date interval."""
    if type(start) is not date or type(end) is not date:
        raise TypeError("start and end must be built-in date instances")
    if start > end:
        return ()

    months: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return tuple(months)


def normalize_event(raw: object) -> tuple[EventFacts | None, bool]:
    """Normalize one untrusted calendar entry without changing its input value."""
    if type(raw) is not dict:
        return None, True
    if type(raw.get("itemType")) is not str or raw["itemType"] != "event":
        return None, False

    title = _normalize_required_text(raw.get("title"), MAX_TITLE_LENGTH)
    if title is None:
        return None, True

    event_date = _normalize_date(raw.get("date"))
    if event_date is None:
        return None, True

    is_race, is_race_malformed = _normalize_optional_bool(raw.get("isRace"))
    primary_event, primary_event_malformed = _normalize_optional_bool(
        raw.get("primaryEvent")
    )
    distance_km, distance_malformed = _normalize_distance(raw.get("completionTarget"))
    start_time_local, time_zone, time_malformed = _normalize_event_time(
        raw.get("eventTimeLocal")
    )
    location, location_malformed = _normalize_location(raw.get("location"))
    source_uuid = _normalize_private_uuid(raw.get("shareableEventUuid"))

    return (
        EventFacts(
            title=title,
            date=event_date,
            is_race=is_race,
            primary_event=primary_event,
            distance_km=distance_km,
            start_time_local=start_time_local,
            time_zone=time_zone,
            location=location,
            source_uuid=source_uuid,
        ),
        any(
            (
                is_race_malformed,
                primary_event_malformed,
                distance_malformed,
                time_malformed,
                location_malformed,
            )
        ),
    )


def _normalize_required_text(value: object, maximum_length: int) -> str | None:
    if type(value) is not str:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > maximum_length:
        return None
    return normalized


def _normalize_date(value: object) -> date | None:
    if type(value) is not str:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _normalize_optional_bool(value: object) -> tuple[bool | None, bool]:
    if value is None:
        return None, False
    if type(value) is bool:
        return value, False
    return None, True


def _normalize_distance(value: object) -> tuple[float | None, bool]:
    if value is None:
        return None, False
    if type(value) is not dict:
        return None, True
    if value.get("unitType") != "distance":
        return None, False

    meters = value.get("value")
    if type(meters) not in (int, float):
        return None, True
    try:
        if not isfinite(meters) or meters < 0:
            return None, True
        return round(meters / 1000, 3), False
    except OverflowError:
        return None, True


def _normalize_event_time(value: object) -> tuple[str | None, str | None, bool]:
    if value is None:
        return None, None, False
    if type(value) is not dict:
        return None, None, True

    start_time_local, start_malformed = _normalize_start_time(
        value.get("startTimeHhMm")
    )
    time_zone, time_zone_malformed = _normalize_time_zone(value.get("timeZoneId"))
    return start_time_local, time_zone, start_malformed or time_zone_malformed


def _normalize_start_time(value: object) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if type(value) is not str or len(value) != 5 or value[2] != ":":
        return None, True
    if not all("0" <= character <= "9" for character in value[:2] + value[3:]):
        return None, True

    hours, minutes = int(value[:2]), int(value[3:])
    if hours > 23 or minutes > 59:
        return None, True
    return value, False


def _normalize_time_zone(value: object) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if type(value) is not str:
        return None, True
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_TIME_ZONE_LENGTH:
        return None, True
    return normalized, False


def _normalize_location(value: object) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if type(value) is not str:
        return None, True
    normalized = value.strip()
    if not normalized:
        return None, False
    if len(normalized) > MAX_LOCATION_LENGTH:
        return None, True
    return normalized, False


def _normalize_private_uuid(value: object) -> str | None:
    if type(value) is not str:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_UUID_LENGTH:
        return None
    return normalized


__all__ = [
    "DEFAULT_LOOKAHEAD_DAYS",
    "MAX_EVENTS",
    "MAX_LOCATION_LENGTH",
    "MAX_LOOKAHEAD_DAYS",
    "MAX_TIME_ZONE_LENGTH",
    "MAX_TITLE_LENGTH",
    "EventFacts",
    "event_months",
    "normalize_event",
]
