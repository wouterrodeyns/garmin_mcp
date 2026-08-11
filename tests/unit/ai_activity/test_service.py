"""Contract tests for the stable AI activity summary service."""

from __future__ import annotations

import json
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
            "activityTrainingLoad": 71, "directWorkoutRpe": 70,
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
    monkeypatch.setattr(service, "get_splits", Mock(return_value=ProviderResult(None)), raising=False)
    monkeypatch.setattr(service, "get_heart_rate_zones", Mock(return_value=ProviderResult(None)), raising=False)
    monkeypatch.setattr(service, "get_power_zones", Mock(return_value=ProviderResult(None)), raising=False)
    monkeypatch.setattr(service, "get_strength", Mock(return_value=ProviderResult(None)), raising=False)
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
        "workout_feedback": {"rpe": 7.0, "feel": 75},
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


@pytest.mark.parametrize(
    ("raw_rpe", "expected"),
    [(70, 7.0), (75, 7.5), (0, 0.0)],
)
def test_direct_workout_rpe_uses_garmins_raw_x10_scale(reader: Mock, raw_rpe: int, expected: float):
    reader.return_value = ProviderResult(raw_activity(summaryDTO={"directWorkoutRpe": raw_rpe}))

    result = analyze_activity_service(Mock(), 123)

    assert result["activity"]["workout_feedback"]["rpe"] == expected


@pytest.mark.parametrize(
    "raw_rpe",
    [-1, 101, True, float("nan"), float("inf"), pytest.param(10 ** 5000, id="oversized")],
)
def test_invalid_or_unsafe_raw_rpe_is_null_and_json_safe(reader: Mock, raw_rpe: object):
    reader.return_value = ProviderResult(raw_activity(summaryDTO={"directWorkoutRpe": raw_rpe}))

    result = analyze_activity_service(Mock(), 123)

    assert result["activity"]["workout_feedback"]["rpe"] is None
    json.dumps(result, allow_nan=False)


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


def test_overflowed_derived_speed_and_pace_are_null_in_a_stable_success_response(reader: Mock):
    reader.return_value = ProviderResult(raw_activity(summaryDTO={
        "duration": 1e308,
        "movingDuration": 1e308,
        "elapsedDuration": 1e308,
        "distance": 1.0,
        "averageSpeed": 1e308,
        "maxSpeed": 1e308,
    }))

    result = analyze_activity_service(Mock(), 123)
    activity = result["activity"]

    assert result["status"] == "success"
    assert activity["duration_minutes"] == 1.6666666666666666e306  # type: ignore[index]
    assert activity["moving_duration_minutes"] == 1.6666666666666666e306  # type: ignore[index]
    assert activity["elapsed_duration_minutes"] == 1.6666666666666666e306  # type: ignore[index]
    assert activity["average_speed_kph"] is None  # type: ignore[index]
    assert activity["max_speed_kph"] is None  # type: ignore[index]
    assert activity["average_pace"] is None  # type: ignore[index]


def test_underflowed_pace_divisor_and_large_kilometers_remain_finite(reader: Mock):
    reader.return_value = ProviderResult(raw_activity(summaryDTO={
        "duration": 1.0,
        "distance": 5e-324,
    }))

    result = analyze_activity_service(Mock(), 123)
    activity = result["activity"]

    assert result["status"] == "success"
    assert activity["distance_km"] == 0.0  # type: ignore[index]
    assert activity["average_pace"] is None  # type: ignore[index]


def split(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "lapIndex": 1,
        "startTimeGMT": "2026-02-14T08:30:00Z",
        "duration": 360,
        "movingDuration": 350,
        "elapsedDuration": 370,
        "distance": 1000,
        "averageSpeed": 2.5,
        "maxSpeed": 3.0,
        "averageHR": 145,
        "maxHR": 160,
        "averageRunCadence": 176,
        "averagePower": 222,
        "calories": 80,
        "elevationGain": 4.44,
        "elevationLoss": 2.22,
        "intensityType": "  ACTIVE  ",
    }
    value.update(overrides)
    return value


def split_reader(monkeypatch: pytest.MonkeyPatch, data: object = None) -> Mock:
    mock = Mock(return_value=ProviderResult(data))
    monkeypatch.setattr(service, "get_splits", mock, raising=False)
    return mock


@pytest.mark.parametrize("type_key", ["running", "walking", "cycling"])
def test_eligible_sports_fetch_splits_after_the_base_activity(
    reader: Mock, monkeypatch: pytest.MonkeyPatch, type_key: str
):
    reader.return_value = ProviderResult(raw_activity(activityTypeDTO={"typeKey": type_key}))
    splits = split_reader(monkeypatch, {"lapDTOs": []})
    client = Mock()

    result = analyze_activity_service(client, 123)

    assert result["status"] == "success"
    reader.assert_called_once_with(client, 123)
    splits.assert_called_once_with(client, 123)


@pytest.mark.parametrize("type_key", ["yoga", "strength_training"])
def test_generic_and_strength_activities_never_fetch_splits(
    reader: Mock, monkeypatch: pytest.MonkeyPatch, type_key: str
):
    reader.return_value = ProviderResult(raw_activity(activityTypeDTO={"typeKey": type_key}))
    splits = split_reader(monkeypatch, {"lapDTOs": []})

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    splits.assert_not_called()


@pytest.mark.parametrize("has_splits", [None, "false", 0])
def test_only_literal_false_suppresses_an_eligible_split_fetch(
    reader: Mock, monkeypatch: pytest.MonkeyPatch, has_splits: object
):
    reader.return_value = ProviderResult(raw_activity(metadataDTO={"hasSplits": has_splits}))
    splits = split_reader(monkeypatch, {"lapDTOs": []})

    analyze_activity_service(Mock(), 123)

    splits.assert_called_once()


@pytest.mark.parametrize(
    ("metadata", "metadata_is_absent"),
    [(None, True), (None, False), ({"hasSplits": None}, False)],
    ids=["absent", "null_metadata", "null_signal"],
)
def test_absent_or_null_split_metadata_does_not_suppress_an_eligible_split_fetch(
    reader: Mock, monkeypatch: pytest.MonkeyPatch, metadata: object, metadata_is_absent: bool
):
    data = raw_activity()
    if metadata_is_absent:
        data.pop("metadataDTO")
    else:
        data["metadataDTO"] = metadata
    reader.return_value = ProviderResult(data)
    splits = split_reader(monkeypatch, {"lapDTOs": []})

    analyze_activity_service(Mock(), 123)

    splits.assert_called_once()


def test_literal_false_suppresses_an_eligible_split_fetch(reader: Mock, monkeypatch: pytest.MonkeyPatch):
    reader.return_value = ProviderResult(raw_activity(metadataDTO={"hasSplits": False}))
    splits = split_reader(monkeypatch, {"lapDTOs": []})

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    splits.assert_not_called()


