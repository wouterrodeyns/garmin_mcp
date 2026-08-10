"""Contract tests for the stable AI activity summary service."""

from __future__ import annotations

from unittest.mock import ANY, Mock

import pytest

import garmin_mcp.ai_activity.service as service
from garmin_mcp.ai_activity.providers import ProviderResult
from garmin_mcp.ai_activity.service import analyze_activity_service


def raw_activity(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "activityId": 123,
        "activityName": "  Private morning run  ",
        "description": "  steady session  ",
        "activityTypeDTO": {"typeKey": "running"},
        "eventTypeDTO": {"typeKey": "race"},
        "summaryDTO": {
            "startTimeLocal": " 2026-02-14 08:30:00 ", "duration": 1801,
            "movingDuration": 1700, "elapsedDuration": 1900, "distance": 5000,
            "averageSpeed": 2.75, "maxSpeed": 4.25, "averageHR": 145,
            "maxHR": 170, "minHR": 91, "averagePower": 222, "maxPower": 333,
            "normalizedPower": 250, "averageRunCadence": 176, "maxRunCadence": 190,
            "elevationGain": 42.45, "elevationLoss": 20.04, "minElevation": -2.55,
            "maxElevation": 86.66, "calories": 450, "trainingEffect": 3.4,
            "anaerobicTrainingEffect": 1.2, "trainingEffectLabel": "PRODUCTIVE",
            "activityTrainingLoad": 71, "directWorkoutRpe": 7,
            "directWorkoutFeel": 75, "recoveryHeartRate": 32,
            "differenceBodyBattery": -8,
        },
        "metadataDTO": {"lapCount": 5, "hasSplits": True},
    }
    value.update(overrides)
    return value


def assert_envelope(result: dict[str, object]) -> None:
    assert list(result) == [
        "status", "error", "activity", "availability", "splits", "heart_rate_zones",
        "power_zones", "strength", "derived", "warnings",
    ]
    assert result["availability"] == {
        "activity": False, "splits": False, "heart_rate_zones": False,
        "power_zones": False, "strength": False,
    }
    assert result["splits"] is None
    assert result["heart_rate_zones"] is None
    assert result["power_zones"] is None
    assert result["strength"] is None
    assert result["derived"] == {
        "scope": None, "fastest_split_number": None, "fastest_pace": None,
        "slowest_split_number": None, "slowest_pace": None,
        "pace_range_seconds_per_km": None,
    }
    assert result["warnings"] == []


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock(return_value=ProviderResult(raw_activity()))
    monkeypatch.setattr(service, "get_activity", mock)
    return mock


@pytest.mark.parametrize(
    "activity_id", [True, False, 0, -1, 1.0, "", "  ", "+1", "-1", "1.0", "1e3", "1_000", "1,000", "١", [], {}]
)
def test_invalid_activity_ids_return_a_complete_error_envelope_without_a_provider_call(
    activity_id: object, reader: Mock
):
    result = analyze_activity_service(Mock(), activity_id)  # type: ignore[arg-type]

    assert_envelope(result)
    assert result["status"] == "error"
    assert result["error"] == {
        "code": "invalid_activity_id",
        "message": "activity_id must be a positive integer or decimal string.",
    }
    assert result["activity"] is None
    reader.assert_not_called()


def test_client_none_returns_bounded_error_without_a_provider_call(reader: Mock):
    result = analyze_activity_service(None, " 123 ")

    assert_envelope(result)
    assert result["error"] == {
        "code": "client_unavailable",
        "message": "Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.",
    }
    reader.assert_not_called()


def test_a_raised_base_provider_returns_a_bounded_unavailable_error(reader: Mock):
    reader.side_effect = RuntimeError("token=private@example.test")

    result = analyze_activity_service(Mock(), 123)

    assert_envelope(result)
    assert result["error"] == {
        "code": "activity_unavailable",
        "message": "Activity data is unavailable. Check the activity ID, re-run garmin-mcp-auth if the session expired, or retry later.",
    }
    assert "private" not in str(result)


def test_pathologically_large_decimal_input_is_invalid_without_a_provider_call(reader: Mock):
    result = analyze_activity_service(Mock(), "9" * 5_000)

    assert_envelope(result)
    assert result["error"] == {
        "code": "invalid_activity_id",
        "message": "activity_id must be a positive integer or decimal string.",
    }
    reader.assert_not_called()


