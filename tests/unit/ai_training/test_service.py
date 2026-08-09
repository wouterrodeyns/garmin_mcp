"""Unit tests for the compact AI training-context service."""

from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest

from garmin_mcp.ai_training.providers import ProviderResult
from garmin_mcp.ai_training.service import get_training_context_service


TODAY = date(2026, 2, 14)


def activity(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "activityId": 987,
        "activityName": "Private morning run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2026-02-13 08:30:00",
        "duration": 1800,
        "distance": 5000,
    }
    item.update(overrides)
    return item


def schedule(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "scheduleDate": "2026-02-15",
        "scheduledWorkoutId": 22,
        "workoutId": 33,
        "workoutUuid": "uuid-44",
        "workoutName": "Intervals",
        "workoutType": "RUNNING",
        "associatedActivityId": None,
    }
    item.update(overrides)
    return item


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> dict[str, Mock]:
    import garmin_mcp.ai_training.service as service

    mocks = {
        "activities": Mock(return_value=ProviderResult(data=())),
        "scheduled": Mock(return_value=ProviderResult(data=())),
        "last_run": Mock(return_value=ProviderResult(data=None)),
        "daily_stats": Mock(return_value={}),
        "sleep": Mock(return_value={}),
        "hrv": Mock(return_value={}),
        "readiness": Mock(return_value={}),
        "training_status": Mock(return_value={}),
    }
    monkeypatch.setattr(service, "get_period_activities", mocks["activities"])
    monkeypatch.setattr(service, "get_scheduled_workouts", mocks["scheduled"])
    monkeypatch.setattr(service, "get_last_run", mocks["last_run"])
    monkeypatch.setattr(service, "get_daily_stats", mocks["daily_stats"])
    monkeypatch.setattr(service, "get_sleep", mocks["sleep"])
    monkeypatch.setattr(service, "get_hrv", mocks["hrv"])
    monkeypatch.setattr(service, "get_training_readiness", mocks["readiness"])
    monkeypatch.setattr(service, "get_training_status", mocks["training_status"])
    return mocks


def assert_stable_envelope(result: dict[str, object]) -> None:
    assert list(result) == [
        "status", "error", "period", "schedule_period", "availability", "training",
        "recent_activities", "recovery", "sleep", "hrv", "heart_rate", "fitness",
        "scheduled_workouts", "warnings",
    ]
    assert result["availability"] == {
        "activities": False, "last_run": False, "scheduled_workouts": False,
        "sleep": False, "hrv": False, "resting_heart_rate": False,
        "body_battery": False, "training_readiness": False, "recovery_time": False,
        "training_status": False, "training_load": False, "load_focus": False,
        "vo2max": False,
    }
    assert result["recovery"] == {
        "readiness_date": None, "training_readiness": None,
        "training_readiness_level": None, "recovery_hours": None,
        "body_battery": None, "body_battery_date": None,
    }
    assert result["sleep"] == {
        "date": None, "duration_hours": None, "score": None, "score_qualifier": None,
    }
    assert result["hrv"] == {
        "date": None, "last_night_avg_ms": None, "weekly_avg_ms": None, "status": None,
        "baseline_balanced_low_ms": None, "baseline_balanced_upper_ms": None,
    }
    assert result["heart_rate"] == {
        "date": None, "resting_hr": None, "resting_hr_7_day_avg": None,
    }
    assert result["fitness"] == {
        "training_status": None, "training_status_feedback": None, "fitness_trend": None,
        "acute_load": None, "chronic_load": None, "acute_chronic_ratio": None,
        "acwr_status": None, "vo2max_running": None, "vo2max_cycling": None,
        "load_focus": {"aerobic_low": None, "aerobic_high": None, "anaerobic": None, "feedback": None},
    }


@pytest.mark.parametrize("bad_days", [True, False, 0, -1, 91, 1.0, "14", None])
def test_invalid_days_returns_full_error_envelope_without_reads(bad_days: object, providers: dict[str, Mock]):
    result = get_training_context_service(Mock(), days=bad_days, today=TODAY)  # type: ignore[arg-type]

    assert_stable_envelope(result)
    assert result["status"] == "error"
    assert result["error"] == {"code": "invalid_days", "message": "days must be an integer from 1 through 90"}
    assert result["period"] == {"days": None, "start_date": None, "end_date": "2026-02-14"}
    assert result["schedule_period"] == {"start_date": "2026-02-14", "end_date": "2026-02-20"}
    assert result["training"] == {
        "activity_count": 0, "running_sessions": 0, "sessions_by_sport": {},
        "total_training_minutes": None, "running_distance_km": None, "last_run_date": None,
        "days_since_last_run": None, "activities_truncated": False,
    }
    assert result["recent_activities"] == []
    assert result["scheduled_workouts"] == []
    assert result["warnings"] == []
    assert all(mock.call_count == 0 for mock in providers.values())