def test_splits_have_exact_normalized_fields_and_raw_pace_comparisons(
    reader: Mock, monkeypatch: pytest.MonkeyPatch
):
    splits = split_reader(monkeypatch, {"lapDTOs": [split(duration=359.6, distance=999.0)]})

    result = analyze_activity_service(Mock(), 123)

    splits.assert_called_once()
    assert result["availability"]["splits"] is True
    assert result["splits"] == {
        "total_count": 1,
        "returned_count": 1,
        "truncated": False,
        "items": [{
            "lap_number": 1, "start_time": "2026-02-14T08:30:00Z",
            "duration_minutes": 6.0, "moving_duration_minutes": 5.8,
            "elapsed_duration_minutes": 6.2, "distance_km": 1.0,
            "average_speed_kph": 9.0, "max_speed_kph": 10.8,
            "pace": "6:00/km", "average_hr_bpm": 145,
            "max_hr_bpm": 160, "average_cadence_spm": 176,
            "average_power_watts": 222, "calories": 80,
            "elevation_gain_meters": 4.4, "elevation_loss_meters": 2.2,
            "intensity_type": "ACTIVE",
        }],
    }
    assert result["derived"] == {
        "scope": "all_returned_splits", "fastest_split_number": 1,
        "fastest_pace": "6:00/km", "slowest_split_number": 1,
        "slowest_pace": "6:00/km", "pace_range_seconds_per_km": 0,
    }


@pytest.mark.parametrize("payload", [None, {}])
def test_missing_or_empty_split_root_is_unavailable_without_a_warning(
    reader: Mock, monkeypatch: pytest.MonkeyPatch, payload: object
):
    split_reader(monkeypatch, payload)

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    assert result["availability"]["splits"] is False
    assert result["splits"] is None
    assert result["warnings"] == []


def test_empty_lap_list_is_an_available_empty_split_section(reader: Mock, monkeypatch: pytest.MonkeyPatch):
    split_reader(monkeypatch, {"lapDTOs": []})

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    assert result["availability"]["splits"] is True
    assert result["splits"] == {"total_count": 0, "returned_count": 0, "truncated": False, "items": []}


@pytest.mark.parametrize("payload", [[], {"other": []}, {"lapDTOs": "not-a-list"}])
def test_unexpected_nonempty_split_roots_are_bounded_partial_warnings(
    reader: Mock, monkeypatch: pytest.MonkeyPatch, payload: object
):
    split_reader(monkeypatch, payload)

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "partial_success"
    assert result["availability"]["splits"] is False
    assert result["splits"] is None
    assert result["warnings"] == [{
        "provider": "splits", "code": "invalid_provider_response",
        "message": "Activity splits response had an unexpected shape.",
    }]


def test_invalid_laps_are_dropped_once_without_affecting_valid_source_order(
    reader: Mock, monkeypatch: pytest.MonkeyPatch
):
    split_reader(monkeypatch, {"lapDTOs": [None, {}, split(lapIndex=4), [], split(lapIndex=2)]})

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "partial_success"
    assert result["splits"]["total_count"] == 5  # type: ignore[index]
    assert [item["lap_number"] for item in result["splits"]["items"]] == [4, 2]  # type: ignore[index]
    assert result["warnings"] == [{
        "provider": "splits", "code": "invalid_provider_response",
        "message": "Activity splits response had an unexpected shape.",
    }]


def test_split_pace_ties_keep_first_source_entry_and_lap_number_falls_back_to_position(
    reader: Mock, monkeypatch: pytest.MonkeyPatch
):
    split_reader(monkeypatch, {"lapDTOs": [split(lapIndex=0), split(lapIndex=9)]})

    result = analyze_activity_service(Mock(), 123)

    assert result["derived"] == {
        "scope": "all_returned_splits", "fastest_split_number": 1,
        "fastest_pace": "6:00/km", "slowest_split_number": 1,
        "slowest_pace": "6:00/km", "pace_range_seconds_per_km": 0,
    }


def test_split_extrema_and_range_use_raw_pace_when_displayed_paces_match(
    reader: Mock, monkeypatch: pytest.MonkeyPatch
):
    split_reader(monkeypatch, {"lapDTOs": [
        split(lapIndex=1, duration=359.6, distance=1000),
        split(lapIndex=2, duration=360.4, distance=1000),
    ]})

    result = analyze_activity_service(Mock(), 123)

    assert [item["pace"] for item in result["splits"]["items"]] == ["6:00/km", "6:00/km"]  # type: ignore[index]
    assert result["derived"] == {
        "scope": "all_returned_splits", "fastest_split_number": 1,
        "fastest_pace": "6:00/km", "slowest_split_number": 2,
        "slowest_pace": "6:00/km", "pace_range_seconds_per_km": 1,
    }


@pytest.mark.parametrize("count", [0, 1, 100])
def test_up_to_one_hundred_splits_are_not_truncated(
    reader: Mock, monkeypatch: pytest.MonkeyPatch, count: int
):
    split_reader(monkeypatch, {"lapDTOs": [split(lapIndex=index + 1) for index in range(count)]})

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    assert result["splits"]["returned_count"] == count  # type: ignore[index]
    assert result["splits"]["truncated"] is False  # type: ignore[index]


def test_more_than_one_hundred_splits_are_capped_and_disable_pace_comparisons(
    reader: Mock, monkeypatch: pytest.MonkeyPatch
):
    split_reader(monkeypatch, {"lapDTOs": [split(lapIndex=index + 1) for index in range(101)]})

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    assert result["splits"]["total_count"] == 101  # type: ignore[index]
    assert result["splits"]["returned_count"] == 100  # type: ignore[index]
    assert result["splits"]["truncated"] is True  # type: ignore[index]
    assert result["splits"]["items"][-1]["lap_number"] == 100  # type: ignore[index]
    assert result["derived"] == {
        "scope": None, "fastest_split_number": None, "fastest_pace": None,
        "slowest_split_number": None, "slowest_pace": None, "pace_range_seconds_per_km": None,
    }
    assert result["warnings"] == [{
        "provider": "splits", "code": "splits_truncated",
        "message": "Activity splits were limited to 100 laps; split comparisons are unavailable.",
    }]


def test_invalid_entries_and_truncation_have_stable_warning_order(reader: Mock, monkeypatch: pytest.MonkeyPatch):
    split_reader(monkeypatch, {"lapDTOs": [None] + [split(lapIndex=index + 1) for index in range(100)]})

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "partial_success"
    assert [warning["code"] for warning in result["warnings"]] == ["splits_truncated", "invalid_provider_response"]


def test_cycling_splits_do_not_produce_pace_comparisons(reader: Mock, monkeypatch: pytest.MonkeyPatch):
    reader.return_value = ProviderResult(raw_activity(activityTypeDTO={"typeKey": "cycling"}))
    split_reader(monkeypatch, {"lapDTOs": [split()]})

    result = analyze_activity_service(Mock(), 123)

    assert result["derived"]["scope"] is None


def test_overflow_and_subnormal_split_facts_are_safely_null(reader: Mock, monkeypatch: pytest.MonkeyPatch):
    split_reader(monkeypatch, {"lapDTOs": [split(
        duration=1e308, movingDuration=1e308, elapsedDuration=1e308,
        distance=5e-324, averageSpeed=1e308, maxSpeed=1e308,
    )]})

    result = analyze_activity_service(Mock(), 123)
    item = result["splits"]["items"][0]  # type: ignore[index]

    assert item["duration_minutes"] == 1.6666666666666666e306
    assert item["distance_km"] == 0.0
    assert item["average_speed_kph"] is None and item["max_speed_kph"] is None
    assert item["pace"] is None


