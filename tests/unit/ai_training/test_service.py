"""Unit tests for the compact AI training-context service."""

from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest

from garmin_mcp.ai_training.providers import ProviderResult
from garmin_mcp.ai_training.service import AVAILABILITY_KEYS, get_training_context_service


TODAY = date(2026, 2, 14)


def test_availability_keys_are_the_stable_public_contract():
    assert AVAILABILITY_KEYS == (
        "activities", "last_run", "scheduled_workouts", "sleep", "hrv",
        "resting_heart_rate", "body_battery", "training_readiness", "recovery_time",
        "training_status", "training_load", "load_focus", "vo2max",
    )


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
    monkeypatch.setattr(service, "get_daily_stats", mocks["daily_stats"], raising=False)
    monkeypatch.setattr(service, "get_sleep", mocks["sleep"], raising=False)
    monkeypatch.setattr(service, "get_hrv", mocks["hrv"], raising=False)
    monkeypatch.setattr(service, "get_training_readiness", mocks["readiness"], raising=False)
    monkeypatch.setattr(service, "get_training_status", mocks["training_status"], raising=False)
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


def test_optional_sections_are_read_with_one_empty_overnight_fallback(providers: dict[str, Mock]):
    get_training_context_service(Mock(), today=TODAY)

    assert providers["daily_stats"].call_count == 1
    assert providers["training_status"].call_count == 1
    for name in ("sleep", "hrv", "readiness"):
        assert [call.args[1] for call in providers[name].call_args_list] == ["2026-02-14", "2026-02-13"]


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
        "distance_km": 1.25, "average_hr": 146, "max_hr": 172, "average_speed_kph": 12.0,
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


def test_retained_activities_remain_available_after_a_later_page_failure(providers: dict[str, Mock]):
    providers["activities"].return_value = ProviderResult(data=(activity(),), failed=True, truncated=True)

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["availability"]["activities"] is True  # type: ignore[index]
    assert result["training"]["activity_count"] == 1  # type: ignore[index]
    assert result["training"]["activities_truncated"] is True  # type: ignore[index]


def test_invalid_scheduled_entries_are_redacted_and_reported(providers: dict[str, Mock]):
    providers["scheduled"].return_value = ProviderResult(data=(schedule(), "secret raw payload"))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["scheduled_workouts"] == [{"date": "2026-02-15", "scheduled_workout_id": 22, "workout_id": 33, "workout_uuid": "uuid-44", "name": "Intervals", "sport": "RUNNING", "completed": False}]
    assert result["warnings"] == [{
        "provider": "scheduled_workouts", "code": "invalid_provider_response",
        "message": "Scheduled workout response had an unexpected item.",
    }]


def test_scheduled_workouts_redact_structured_field_values(providers: dict[str, Mock]):
    providers["scheduled"].return_value = ProviderResult(data=(schedule(
        scheduledWorkoutId={"secret": "scheduled"},
        workoutId=33,
        workoutUuid=["private"],
        workoutName={"secret": "name"},
        workoutType=17,
        associatedActivityId={"secret": "activity"},
    ),))

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["scheduled_workouts"] == [{"date": "2026-02-15", "workout_id": 33, "completed": False}]
    assert result["warnings"] == [{
        "provider": "scheduled_workouts", "code": "invalid_provider_response",
        "message": "Scheduled workout response had an unexpected item.",
    }]


def test_daily_stats_populates_metric_granular_heart_rate_and_body_battery(providers: dict[str, Mock]):
    providers["daily_stats"].return_value = {
        "calendarDate": "2026-02-14",
        "restingHeartRate": 49,
        "lastSevenDaysAvgRestingHeartRate": 51,
        "bodyBatteryMostRecentValue": 78,
    }

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["heart_rate"] == {
        "date": "2026-02-14", "resting_hr": 49, "resting_hr_7_day_avg": 51,
    }
    assert result["recovery"]["body_battery"] == 78  # type: ignore[index]
    assert result["recovery"]["body_battery_date"] == "2026-02-14"  # type: ignore[index]
    assert result["availability"]["resting_heart_rate"] is True  # type: ignore[index]
    assert result["availability"]["body_battery"] is True  # type: ignore[index]


def test_daily_stats_does_not_make_absent_metric_groups_available(providers: dict[str, Mock]):
    providers["daily_stats"].return_value = {"calendarDate": "2026-02-14", "restingHeartRate": 48}

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["availability"]["resting_heart_rate"] is True  # type: ignore[index]
    assert result["availability"]["body_battery"] is False  # type: ignore[index]
    assert result["recovery"]["body_battery"] is None  # type: ignore[index]


