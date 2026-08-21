"""Pure normalization primitives for Garmin target events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite

from .providers import get_calendar_month

DEFAULT_LOOKAHEAD_DAYS = 180
MAX_LOOKAHEAD_DAYS = 366
MAX_EVENTS = 100
MAX_TITLE_LENGTH = 256
MAX_LOCATION_LENGTH = 256
MAX_TIME_ZONE_LENGTH = 128
_MAX_UUID_LENGTH = 256

PUBLIC_EVENT_ERRORS = {
    "invalid_days": {
        "code": "invalid_days",
        "message": "days must be an integer from 1 through 366.",
    },
    "client_unavailable": {
        "code": "client_unavailable",
        "message": "Garmin client is unavailable.",
    },
    "target_events_unavailable": {
        "code": "target_events_unavailable",
        "message": "Target-event calendar data is unavailable for the requested period.",
    },
}

EVENT_WARNINGS = {
    "provider_unavailable": {
        "provider": "calendar_events",
        "code": "provider_unavailable",
        "message": "Target-event calendar data is unavailable for this month.",
    },
    "invalid_provider_response": {
        "provider": "calendar_events",
        "code": "invalid_provider_response",
        "message": "Target-event calendar data returned an invalid response for this month.",
    },
    "events_truncated": {
        "provider": "calendar_events",
        "code": "events_truncated",
        "message": "Additional target events were omitted after the 100-event output limit.",
    },
}


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


def get_target_events_service(
    client: object | None,
    days: int = DEFAULT_LOOKAHEAD_DAYS,
    *,
    today: date | None = None,
) -> dict[str, object]:
    """Return a bounded, sanitized view of scheduled Garmin target events."""
    if type(days) is not int or not 1 <= days <= MAX_LOOKAHEAD_DAYS:
        return _target_events_response(
            status="error",
            error=_public_error("invalid_days"),
            period={"days": None, "start_date": None, "end_date": None},
            events_available=False,
        )

    resolved_today = date.today() if today is None else today  # noqa: DTZ011
    if type(resolved_today) is not date:
        raise TypeError("today must be a built-in date instance")

    end = resolved_today + timedelta(days=days - 1)
    period = {
        "days": days,
        "start_date": resolved_today.isoformat(),
        "end_date": end.isoformat(),
    }
    if client is None:
        return _target_events_response(
            status="error",
            error=_public_error("client_unavailable"),
            period=period,
            events_available=False,
        )

    readable_month_found = False
    degraded = False
    warnings: list[dict[str, str]] = []
    events: list[EventFacts] = []
    seen: set[tuple[object, ...]] = set()

    for year, month in event_months(resolved_today, end):
        result = get_calendar_month(client, year, month)
        if result.failed:
            degraded = True
            warnings.append(_month_warning("provider_unavailable", result.month))
            continue
        if result.invalid:
            degraded = True
            warnings.append(_month_warning("invalid_provider_response", result.month))
            continue

        readable_month_found = True
        month_has_malformed_candidate = False
        for raw in result.data:
            facts, malformed = normalize_event(raw)
            month_has_malformed_candidate = month_has_malformed_candidate or malformed
            if facts is None or not resolved_today <= facts.date <= end:
                continue

            key = _event_identity(facts)
            if key not in seen:
                seen.add(key)
                events.append(facts)

        if month_has_malformed_candidate:
            degraded = True
            warnings.append(_month_warning("invalid_provider_response", result.month))

    if not readable_month_found:
        return _target_events_response(
            status="error",
            error=_public_error("target_events_unavailable"),
            period=period,
            events_available=False,
            warnings=warnings,
        )

    events.sort(key=lambda facts: (facts.date, facts.title.casefold(), facts.title))
    events_truncated = len(events) > MAX_EVENTS
    if events_truncated:
        events = events[:MAX_EVENTS]
        warnings.append(dict(EVENT_WARNINGS["events_truncated"]))

    return _target_events_response(
        status="partial_success" if degraded else "success",
        error=None,
        period=period,
        events_available=True,
        events_truncated=events_truncated,
        events=[facts.to_public_dict(resolved_today) for facts in events],
        warnings=warnings,
    )


def _event_identity(facts: EventFacts) -> tuple[object, ...]:
    if facts.source_uuid is not None:
        return ("uuid", facts.source_uuid)
    return (
        "fallback",
        facts.date,
        facts.title,
        facts.start_time_local,
        facts.distance_km,
        facts.location,
    )


def _public_error(code: str) -> dict[str, str]:
    return dict(PUBLIC_EVENT_ERRORS[code])


def _month_warning(code: str, month: str) -> dict[str, str]:
    warning = EVENT_WARNINGS[code]
    return {
        "provider": warning["provider"],
        "month": month,
        "code": warning["code"],
        "message": warning["message"],
    }


def _target_events_response(
    *,
    status: str,
    error: dict[str, str] | None,
    period: dict[str, int | str | None],
    events_available: bool,
    events_truncated: bool = False,
    events: list[dict[str, object]] | None = None,
    warnings: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "error": error,
        "period": period,
        "availability": {"events": events_available},
        "events_truncated": events_truncated,
        "events": [] if events is None else events,
        "warnings": [] if warnings is None else warnings,
    }


__all__ = [
    "DEFAULT_LOOKAHEAD_DAYS",
    "EVENT_WARNINGS",
    "MAX_EVENTS",
    "MAX_LOCATION_LENGTH",
    "MAX_LOOKAHEAD_DAYS",
    "MAX_TIME_ZONE_LENGTH",
    "MAX_TITLE_LENGTH",
    "PUBLIC_EVENT_ERRORS",
    "EventFacts",
    "event_months",
    "get_target_events_service",
    "normalize_event",
]