def test_valid_base_then_split_then_hr_zone_is_the_provider_call_sequence(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, int]] = []

    def base(_client: object, activity_id: int) -> ProviderResult:
        calls.append(("activity", activity_id))
        return ProviderResult(raw_activity())

    def splits(_client: object, activity_id: int) -> ProviderResult:
        calls.append(("splits", activity_id))
        return ProviderResult({"lapDTOs": []})

    def heart_rate_zones(_client: object, activity_id: int) -> ProviderResult:
        calls.append(("heart_rate_zones", activity_id))
        return ProviderResult(None)

    monkeypatch.setattr(service, "get_activity", base)
    monkeypatch.setattr(service, "get_splits", splits)
    monkeypatch.setattr(service, "get_heart_rate_zones", heart_rate_zones, raising=False)

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    assert calls == [("activity", 123), ("splits", 123), ("heart_rate_zones", 123)]


def test_base_error_never_attempts_splits(reader: Mock, monkeypatch: pytest.MonkeyPatch):
    reader.return_value = ProviderResult(None, failed=True)
    splits = split_reader(monkeypatch, {"lapDTOs": []})

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "error"
    splits.assert_not_called()


def test_failed_split_provider_is_a_sanitized_partial_warning(reader: Mock, monkeypatch: pytest.MonkeyPatch):
    def fail(_client: object, _activity_id: int) -> ProviderResult:
        raise RuntimeError("token=secret@example.test")

    monkeypatch.setattr(service, "get_splits", fail)

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "partial_success"
    assert result["warnings"] == [{
        "provider": "splits", "code": "provider_unavailable",
        "message": "Activity splits are unavailable.",
    }]
    assert "secret" not in str(result)


def test_oversized_native_integer_fields_are_null_and_the_response_stays_json_serializable(
    reader: Mock, monkeypatch: pytest.MonkeyPatch
):
    oversized = 10**5_000
    reader.return_value = ProviderResult(raw_activity(metadataDTO={"lapCount": oversized, "hasSplits": True}))
    split_reader(monkeypatch, {"lapDTOs": [split(lapIndex=oversized)]})

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    assert result["availability"]["activity"] is True
    assert result["availability"]["splits"] is True
    assert result["activity"]["reported_lap_count"] is None  # type: ignore[index]
    assert result["splits"]["items"][0]["lap_number"] is None  # type: ignore[index]
    assert result["warnings"] == []
    json.dumps(result, allow_nan=False)

    invalid_id_result = analyze_activity_service(Mock(), oversized)

    assert invalid_id_result["status"] == "error"
    assert invalid_id_result["error"]["code"] == "invalid_activity_id"  # type: ignore[index]
    json.dumps(invalid_id_result, allow_nan=False)


def test_running_hr_signal_fetches_hr_zones_after_splits(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def base(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("activity")
        return ProviderResult(raw_activity())

    def splits(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("splits")
        return ProviderResult({"lapDTOs": []})

    def zones(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("heart_rate_zones")
        return ProviderResult([])

    monkeypatch.setattr(service, "get_activity", base)
    monkeypatch.setattr(service, "get_splits", splits)
    monkeypatch.setattr(service, "get_heart_rate_zones", zones, raising=False)
    monkeypatch.setattr(service, "get_power_zones", Mock(return_value=ProviderResult(None)), raising=False)
    monkeypatch.setattr(service, "get_strength", Mock(return_value=ProviderResult(None)), raising=False)

    result = analyze_activity_service(Mock(), 123)

    assert calls == ["activity", "splits", "heart_rate_zones"]
    assert result["availability"]["heart_rate_zones"] is True
    assert result["heart_rate_zones"] == {"items": []}


def optional_readers(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], *, hr: object = None,
    power: object = None, strength: object = None,
) -> None:
    def optional(name: str, data: object):
        def read(_client: object, _activity_id: int) -> ProviderResult:
            calls.append(name)
            return ProviderResult(data)
        return read

    monkeypatch.setattr(service, "get_heart_rate_zones", optional("heart_rate_zones", hr), raising=False)
    monkeypatch.setattr(service, "get_power_zones", optional("power_zones", power), raising=False)
    monkeypatch.setattr(service, "get_strength", optional("strength", strength), raising=False)


@pytest.mark.parametrize(
    ("type_key", "summary", "expected"),
    [
        ("running", {"averageHR": 1}, ["activity", "splits", "heart_rate_zones"]),
        ("trail_running", {"maxHR": 1}, ["activity", "splits", "heart_rate_zones"]),
        ("treadmill_running", {"minHR": 1}, ["activity", "splits", "heart_rate_zones"]),
        ("walking", {"averageHR": 1}, ["activity", "splits", "heart_rate_zones"]),
        ("treadmill_walking", {"maxHR": 1}, ["activity", "splits", "heart_rate_zones"]),
        ("cycling", {"averageHR": 1, "averagePower": 1}, ["activity", "splits", "heart_rate_zones", "power_zones"]),
        ("indoor_cycling", {"averagePower": 1}, ["activity", "splits", "power_zones"]),
        ("road_biking", {"maxPower": 1}, ["activity", "splits", "power_zones"]),
        ("mountain_biking", {"normalizedPower": 1}, ["activity", "splits", "power_zones"]),
        ("gravel_cycling", {"averageHR": 1}, ["activity", "splits", "heart_rate_zones"]),
        ("strength_training", {"averageHR": 1, "averagePower": 1}, ["activity", "strength"]),
        ("yoga", {"averageHR": 1, "averagePower": 1}, ["activity"]),
    ],
)
def test_sport_keys_have_exact_optional_provider_budgets_and_order(
    monkeypatch: pytest.MonkeyPatch, type_key: str, summary: dict[str, object], expected: list[str],
):
    calls: list[str] = []

    def base(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("activity")
        return ProviderResult(raw_activity(activityTypeDTO={"typeKey": type_key}, summaryDTO=summary))

    def splits(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("splits")
        return ProviderResult({"lapDTOs": []})

    monkeypatch.setattr(service, "get_activity", base)
    monkeypatch.setattr(service, "get_splits", splits)
    optional_readers(monkeypatch, calls, hr=None, power=None, strength=None)

    result = analyze_activity_service(Mock(), 123)

    assert calls == expected
    assert result["status"] == "success"


@pytest.mark.parametrize("signal", [0, -1, True, False, float("nan"), float("inf"), "1", None])
def test_invalid_or_nonpositive_summary_signals_skip_optional_zone_providers(
    monkeypatch: pytest.MonkeyPatch, signal: object,
):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "cycling"},
        summaryDTO={"averageHR": signal, "maxHR": signal, "minHR": signal,
                    "averagePower": signal, "maxPower": signal, "normalizedPower": signal},
    )))
    monkeypatch.setattr(service, "get_splits", lambda _c, _i: ProviderResult({"lapDTOs": []}))
    optional_readers(monkeypatch, calls)

    result = analyze_activity_service(Mock(), 123)

    assert calls == []
    assert result["availability"]["heart_rate_zones"] is False
    assert result["availability"]["power_zones"] is False
    assert result["warnings"] == []


@pytest.mark.parametrize(
    ("type_key", "summary", "expected_calls"),
    [
        ("running", {"averageHR": 0.5}, ["activity", "splits", "heart_rate_zones"]),
        ("cycling", {"averageHR": 0.5, "averagePower": 0.5}, [
            "activity", "splits", "heart_rate_zones", "power_zones",
        ]),
    ],
)
def test_subunit_positive_summary_signals_fetch_eligible_zone_providers(
    monkeypatch: pytest.MonkeyPatch, type_key: str, summary: dict[str, object], expected_calls: list[str],
):
    calls: list[str] = []

    def base(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("activity")
        return ProviderResult(raw_activity(activityTypeDTO={"typeKey": type_key}, summaryDTO=summary))

    def splits(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("splits")
        return ProviderResult({"lapDTOs": []})

    monkeypatch.setattr(service, "get_activity", base)
    monkeypatch.setattr(service, "get_splits", splits)
    optional_readers(monkeypatch, calls)

    analyze_activity_service(Mock(), 123)

    assert calls == expected_calls


@pytest.mark.parametrize("root", [[], {"zones": []}])
def test_zone_empty_roots_are_available_empty_sections(monkeypatch: pytest.MonkeyPatch, root: object):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "cycling"}, summaryDTO={"averageHR": 1, "averagePower": 1},
    )))
    monkeypatch.setattr(service, "get_splits", lambda _c, _i: ProviderResult({"lapDTOs": []}))
    optional_readers(monkeypatch, calls, hr=root, power=root)

    result = analyze_activity_service(Mock(), 123)

    assert result["heart_rate_zones"] == {"items": []}
    assert result["power_zones"] == {"items": []}
    assert result["availability"]["heart_rate_zones"] is True
    assert result["availability"]["power_zones"] is True


