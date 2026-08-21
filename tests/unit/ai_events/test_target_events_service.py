"""Tests for the bounded target-event aggregation service."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from garmin_mcp.ai_events.service import (
    EVENT_WARNINGS,
    MAX_EVENTS,
    MAX_TITLE_LENGTH,
    PUBLIC_EVENT_ERRORS,
    get_target_events_service,
)


class DateSubclass(date):
    pass


class CalendarClient:
    def __init__(self, responses: dict[tuple[int, int], object]) -> None:
        self.responses = responses
        self.calls: list[tuple[int, int]] = []

    def get_scheduled_workouts(self, year: int, month: int) -> object:
        self.calls.append((year, month))
        response = self.responses.get((year, month), {"calendarItems": []})
        if isinstance(response, BaseException):
            raise response
        return response


def calendar_response(*items: object) -> dict[str, object]:
    return {"calendarItems": list(items)}


def event_raw(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "itemType": "event",
        "title": "Spring Marathon",
        "date": "2026-05-03",
    }
    raw.update(overrides)
    return raw


def event_for_day(day: date, **overrides: object) -> dict[str, object]:
    return event_raw(date=day.isoformat(), **overrides)


def month_warning(code: str, month: str) -> dict[str, str]:
    return {
        "provider": "calendar_events",
        "month": month,
        "code": EVENT_WARNINGS[code]["code"],
        "message": EVENT_WARNINGS[code]["message"],
    }


def assert_target_envelope(result: dict[str, object]) -> None:
    assert tuple(result) == (
        "status",
        "error",
        "period",
        "availability",
        "events_truncated",
        "events",
        "warnings",
    )


def test_target_event_error_and_warning_catalogues_are_fixed_and_sanitized() -> None:
    assert PUBLIC_EVENT_ERRORS == {
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
    assert EVENT_WARNINGS == {
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


@pytest.mark.parametrize("days", [True, False, 0, 367, "180"])
def test_target_events_rejects_invalid_days_without_reading_calendar(days: object) -> None:
    client = CalendarClient({})

    result = get_target_events_service(client, days, today=date(2026, 1, 15))

    assert_target_envelope(result)
    assert result == {
        "status": "error",
        "error": PUBLIC_EVENT_ERRORS["invalid_days"],
        "period": {"days": None, "start_date": None, "end_date": None},
        "availability": {"events": False},
        "events_truncated": False,
        "events": [],
        "warnings": [],
    }
    assert client.calls == []


@pytest.mark.parametrize(
    "invalid_today",
    [datetime(2026, 1, 15, tzinfo=UTC), DateSubclass(2026, 1, 15), "2026-01-15"],
)
def test_target_events_requires_exact_injected_builtin_date(invalid_today: object) -> None:
    with pytest.raises(TypeError):
        get_target_events_service(CalendarClient({}), today=invalid_today)


def test_target_events_missing_client_keeps_derived_leap_period() -> None:
    result = get_target_events_service(None, 2, today=date(2024, 2, 29))

    assert_target_envelope(result)
    assert result == {
        "status": "error",
        "error": PUBLIC_EVENT_ERRORS["client_unavailable"],
        "period": {"days": 2, "start_date": "2024-02-29", "end_date": "2024-03-01"},
        "availability": {"events": False},
        "events_truncated": False,
        "events": [],
        "warnings": [],
    }


def test_target_events_reads_each_of_thirteen_touched_months_in_order() -> None:
    client = CalendarClient({})

    result = get_target_events_service(client, 366, today=date(2024, 1, 31))

    assert result["status"] == "success"
    assert result["availability"] == {"events": True}
    assert result["period"] == {
        "days": 366,
        "start_date": "2024-01-31",
        "end_date": "2025-01-30",
    }
    assert client.calls == [
        (2024, month) for month in range(1, 13)
    ] + [(2025, 1)]


def test_target_events_accepts_one_day_and_a_valid_empty_calendar() -> None:
    client = CalendarClient({})

    result = get_target_events_service(client, 1, today=date(2026, 1, 15))

    assert result["status"] == "success"
    assert result["availability"] == {"events": True}
    assert result["events"] == []
    assert result["warnings"] == []
    assert client.calls == [(2026, 1)]


def test_target_events_clips_out_of_range_entries_and_keeps_valid_empty_calendar() -> None:
    client = CalendarClient(
        {
            (2026, 1): calendar_response(
                event_for_day(date(2025, 12, 31), title="Past"),
                event_for_day(date(2026, 1, 2), title="In range"),
                event_for_day(date(2026, 1, 4), title="Future"),
                {"itemType": "workout", "title": "Ignored"},
            )
        }
    )

    result = get_target_events_service(client, 3, today=date(2026, 1, 1))

    assert result["status"] == "success"
    assert result["availability"] == {"events": True}
    assert result["events"] == [
        {
            "title": "In range",
            "date": "2026-01-02",
            "days_until": 1,
            "is_race": None,
            "primary_event": None,
            "distance_km": None,
            "start_time_local": None,
            "time_zone": None,
            "location": None,
        }
    ]
    assert result["warnings"] == []


def test_target_events_returns_error_when_all_requested_months_are_unreadable() -> None:
    client = CalendarClient(
        {
            (2026, 1): RuntimeError("https://garmin.example/?token=secret"),
            (2026, 2): {"unexpected": "response"},
        }
    )

    result = get_target_events_service(client, 29, today=date(2026, 1, 31))

    assert result["status"] == "error"
    assert result["error"] == PUBLIC_EVENT_ERRORS["target_events_unavailable"]
    assert result["availability"] == {"events": False}
    assert result["events"] == []
    assert result["warnings"] == [
        month_warning("provider_unavailable", "2026-01"),
        month_warning("invalid_provider_response", "2026-02"),
    ]
    assert [tuple(warning) for warning in result["warnings"]] == [
        ("provider", "month", "code", "message"),
        ("provider", "month", "code", "message"),
    ]


def test_target_events_marks_readable_month_with_malformed_candidates_partial_once() -> None:
    client = CalendarClient(
        {
            (2026, 1): calendar_response(
                {"itemType": "event", "title": "", "date": "2026-01-02"},
                {"itemType": "event", "title": "", "date": "2026-01-03"},
                "not a calendar item",
            )
        }
    )

    result = get_target_events_service(client, 3, today=date(2026, 1, 1))

    assert result["status"] == "partial_success"
    assert result["availability"] == {"events": True}
    assert result["events"] == []
    assert result["warnings"] == [
        month_warning("invalid_provider_response", "2026-01")
    ]


def test_target_events_keeps_month_warnings_in_chronological_order() -> None:
    client = CalendarClient(
        {
            (2026, 1): RuntimeError("private error"),
            (2026, 2): calendar_response(
                {"itemType": "event", "title": "", "date": "2026-02-01"}
            ),
            (2026, 3): {"invalid": "payload"},
        }
    )

    result = get_target_events_service(client, 60, today=date(2026, 1, 15))

    assert result["status"] == "partial_success"
    assert [warning["month"] for warning in result["warnings"]] == [
        "2026-01",
        "2026-02",
        "2026-03",
    ]
    assert [warning["code"] for warning in result["warnings"]] == [
        "provider_unavailable",
        "invalid_provider_response",
        "invalid_provider_response",
    ]
    assert all(warning["provider"] == "calendar_events" for warning in result["warnings"])


def test_target_events_deduplicates_uuid_and_fallback_namespaces_independently() -> None:
    event_day = date(2026, 1, 2)
    client = CalendarClient(
        {
            (2026, 1): calendar_response(
                event_for_day(event_day, title="UUID first", shareableEventUuid="same"),
                event_for_day(event_day, title="UUID duplicate", shareableEventUuid="same"),
                event_for_day(
                    event_day,
                    title="Fallback duplicate",
                    location="Ghent",
                    eventTimeLocal={"startTimeHhMm": "09:00"},
                    completionTarget={"unitType": "distance", "value": 5000},
                ),
                event_for_day(
                    event_day,
                    title="Fallback duplicate",
                    location="Ghent",
                    eventTimeLocal={"startTimeHhMm": "09:00"},
                    completionTarget={"unitType": "distance", "value": 5000},
                ),
                event_for_day(
                    event_day,
                    title="same",
                    location=None,
                    eventTimeLocal=None,
                    completionTarget=None,
                ),
            )
        }
    )

    result = get_target_events_service(client, 2, today=date(2026, 1, 1))

    assert [event["title"] for event in result["events"]] == [
        "Fallback duplicate",
        "same",
        "UUID first",
    ]
    assert all("uuid" not in event for event in result["events"])


def test_target_events_keeps_first_uuid_occurrence_before_sorting() -> None:
    client = CalendarClient(
        {
            (2026, 1): calendar_response(
                event_for_day(
                    date(2026, 1, 3), title="First but later", shareableEventUuid="race"
                ),
                event_for_day(
                    date(2026, 1, 2), title="Second but sooner", shareableEventUuid="race"
                ),
            )
        }
    )

    result = get_target_events_service(client, 3, today=date(2026, 1, 1))

    assert result["events"] == [
        {
            "title": "First but later",
            "date": "2026-01-03",
            "days_until": 2,
            "is_race": None,
            "primary_event": None,
            "distance_km": None,
            "start_time_local": None,
            "time_zone": None,
            "location": None,
        }
    ]


def test_target_events_truncates_sorted_results_with_trailing_warning() -> None:
    event_day = date(2026, 1, 2)
    client = CalendarClient(
        {
            (2026, 1): calendar_response(
                *[
                    event_for_day(event_day, title=f"Event {index:03d}")
                    for index in range(100, -1, -1)
                ]
            )
        }
    )

    result = get_target_events_service(client, 2, today=date(2026, 1, 1))

    assert result["status"] == "success"
    assert result["events_truncated"] is True
    assert len(result["events"]) == MAX_EVENTS
    assert result["events"][0]["title"] == "Event 000"
    assert result["events"][-1]["title"] == "Event 099"
    assert result["warnings"] == [EVENT_WARNINGS["events_truncated"]]
    assert tuple(result["warnings"][0]) == ("provider", "code", "message")


def test_target_events_does_not_expose_private_provider_data_or_exception_details() -> None:
    secret_uuid = "private-uuid"
    client = CalendarClient(
        {
            (2026, 1): calendar_response(
                event_for_day(
                    date(2026, 1, 2),
                    title="Public event",
                    shareableEventUuid=secret_uuid,
                    authorization="Bearer token",
                    location="Antwerp",
                    coordinates={"lat": 51.2, "lon": 4.4},
                ),
                event_for_day(date(2026, 1, 3), title="x" * (MAX_TITLE_LENGTH + 1)),
            ),
            (2026, 2): RuntimeError("https://garmin.example/?token=secret"),
        }
    )

    result = get_target_events_service(client, 32, today=date(2026, 1, 2))

    assert result["status"] == "partial_success"
    assert result["availability"] == {"events": True}
    assert result["events"] == [
        {
            "title": "Public event",
            "date": "2026-01-02",
            "days_until": 0,
            "is_race": None,
            "primary_event": None,
            "distance_km": None,
            "start_time_local": None,
            "time_zone": None,
            "location": "Antwerp",
        }
    ]
    assert secret_uuid not in repr(result)
    assert "token" not in repr(result)
    assert "https://" not in repr(result)
    assert "authorization" not in repr(result)
    assert "coordinates" not in repr(result)
