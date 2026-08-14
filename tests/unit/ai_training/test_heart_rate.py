"""Request-contract tests for the AI wellness heart-rate service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

import garmin_mcp.ai_training.heart_rate as heart_rate
from garmin_mcp.ai_training.heart_rate import (
    BIN_MINUTES,
    GAP_THRESHOLD_SECONDS,
    MAX_DAYS,
    MAX_RAW_POINTS,
    MAX_RETURNED_BINS,
    MAX_SERIALIZED_BYTES,
    MAX_SOURCE_POINTS_PER_DAY,
    RESOLUTIONS,
    get_wellness_heart_rate_service,
)
from garmin_mcp.ai_training.providers import ProviderResult


PUBLIC_ERROR_MESSAGES = {
    "invalid_start_date": "start_date must be a real calendar date in YYYY-MM-DD format.",
    "invalid_end_date": "end_date must be null or a real calendar date in YYYY-MM-DD format.",
    "invalid_date_range": "start_date must be on or before end_date.",
    "date_range_too_large": "The inclusive date range must contain at most 7 dates.",
    "invalid_resolution": "resolution must be one of: daily, raw, 5m, 15m, 30m, 60m.",
    "raw_requires_single_date": "raw resolution requires a single calendar date.",
    "invalid_time_window": "start_time and end_time must be paired HH:MM values with start_time earlier than end_time; daily resolution does not accept a window.",
    "request_too_large": "The requested bin count exceeds 1000; shorten the date/time range or use a coarser resolution.",
    "client_unavailable": "The Garmin client is unavailable.",
    "wellness_heart_rate_unavailable": "Wellness heart-rate data is unavailable for every requested date.",
    "raw_response_too_large": "The raw result exceeds 1000 points; narrow the time window or choose a binned resolution.",
    "response_too_large": "The normalized result exceeds 262144 bytes; narrow the time window or choose a coarser resolution.",
}


@dataclass
class RecordingClient:
    """A small client fake that makes provider access observable."""

    payloads: dict[str, Any] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def get_heart_rates(self, date: str) -> Any:
        self.calls.append(date)
        payload = self.payloads.get(date, {})
        if isinstance(payload, Exception):
            raise payload
        return payload


def assert_envelope(result: dict[str, Any]) -> None:
    assert list(result) == [
        "status", "error", "period", "resolution", "availability", "days", "warnings",
    ]
    assert list(result["period"]) == ["start_date", "end_date", "start_time", "end_time"]
    assert isinstance(result["availability"], dict)
    assert isinstance(result["days"], list)
    assert isinstance(result["warnings"], list)


def assert_error(result: dict[str, Any], code: str) -> None:
    assert_envelope(result)
    assert result["status"] == "error"
    assert result["error"] == {"code": code, "message": PUBLIC_ERROR_MESSAGES[code]}
    assert result["availability"] == {}
    assert result["days"] == []
    assert result["warnings"] == []


def test_public_constants_and_stable_envelope_are_pinned():
    assert MAX_DAYS == 7
    assert MAX_SOURCE_POINTS_PER_DAY == 10_000
    assert MAX_RAW_POINTS == 1_000
    assert MAX_RETURNED_BINS == 1_000
    assert MAX_SERIALIZED_BYTES == 262_144
    assert GAP_THRESHOLD_SECONDS == 300
    assert RESOLUTIONS == ("daily", "raw", "5m", "15m", "30m", "60m")
    assert BIN_MINUTES == {"5m": 5, "15m": 15, "30m": 30, "60m": 60}

    result = get_wellness_heart_rate_service(None, "bad-date")

    assert_error(result, "invalid_start_date")


def test_public_error_messages_match_the_approved_literal_contract():
    assert heart_rate.ERROR_MESSAGES == PUBLIC_ERROR_MESSAGES


@pytest.mark.parametrize(
    "start_date",
    [None, True, 1, 1.0, b"2026-01-01", "2026-1-01", "2026/01/01", "2026-02-30"],
)
def test_invalid_start_date_is_rejected_before_provider_access(start_date: Any):
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, start_date)

    assert_error(result, "invalid_start_date")
    assert client.calls == []


class TextSubclass(str):
    pass


@pytest.mark.parametrize("value", [TextSubclass("2026-01-01"), True, 1, "2026-02-30"])
def test_end_date_must_be_an_exact_string_calendar_date(value: Any):
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, "2026-01-01", value)

    assert_error(result, "invalid_end_date")
    assert client.calls == []


@pytest.mark.parametrize(
    ("start_date", "end_date", "code"),
    [
        ("2026-01-02", "2026-01-01", "invalid_date_range"),
        ("2026-01-01", "2026-01-08", "date_range_too_large"),
    ],
)
def test_invalid_date_ranges_are_rejected_before_provider_access(
    start_date: str, end_date: str, code: str
):
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, start_date, end_date, "daily")

    assert_error(result, code)
    assert client.calls == []


@pytest.mark.parametrize("resolution", [None, True, 5, "RAW", "1m", TextSubclass("raw")])
def test_resolution_must_be_an_exact_supported_string(resolution: Any):
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, "2026-01-01", resolution=resolution)

    assert_error(result, "invalid_resolution")
    assert client.calls == []


def test_raw_requires_a_single_calendar_date_before_provider_access():
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, "2026-01-01", "2026-01-02")

    assert_error(result, "raw_requires_single_date")
    assert client.calls == []


@pytest.mark.parametrize(
    ("resolution", "start_time", "end_time"),
    [
        ("raw", "10:00", None),
        ("raw", None, "10:00"),
        ("raw", True, "10:00"),
        ("raw", "1:00", "10:00"),
        ("raw", "24:00", "10:00"),
        ("raw", "10:00", "10:00"),
        ("raw", "18:00", "08:00"),
        ("daily", "08:00", "09:00"),
    ],
)
def test_invalid_time_windows_are_rejected_before_provider_access(
    resolution: str, start_time: Any, end_time: Any
):
    client = RecordingClient()

    result = get_wellness_heart_rate_service(
        client, "2026-01-01", resolution=resolution, start_time=start_time, end_time=end_time
    )

    assert_error(result, "invalid_time_window")
    assert client.calls == []


@pytest.mark.parametrize("resolution", RESOLUTIONS)
def test_every_resolution_accepts_a_valid_one_date_request(resolution: str):
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, "2099-01-01", resolution=resolution)

    assert_envelope(result)
    assert result["status"] == "success"
    assert result["error"] is None
    assert result["period"] == {
        "start_date": "2099-01-01", "end_date": "2099-01-01", "start_time": None, "end_time": None,
    }
    assert result["resolution"] == resolution
    assert client.calls == ["2099-01-01"]


def test_omitted_end_date_resolves_to_start_date():
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, "2026-01-03", resolution="daily")

    assert result["period"]["start_date"] == "2026-01-03"
    assert result["period"]["end_date"] == "2026-01-03"


def test_exact_seven_day_boundary_is_accepted_when_projected_bins_fit():
    client = RecordingClient()

    result = get_wellness_heart_rate_service(
        client, "2026-01-01", "2026-01-07", resolution="15m"
    )

    assert result["status"] == "success"
    assert client.calls == [
        "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07",
    ]


def test_oversized_date_range_is_rejected_before_date_list_materialization(
    monkeypatch: pytest.MonkeyPatch,
):
    requested_dates_calls: list[tuple[object, object]] = []

    def unexpected_requested_dates(start: object, end: object) -> list[str]:
        requested_dates_calls.append((start, end))
        raise AssertionError("oversized ranges must not materialize date strings")

    monkeypatch.setattr(heart_rate, "_requested_dates", unexpected_requested_dates)
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, "0001-01-01", "9999-12-31", "daily")

    assert_error(result, "date_range_too_large")
    assert requested_dates_calls == []
    assert client.calls == []


def test_binned_projection_cap_precedes_client_access(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(heart_rate, "MAX_RETURNED_BINS", 2)
    client = RecordingClient()

    accepted = get_wellness_heart_rate_service(
        client, "2026-01-01", resolution="5m", start_time="00:00", end_time="00:10"
    )
    rejected = get_wellness_heart_rate_service(
        client, "2026-01-01", resolution="5m", start_time="00:00", end_time="00:11"
    )

    assert accepted["status"] == "success"
    assert_error(rejected, "request_too_large")
    assert client.calls == ["2026-01-01"]


def test_invalid_input_precedes_the_missing_client_error():
    result = get_wellness_heart_rate_service(None, "not-a-date", resolution="wat")

    assert_error(result, "invalid_start_date")


def test_missing_client_is_a_structured_error_after_valid_validation():
    result = get_wellness_heart_rate_service(None, "2026-01-01")

    assert_error(result, "client_unavailable")


def test_valid_provider_requests_are_one_per_date_in_date_order():
    client = RecordingClient()

    result = get_wellness_heart_rate_service(
        client, "2026-01-02", "2026-01-04", resolution="daily"
    )

    assert result["status"] == "success"
    assert client.calls == ["2026-01-02", "2026-01-03", "2026-01-04"]


def test_nonfailed_provider_result_is_a_legitimate_empty_day_for_now():
    client = RecordingClient(payloads={"2026-01-01": {"heartRateValues": [[1, 99]]}})

    result = get_wellness_heart_rate_service(client, "2026-01-01")

    assert result["status"] == "success"
    assert result["availability"] == {"2026-01-01": False}
    assert result["days"] == [{
        "date": "2026-01-01",
        "available": False,
        "summary": {"resting_hr_bpm": None, "min_hr_bpm": None, "max_hr_bpm": None, "seven_day_avg_resting_hr_bpm": None},
        "time_provenance": {"local_offset_minutes": None, "local_time_available": False},
        "sampling": {"source_points": 0, "valid_bpm_points": None, "null_bpm_points": None, "returned_points": 0, "observed_median_interval_seconds": None, "duration_from_sample_count_valid": False},
        "points": [],
        "gaps": [],
    }]


def test_all_failed_provider_dates_return_one_stable_unavailable_error(
    monkeypatch: pytest.MonkeyPatch,
):
    def failed_day(_client: Any, _date: str) -> ProviderResult:
        return ProviderResult(
            data=None,
            failed=True,
            warnings=({"provider": "wellness_heart_rate", "code": "provider_unavailable", "message": "Unavailable", "private": "nope"},),
        )

    monkeypatch.setattr(heart_rate, "get_wellness_heart_rate_day", failed_day)
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, "2026-01-01", "2026-01-02", "daily")

    assert_envelope(result)
    assert result["status"] == "error"
    assert result["error"] == {
        "code": "wellness_heart_rate_unavailable",
        "message": PUBLIC_ERROR_MESSAGES["wellness_heart_rate_unavailable"],
    }
    assert result["warnings"] == [
        {"provider": "wellness_heart_rate", "code": "provider_unavailable", "message": "Unavailable", "date": "2026-01-01"},
        {"provider": "wellness_heart_rate", "code": "provider_unavailable", "message": "Unavailable", "date": "2026-01-02"},
    ]


def test_mixed_provider_results_are_partial_success_and_keep_only_safe_warnings(
    monkeypatch: pytest.MonkeyPatch,
):
    results = iter((
        ProviderResult(data=None, failed=True, warnings=({"provider": "wellness_heart_rate", "code": "provider_unavailable", "message": "Unavailable", "secret": "no"},)),
        ProviderResult(data={}),
    ))
    monkeypatch.setattr(heart_rate, "get_wellness_heart_rate_day", lambda *_args: next(results))
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, "2026-01-01", "2026-01-02", "daily")

    assert result["status"] == "partial_success"
    assert result["error"] is None
    assert result["availability"] == {"2026-01-01": False, "2026-01-02": False}
    assert [day["date"] for day in result["days"]] == ["2026-01-02"]
    assert result["warnings"] == [
        {"provider": "wellness_heart_rate", "code": "provider_unavailable", "message": "Unavailable", "date": "2026-01-01"},
    ]