@pytest.mark.parametrize("root", [None, {}])
def test_absent_zone_roots_are_silent_and_unavailable(monkeypatch: pytest.MonkeyPatch, root: object):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        summaryDTO={"averageHR": 1}, activityTypeDTO={"typeKey": "running"},
    )))
    monkeypatch.setattr(service, "get_splits", lambda _c, _i: ProviderResult({"lapDTOs": []}))
    optional_readers(monkeypatch, calls, hr=root)
    result = analyze_activity_service(Mock(), 123)
    assert result["heart_rate_zones"] is None
    assert result["warnings"] == []


def test_zone_items_preserve_fields_units_source_order_and_percentages(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    zones = [
        {"zone": 2, "timeInZone": 90, "percentageInZone": 22.24,
         "zoneLowBoundary": 120, "zoneHighBoundary": 140, "label": "ignored"},
        {"timeInZone": 0, "percentageInZone": 50, "zoneLowBoundary": 0, "zoneHighBoundary": 200},
    ]
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "cycling"}, summaryDTO={"averageHR": 1, "averagePower": 1},
    )))
    monkeypatch.setattr(service, "get_splits", lambda _c, _i: ProviderResult({"lapDTOs": []}))
    optional_readers(monkeypatch, calls, hr=zones, power={"zones": zones})
    result = analyze_activity_service(Mock(), 123)
    assert result["heart_rate_zones"] == {"items": [
        {"zone": 2, "duration_seconds": 90, "duration_minutes": 1.5, "percentage": 22.2,
         "lower_bpm": 120, "upper_bpm": 140},
        {"zone": None, "duration_seconds": 0, "duration_minutes": 0.0, "percentage": 50.0,
         "lower_bpm": 0, "upper_bpm": 200},
    ]}
    assert result["power_zones"] == {"items": [
        {"zone": 2, "duration_seconds": 90, "duration_minutes": 1.5, "percentage": 22.2,
         "lower_watts": 120, "upper_watts": 140},
        {"zone": None, "duration_seconds": 0, "duration_minutes": 0.0, "percentage": 50.0,
         "lower_watts": 0, "upper_watts": 200},
    ]}


def test_upstream_hr_and_power_zone_shapes_preserve_explicit_zone_values(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    zones = [
        {"zone": 1, "timeInZone": 60, "percentageInZone": 25,
         "zoneLowBoundary": 100, "zoneHighBoundary": 120},
        {"zone": 2, "timeInZone": 180, "percentageInZone": 75,
         "zoneLowBoundary": 120, "zoneHighBoundary": 140},
    ]
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "cycling"}, summaryDTO={"averageHR": 1, "averagePower": 1},
    )))
    monkeypatch.setattr(service, "get_splits", lambda _c, _i: ProviderResult({"lapDTOs": []}))
    optional_readers(monkeypatch, calls, hr=zones, power={"zones": zones})

    result = analyze_activity_service(Mock(), 123)

    assert [item["zone"] for item in result["heart_rate_zones"]["items"]] == [1, 2]
    assert [item["zone"] for item in result["power_zones"]["items"]] == [1, 2]


@pytest.mark.parametrize(
    ("provider", "root", "message"),
    [
        ("heart_rate_zones", [None, {}, {"zone": True}, 7], "Heart-rate zone response had an unexpected shape."),
        ("power_zones", {"bad": []}, "Power-zone response had an unexpected shape."),
    ],
)
def test_malformed_and_all_invalid_zone_data_are_bounded(monkeypatch: pytest.MonkeyPatch, provider: str, root: object, message: str):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "cycling"}, summaryDTO={"averageHR": 1, "averagePower": 1},
    )))
    monkeypatch.setattr(service, "get_splits", lambda _c, _i: ProviderResult({"lapDTOs": []}))
    optional_readers(monkeypatch, calls, hr=root if provider == "heart_rate_zones" else None,
                     power=root if provider == "power_zones" else None)
    result = analyze_activity_service(Mock(), 123)
    assert result["status"] == "partial_success"
    assert result[provider] is None
    assert result["warnings"] == [{"provider": provider, "code": "invalid_provider_response", "message": message}]


def test_mixed_zone_items_drop_invalid_values_once_and_unsafe_ints_are_null(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    huge = 10 ** 5000
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(summaryDTO={"averageHR": 1})))
    monkeypatch.setattr(service, "get_splits", lambda _c, _i: ProviderResult({"lapDTOs": []}))
    optional_readers(monkeypatch, calls, hr=[{"zone": huge, "timeInZone": 10}, {"percentageInZone": 101}, {"timeInZone": 2}])
    result = analyze_activity_service(Mock(), 123)
    assert result["heart_rate_zones"] == {"items": [
        {"zone": None, "duration_seconds": 10, "duration_minutes": 0.2, "percentage": None, "lower_bpm": None, "upper_bpm": None},
        {"zone": None, "duration_seconds": 2, "duration_minutes": 0.0, "percentage": None, "lower_bpm": None, "upper_bpm": None},
    ]}
    assert result["warnings"] == [{"provider": "heart_rate_zones", "code": "invalid_provider_response", "message": "Heart-rate zone response had an unexpected shape."}]


@pytest.mark.parametrize("root", [None, {}])
def test_absent_strength_roots_are_silent(monkeypatch: pytest.MonkeyPatch, root: object):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(activityTypeDTO={"typeKey": "strength_training"})))
    optional_readers(monkeypatch, calls, strength=root)
    result = analyze_activity_service(Mock(), 123)
    assert result["strength"] is None and result["warnings"] == []