@pytest.mark.parametrize(
    ("provided", "code", "message"),
    [
        (ProviderResult(None, failed=True), "activity_unavailable", "Activity data is unavailable. Check the activity ID, re-run garmin-mcp-auth if the session expired, or retry later."),
        (ProviderResult(None), "activity_not_found", "No activity data was found for the requested activity ID."),
        (ProviderResult({}), "activity_not_found", "No activity data was found for the requested activity ID."),
    ],
)
def test_base_provider_failure_and_missing_data_are_bounded(
    reader: Mock, provided: ProviderResult, code: str, message: str
):
    reader.return_value = provided
    result = analyze_activity_service(Mock(), 123)

    assert_envelope(result)
    assert result["error"] == {"code": code, "message": message}
    reader.assert_called_once_with(ANY, 123)


@pytest.mark.parametrize(
    "payload",
    ["secret raw payload", [], {"activityId": 0}, {"activityId": 123.5}, {"activityId": "124"}, {"activityId": 124}],
)
def test_malformed_or_mismatched_base_activity_is_bounded(reader: Mock, payload: object):
    reader.return_value = ProviderResult(payload)
    result = analyze_activity_service(Mock(), "123")

    assert_envelope(result)
    assert result["error"] == {
        "code": "invalid_activity_response", "message": "Activity data had an unexpected shape.",
    }
    assert "secret" not in str(result)


def test_pathologically_large_response_identifier_is_an_invalid_response(reader: Mock):
    reader.return_value = ProviderResult({"activityId": "9" * 5_000})

    result = analyze_activity_service(Mock(), 123)

    assert_envelope(result)
    assert result["error"] == {
        "code": "invalid_activity_response", "message": "Activity data had an unexpected shape.",
    }


def test_success_has_an_exact_stable_envelope_and_all_normalized_summary_fields(reader: Mock):
    client = Mock()
    result = analyze_activity_service(client, " 123 ")

    assert list(result) == [
        "status", "error", "activity", "availability", "splits", "heart_rate_zones",
        "power_zones", "strength", "derived", "warnings",
    ]
    assert result["status"] == "success"
    assert result["error"] is None
    assert result["availability"] == {
        "activity": True, "splits": False, "heart_rate_zones": False,
        "power_zones": False, "strength": False,
    }
    assert result["activity"] == {
        "id": 123, "name": "Private morning run", "description": "steady session",
        "sport": "running", "sport_family": "running", "event_type": "race",
        "start_time_local": "2026-02-14 08:30:00", "duration_minutes": 30.0,
        "moving_duration_minutes": 28.3, "elapsed_duration_minutes": 31.7,
        "distance_km": 5.0, "average_speed_kph": 9.9, "max_speed_kph": 15.3,
        "average_pace": "6:00/km", "heart_rate": {"average_bpm": 145, "max_bpm": 170, "min_bpm": 91},
        "power": {"average_watts": 222, "max_watts": 333, "normalized_watts": 250},
        "cadence": {"average_spm": 176, "max_spm": 190},
        "elevation": {"gain_meters": 42.5, "loss_meters": 20.0, "minimum_meters": -2.5, "maximum_meters": 86.7},
        "calories": 450, "training_effect": {"aerobic": 3.4, "anaerobic": 1.2, "label": "PRODUCTIVE", "load": 71},
        "workout_feedback": {"rpe": 7, "feel": 75},
        "recovery": {"heart_rate_bpm": 32, "body_battery_impact": -8}, "reported_lap_count": 5,
    }
    assert result["splits"] is None and result["heart_rate_zones"] is None
    assert result["power_zones"] is None and result["strength"] is None
    assert result["derived"] == {
        "scope": None, "fastest_split_number": None, "fastest_pace": None,
        "slowest_split_number": None, "slowest_pace": None, "pace_range_seconds_per_km": None,
    }
    assert result["warnings"] == []
    reader.assert_called_once_with(client, 123)