@pytest.mark.parametrize(("days", "start"), [(1, "2026-02-14"), (90, "2025-11-17")])
def test_period_and_schedule_bounds_and_provider_order(days: int, start: str, providers: dict[str, Mock]):
    calls: list[str] = []
    for name in ("activities", "scheduled", "last_run"):
        providers[name].side_effect = lambda *args, _name=name, **kwargs: (calls.append(_name), ProviderResult(data=()))[1]

    result = get_training_context_service(Mock(), days=days, today=TODAY)

    assert result["period"] == {"days": days, "start_date": start, "end_date": "2026-02-14"}
    assert result["schedule_period"] == {"start_date": "2026-02-14", "end_date": "2026-02-20"}
    assert providers["activities"].call_args.args[1:] == (start, "2026-02-14", days)
    assert providers["scheduled"].call_args.args[1:] == ("2026-02-14", "2026-02-20")
    assert calls == ["activities", "scheduled", "last_run"]


def test_successful_empty_period_is_available_with_zero_aggregates(providers: dict[str, Mock]):
    result = get_training_context_service(Mock(), today=TODAY)

    assert result["status"] == "success"
    assert result["error"] is None
    assert result["availability"]["activities"] is True  # type: ignore[index]
    assert result["training"] == {
        "activity_count": 0, "running_sessions": 0, "sessions_by_sport": {},
        "total_training_minutes": 0.0, "running_distance_km": 0.0, "last_run_date": None,
        "days_since_last_run": None, "activities_truncated": False,
    }
    assert result["recent_activities"] == []


def test_unavailable_empty_period_keeps_unknown_aggregates_null(providers: dict[str, Mock]):
    providers["activities"].return_value = ProviderResult(data=(), failed=True)

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["availability"]["activities"] is False  # type: ignore[index]
    assert result["training"]["activity_count"] == 0  # type: ignore[index]
    assert result["training"]["total_training_minutes"] is None  # type: ignore[index]
    assert result["training"]["running_distance_km"] is None  # type: ignore[index]


def test_reduces_activities_from_raw_values_and_rounds_only_final_totals(providers: dict[str, Mock]):
    providers["activities"].return_value = ProviderResult(data=(
        activity(duration=1838, distance=1250, averageHR=146, maxHR=172, averageSpeed=3.3333),
        activity(duration=1838, distance=1250),
        activity(duration=1838, distance=1250),
    ))

    result = get_training_context_service(Mock(), today=TODAY)

    training = result["training"]
    assert training["activity_count"] == 3  # type: ignore[index]
    assert training["running_sessions"] == 3  # type: ignore[index]
    assert training["total_training_minutes"] == 91.9  # type: ignore[index]
    assert training["running_distance_km"] == 3.75  # type: ignore[index]
    reduced = result["recent_activities"][0]  # type: ignore[index]
    assert reduced == {
        "sport": "running", "date": "2026-02-13", "duration_minutes": 30.6,
        "distance_km": 1.25, "average_hr": 146, "max_hr": 172, "average_speed_kmh": 12.0,
    }
    assert "activityId" not in reduced and "name" not in reduced


@pytest.mark.parametrize("type_key", ["running", "trail_running", "treadmill_running"])
def test_all_running_type_keys_contribute_consistently(type_key: str, providers: dict[str, Mock]):
    providers["activities"].return_value = ProviderResult(data=(activity(activityType={"typeKey": type_key}),))
    providers["last_run"].return_value = ProviderResult(data=activity(activityType={"typeKey": type_key}))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["training"]["running_sessions"] == 1  # type: ignore[index]
    assert result["training"]["running_distance_km"] == 5.0  # type: ignore[index]
    assert result["training"]["last_run_date"] == "2026-02-13"  # type: ignore[index]
    assert result["training"]["days_since_last_run"] == 1  # type: ignore[index]


def test_running_distance_distinguishes_missing_values_from_confirmed_zero(providers: dict[str, Mock]):
    providers["activities"].return_value = ProviderResult(data=(activity(distance=None), activity(distance=0)))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["training"]["running_distance_km"] == 0.0  # type: ignore[index]
    providers["activities"].return_value = ProviderResult(data=(activity(distance=None),))
    assert get_training_context_service(Mock(), today=TODAY)["training"]["running_distance_km"] is None  # type: ignore[index]


@pytest.mark.parametrize(
    ("start_time", "expected_date", "expected_days", "available"),
    [
        ("2026-02-14 06:00:00", "2026-02-14", 0, True),
        ("2026-02-15 06:00:00", None, None, False),
        ("bad-date", None, None, False),
    ],
)
def test_last_run_uses_only_valid_nonfuture_running_dates(
    start_time: str, expected_date: str | None, expected_days: int | None, available: bool, providers: dict[str, Mock]
):
    providers["last_run"].return_value = ProviderResult(data=activity(startTimeLocal=start_time))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["availability"]["last_run"] is available  # type: ignore[index]
    assert result["training"]["last_run_date"] == expected_date  # type: ignore[index]
    assert result["training"]["days_since_last_run"] == expected_days  # type: ignore[index]