def test_strength_garmin_set_records_group_active_sets_and_ignore_raw_fields(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    strength = {"activityId": 123, "exerciseSets": [
        {"setType": "ACTIVE", "repetitionCount": 0, "weight": 100, "duration": 45,
         "startTime": 100, "wktStepIndex": 2,
         "exercises": [
             {"name": "  Squat  ", "category": "STRENGTH", "probability": 0.99},
             {"name": "Wrong candidate", "category": "OTHER", "probability": 1},
         ]},
        {"setType": "REST", "repetitionCount": 99, "weight": 999, "duration": 60,
         "startTime": 145, "wktStepIndex": 3,
         "exercises": [{"name": "Ignored rest", "category": "REST", "probability": 1}]},
        {"setType": "ACTIVE", "repetitionCount": 8,
         "exercises": [{"name": "Squat", "category": "STRENGTH", "probability": 0.5}]},
        {"setType": "ACTIVE", "repetitionCount": 12,
         "exercises": [{"name": "Push-up", "category": "STRENGTH", "probability": 0.8}]},
        {"setType": "ACTIVE", "repetitionCount": None,
         "exercises": [{"name": "Push-up", "category": "STRENGTH", "probability": 0.7}]},
    ]}
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(activityTypeDTO={"typeKey": "strength_training"})))
    optional_readers(monkeypatch, calls, strength=strength)
    result = analyze_activity_service(Mock(), 123)
    assert result["strength"] == {"exercise_count": 2, "set_count": 4, "repetition_count": 20, "items": [
        {"name": "Squat", "set_count": 2, "repetition_count": 8,
         "sets": [{"set_number": None, "repetitions": 0}, {"set_number": None, "repetitions": 8}]},
        {"name": "Push-up", "set_count": 2, "repetition_count": 12,
         "sets": [{"set_number": None, "repetitions": 12}, {"set_number": None, "repetitions": None}]},
    ]}
    assert result["availability"]["strength"] is True
    assert result["warnings"] == []


def test_strength_exercise_name_is_trimmed_to_the_approved_120_character_bound(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "strength_training"},
    )))
    optional_readers(monkeypatch, calls, strength={"exerciseSets": [{
        "setType": "ACTIVE", "exercises": [{"name": "x" * 121, "category": "STRENGTH"}],
    }]})

    result = analyze_activity_service(Mock(), 123)

    assert result["strength"]["items"][0]["name"] == "x" * 120


def test_strength_groups_by_full_trimmed_candidate_identity_before_bounding_display_name(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []
    shared_name_prefix = "n" * 120
    shared_category_prefix = "c" * 120
    first_identity = {"name": f" {shared_name_prefix}A ", "category": f" {shared_category_prefix}A "}
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "strength_training"},
    )))
    optional_readers(monkeypatch, calls, strength={"exerciseSets": [
        {"setType": "ACTIVE", "repetitionCount": 1, "exercises": [first_identity]},
        {"setType": "ACTIVE", "repetitionCount": 2,
         "exercises": [{"name": f" {shared_name_prefix}B ", "category": f" {shared_category_prefix}A "}]},
        {"setType": "ACTIVE", "repetitionCount": 3,
         "exercises": [{"name": f" {shared_name_prefix}A ", "category": f" {shared_category_prefix}B "}]},
        {"setType": "ACTIVE", "repetitionCount": 4, "exercises": [first_identity]},
    ]})

    result = analyze_activity_service(Mock(), 123)

    assert result["strength"] == {"exercise_count": 3, "set_count": 4, "repetition_count": 10, "items": [
        {"name": shared_name_prefix, "set_count": 2, "repetition_count": 5,
         "sets": [{"set_number": None, "repetitions": 1}, {"set_number": None, "repetitions": 4}]},
        {"name": shared_name_prefix, "set_count": 1, "repetition_count": 2,
         "sets": [{"set_number": None, "repetitions": 2}]},
        {"name": shared_name_prefix, "set_count": 1, "repetition_count": 3,
         "sets": [{"set_number": None, "repetitions": 3}]},
    ]}
    assert result["warnings"] == []


def test_strength_empty_exercise_sets_are_available_and_zero_count(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(activityTypeDTO={"typeKey": "strength_training"})))
    optional_readers(monkeypatch, calls, strength={"exerciseSets": []})
    assert analyze_activity_service(Mock(), 123)["strength"] == {
        "exercise_count": 0, "set_count": 0, "repetition_count": None, "items": [],
    }


def test_strength_rest_only_payload_is_available_empty_without_a_warning(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "strength_training"},
    )))
    optional_readers(monkeypatch, calls, strength={"exerciseSets": [
        {"setType": "REST", "repetitionCount": 12, "exercises": "ignored"},
        {"setType": "REST", "weight": 50},
    ]})

    result = analyze_activity_service(Mock(), 123)

    assert result["availability"]["strength"] is True
    assert result["strength"] == {
        "exercise_count": 0, "set_count": 0, "repetition_count": None, "items": [],
    }
    assert result["warnings"] == []


def test_strength_missing_repetitions_stay_null_while_known_zero_totals_stay_zero(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(activityTypeDTO={"typeKey": "strength_training"})))
    optional_readers(monkeypatch, calls, strength={"exerciseSets": [
        {"setType": "ACTIVE", "repetitionCount": 0},
        {"setType": "ACTIVE"},
    ]})
    result = analyze_activity_service(Mock(), 123)
    strength = result["strength"]
    assert strength["repetition_count"] == 0
    assert strength["items"][0]["repetition_count"] == 0
    assert strength["items"][1]["repetition_count"] is None
    assert result["warnings"] == []


def test_strength_identityless_active_entries_remain_separate_and_malformed_sets_remain_known(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    huge = 10 ** 5000
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(activityTypeDTO={"typeKey": "strength_training"})))
    optional_readers(monkeypatch, calls, strength={"exerciseSets": [
        {"setType": "ACTIVE", "repetitionCount": 3},
        {"setType": "ACTIVE", "repetitionCount": huge},
        {"setType": "ACTIVE", "repetitionCount": True},
        {"setType": "ACTIVE", "exercises": "bad"},
        {"setType": "REST"},
        {"setType": "active"},
        None,
    ]})
    result = analyze_activity_service(Mock(), 123)
    assert result["strength"] == {"exercise_count": 4, "set_count": 4, "repetition_count": 3, "items": [
        {"name": None, "set_count": 1, "repetition_count": 3,
         "sets": [{"set_number": None, "repetitions": 3}]},
        {"name": None, "set_count": 1, "repetition_count": None,
         "sets": [{"set_number": None, "repetitions": None}]},
        {"name": None, "set_count": 1, "repetition_count": None,
         "sets": [{"set_number": None, "repetitions": None}]},
        {"name": None, "set_count": 1, "repetition_count": None,
         "sets": [{"set_number": None, "repetitions": None}]},
    ]}
    assert result["warnings"] == [{"provider": "strength", "code": "invalid_provider_response", "message": "Strength exercise-set response had an unexpected shape."}]


def test_strength_invalid_first_candidate_is_retained_unnamed_with_one_warning(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "strength_training"},
    )))
    optional_readers(monkeypatch, calls, strength={"exerciseSets": [
        {"setType": "ACTIVE", "repetitionCount": 2,
         "exercises": [{"name": "Known", "category": "STRENGTH"}]},
        {"setType": "ACTIVE", "repetitionCount": 4,
         "exercises": [{"name": "Missing category"}]},
        {"setType": "ACTIVE", "repetitionCount": 6, "weight": 99, "duration": 30,
         "startTime": 123, "wktStepIndex": 2, "exercises": ["bad first candidate"]},
    ]})

    result = analyze_activity_service(Mock(), 123)

    assert result["strength"] == {"exercise_count": 3, "set_count": 3, "repetition_count": 12, "items": [
        {"name": "Known", "set_count": 1, "repetition_count": 2,
         "sets": [{"set_number": None, "repetitions": 2}]},
        {"name": None, "set_count": 1, "repetition_count": 4,
         "sets": [{"set_number": None, "repetitions": 4}]},
        {"name": None, "set_count": 1, "repetition_count": 6,
         "sets": [{"set_number": None, "repetitions": 6}]},
    ]}
    assert result["warnings"] == [{
        "provider": "strength", "code": "invalid_provider_response",
        "message": "Strength exercise-set response had an unexpected shape.",
    }]
    serialized = json.dumps(result["strength"])
    assert all(field not in serialized for field in (
        "weight", "duration", "probability", "category", "startTime", "wktStepIndex",
    ))


