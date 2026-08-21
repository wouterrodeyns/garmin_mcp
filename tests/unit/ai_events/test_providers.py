"""Contract tests for the bounded calendar provider seam."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from garmin_mcp.ai_events.providers import CalendarMonthResult, get_calendar_month


class CalendarClient:
    """Client double exposing only the pinned calendar operation."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[int, int]] = []

    def get_scheduled_workouts(self, year: int, month: int) -> object:
        self.calls.append((year, month))
        return self.response

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected client attribute: {name}")


def test_calendar_provider_uses_exact_pinned_method_and_month_key() -> None:
    client = CalendarClient({"calendarItems": [{"workoutId": 7}]})

    result = get_calendar_month(client, 2026, 10)

    assert client.calls == [(2026, 10)]
    assert result == CalendarMonthResult("2026-10", ({"workoutId": 7},))


def test_calendar_month_result_is_frozen_with_exact_public_fields() -> None:
    result = CalendarMonthResult("2026-10")

    assert result.data == ()
    assert result.failed is False
    assert result.invalid is False
    assert set(result.__dataclass_fields__) == {"month", "data", "failed", "invalid"}
    with pytest.raises(FrozenInstanceError):
        result.failed = True


@pytest.mark.parametrize("response", [None, {}, {"calendarItems": None}])
def test_calendar_provider_accepts_supported_empty_roots(response: object) -> None:
    result = get_calendar_month(CalendarClient(response), 2026, 10)

    assert result == CalendarMonthResult("2026-10")


@pytest.mark.parametrize(
    "response",
    [
        False,
        0,
        "",
        [],
        {"items": []},
        {"calendarItems": {}},
        {"calendarItems": "secret"},
    ],
)
def test_calendar_provider_rejects_invalid_roots_without_exposing_response(
    response: object,
) -> None:
    result = get_calendar_month(CalendarClient(response), 2026, 10)

    assert result == CalendarMonthResult("2026-10", invalid=True)
    assert "secret" not in repr(result)


def test_calendar_provider_snapshots_valid_items_as_tuple_without_mutating_response() -> None:
    items = [{"workoutId": 7}]
    response = {"calendarItems": items}

    result = get_calendar_month(CalendarClient(response), 2026, 10)
    items.append({"workoutId": 8})

    assert result.data == ({"workoutId": 7},)
    assert response == {"calendarItems": [{"workoutId": 7}, {"workoutId": 8}]}
    assert type(result.data) is tuple


def test_calendar_provider_sanitizes_provider_exception() -> None:
    secret = "https://private.example/request?token=super-secret"

    class FailingClient(CalendarClient):
        def get_scheduled_workouts(self, year: int, month: int) -> object:
            raise RuntimeError(secret)

    result = get_calendar_month(FailingClient(None), 2026, 10)

    assert result == CalendarMonthResult("2026-10", failed=True)
    assert secret not in repr(result)
    assert "private.example" not in str(result)