def test_last_run_without_match_is_unavailable_without_a_warning(providers: dict[str, Mock]):
    result = get_training_context_service(Mock(), today=TODAY)

    assert result["availability"]["last_run"] is False  # type: ignore[index]
    assert result["training"]["last_run_date"] is None  # type: ignore[index]
    assert result["warnings"] == []


def test_unknown_sports_are_retained_and_activities_are_sorted_and_capped_locally(providers: dict[str, Mock]):
    newest = activity(activityType={"typeKey": "paddling"}, startTimeLocal="2026-02-14 12:00:00")
    older = [activity(startTimeLocal=f"2026-01-{day:02d} 08:00:00") for day in range(1, 22)]
    providers["activities"].return_value = ProviderResult(data=tuple(older + [newest]))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["training"]["activity_count"] == 22  # type: ignore[index]
    assert result["training"]["sessions_by_sport"] == {"running": 21, "paddling": 1}  # type: ignore[index]
    assert len(result["recent_activities"]) == 20  # type: ignore[arg-type]
    assert result["recent_activities"][0]["sport"] == "paddling"  # type: ignore[index]
    assert result["recent_activities"][0]["date"] == "2026-02-14"  # type: ignore[index]


def test_recent_activities_sort_by_the_full_valid_local_start_time(providers: dict[str, Mock]):
    providers["activities"].return_value = ProviderResult(data=(
        activity(startTimeLocal="2026-02-13 07:00:00", activityType={"typeKey": "early"}),
        activity(startTimeLocal="2026-02-13 19:00:00", activityType={"typeKey": "late"}),
    ))

    result = get_training_context_service(Mock(), today=TODAY)

    assert [item["sport"] for item in result["recent_activities"]] == ["late", "early"]  # type: ignore[index]


def test_missing_or_invalid_duration_has_no_zero_coercion(providers: dict[str, Mock]):
    providers["activities"].return_value = ProviderResult(data=(
        activity(duration=None), activity(duration=True), activity(duration=float("inf")),
    ))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["training"]["total_training_minutes"] is None  # type: ignore[index]
    assert all("duration_minutes" not in item for item in result["recent_activities"])  # type: ignore[arg-type]


def test_scheduled_workouts_reduce_known_fields_and_completion(providers: dict[str, Mock]):
    providers["scheduled"].return_value = ProviderResult(data=(
        schedule(), schedule(scheduledWorkoutId=None, workoutId=None, workoutUuid=None, associatedActivityId=123),
    ))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["availability"]["scheduled_workouts"] is True  # type: ignore[index]
    assert result["scheduled_workouts"] == [
        {"date": "2026-02-15", "scheduled_workout_id": 22, "workout_id": 33,
         "workout_uuid": "uuid-44", "name": "Intervals", "sport": "RUNNING", "completed": False},
        {"date": "2026-02-15", "name": "Intervals", "sport": "RUNNING", "completed": True, "activity_id": 123},
    ]


def test_provider_warnings_and_activity_truncation_are_propagated(providers: dict[str, Mock]):
    warning = {"provider": "activities", "code": "activities_truncated", "message": "bounded"}
    providers["activities"].return_value = ProviderResult(data=(activity(),), failed=True, truncated=True, warnings=(warning,))
    providers["scheduled"].return_value = ProviderResult(data=(), warnings=({"provider": "scheduled_workouts", "code": "notice", "message": "x"},))
    providers["last_run"].return_value = ProviderResult(data=None, truncated=True, warnings=({"provider": "last_run", "code": "notice", "message": "y"},))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["training"]["activity_count"] == 1  # type: ignore[index]
    assert result["training"]["activities_truncated"] is True  # type: ignore[index]
    assert result["warnings"] == [warning, {"provider": "scheduled_workouts", "code": "notice", "message": "x"}, {"provider": "last_run", "code": "notice", "message": "y"}]


def test_invalid_scheduled_entries_are_redacted_and_reported(providers: dict[str, Mock]):
    providers["scheduled"].return_value = ProviderResult(data=(schedule(), "secret raw payload"))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["scheduled_workouts"] == [{"date": "2026-02-15", "scheduled_workout_id": 22, "workout_id": 33, "workout_uuid": "uuid-44", "name": "Intervals", "sport": "RUNNING", "completed": False}]
    assert result["warnings"] == [{
        "provider": "scheduled_workouts", "code": "invalid_provider_response",
        "message": "Scheduled workout response had an unexpected item.",
    }]
