"""Contract tests for bounded, read-only Garmin training providers."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, call

import pytest
from garminconnect import GarminConnectConnectionError

from garmin_mcp.ai_training.providers import (
    MAX_ACTIVITY_RECORDS,
    PAGE_SIZE,
    RUNNING_TYPE_KEYS,
    ProviderResult,
    activity_cap,
    get_daily_stats,
    get_hrv,
    get_last_run,
    get_period_activities,
    get_scheduled_workouts,
    get_sleep,
    get_training_readiness,
    get_training_status,
)


ACTIVITIES_ENDPOINT = "/activity-service/activities/search/activities"


def client() -> Mock:
    result = Mock()
    result.garmin_connect_activities = ACTIVITIES_ENDPOINT
    return result


def page(count: int, type_key: str = "cycling") -> list[dict[str, object]]:
    return [{"activityId": index, "activityType": {"typeKey": type_key}} for index in range(count)]


def test_public_constants_and_provider_result_are_immutable():
    assert RUNNING_TYPE_KEYS == frozenset({"running", "trail_running", "treadmill_running"})
    assert PAGE_SIZE == 200
    assert MAX_ACTIVITY_RECORDS == 1000
    result = ProviderResult(data=("item",))
    assert result.failed is False
    assert result.truncated is False
    assert result.warnings == ()
    with pytest.raises(FrozenInstanceError):
        result.failed = True


@pytest.mark.parametrize(("days", "expected"), [(1, 200), (14, 200), (25, 400), (30, 400), (90, 1000)])
def test_activity_cap_rounds_to_bounded_two_hundred_record_pages(days: int, expected: int):
    assert activity_cap(days) == expected


@pytest.mark.parametrize("raw", [page(1), {"activityList": page(1)}, None])
def test_period_activities_accepts_supported_raw_roots(raw: object):
    garmin = client()
    garmin.connectapi.return_value = raw

    result = get_period_activities(garmin, "2026-01-01", "2026-01-14", 14)

    expected = [] if raw is None else page(1)
    assert result == ProviderResult(data=tuple(expected))


@pytest.mark.parametrize("reader", [
    lambda garmin: get_period_activities(garmin, "2026-01-01", "2026-01-14", 14),
    get_last_run,
])
@pytest.mark.parametrize(
    "raw",
    [
        {},
        False,
        0,
        "",
        {"items": page(1)},
        {"activityList": None},
        {"activityList": {}},
        ["sensitive non-dict item"],
        {"activityList": ["sensitive non-dict item"]},
    ],
)
def test_activity_readers_reject_every_malformed_root_without_exposing_response(reader, raw: object):
    garmin = client()
    garmin.connectapi.return_value = raw

    result = reader(garmin)

    assert result.data in ((), None)
    assert result.failed is True
    assert result.warnings[0]["code"] == "invalid_provider_response"
    assert "sensitive non-dict item" not in result.warnings[0]["message"]


def test_period_activities_pages_with_exact_string_params_and_no_sort_by():
    garmin = client()
    garmin.connectapi.side_effect = [page(200), page(1)]

    result = get_period_activities(garmin, "2026-01-01", "2026-01-25", 25)

    assert result == ProviderResult(data=tuple(page(200) + page(1)))
    assert garmin.connectapi.call_args_list == [
        call(
            ACTIVITIES_ENDPOINT,
            params={
                "startDate": "2026-01-01",
                "endDate": "2026-01-25",
                "start": "0",
                "limit": "200",
                "sortOrder": "desc",
            },
        ),
        call(
            ACTIVITIES_ENDPOINT,
            params={
                "startDate": "2026-01-01",
                "endDate": "2026-01-25",
                "start": "200",
                "limit": "200",
                "sortOrder": "desc",
            },
        ),
    ]


def test_period_activities_marks_exact_cap_as_truncated_lower_bound():
    garmin = client()
    garmin.connectapi.side_effect = [page(200), page(200)]

    result = get_period_activities(garmin, "2026-01-01", "2026-01-25", 25)

    assert len(result.data) == 400
    assert result.failed is False
    assert result.truncated is True
    assert result.warnings == (
        {
            "provider": "activities",
            "code": "activities_truncated",
            "message": "Activity history was limited to 400 records; period totals are lower bounds.",
        },
    )
    assert garmin.connectapi.call_count == 2


def test_period_activities_preserves_prior_pages_when_later_page_is_unavailable():
    garmin = client()
    garmin.connectapi.side_effect = [page(200), GarminConnectConnectionError("secret upstream failure")]

    result = get_period_activities(garmin, "2026-01-01", "2026-01-25", 25)

    assert result.data == tuple(page(200))
    assert result.failed is True
    assert result.truncated is True
    assert result.warnings == (
        {
            "provider": "activities",
            "code": "provider_unavailable",
            "message": "Activity history is incomplete because a later page was unavailable.",
        },
    )


def test_period_activities_reports_a_sanitized_unavailable_first_page():
    garmin = client()
    garmin.connectapi.side_effect = GarminConnectConnectionError("token=private")

    result = get_period_activities(garmin, "2026-01-01", "2026-01-14", 14)

    assert result.data == ()
    assert result.failed is True
    assert result.truncated is False
    assert result.warnings[0]["code"] == "provider_unavailable"
    assert "token=private" not in result.warnings[0]["message"]


@pytest.mark.parametrize("raw", [page(1, "running"), {"activityList": page(1, "running")}, None])
def test_last_run_accepts_supported_activity_roots(raw: object):
    garmin = client()
    garmin.connectapi.return_value = raw

    result = get_last_run(garmin)

    expected = None if raw is None else page(1, "running")[0]
    assert result == ProviderResult(data=expected)


def test_last_run_is_unfiltered_and_stops_when_a_local_running_type_matches():
    garmin = client()
    matching = {"activityId": 202, "activityType": {"typeKey": "trail_running"}}
    garmin.connectapi.side_effect = [page(200), [matching]]

    result = get_last_run(garmin)

    assert result == ProviderResult(data=matching)
    assert garmin.connectapi.call_args_list == [
        call(ACTIVITIES_ENDPOINT, params={"start": "0", "limit": "200", "sortOrder": "desc"}),
        call(ACTIVITIES_ENDPOINT, params={"start": "200", "limit": "200", "sortOrder": "desc"}),
    ]


def test_last_run_returns_empty_without_warning_after_a_short_nonmatching_page():
    garmin = client()
    garmin.connectapi.return_value = page(1)

    assert get_last_run(garmin) == ProviderResult(data=None)


def test_last_run_marks_a_full_bounded_search_without_match_as_truncated():
    garmin = client()
    garmin.connectapi.side_effect = [page(200)] * 5

    result = get_last_run(garmin)

    assert result.data is None
    assert result.failed is False
    assert result.truncated is True
    assert result.warnings == (
        {
            "provider": "last_run",
            "code": "activities_truncated",
            "message": "Latest-run search reached the 1000-record limit and was inconclusive.",
        },
    )


def test_last_run_reports_sanitized_unavailable_error_before_a_match():
    garmin = client()
    garmin.connectapi.side_effect = GarminConnectConnectionError("credentials leaked")

    result = get_last_run(garmin)

    assert result.data is None
    assert result.failed is True
    assert result.warnings[0]["provider"] == "last_run"
    assert result.warnings[0]["code"] == "provider_unavailable"
    assert "credentials leaked" not in result.warnings[0]["message"]


def test_last_run_rejects_invalid_activity_root_without_exposing_its_contents():
    garmin = client()
    garmin.connectapi.return_value = {"activityList": "secret malformed payload"}

    result = get_last_run(garmin)

    assert result.data is None
    assert result.failed is True
    assert result.warnings[0]["provider"] == "last_run"
    assert result.warnings[0]["code"] == "invalid_provider_response"
    assert "secret malformed payload" not in result.warnings[0]["message"]


def test_last_run_discards_prior_nonmatches_when_a_later_page_is_unavailable():
    garmin = client()
    garmin.connectapi.side_effect = [page(200), GarminConnectConnectionError("secret later failure")]

    result = get_last_run(garmin)

    assert result.data is None
    assert result.failed is True
    assert result.truncated is True
    assert result.warnings[0]["provider"] == "last_run"
    assert result.warnings[0]["code"] == "provider_unavailable"
    assert "secret later failure" not in result.warnings[0]["message"]


def test_scheduled_workouts_uses_the_exact_read_only_graphql_query():
    garmin = client()
    workouts = [{"workoutId": 1}]
    garmin.query_garmin_graphql.return_value = {"data": {"workoutScheduleSummariesScalar": workouts}}

    result = get_scheduled_workouts(garmin, "2026-01-01", "2026-01-14")

    assert result == ProviderResult(data=tuple(workouts))
    garmin.query_garmin_graphql.assert_called_once_with(
        {"query": 'query{workoutScheduleSummariesScalar(startDate:"2026-01-01", endDate:"2026-01-14")}'},
    )


@pytest.mark.parametrize("scalar", [None, []])
def test_scheduled_workouts_accepts_empty_scalar_values(scalar: object):
    garmin = client()
    garmin.query_garmin_graphql.return_value = {"data": {"workoutScheduleSummariesScalar": scalar}}

    assert get_scheduled_workouts(garmin, "2026-01-01", "2026-01-14") == ProviderResult(data=())


@pytest.mark.parametrize(
    "response",
    [
        {"errors": [{"message": "secret graphql message"}]},
        None,
        [],
        {"data": None},
        {"data": []},
        {"data": {}},
        {"data": {"workoutScheduleSummariesScalar": {}}},
    ],
)
def test_scheduled_workouts_rejects_invalid_graphql_responses_without_exposing_them(response: object):
    garmin = client()
    garmin.query_garmin_graphql.return_value = response

    result = get_scheduled_workouts(garmin, "2026-01-01", "2026-01-14")

    assert result.data == ()
    assert result.failed is True
    assert result.warnings[0]["code"] == "invalid_provider_response"
    assert "secret graphql message" not in result.warnings[0]["message"]


@pytest.mark.parametrize(
    "error",
    [json.JSONDecodeError("secret JSON", "not-json", 0), GarminConnectConnectionError("secret connection")],
)
def test_scheduled_workouts_maps_decode_and_connection_errors_without_exposing_details(error: Exception):
    garmin = client()
    garmin.query_garmin_graphql.side_effect = error

    result = get_scheduled_workouts(garmin, "2026-01-01", "2026-01-14")

    assert result.data == ()
    assert result.failed is True
    expected = "invalid_provider_response" if isinstance(error, json.JSONDecodeError) else "provider_unavailable"
    assert result.warnings[0]["code"] == expected
    assert "secret" not in result.warnings[0]["message"]


def test_scheduled_workouts_maps_other_exceptions_to_sanitized_unavailable():
    garmin = client()
    garmin.query_garmin_graphql.side_effect = RuntimeError("secret implementation details")

    result = get_scheduled_workouts(garmin, "2026-01-01", "2026-01-14")

    assert result.failed is True
    assert result.warnings[0]["code"] == "provider_unavailable"
    assert "secret implementation details" not in result.warnings[0]["message"]


@pytest.mark.parametrize(
    ("provider", "method", "args", "returned"),
    [
        (get_daily_stats, "get_stats", ("2026-01-01",), {"stats": 1}),
        (get_sleep, "get_sleep_data", ("2026-01-01",), {"sleep": 1}),
        (get_hrv, "get_hrv_data", ("2026-01-01",), {"hrv": 1}),
        (get_training_readiness, "get_morning_training_readiness", ("2026-01-01",), {"readiness": 1}),
        (get_training_status, "get_training_status", ("2026-01-01",), {"status": 1}),
    ],
)
def test_raw_delegates_forward_calls_without_wrapping(provider, method, args, returned):
    garmin = client()
    getattr(garmin, method).return_value = returned

    assert provider(garmin, *args) == returned
    getattr(garmin, method).assert_called_once_with(*args)


@pytest.mark.parametrize(
    ("provider", "method", "args"),
    [
        (get_daily_stats, "get_stats", ("2026-01-01",)),
        (get_sleep, "get_sleep_data", ("2026-01-01",)),
        (get_hrv, "get_hrv_data", ("2026-01-01",)),
        (get_training_readiness, "get_morning_training_readiness", ("2026-01-01",)),
        (get_training_status, "get_training_status", ("2026-01-01",)),
    ],
)
def test_raw_delegates_do_not_catch_exceptions(provider, method, args):
    garmin = client()
    getattr(garmin, method).side_effect = GarminConnectConnectionError("pass through")

    with pytest.raises(GarminConnectConnectionError, match="pass through"):
        provider(garmin, *args)
    getattr(garmin, method).assert_called_once_with(*args)