def test_sleep_normalizes_nested_score_and_falls_back_only_when_today_is_empty(providers: dict[str, Mock]):
    providers["sleep"].side_effect = [
        {"dailySleepDTO": {}},
        {"dailySleepDTO": {
            "calendarDate": "2026-02-13",
            "sleepTimeSeconds": 27360,
            "sleepScores": {"overall": {"value": 82, "qualifierKey": "GOOD"}},
        }},
    ]

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["sleep"] == {
        "date": "2026-02-13", "duration_hours": 7.6,
        "score": 82, "score_qualifier": "GOOD",
    }
    assert result["availability"]["sleep"] is True  # type: ignore[index]
    assert [call.args[1] for call in providers["sleep"].call_args_list] == ["2026-02-14", "2026-02-13"]


def test_nonempty_unknown_sleep_shape_does_not_trigger_fallback(providers: dict[str, Mock]):
    providers["sleep"].return_value = {"unexpected": "private payload"}

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["sleep"] == {
        "date": None, "duration_hours": None, "score": None, "score_qualifier": None,
    }
    assert result["availability"]["sleep"] is False  # type: ignore[index]
    providers["sleep"].assert_called_once()


@pytest.mark.parametrize(
    ("provider_name", "payload", "availability_key"),
    [
        ("sleep", {"dailySleepDTO": {"sleepTimeSeconds": "invalid"}}, "sleep"),
        ("hrv", {"hrvSummary": {"lastNightAvg": "invalid"}}, "hrv"),
        ("readiness", {"readinessScore": "invalid"}, "training_readiness"),
    ],
)
def test_malformed_nonempty_overnight_payload_never_triggers_fallback(
    provider_name: str, payload: dict[str, object], availability_key: str, providers: dict[str, Mock]
):
    providers[provider_name].return_value = payload

    result = get_training_context_service(Mock(), today=TODAY)

    providers[provider_name].assert_called_once()
    assert result["availability"][availability_key] is False  # type: ignore[index]


@pytest.mark.parametrize(
    ("provider_name", "empty_today", "valid_yesterday", "availability_key"),
    [
        (
            "sleep",
            {"dailySleepDTO": {"sleepTimeSeconds": None, "sleepScores": {}}},
            {"dailySleepDTO": {"sleepTimeSeconds": 25200}},
            "sleep",
        ),
        (
            "hrv",
            {"hrvSummary": {"lastNightAvg": None, "baseline": {}}},
            {"hrvSummary": {"lastNightAvg": 52}},
            "hrv",
        ),
        (
            "readiness",
            {"readinessScore": None},
            {"readinessScore": 71},
            "training_readiness",
        ),
    ],
)
def test_present_but_empty_overnight_metrics_fallback_once(
    provider_name: str,
    empty_today: dict[str, object],
    valid_yesterday: dict[str, object],
    availability_key: str,
    providers: dict[str, Mock],
):
    providers[provider_name].side_effect = [empty_today, valid_yesterday]

    result = get_training_context_service(Mock(), today=TODAY)

    assert [call.args[1] for call in providers[provider_name].call_args_list] == [
        "2026-02-14", "2026-02-13",
    ]
    assert result["availability"][availability_key] is True  # type: ignore[index]


def test_hrv_normalizes_summary_baseline_and_actual_fallback_date(providers: dict[str, Mock]):
    providers["hrv"].side_effect = [None, {"hrvSummary": {
        "calendarDate": "2026-02-13", "lastNightAvg": 54, "weeklyAvg": 52,
        "status": "BALANCED", "baseline": {"balancedLow": 46, "balancedUpper": 62},
    }}]

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["hrv"] == {
        "date": "2026-02-13", "last_night_avg_ms": 54, "weekly_avg_ms": 52,
        "status": "BALANCED", "baseline_balanced_low_ms": 46,
        "baseline_balanced_upper_ms": 62,
    }
    assert result["availability"]["hrv"] is True  # type: ignore[index]
    assert [call.args[1] for call in providers["hrv"].call_args_list] == ["2026-02-14", "2026-02-13"]