@pytest.mark.parametrize(
    "root",
    [
        {"exercises": []}, {"exerciseSets": "bad"}, [],
        {"exerciseSets": [{"setType": "unknown"}]}, {"exerciseSets": [{"setType": "ACTIVE "}]},
        {"exerciseSets": [{"setType": True}]}, {"exerciseSets": [{}]},
    ],
)
def test_wrong_or_all_invalid_strength_roots_are_unavailable_with_one_fixed_warning(monkeypatch: pytest.MonkeyPatch, root: object):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(activityTypeDTO={"typeKey": "strength_training"})))
    optional_readers(monkeypatch, calls, strength=root)
    result = analyze_activity_service(Mock(), 123)
    assert result["status"] == "partial_success" and result["strength"] is None
    assert result["warnings"] == [{"provider": "strength", "code": "invalid_provider_response", "message": "Strength exercise-set response had an unexpected shape."}]


def test_later_optional_provider_runs_after_prior_malformed_response_and_warnings_compose(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": "cycling"}, summaryDTO={"averageHR": 1, "averagePower": 1},
    )))
    monkeypatch.setattr(service, "get_splits", lambda _c, _i: ProviderResult({"lapDTOs": []}))
    optional_readers(monkeypatch, calls, hr={"bad": []}, power={"bad": []})
    result = analyze_activity_service(Mock(), 123)
    assert calls == ["heart_rate_zones", "power_zones"]
    assert result["status"] == "partial_success"
    assert result["warnings"] == [
        {"provider": "heart_rate_zones", "code": "invalid_provider_response", "message": "Heart-rate zone response had an unexpected shape."},
        {"provider": "power_zones", "code": "invalid_provider_response", "message": "Power-zone response had an unexpected shape."},
    ]


@pytest.mark.parametrize(
    ("provider", "exception", "message"),
    [
        ("splits", RuntimeError("token=private; Authorization: Bearer secret"), "Activity splits are unavailable."),
        ("heart_rate_zones", RuntimeError("https://private.example/?token=private"), "Heart-rate zone data is unavailable."),
        ("power_zones", RuntimeError("email=private@example.test; request-id=private"), "Power-zone data is unavailable."),
    ],
)
def test_raised_optional_provider_seams_are_sanitized_and_later_reads_continue(
    monkeypatch: pytest.MonkeyPatch, provider: str, exception: Exception, message: str,
):
    calls: list[str] = []

    def base(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("activity")
        return ProviderResult(raw_activity(
            activityTypeDTO={"typeKey": "cycling"}, summaryDTO={"averageHR": 1, "averagePower": 1},
        ))

    def split_provider(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("splits")
        if provider == "splits":
            raise exception
        return ProviderResult({"lapDTOs": []})

    def zone_provider(name: str):
        def read(_client: object, _activity_id: int) -> ProviderResult:
            calls.append(name)
            if provider == name:
                raise exception
            return ProviderResult([])
        return read

    monkeypatch.setattr(service, "get_activity", base)
    monkeypatch.setattr(service, "get_splits", split_provider)
    monkeypatch.setattr(service, "get_heart_rate_zones", zone_provider("heart_rate_zones"))
    monkeypatch.setattr(service, "get_power_zones", zone_provider("power_zones"))

    result = analyze_activity_service(Mock(), 123)

    assert calls == ["activity", "splits", "heart_rate_zones", "power_zones"]
    assert result["status"] == "partial_success"
    assert result["availability"][provider] is False
    assert result[provider] is None
    assert result["warnings"] == [{"provider": provider, "code": "provider_unavailable", "message": message}]
    serialized = json.dumps(result, allow_nan=False)
    for secret in ("private", "Bearer", "example.test", "request-id", "Authorization"):
        assert secret not in serialized


@pytest.mark.parametrize("raise_directly", [False, True])
def test_strength_provider_failures_are_sanitized_and_json_safe(
    monkeypatch: pytest.MonkeyPatch, raise_directly: bool,
):
    def strength(_client: object, _activity_id: int) -> ProviderResult:
        if raise_directly:
            raise RuntimeError("token=private@example.test")
        return ProviderResult({"payload": "token=private@example.test"}, failed=True)

    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(
        raw_activity(activityTypeDTO={"typeKey": "strength_training"})
    ))
    monkeypatch.setattr(service, "get_strength", strength)

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "partial_success"
    assert result["strength"] is None and result["availability"]["strength"] is False
    assert result["warnings"] == [{
        "provider": "strength", "code": "provider_unavailable",
        "message": "Strength exercise-set data is unavailable.",
    }]
    assert "private" not in json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    ("provider", "type_key", "summary", "expected_calls", "message"),
    [
        ("splits", "cycling", {"averageHR": 1, "averagePower": 1},
         ["splits", "heart_rate_zones", "power_zones"], "Activity splits are unavailable."),
        ("heart_rate_zones", "cycling", {"averageHR": 1, "averagePower": 1},
         ["splits", "heart_rate_zones", "power_zones"], "Heart-rate zone data is unavailable."),
        ("power_zones", "cycling", {"averageHR": 1, "averagePower": 1},
         ["splits", "heart_rate_zones", "power_zones"], "Power-zone data is unavailable."),
        ("strength", "strength_training", {}, ["strength"], "Strength exercise-set data is unavailable."),
    ],
)
def test_failed_optional_provider_results_are_sanitized_once_and_do_not_stop_later_calls(
    monkeypatch: pytest.MonkeyPatch, provider: str, type_key: str, summary: dict[str, object],
    expected_calls: list[str], message: str,
):
    calls: list[str] = []

    def optional(name: str):
        def read(_client: object, _activity_id: int) -> ProviderResult:
            calls.append(name)
            if name == provider:
                return ProviderResult({"token": "private@example.test"}, failed=True)
            data = {
                "splits": {"lapDTOs": []},
                "heart_rate_zones": [],
                "power_zones": [],
                "strength": {"exerciseSets": []},
            }[name]
            return ProviderResult(data)
        return read

    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity(
        activityTypeDTO={"typeKey": type_key}, summaryDTO=summary,
    )))
    monkeypatch.setattr(service, "get_splits", optional("splits"))
    monkeypatch.setattr(service, "get_heart_rate_zones", optional("heart_rate_zones"))
    monkeypatch.setattr(service, "get_power_zones", optional("power_zones"))
    monkeypatch.setattr(service, "get_strength", optional("strength"))

    result = analyze_activity_service(Mock(), 123)

    assert calls == expected_calls
    assert result["status"] == "partial_success"
    assert result[provider] is None and result["availability"][provider] is False
    assert result["warnings"] == [{"provider": provider, "code": "provider_unavailable", "message": message}]
    assert "private" not in json.dumps(result, allow_nan=False)


