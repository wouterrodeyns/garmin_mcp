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
    monkeypatch.setattr(service, "get_splits", Mock(return_value=ProviderResult(None)), raising=False)
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


def test_valid_base_then_split_is_the_only_provider_call_sequence(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, int]] = []

    def base(_client: object, activity_id: int) -> ProviderResult:
        calls.append(("activity", activity_id))
        return ProviderResult(raw_activity())

    def splits(_client: object, activity_id: int) -> ProviderResult:
        calls.append(("splits", activity_id))
        return ProviderResult({"lapDTOs": []})

    monkeypatch.setattr(service, "get_activity", base)
    monkeypatch.setattr(service, "get_splits", splits)

    result = analyze_activity_service(Mock(), 123)

    assert result["status"] == "success"
    assert calls == [("activity", 123), ("splits", 123)]


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