@pytest.mark.parametrize(
    ("payload", "expected_score", "expected_level"),
    [
        ({"readinessScore": 72, "readinessLevel": "HIGH"}, 72, "HIGH"),
        ({"score": 68, "level": "MEDIUM"}, 68, "MEDIUM"),
        ({"trainingReadinessLevel": 64, "trainingReadinessLevelKey": "GOOD"}, 64, "GOOD"),
    ],
)
def test_training_readiness_supports_all_verified_alias_pairs(
    payload: dict[str, object], expected_score: int, expected_level: str, providers: dict[str, Mock]
):
    providers["readiness"].return_value = {"calendarDate": "2026-02-14", **payload}

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["recovery"]["readiness_date"] == "2026-02-14"  # type: ignore[index]
    assert result["recovery"]["training_readiness"] == expected_score  # type: ignore[index]
    assert result["recovery"]["training_readiness_level"] == expected_level  # type: ignore[index]
    assert result["availability"]["training_readiness"] is True  # type: ignore[index]


def test_readiness_recovery_minutes_are_converted_only_when_present(providers: dict[str, Mock]):
    providers["readiness"].side_effect = [[], {"recoveryTime": 270, "score": 70}]

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["recovery"]["readiness_date"] == "2026-02-13"  # type: ignore[index]
    assert result["recovery"]["recovery_hours"] == 4.5  # type: ignore[index]
    assert result["availability"]["recovery_time"] is True  # type: ignore[index]
    assert [call.args[1] for call in providers["readiness"].call_args_list] == ["2026-02-14", "2026-02-13"]


def test_invalid_recovery_time_is_not_coerced_or_made_available(providers: dict[str, Mock]):
    providers["readiness"].return_value = {"readinessScore": 70, "recoveryTime": None}

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["recovery"]["recovery_hours"] is None  # type: ignore[index]
    assert result["availability"]["recovery_time"] is False  # type: ignore[index]


def test_overnight_provider_exception_never_triggers_previous_day_fallback(providers: dict[str, Mock]):
    providers["sleep"].side_effect = RuntimeError("unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        get_training_context_service(Mock(), today=TODAY)

    providers["sleep"].assert_called_once()


def test_training_status_selects_primary_devices_independently_and_uses_exact_paths(providers: dict[str, Mock]):
    providers["training_status"].return_value = {
        "primaryTrainingDevice": "primary",
        "mostRecentTrainingStatus": {"latestTrainingStatusData": {
            "secondary": {"trainingStatus": "MAINTAINING"},
            "primary": {
                "trainingStatus": "PRODUCTIVE",
                "trainingStatusFeedbackPhrase": "KEEP_GOING",
                "fitnessTrend": "INCREASING",
                "acuteTrainingLoadDTO": {
                    "dailyTrainingLoadAcute": 250,
                    "dailyTrainingLoadChronic": 217,
                    "dailyAcuteChronicWorkloadRatio": 1.15,
                    "acwrStatus": "OPTIMAL",
                },
            },
        }},
        "mostRecentTrainingLoadBalance": {"metricsTrainingLoadBalanceDTOMap": {
            "other": {"monthlyLoadAerobicLow": 1},
            "primary": {
                "monthlyLoadAerobicLow": 320,
                "monthlyLoadAerobicHigh": 190,
                "monthlyLoadAnaerobic": 80,
                "trainingBalanceFeedbackPhrase": "BALANCED",
            },
        }},
        "mostRecentVO2Max": {
            "generic": {"vo2MaxValue": 51},
            "cycling": {"vo2MaxValue": 55},
        },
    }

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["fitness"] == {
        "training_status": "PRODUCTIVE", "training_status_feedback": "KEEP_GOING",
        "fitness_trend": "INCREASING", "acute_load": 250, "chronic_load": 217,
        "acute_chronic_ratio": 1.15, "acwr_status": "OPTIMAL",
        "vo2max_running": 51, "vo2max_cycling": 55,
        "load_focus": {"aerobic_low": 320, "aerobic_high": 190, "anaerobic": 80, "feedback": "BALANCED"},
    }
    for key in ("training_status", "training_load", "load_focus", "vo2max"):
        assert result["availability"][key] is True  # type: ignore[index]


def test_training_status_never_derives_acwr_from_acute_and_chronic_load(providers: dict[str, Mock]):
    providers["training_status"].return_value = {
        "mostRecentTrainingStatus": {"latestTrainingStatusData": {"device": {
            "acuteTrainingLoadDTO": {"dailyTrainingLoadAcute": 250, "dailyTrainingLoadChronic": 217},
        }}},
    }

    result = get_training_context_service(Mock(), today=TODAY)

    assert result["fitness"]["acute_load"] == 250  # type: ignore[index]
    assert result["fitness"]["chronic_load"] == 217  # type: ignore[index]
    assert result["fitness"]["acute_chronic_ratio"] is None  # type: ignore[index]
    assert result["fitness"]["acwr_status"] is None  # type: ignore[index]
    assert result["availability"]["training_load"] is True  # type: ignore[index]