class ForbiddenNestedClient:
    def __init__(self, record_forbidden: object):
        self._record_forbidden = record_forbidden

    def post(self, *_args: object, **_kwargs: object) -> None:
        self._record_forbidden("client.post")  # type: ignore[operator]

    def put(self, *_args: object, **_kwargs: object) -> None:
        self._record_forbidden("client.put")  # type: ignore[operator]

    def delete(self, *_args: object, **_kwargs: object) -> None:
        self._record_forbidden("client.delete")  # type: ignore[operator]


class RecordingReadOnlyClient:
    """Client double that permits only the documented activity reads."""

    def __init__(self, payload: dict[str, object], *, failures: set[str] | None = None):
        self.calls: list[str] = []
        self.forbidden_calls: list[str] = []
        self.payload = payload
        self.failures = failures or set()
        self.client = ForbiddenNestedClient(self._forbidden)

    def _read(self, name: str, value: object) -> object:
        self.calls.append(name)
        if name in self.failures:
            raise RuntimeError("token=private@example.test")
        return value

    def get_activity(self, activity_id: int) -> object:
        assert activity_id == 123
        return self._read("get_activity", self.payload)

    def get_activity_splits(self, activity_id: int) -> object:
        assert activity_id == 123
        return self._read("get_activity_splits", {"lapDTOs": []})

    def get_activity_hr_in_timezones(self, activity_id: int) -> object:
        assert activity_id == 123
        return self._read("get_activity_hr_in_timezones", [])

    def get_activity_power_in_timezones(self, activity_id: int) -> object:
        assert activity_id == 123
        return self._read("get_activity_power_in_timezones", [])

    def get_activity_exercise_sets(self, activity_id: int) -> object:
        assert activity_id == 123
        return self._read("get_activity_exercise_sets", {"exerciseSets": []})

    def upload_workout(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("upload_workout")

    def schedule_workout(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("schedule_workout")

    def unschedule_workout(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("unschedule_workout")

    def delete_workout(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("delete_workout")

    def set_activity_name(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("set_activity_name")

    def set_activity_description(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("set_activity_description")

    def set_activity_type(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("set_activity_type")

    def post(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("post")

    def put(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("put")

    def delete(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("delete")

    def _forbidden(self, name: str) -> None:
        self.forbidden_calls.append(name)
        raise AssertionError("mutating or raw request client API accessed")

    def __getattr__(self, name: str) -> object:
        self.forbidden_calls.append(name)
        raise AssertionError(f"unexpected client attribute accessed: {name}")


@pytest.mark.parametrize(
    "attempt, expected",
    [
        (lambda client: client.upload_workout(), "upload_workout"),
        (lambda client: client.schedule_workout(), "schedule_workout"),
        (lambda client: client.unschedule_workout(), "unschedule_workout"),
        (lambda client: client.delete_workout(), "delete_workout"),
        (lambda client: client.set_activity_name(), "set_activity_name"),
        (lambda client: client.set_activity_description(), "set_activity_description"),
        (lambda client: client.set_activity_type(), "set_activity_type"),
        (lambda client: client.post(), "post"),
        (lambda client: client.put(), "put"),
        (lambda client: client.delete(), "delete"),
        (lambda client: client.client.post(), "client.post"),
        (lambda client: client.client.put(), "client.put"),
        (lambda client: client.client.delete(), "client.delete"),
        (lambda client: client.unknown_client_api, "unknown_client_api"),
    ],
)
def test_recording_read_only_client_records_each_forbidden_attempt_before_raising(
    attempt: object, expected: str,
):
    client = RecordingReadOnlyClient(raw_activity())

    with pytest.raises(AssertionError):
        attempt(client)  # type: ignore[operator]

    assert client.forbidden_calls == [expected]


@pytest.mark.parametrize(
    ("type_key", "summary", "expected_reads"),
    [
        ("running", {"averageHR": 1}, ["get_activity", "get_activity_splits", "get_activity_hr_in_timezones"]),
        ("walking", {"averageHR": 1}, ["get_activity", "get_activity_splits", "get_activity_hr_in_timezones"]),
        ("cycling", {"averageHR": 1, "averagePower": 1}, [
            "get_activity", "get_activity_splits", "get_activity_hr_in_timezones", "get_activity_power_in_timezones",
        ]),
        ("strength_training", {}, ["get_activity", "get_activity_exercise_sets"]),
        ("yoga", {}, ["get_activity"]),
    ],
)
def test_real_provider_seams_use_only_documented_reads_in_exact_order(
    type_key: str, summary: dict[str, object], expected_reads: list[str],
):
    client = RecordingReadOnlyClient(raw_activity(activityTypeDTO={"typeKey": type_key}, summaryDTO=summary))

    result = analyze_activity_service(client, 123)

    assert result["status"] == "success"
    assert client.calls == expected_reads
    assert client.forbidden_calls == []
    json.dumps(result, allow_nan=False)


def test_real_provider_seams_remain_read_only_after_a_partial_failure():
    client = RecordingReadOnlyClient(
        raw_activity(activityTypeDTO={"typeKey": "cycling"}, summaryDTO={"averageHR": 1, "averagePower": 1}),
        failures={"get_activity_splits"},
    )

    result = analyze_activity_service(client, 123)

    assert result["status"] == "partial_success"
    assert client.calls == [
        "get_activity", "get_activity_splits", "get_activity_hr_in_timezones", "get_activity_power_in_timezones",
    ]
    assert client.forbidden_calls == []
    assert "private" not in json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    ("type_key", "summary", "failure", "expected_reads"),
    [
        ("cycling", {"averageHR": 1, "averagePower": 1}, "get_activity_splits", [
            "get_activity", "get_activity_splits", "get_activity_hr_in_timezones", "get_activity_power_in_timezones",
        ]),
        ("cycling", {"averageHR": 1, "averagePower": 1}, "get_activity_hr_in_timezones", [
            "get_activity", "get_activity_splits", "get_activity_hr_in_timezones", "get_activity_power_in_timezones",
        ]),
        ("cycling", {"averageHR": 1, "averagePower": 1}, "get_activity_power_in_timezones", [
            "get_activity", "get_activity_splits", "get_activity_hr_in_timezones", "get_activity_power_in_timezones",
        ]),
        ("strength_training", {}, "get_activity_exercise_sets", ["get_activity", "get_activity_exercise_sets"]),
    ],
)
def test_real_provider_seam_optional_failures_continue_later_reads_without_forbidden_calls(
    type_key: str, summary: dict[str, object], failure: str, expected_reads: list[str],
):
    client = RecordingReadOnlyClient(
        raw_activity(activityTypeDTO={"typeKey": type_key}, summaryDTO=summary), failures={failure},
    )

    result = analyze_activity_service(client, 123)

    assert result["status"] == "partial_success"
    assert client.calls == expected_reads
    assert client.forbidden_calls == []
    assert "private" not in json.dumps(result, allow_nan=False)


class ExplodingEq:
    def __eq__(self, _other: object) -> bool:
        raise RuntimeError("token=private@example.test")


class ExplodingBoolDict(dict[str, object]):
    def __bool__(self) -> bool:
        raise RuntimeError("token=private@example.test")


class ExplodingGetDict(dict[str, object]):
    def get(self, _key: object, _default: object = None) -> object:
        raise RuntimeError("token=private@example.test")


def test_base_exploding_equality_payload_is_a_bounded_invalid_response_without_optional_calls(
    monkeypatch: pytest.MonkeyPatch,
):
    optional_calls: list[str] = []
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(ExplodingEq()))
    for name in ("get_splits", "get_heart_rate_zones", "get_power_zones", "get_strength"):
        monkeypatch.setattr(service, name, lambda _c, _i, name=name: optional_calls.append(name), raising=False)

    result = analyze_activity_service(Mock(), 123)

    assert_envelope(result)
    assert result["error"] == {
        "code": "invalid_activity_response", "message": "Activity data had an unexpected shape.",
    }
    assert optional_calls == []
    serialized = json.dumps(result, allow_nan=False)
    assert "private" not in serialized and "token" not in serialized


@pytest.mark.parametrize(
    ("provider", "type_key", "summary", "expected_calls", "message"),
    [
        ("splits", "cycling", {"averageHR": 1, "averagePower": 1},
         ["activity", "splits", "heart_rate_zones", "power_zones"], "Activity splits response had an unexpected shape."),
        ("heart_rate_zones", "cycling", {"averageHR": 1, "averagePower": 1},
         ["activity", "splits", "heart_rate_zones", "power_zones"], "Heart-rate zone response had an unexpected shape."),
        ("power_zones", "cycling", {"averageHR": 1, "averagePower": 1},
         ["activity", "splits", "heart_rate_zones", "power_zones"], "Power-zone response had an unexpected shape."),
        ("strength", "strength_training", {}, ["activity", "strength"], "Strength exercise-set response had an unexpected shape."),
    ],
)
def test_optional_exploding_equality_payloads_are_bounded_and_later_reads_continue(
    monkeypatch: pytest.MonkeyPatch, provider: str, type_key: str, summary: dict[str, object],
    expected_calls: list[str], message: str,
):
    calls: list[str] = []

    def reader(name: str):
        def read(_client: object, _activity_id: int) -> ProviderResult:
            calls.append(name)
            if name == provider:
                return ProviderResult(ExplodingEq())
            return ProviderResult({
                "splits": {"lapDTOs": []},
                "heart_rate_zones": [],
                "power_zones": [],
                "strength": {"exerciseSets": []},
            }[name])
        return read

    def base(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("activity")
        return ProviderResult(raw_activity(activityTypeDTO={"typeKey": type_key}, summaryDTO=summary))

    monkeypatch.setattr(service, "get_activity", base)
    monkeypatch.setattr(service, "get_splits", reader("splits"))
    monkeypatch.setattr(service, "get_heart_rate_zones", reader("heart_rate_zones"))
    monkeypatch.setattr(service, "get_power_zones", reader("power_zones"))
    monkeypatch.setattr(service, "get_strength", reader("strength"))

    result = analyze_activity_service(Mock(), 123)

    assert calls == expected_calls
    assert result["status"] == "partial_success"
    assert result[provider] is None and result["availability"][provider] is False
    assert result["warnings"] == [{
        "provider": provider, "code": "invalid_provider_response", "message": message,
    }]
    serialized = json.dumps(result, allow_nan=False)
    assert "private" not in serialized and "token" not in serialized


@pytest.mark.parametrize("payload_type", [ExplodingBoolDict, ExplodingGetDict])
def test_base_exploding_dict_payloads_are_bounded_invalid_responses(
    monkeypatch: pytest.MonkeyPatch, payload_type: type[dict[str, object]],
):
    calls: list[str] = []

    def base(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("activity")
        return ProviderResult(payload_type(raw_activity()))

    monkeypatch.setattr(service, "get_activity", base)
    for name in ("get_splits", "get_heart_rate_zones", "get_power_zones", "get_strength"):
        monkeypatch.setattr(service, name, lambda _c, _i, name=name: calls.append(name), raising=False)

    result = analyze_activity_service(Mock(), 123)

    assert_envelope(result)
    assert result["error"] == {
        "code": "invalid_activity_response", "message": "Activity data had an unexpected shape.",
    }
    assert calls == ["activity"]
    assert "private" not in json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    ("provider", "type_key", "summary", "expected_calls", "message"),
    [
        ("splits", "cycling", {"averageHR": 1, "averagePower": 1},
         ["activity", "splits", "heart_rate_zones", "power_zones"], "Activity splits response had an unexpected shape."),
        ("heart_rate_zones", "cycling", {"averageHR": 1, "averagePower": 1},
         ["activity", "splits", "heart_rate_zones", "power_zones"], "Heart-rate zone response had an unexpected shape."),
        ("power_zones", "cycling", {"averageHR": 1, "averagePower": 1},
         ["activity", "splits", "heart_rate_zones", "power_zones"], "Power-zone response had an unexpected shape."),
        ("strength", "strength_training", {}, ["activity", "strength"], "Strength exercise-set response had an unexpected shape."),
    ],
)
@pytest.mark.parametrize("payload_type", [ExplodingBoolDict, ExplodingGetDict])
def test_optional_exploding_dict_payloads_are_bounded_and_later_reads_continue(
    monkeypatch: pytest.MonkeyPatch, provider: str, type_key: str, summary: dict[str, object],
    expected_calls: list[str], message: str, payload_type: type[dict[str, object]],
):
    calls: list[str] = []

    def reader(name: str):
        def read(_client: object, _activity_id: int) -> ProviderResult:
            calls.append(name)
            if name == provider:
                return ProviderResult(payload_type({"opaque": "token=private@example.test"}))
            return ProviderResult({
                "splits": {"lapDTOs": []},
                "heart_rate_zones": [],
                "power_zones": [],
                "strength": {"exerciseSets": []},
            }[name])
        return read

    def base(_client: object, _activity_id: int) -> ProviderResult:
        calls.append("activity")
        return ProviderResult(raw_activity(activityTypeDTO={"typeKey": type_key}, summaryDTO=summary))

    monkeypatch.setattr(service, "get_activity", base)
    monkeypatch.setattr(service, "get_splits", reader("splits"))
    monkeypatch.setattr(service, "get_heart_rate_zones", reader("heart_rate_zones"))
    monkeypatch.setattr(service, "get_power_zones", reader("power_zones"))
    monkeypatch.setattr(service, "get_strength", reader("strength"))

    result = analyze_activity_service(Mock(), 123)

    assert calls == expected_calls
    assert result["status"] == "partial_success"
    assert result[provider] is None and result["availability"][provider] is False
    assert result["warnings"] == [{
        "provider": provider, "code": "invalid_provider_response", "message": message,
    }]
    assert "private" not in json.dumps(result, allow_nan=False)


def test_internal_base_normalizer_errors_propagate_instead_of_becoming_client_errors(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity()))
    monkeypatch.setattr(service, "_activity_summary", Mock(side_effect=RuntimeError("internal failure")))

    with pytest.raises(RuntimeError, match="internal failure"):
        analyze_activity_service(Mock(), 123)


def test_internal_split_normalizer_errors_propagate_instead_of_becoming_provider_warnings(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(service, "get_activity", lambda _c, _i: ProviderResult(raw_activity()))
    monkeypatch.setattr(service, "get_splits", lambda _c, _i: ProviderResult({"lapDTOs": [split()]}))
    monkeypatch.setattr(service, "_split_item", Mock(side_effect=RuntimeError("internal split failure")))

    with pytest.raises(RuntimeError, match="internal split failure"):
        analyze_activity_service(Mock(), 123)