def test_fallback_types_missing_fields_invalid_physical_facts_and_text_bounds_are_sanitized(reader: Mock):
    data = raw_activity(
        activityTypeDTO={}, activityType={"typeKey": "walking"}, eventTypeDTO={}, eventType={"typeKey": "hike"},
        activityName="x" * 250, description="y" * 600,
        summaryDTO={
            "duration": float("inf"), "movingDuration": -1, "elapsedDuration": True,
            "distance": -1, "averageSpeed": float("nan"), "maxSpeed": -2,
            "averageHR": 0, "maxHR": -1, "minHR": True, "averagePower": 0,
            "maxPower": -1, "normalizedPower": True, "averageRunCadence": 0,
            "maxRunCadence": -1, "elevationGain": -4, "elevationLoss": 2.222,
            "minElevation": float("nan"), "maxElevation": -3.333, "calories": -1,
            "trainingEffect": float("nan"), "anaerobicTrainingEffect": True,
            "trainingEffectLabel": "z" * 101, "activityTrainingLoad": -1,
            "directWorkoutRpe": True, "directWorkoutFeel": "f" * 101,
            "recoveryHeartRate": 0, "differenceBodyBattery": -4.444,
        }, metadataDTO={"lapCount": 1.5},
    )
    reader.return_value = ProviderResult(data)
    result = analyze_activity_service(Mock(), 123)
    activity = result["activity"]

    assert result["status"] == "success"
    assert activity == {
        "id": 123, "name": "x" * 200, "description": "y" * 500,
        "sport": "walking", "sport_family": "walking", "event_type": ("hike"), "start_time_local": None,
        "duration_minutes": None, "moving_duration_minutes": None, "elapsed_duration_minutes": None,
        "distance_km": None, "average_speed_kph": None, "max_speed_kph": None, "average_pace": None,
        "heart_rate": {"average_bpm": None, "max_bpm": None, "min_bpm": None},
        "power": {"average_watts": None, "max_watts": None, "normalized_watts": None},
        "cadence": {"average_spm": None, "max_spm": None},
        "elevation": {"gain_meters": -4.0, "loss_meters": 2.2, "minimum_meters": None, "maximum_meters": -3.3},
        "calories": None, "training_effect": {"aerobic": None, "anaerobic": None, "label": "z" * 100, "load": None},
        "workout_feedback": {"rpe": None, "feel": "f" * 100},
        "recovery": {"heart_rate_bpm": None, "body_battery_impact": -4.444}, "reported_lap_count": None,
    }


@pytest.mark.parametrize(
    ("type_key", "family", "pace"),
    [
        ("running", "running", "6:00/km"), ("trail_running", "running", "6:00/km"),
        ("treadmill_running", "running", "6:00/km"), ("walking", "walking", "6:00/km"),
        ("treadmill_walking", "walking", "6:00/km"), ("cycling", "cycling", None),
        ("indoor_cycling", "cycling", None), ("road_biking", "cycling", None),
        ("mountain_biking", "cycling", None), ("gravel_cycling", "cycling", None),
        ("strength_training", "strength", None), ("yoga", "generic", None),
    ],
)
def test_exact_sport_sets_drive_family_and_pace(reader: Mock, type_key: str, family: str, pace: str | None):
    reader.return_value = ProviderResult(raw_activity(activityTypeDTO={"typeKey": type_key}))
    result = analyze_activity_service(Mock(), 123)

    assert result["activity"]["sport"] == type_key  # type: ignore[index]
    assert result["activity"]["sport_family"] == family  # type: ignore[index]
    assert result["activity"]["average_pace"] == pace  # type: ignore[index]


def test_pace_uses_raw_seconds_and_meters_before_display_rounding(reader: Mock):
    data = raw_activity(summaryDTO={"duration": 359.6, "distance": 999.0})
    reader.return_value = ProviderResult(data)
    result = analyze_activity_service(Mock(), 123)

    assert result["activity"]["duration_minutes"] == 6.0  # type: ignore[index]
    assert result["activity"]["distance_km"] == 1.0  # type: ignore[index]
    assert result["activity"]["average_pace"] == "6:00/km"  # type: ignore[index]


def test_huge_numeric_facts_are_treated_as_missing_without_raising(reader: Mock):
    reader.return_value = ProviderResult(raw_activity(summaryDTO={"averageHR": 10**5_000}))

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    assert result["activity"]["heart_rate"]["average_bpm"] is None  # type: ignore[index]
