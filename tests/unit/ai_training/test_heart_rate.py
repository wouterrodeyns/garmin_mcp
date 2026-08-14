"""Request-contract tests for the AI wellness heart-rate service."""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import json
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


def canonical_payload(
    *,
    heart_rate_values: Any = None,
    include_values: bool = True,
    resting_heart_rate: Any = 45,
    min_heart_rate: Any = 41,
    max_heart_rate: Any = 166,
    seven_day_average: Any = 46,
    **overrides: Any,
) -> dict[str, Any]:
    """Return the synthetic Garmin DTO pinned by the wellness-HR contract."""
    payload: dict[str, Any] = {
        "calendarDate": "2026-08-14",
        "startTimestampGMT": "2026-08-13T22:00:00.0",
        "endTimestampGMT": "2026-08-14T22:00:00.0",
        "startTimestampLocal": "2026-08-14T00:00:00.0",
        "endTimestampLocal": "2026-08-15T00:00:00.0",
        "restingHeartRate": resting_heart_rate,
        "minHeartRate": min_heart_rate,
        "maxHeartRate": max_heart_rate,
        "lastSevenDaysAvgRestingHeartRate": seven_day_average,
    }
    if include_values:
        payload["heartRateValues"] = (
            [[1786665600000, 48], [1786665720000, None], [1786665840000, 51]]
            if heart_rate_values is None
            else heart_rate_values
        )
    payload.update(overrides)
    return payload


def normalized_warning(date_text: str, code: str, message: str) -> dict[str, str]:
    return {"provider": "wellness_heart_rate", "date": date_text, "code": code, "message": message}


LOCAL_TIME_WARNING = "Local wellness heart-rate time is unavailable for this date."
INVALID_DTO_WARNING = "Wellness heart-rate data had an unexpected shape for this date."
PROVIDER_UNAVAILABLE_WARNING = "Wellness heart-rate data is unavailable for this date."


def empty_day(date_text: str) -> dict[str, Any]:
    """The stable unavailable per-date object required after a failed read."""
    return {
        "date": date_text,
        "available": False,
        "summary": {
            "resting_hr_bpm": None,
            "min_hr_bpm": None,
            "max_hr_bpm": None,
            "seven_day_avg_resting_hr_bpm": None,
        },
        "time_provenance": {"local_offset_minutes": None, "local_time_available": False},
        "sampling": {
            "source_points": 0,
            "valid_bpm_points": None,
            "null_bpm_points": None,
            "returned_points": 0,
            "observed_median_interval_seconds": None,
            "duration_from_sample_count_valid": False,
        },
        "points": [],
        "gaps": [],
    }


def utc_ms(minute: int, second: int = 0, day_offset: int = 0) -> int:
    """Epoch milliseconds from the canonical payload's UTC midnight."""
    return 1786665600000 + ((day_offset * 24 * 60 + minute) * 60 + second) * 1000


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
    client = RecordingClient(payloads={"2099-01-01": canonical_payload()})

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
    client = RecordingClient(
        payloads={
            f"2026-01-0{day}": canonical_payload()
            for day in range(1, 8)
        }
    )

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
    client = RecordingClient(payloads={"2026-01-01": canonical_payload()})

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


def test_absent_or_none_heart_rate_values_are_legitimate_empty_raw_days():
    client = RecordingClient(
        payloads={
            "2026-01-01": canonical_payload(include_values=False),
        }
    )

    result = get_wellness_heart_rate_service(client, "2026-01-01")

    assert result["status"] == "success"
    assert result["availability"] == {"2026-01-01": True}
    assert result["days"] == [{
        "date": "2026-01-01",
        "available": True,
        "summary": {"resting_hr_bpm": 45, "min_hr_bpm": 41, "max_hr_bpm": 166, "seven_day_avg_resting_hr_bpm": 46},
        "time_provenance": {"local_offset_minutes": 120, "local_time_available": True},
        "sampling": {"source_points": 0, "valid_bpm_points": 0, "null_bpm_points": 0, "returned_points": 0, "observed_median_interval_seconds": None, "duration_from_sample_count_valid": False},
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
        normalized_warning("2026-01-01", "provider_unavailable", PROVIDER_UNAVAILABLE_WARNING),
        normalized_warning("2026-01-02", "provider_unavailable", PROVIDER_UNAVAILABLE_WARNING),
    ]
    assert result["days"] == [empty_day("2026-01-01"), empty_day("2026-01-02")]
    assert result["availability"] == {"2026-01-01": False, "2026-01-02": False}


def test_mixed_provider_results_are_partial_success_and_keep_only_safe_warnings(
    monkeypatch: pytest.MonkeyPatch,
):
    results = iter((
        ProviderResult(data=None, failed=True, warnings=({"provider": "wellness_heart_rate", "code": "provider_unavailable", "message": "Unavailable", "secret": "no"},)),
        ProviderResult(data=canonical_payload(heart_rate_values=[])),
    ))
    monkeypatch.setattr(heart_rate, "get_wellness_heart_rate_day", lambda *_args: next(results))
    client = RecordingClient()

    result = get_wellness_heart_rate_service(client, "2026-01-01", "2026-01-02", "daily")

    assert result["status"] == "partial_success"
    assert result["error"] is None
    assert result["availability"] == {"2026-01-01": False, "2026-01-02": True}
    assert [day["date"] for day in result["days"]] == ["2026-01-01", "2026-01-02"]
    assert result["days"][0] == empty_day("2026-01-01")
    assert result["warnings"] == [
        normalized_warning("2026-01-01", "provider_unavailable", PROVIDER_UNAVAILABLE_WARNING),
    ]


def test_daily_normalizes_only_summary_and_collection_metadata_without_reading_samples():
    class HostileSample:
        def __iter__(self):
            raise AssertionError("daily mode must not iterate sample entries")

        def __getitem__(self, index: int):
            raise AssertionError(f"daily mode indexed sample entry {index}")

    client = RecordingClient(
        payloads={"2026-08-14": canonical_payload(heart_rate_values=[HostileSample()])}
    )

    result = get_wellness_heart_rate_service(client, "2026-08-14", resolution="daily")

    assert result == {
        "status": "success",
        "error": None,
        "period": {
            "start_date": "2026-08-14",
            "end_date": "2026-08-14",
            "start_time": None,
            "end_time": None,
        },
        "resolution": "daily",
        "availability": {"2026-08-14": True},
        "days": [{
            "date": "2026-08-14",
            "available": True,
            "summary": {
                "resting_hr_bpm": 45,
                "min_hr_bpm": 41,
                "max_hr_bpm": 166,
                "seven_day_avg_resting_hr_bpm": 46,
            },
            "time_provenance": {"local_offset_minutes": 120, "local_time_available": True},
            "sampling": {
                "source_points": 1,
                "valid_bpm_points": None,
                "null_bpm_points": None,
                "returned_points": 0,
                "observed_median_interval_seconds": None,
                "duration_from_sample_count_valid": False,
            },
            "points": [],
            "gaps": [],
        }],
        "warnings": [],
    }


def test_raw_projects_complete_garmin_dto_with_null_bpm_and_missing_summary_as_null():
    payload = canonical_payload(max_heart_rate=None)
    payload.pop("minHeartRate")
    client = RecordingClient(payloads={"2026-08-14": payload})

    result = get_wellness_heart_rate_service(client, "2026-08-14")

    assert result == {
        "status": "success",
        "error": None,
        "period": {
            "start_date": "2026-08-14",
            "end_date": "2026-08-14",
            "start_time": None,
            "end_time": None,
        },
        "resolution": "raw",
        "availability": {"2026-08-14": True},
        "days": [{
            "date": "2026-08-14",
            "available": True,
            "summary": {
                "resting_hr_bpm": 45,
                "min_hr_bpm": None,
                "max_hr_bpm": None,
                "seven_day_avg_resting_hr_bpm": 46,
            },
            "time_provenance": {"local_offset_minutes": 120, "local_time_available": True},
            "sampling": {
                "source_points": 3,
                "valid_bpm_points": 2,
                "null_bpm_points": 1,
                "returned_points": 3,
                "observed_median_interval_seconds": 120,
                "duration_from_sample_count_valid": False,
            },
            "points": [
                {"time_local": "2026-08-14T02:00:00+02:00", "time_utc": "2026-08-14T00:00:00Z", "bpm": 48},
                {"time_local": "2026-08-14T02:02:00+02:00", "time_utc": "2026-08-14T00:02:00Z", "bpm": None},
                {"time_local": "2026-08-14T02:04:00+02:00", "time_utc": "2026-08-14T00:04:00Z", "bpm": 51},
            ],
            "gaps": [],
        }],
        "warnings": [],
    }


def test_raw_sorts_out_of_order_and_duplicate_timestamps_without_mutating_source():
    source = [
        [1786665840000, 51],
        [1786665600000, 48],
        [1786665720000, None],
        [1786665720000, 49],
    ]
    original = [item[:] for item in source]
    client = RecordingClient(
        payloads={"2026-08-14": canonical_payload(heart_rate_values=source)}
    )

    result = get_wellness_heart_rate_service(client, "2026-08-14")

    assert [point["bpm"] for point in result["days"][0]["points"]] == [48, None, 49, 51]
    assert [point["time_utc"] for point in result["days"][0]["points"]] == [
        "2026-08-14T00:00:00Z",
        "2026-08-14T00:02:00Z",
        "2026-08-14T00:02:00Z",
        "2026-08-14T00:04:00Z",
    ]
    assert source == original


def test_absent_and_explicit_null_collections_are_valid_empty_days_without_fabricated_summary():
    client = RecordingClient(
        payloads={
            "2026-08-14": canonical_payload(
                include_values=False,
                resting_heart_rate=None,
                min_heart_rate=None,
                max_heart_rate=None,
                seven_day_average=None,
            ),
            "2026-08-15": canonical_payload(
                heartRateValues=None,
                resting_heart_rate=None,
                min_heart_rate=None,
                max_heart_rate=None,
                seven_day_average=None,
            ),
        }
    )

    result = get_wellness_heart_rate_service(
        client, "2026-08-14", "2026-08-15", resolution="daily"
    )

    assert result["status"] == "success"
    assert result["availability"] == {"2026-08-14": False, "2026-08-15": False}
    assert [day["summary"] for day in result["days"]] == [{
        "resting_hr_bpm": None,
        "min_hr_bpm": None,
        "max_hr_bpm": None,
        "seven_day_avg_resting_hr_bpm": None,
    }] * 2
    assert [day["sampling"] for day in result["days"]] == [{
        "source_points": 0,
        "valid_bpm_points": None,
        "null_bpm_points": None,
        "returned_points": 0,
        "observed_median_interval_seconds": None,
        "duration_from_sample_count_valid": False,
    }] * 2


class HostileDict(dict[Any, Any]):
    def get(self, key: object, default: object = None) -> object:
        raise AssertionError(f"unexpected mapping access: {key}")


class HostileList(list[Any]):
    def __len__(self) -> int:
        raise AssertionError("unexpected list length")

    def __iter__(self):
        raise AssertionError("unexpected list iteration")

    def __getitem__(self, index: object) -> object:
        raise AssertionError(f"unexpected list index: {index}")


def assert_invalid_dto(result: dict[str, Any], date_text: str, secret: str = "") -> None:
    assert_envelope(result)
    assert result["status"] == "error"
    assert result["error"] == {
        "code": "wellness_heart_rate_unavailable",
        "message": PUBLIC_ERROR_MESSAGES["wellness_heart_rate_unavailable"],
    }
    assert result["days"] == [empty_day(date_text)]
    assert result["warnings"] == [
        normalized_warning(date_text, "invalid_provider_response", INVALID_DTO_WARNING)
    ]
    if secret:
        assert secret not in repr(result)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        HostileDict(),
        canonical_payload(heart_rate_values=()),
        canonical_payload(heart_rate_values=HostileList()),
        canonical_payload(heart_rate_values=[(1786665600000, 48)]),
        canonical_payload(heart_rate_values=[[1786665600000]]),
        canonical_payload(heart_rate_values=[[1786665600000, 48, 2]]),
        canonical_payload(heart_rate_values=[HostileList()]),
    ],
)
def test_raw_rejects_untrusted_root_and_exact_container_violations(payload: Any):
    client = RecordingClient(payloads={"2026-08-14": payload})

    result = get_wellness_heart_rate_service(client, "2026-08-14")

    assert_invalid_dto(result, "2026-08-14")


@pytest.mark.parametrize("timestamp", [True, 1.0, "1786665600000", 10**100])
def test_raw_rejects_invalid_timestamp_types_and_out_of_range_values(timestamp: Any):
    payload = canonical_payload(heart_rate_values=[[timestamp, 50]])

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14"
    )

    assert_invalid_dto(result, "2026-08-14")


@pytest.mark.parametrize("bpm", [True, 0, 301, 1.0, "50"])
def test_raw_rejects_invalid_bpm_types_and_ranges(bpm: Any):
    payload = canonical_payload(heart_rate_values=[[1786665600000, bpm]])

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14"
    )

    assert_invalid_dto(result, "2026-08-14")


@pytest.mark.parametrize("value", [True, 0, 301, 1.0, "45"])
def test_summary_scalars_reject_malformed_supplied_values(value: Any):
    payload = canonical_payload(resting_heart_rate=value)

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14", resolution="daily"
    )

    assert_invalid_dto(result, "2026-08-14")


def test_invalid_date_is_sanitized_and_a_later_valid_date_is_kept():
    payloads = {
        "2026-08-14": {"heartRateValues": "do-not-return"},
        "2026-08-15": canonical_payload(heart_rate_values=[]),
    }

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads=payloads), "2026-08-14", "2026-08-15", resolution="daily"
    )

    assert result["status"] == "partial_success"
    assert result["error"] is None
    assert result["availability"] == {"2026-08-14": False, "2026-08-15": True}
    assert [day["date"] for day in result["days"]] == ["2026-08-14", "2026-08-15"]
    assert result["days"][0] == empty_day("2026-08-14")
    assert result["warnings"] == [
        normalized_warning("2026-08-14", "invalid_provider_response", INVALID_DTO_WARNING)
    ]
    assert "do-not-return" not in repr(result)


def test_source_collection_cap_is_checked_before_any_item_interaction(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(heart_rate, "MAX_SOURCE_POINTS_PER_DAY", 2)
    too_many = [HostileList(), HostileList(), HostileList()]
    client = RecordingClient(
        payloads={"2026-08-14": canonical_payload(heart_rate_values=too_many)}
    )

    result = get_wellness_heart_rate_service(client, "2026-08-14")

    assert_invalid_dto(result, "2026-08-14")


def test_exact_source_cap_is_accepted_after_complete_validation(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(heart_rate, "MAX_SOURCE_POINTS_PER_DAY", 2)
    values = [[1786665600000, 48], [1786665720000, 49]]

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": canonical_payload(heart_rate_values=values)}),
        "2026-08-14",
    )

    assert result["status"] == "success"
    assert result["days"][0]["sampling"]["source_points"] == 2


def test_raw_cap_applies_after_window_filtering_and_never_returns_partial_points(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(heart_rate, "MAX_RAW_POINTS", 2)
    values = [
        [1786665600000, 48],
        [1786665720000, 49],
        [1786665840000, 50],
    ]
    payload = canonical_payload(heart_rate_values=values)
    client = RecordingClient(payloads={"2026-08-14": payload})

    selected_exactly_at_cap = get_wellness_heart_rate_service(
        client, "2026-08-14", start_time="02:00", end_time="02:04"
    )
    too_large = get_wellness_heart_rate_service(client, "2026-08-14")

    assert selected_exactly_at_cap["status"] == "success"
    assert selected_exactly_at_cap["days"][0]["sampling"] == {
        "source_points": 3,
        "valid_bpm_points": 2,
        "null_bpm_points": 0,
        "returned_points": 2,
        "observed_median_interval_seconds": 120,
        "duration_from_sample_count_valid": False,
    }
    assert too_large["status"] == "error"
    assert too_large["error"] == {
        "code": "raw_response_too_large",
        "message": PUBLIC_ERROR_MESSAGES["raw_response_too_large"],
    }
    assert too_large["availability"] == {}
    assert too_large["days"] == []
    assert too_large["warnings"] == []


def test_utc_and_local_time_projection_use_verified_plus_two_hour_offset():
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": canonical_payload()}), "2026-08-14"
    )

    day = result["days"][0]
    assert day["time_provenance"] == {"local_offset_minutes": 120, "local_time_available": True}
    assert day["points"][0] == {
        "time_local": "2026-08-14T02:00:00+02:00",
        "time_utc": "2026-08-14T00:00:00Z",
        "bpm": 48,
    }


def test_raw_utc_projection_preserves_exact_negative_and_near_maximum_milliseconds():
    payload = canonical_payload(
        heart_rate_values=[[-1, 48], [253402300799999, 49]],
        startTimestampGMT=None,
    )

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14"
    )

    assert result["status"] == "success"
    assert [point["time_utc"] for point in result["days"][0]["points"]] == [
        "1969-12-31T23:59:59.999000Z",
        "9999-12-31T23:59:59.999000Z",
    ]
    assert [point["time_local"] for point in result["days"][0]["points"]] == [None, None]


def test_local_projection_overflow_is_a_sanitized_invalid_provider_response():
    payload = canonical_payload(heart_rate_values=[[253402300799999, 49]])

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14"
    )

    assert_invalid_dto(result, "2026-08-14")


def test_exact_dict_with_hostile_colliding_key_is_rejected_before_field_lookup():
    class HostileCollidingKey:
        def __init__(self):
            self.armed = False

        def __hash__(self) -> int:
            return hash("restingHeartRate")

        def __eq__(self, other: object) -> bool:
            if self.armed:
                raise AssertionError("hostile key comparison must not run")
            return False

    hostile_key = HostileCollidingKey()
    payload: dict[Any, Any] = {hostile_key: "secret-colliding-key"}
    payload.update(canonical_payload())
    hostile_key.armed = True

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14"
    )

    assert_invalid_dto(result, "2026-08-14", secret="secret-colliding-key")


def test_timestamp_projection_source_contains_no_float_epoch_conversion_path():
    source = inspect.getsource(heart_rate)

    assert "timestamp_ms / 1000" not in source
    assert "fromtimestamp(" not in source


@pytest.mark.parametrize(
    "overrides",
    [
        {"startTimestampGMT": None},
        {"startTimestampGMT": "not-a-timestamp"},
        {"startTimestampGMT": "2026-08-13T22:00:00+00:00"},
        {"endTimestampLocal": "2026-08-15T00:00:00+01:00"},
    ],
)
@pytest.mark.parametrize("resolution", ["raw", "daily"])
def test_unwindowed_raw_and_daily_keep_facts_when_local_provenance_is_unavailable(
    overrides: dict[str, Any], resolution: str
):
    payload = canonical_payload(**overrides)

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14", resolution=resolution
    )

    assert result["status"] == "success"
    assert result["error"] is None
    assert result["availability"] == {"2026-08-14": True}
    assert result["days"][0]["time_provenance"] == {
        "local_offset_minutes": None,
        "local_time_available": False,
    }
    assert result["warnings"] == [
        normalized_warning("2026-08-14", "local_time_unavailable", LOCAL_TIME_WARNING)
    ]
    if resolution == "raw":
        assert result["days"][0]["points"][0] == {
            "time_local": None,
            "time_utc": "2026-08-14T00:00:00Z",
            "bpm": 48,
        }
    else:
        assert result["days"][0]["points"] == []


def test_offset_transition_is_unavailable_without_invalidating_an_unwindowed_raw_dto():
    payload = canonical_payload(endTimestampLocal="2026-08-14T23:00:00.0")

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14"
    )

    assert result["status"] == "success"
    assert result["days"][0]["time_provenance"]["local_time_available"] is False
    assert result["warnings"] == [
        normalized_warning("2026-08-14", "local_time_unavailable", LOCAL_TIME_WARNING)
    ]


def test_fractional_minute_offset_is_unavailable_without_guessing_local_time():
    payload = canonical_payload(startTimestampLocal="2026-08-14T00:00:00.500")

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14"
    )

    assert result["status"] == "success"
    assert result["days"][0]["time_provenance"] == {
        "local_offset_minutes": None,
        "local_time_available": False,
    }
    assert result["days"][0]["points"][0]["time_local"] is None
    assert result["warnings"] == [
        normalized_warning("2026-08-14", "local_time_unavailable", LOCAL_TIME_WARNING)
    ]


@pytest.mark.parametrize("resolution", ["raw", "5m"])
def test_explicit_window_and_binned_modes_fail_date_when_local_time_is_unavailable(resolution: str):
    payload = canonical_payload(startTimestampGMT=None)
    kwargs = {"start_time": "02:00", "end_time": "02:05"} if resolution == "raw" else {}

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14", resolution=resolution, **kwargs
    )

    assert result["status"] == "error"
    assert result["error"] == {
        "code": "wellness_heart_rate_unavailable",
        "message": PUBLIC_ERROR_MESSAGES["wellness_heart_rate_unavailable"],
    }
    assert result["availability"] == {"2026-08-14": False}
    assert result["days"] == [empty_day("2026-08-14")]
    assert result["warnings"] == [
        normalized_warning("2026-08-14", "local_time_unavailable", LOCAL_TIME_WARNING)
    ]


def test_raw_window_includes_start_and_excludes_end_using_garmin_local_wall_time():
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": canonical_payload()}),
        "2026-08-14",
        start_time="02:00",
        end_time="02:02",
    )

    assert result["status"] == "success"
    assert result["days"][0]["points"] == [{
        "time_local": "2026-08-14T02:00:00+02:00",
        "time_utc": "2026-08-14T00:00:00Z",
        "bpm": 48,
    }]


def test_raw_sampling_counts_and_median_use_selected_sorted_samples_and_positive_intervals_only():
    values = [
        [1786666200000, None],
        [1786665720000, 49],
        [1786665600000, 48],
        [1786665720000, None],
    ]

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": canonical_payload(heart_rate_values=values)}),
        "2026-08-14",
    )

    assert result["days"][0]["sampling"] == {
        "source_points": 4,
        "valid_bpm_points": 2,
        "null_bpm_points": 2,
        "returned_points": 4,
        "observed_median_interval_seconds": 300,
        "duration_from_sample_count_valid": False,
    }


@pytest.mark.parametrize(
    ("resolution", "payload", "expected_available"),
    [
        ("raw", canonical_payload(heart_rate_values=[]), True),
        (
            "raw",
            canonical_payload(
                heart_rate_values=[[1786665600000, None]],
                resting_heart_rate=None,
                min_heart_rate=None,
                max_heart_rate=None,
                seven_day_average=None,
            ),
            True,
        ),
        (
            "raw",
            canonical_payload(
                heart_rate_values=[],
                resting_heart_rate=None,
                min_heart_rate=None,
                max_heart_rate=None,
                seven_day_average=None,
            ),
            False,
        ),
        (
            "5m",
            canonical_payload(
                heart_rate_values=[[1786665600000, 48]],
                resting_heart_rate=None,
                min_heart_rate=None,
                max_heart_rate=None,
                seven_day_average=None,
            ),
            True,
        ),
    ],
)
def test_task_three_availability_rules_distinguish_summary_samples_and_empty_days(
    resolution: str, payload: dict[str, Any], expected_available: bool
):
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}), "2026-08-14", resolution=resolution
    )

    assert result["status"] == "success"
    assert result["availability"] == {"2026-08-14": expected_available}
    assert result["days"][0]["available"] is expected_available
    if resolution == "5m":
        assert result["days"][0]["points"][0]["sample_count"] == 1
        assert result["days"][0]["sampling"]["returned_points"] == 1


def test_internal_normalizer_runtime_error_is_not_sanitized_as_provider_data(
    monkeypatch: pytest.MonkeyPatch,
):
    def unexpected_runtime_error(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("trusted normalizer fault")

    monkeypatch.setattr(heart_rate, "_normalize_day_facts", unexpected_runtime_error, raising=False)

    with pytest.raises(RuntimeError, match="trusted normalizer fault"):
        get_wellness_heart_rate_service(
            RecordingClient(payloads={"2026-08-14": canonical_payload()}), "2026-08-14"
        )


@pytest.mark.parametrize(
    ("resolution", "start_local", "end_local", "start_utc", "end_utc"),
    [
        ("5m", "2026-08-14T02:05:00+02:00", "2026-08-14T02:10:00+02:00", "2026-08-14T00:05:00Z", "2026-08-14T00:10:00Z"),
        ("15m", "2026-08-14T02:00:00+02:00", "2026-08-14T02:15:00+02:00", "2026-08-14T00:00:00Z", "2026-08-14T00:15:00Z"),
        ("30m", "2026-08-14T02:00:00+02:00", "2026-08-14T02:30:00+02:00", "2026-08-14T00:00:00Z", "2026-08-14T00:30:00Z"),
        ("60m", "2026-08-14T02:00:00+02:00", "2026-08-14T03:00:00+02:00", "2026-08-14T00:00:00Z", "2026-08-14T01:00:00Z"),
    ],
)
def test_binned_points_align_to_fixed_garmin_local_boundaries(
    resolution: str, start_local: str, end_local: str, start_utc: str, end_utc: str,
):
    source = [
        [utc_ms(9), 102],
        [utc_ms(7, 30), 101],
        [utc_ms(16), None],
        [utc_ms(8), 102],
    ]
    original = [entry[:] for entry in source]

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": canonical_payload(heart_rate_values=source)}),
        "2026-08-14",
        resolution=resolution,
    )

    point = result["days"][0]["points"][0]
    assert list(point) == [
        "start_time_local", "end_time_local", "start_time_utc", "end_time_utc",
        "min_bpm", "mean_bpm", "max_bpm", "sample_count",
    ]
    assert point == {
        "start_time_local": start_local,
        "end_time_local": end_local,
        "start_time_utc": start_utc,
        "end_time_utc": end_utc,
        "min_bpm": 101,
        "mean_bpm": 101.7,
        "max_bpm": 102,
        "sample_count": 3,
    }
    assert source == original


def test_binned_reducer_excludes_nulls_and_empty_bins_and_keeps_deterministic_order():
    source = [
        [utc_ms(21), 80],
        [utc_ms(16), None],
        [utc_ms(7), 101],
        [utc_ms(8), 102],
        [utc_ms(9), 102],
    ]

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": canonical_payload(heart_rate_values=source)}),
        "2026-08-14",
        resolution="5m",
    )

    points = result["days"][0]["points"]
    assert [point["start_time_utc"] for point in points] == [
        "2026-08-14T00:05:00Z", "2026-08-14T00:20:00Z",
    ]
    assert points[0]["mean_bpm"] == 101.7
    assert points[1]["sample_count"] == 1
    assert result["days"][0]["sampling"] == {
        "source_points": 5,
        "valid_bpm_points": 4,
        "null_bpm_points": 1,
        "returned_points": 2,
        "observed_median_interval_seconds": 180,
        "duration_from_sample_count_valid": False,
    }
    forbidden = {"coverage", "zone", "zone_seconds", "duration", "duration_seconds"}
    assert all(not (set(point) & forbidden) for point in points)


def test_binned_availability_uses_bins_or_summary_and_null_only_data_stays_unavailable():
    no_summary = {
        "resting_heart_rate": None,
        "min_heart_rate": None,
        "max_heart_rate": None,
        "seven_day_average": None,
    }
    client = RecordingClient(payloads={
        "2026-08-14": canonical_payload(heart_rate_values=[[utc_ms(7), 48]], **no_summary),
        "2026-08-15": canonical_payload(heart_rate_values=[],),
        "2026-08-16": canonical_payload(heart_rate_values=[[utc_ms(7), None]], **no_summary),
    })

    result = get_wellness_heart_rate_service(
        client, "2026-08-14", "2026-08-16", resolution="5m"
    )

    by_date = {day["date"]: day for day in result["days"]}
    assert result["status"] == "success"
    assert result["availability"] == {
        "2026-08-14": True, "2026-08-15": True, "2026-08-16": False,
    }
    assert by_date["2026-08-14"]["sampling"]["returned_points"] == 1
    assert by_date["2026-08-15"]["points"] == []
    assert by_date["2026-08-16"]["sampling"] == {
        "source_points": 1,
        "valid_bpm_points": 0,
        "null_bpm_points": 1,
        "returned_points": 0,
        "observed_median_interval_seconds": None,
        "duration_from_sample_count_valid": False,
    }


@pytest.mark.parametrize("elapsed_seconds", [299, 300, 301])
def test_raw_gaps_use_only_adjacent_valid_samples_at_the_exact_threshold(elapsed_seconds: int):
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={
            "2026-08-14": canonical_payload(heart_rate_values=[
                [utc_ms(0), 48], [utc_ms(0, elapsed_seconds), 49],
            ]),
        }),
        "2026-08-14",
    )

    expected = [] if elapsed_seconds < GAP_THRESHOLD_SECONDS else [{
        "start_time_local": "2026-08-14T02:00:00+02:00",
        "end_time_local": f"2026-08-14T02:{elapsed_seconds // 60:02d}:{elapsed_seconds % 60:02d}+02:00",
        "start_time_utc": "2026-08-14T00:00:00Z",
        "end_time_utc": f"2026-08-14T00:{elapsed_seconds // 60:02d}:{elapsed_seconds % 60:02d}Z",
        "elapsed_minutes": round(elapsed_seconds / 60, 1),
    }]
    assert result["days"][0]["gaps"] == expected


def test_gaps_ignore_nulls_duplicates_and_out_of_order_input_without_inventing_boundaries():
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={
            "2026-08-14": canonical_payload(heart_rate_values=[
                [utc_ms(5), 51], [utc_ms(0), 48], [utc_ms(2), None], [utc_ms(0), 49],
            ]),
        }),
        "2026-08-14",
    )

    assert result["days"][0]["gaps"] == [{
        "start_time_local": "2026-08-14T02:00:00+02:00",
        "end_time_local": "2026-08-14T02:05:00+02:00",
        "start_time_utc": "2026-08-14T00:00:00Z",
        "end_time_utc": "2026-08-14T00:05:00Z",
        "elapsed_minutes": 5.0,
    }]


def test_gaps_are_calculated_after_window_filtering_and_can_have_unknown_raw_local_time():
    windowed = get_wellness_heart_rate_service(
        RecordingClient(payloads={
            "2026-08-14": canonical_payload(heart_rate_values=[
                [utc_ms(0), 48], [utc_ms(2), 49], [utc_ms(7), 50], [utc_ms(10), 51],
            ]),
        }),
        "2026-08-14",
        start_time="02:02",
        end_time="02:10",
    )
    local_unknown = get_wellness_heart_rate_service(
        RecordingClient(payloads={
            "2026-08-14": canonical_payload(
                heart_rate_values=[[utc_ms(0), 48], [utc_ms(5), 49]], startTimestampGMT=None,
            ),
        }),
        "2026-08-14",
    )
    daily = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": canonical_payload()}), "2026-08-14", resolution="daily"
    )

    assert windowed["days"][0]["gaps"] == [{
        "start_time_local": "2026-08-14T02:02:00+02:00",
        "end_time_local": "2026-08-14T02:07:00+02:00",
        "start_time_utc": "2026-08-14T00:02:00Z",
        "end_time_utc": "2026-08-14T00:07:00Z",
        "elapsed_minutes": 5.0,
    }]
    assert local_unknown["days"][0]["gaps"][0] == {
        "start_time_local": None,
        "end_time_local": None,
        "start_time_utc": "2026-08-14T00:00:00Z",
        "end_time_utc": "2026-08-14T00:05:00Z",
        "elapsed_minutes": 5.0,
    }
    assert daily["days"][0]["gaps"] == []


def test_failed_dates_keep_fixed_empty_days_warnings_in_date_order_and_later_reads_continue(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []
    outcomes = iter((
        ProviderResult(data=None, failed=True, warnings=({"secret": "provider-token"},)),
        ProviderResult(data={"heartRateValues": "payload-secret"}),
        ProviderResult(data=canonical_payload(startTimestampGMT=None)),
        ProviderResult(data=canonical_payload(heart_rate_values=[[utc_ms(7), 48]])),
    ))

    def next_outcome(_client: Any, date_text: str) -> ProviderResult:
        calls.append(date_text)
        return next(outcomes)

    monkeypatch.setattr(heart_rate, "get_wellness_heart_rate_day", next_outcome)
    result = get_wellness_heart_rate_service(
        RecordingClient(), "2026-08-14", "2026-08-17", resolution="60m"
    )

    assert calls == ["2026-08-14", "2026-08-15", "2026-08-16", "2026-08-17"]
    assert result["status"] == "partial_success"
    assert [day["date"] for day in result["days"]] == calls
    assert result["days"][:3] == [empty_day(date_text) for date_text in calls[:3]]
    assert result["availability"] == {
        day["date"]: day["available"] for day in result["days"]
    }
    assert result["warnings"] == [
        normalized_warning("2026-08-14", "provider_unavailable", PROVIDER_UNAVAILABLE_WARNING),
        normalized_warning("2026-08-15", "invalid_provider_response", INVALID_DTO_WARNING),
        normalized_warning("2026-08-16", "local_time_unavailable", LOCAL_TIME_WARNING),
    ]
    serialized = json.dumps(result, separators=(",", ":"), ensure_ascii=False)
    assert "provider-token" not in serialized
    assert "payload-secret" not in serialized


def test_all_legitimately_empty_dates_are_a_success_with_complete_unavailable_days():
    no_summary = {
        "resting_heart_rate": None,
        "min_heart_rate": None,
        "max_heart_rate": None,
        "seven_day_average": None,
    }
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={
            "2026-08-14": canonical_payload(heart_rate_values=[], **no_summary),
            "2026-08-15": canonical_payload(heart_rate_values=[], **no_summary),
        }),
        "2026-08-14",
        "2026-08-15",
        resolution="daily",
    )

    assert result["status"] == "success"
    assert result["error"] is None
    assert result["availability"] == {"2026-08-14": False, "2026-08-15": False}
    assert [day["date"] for day in result["days"]] == ["2026-08-14", "2026-08-15"]
    assert result["warnings"] == []


def test_serialized_result_cap_accepts_the_exact_size_and_refuses_one_byte_over(
    monkeypatch: pytest.MonkeyPatch,
):
    client = RecordingClient(payloads={"2026-08-14": canonical_payload()})
    baseline = get_wellness_heart_rate_service(client, "2026-08-14")
    byte_count = len(json.dumps(baseline, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(heart_rate, "MAX_SERIALIZED_BYTES", byte_count)
    assert get_wellness_heart_rate_service(client, "2026-08-14") == baseline

    monkeypatch.setattr(heart_rate, "MAX_SERIALIZED_BYTES", byte_count - 1)
    refused = get_wellness_heart_rate_service(client, "2026-08-14")
    assert_error(refused, "response_too_large")


def test_binned_actual_cap_never_silently_truncates_even_when_projection_allows_request(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(heart_rate, "MAX_RETURNED_BINS", 1)
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={
            "2026-08-14": canonical_payload(heart_rate_values=[
                [utc_ms(0), 48], [utc_ms(0, day_offset=1), 49],
            ]),
        }),
        "2026-08-14",
        resolution="5m",
        start_time="02:00",
        end_time="02:05",
    )

    assert_error(result, "request_too_large")


def test_binned_actual_cap_is_request_scoped_across_completed_dates(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(heart_rate, "MAX_RETURNED_BINS", 4)
    monkeypatch.setattr(heart_rate, "MAX_SERIALIZED_BYTES", 10_000_000)
    accepted_client = RecordingClient(payloads={
        "2026-08-14": canonical_payload(heart_rate_values=[
            [utc_ms(0, day_offset=0), 48], [utc_ms(0, day_offset=1), 49],
        ]),
        "2026-08-15": canonical_payload(heart_rate_values=[
            [utc_ms(0, day_offset=2), 50], [utc_ms(0, day_offset=3), 51],
        ]),
    })
    rejected_client = RecordingClient(payloads={
        "2026-08-14": canonical_payload(heart_rate_values=[
            [utc_ms(0, day_offset=0), 48], [utc_ms(0, day_offset=1), 49],
        ]),
        "2026-08-15": canonical_payload(heart_rate_values=[
            [utc_ms(0, day_offset=2), 50], [utc_ms(0, day_offset=3), 51],
            [utc_ms(0, day_offset=4), 52],
        ]),
    })
    request = {
        "start_date": "2026-08-14",
        "end_date": "2026-08-15",
        "resolution": "5m",
        "start_time": "02:00",
        "end_time": "02:10",
    }

    accepted = get_wellness_heart_rate_service(accepted_client, **request)
    rejected = get_wellness_heart_rate_service(rejected_client, **request)

    assert accepted["status"] == "success"
    assert [day["sampling"]["returned_points"] for day in accepted["days"]] == [2, 2]
    assert accepted_client.calls == ["2026-08-14", "2026-08-15"]
    assert_error(rejected, "request_too_large")
    assert rejected_client.calls == ["2026-08-14", "2026-08-15"]


@pytest.mark.parametrize(
    ("timestamp_ms", "bounds"),
    [
        (
            253402300799999,
            {
                "startTimestampGMT": "9999-12-31T00:00:00.0",
                "endTimestampGMT": "9999-12-31T00:00:00.0",
                "startTimestampLocal": "9999-12-31T00:00:00.0",
                "endTimestampLocal": "9999-12-31T00:00:00.0",
            },
        ),
        (
            253402300799999,
            {
                "startTimestampGMT": "9999-12-31T02:00:00.0",
                "endTimestampGMT": "9999-12-31T23:00:00.0",
                "startTimestampLocal": "9999-12-31T00:00:00.0",
                "endTimestampLocal": "9999-12-31T21:00:00.0",
            },
        ),
    ],
)
def test_binned_boundary_overflow_is_a_sanitized_invalid_provider_response(
    timestamp_ms: int, bounds: dict[str, str],
):
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={
            "9999-12-31": canonical_payload(
                heart_rate_values=[[timestamp_ms, 48]], **bounds,
            ),
        }),
        "9999-12-31",
        resolution="5m",
    )

    assert result["status"] == "error"
    assert result["error"] == {
        "code": "wellness_heart_rate_unavailable",
        "message": PUBLIC_ERROR_MESSAGES["wellness_heart_rate_unavailable"],
    }
    assert result["availability"] == {"9999-12-31": False}
    assert result["days"] == [empty_day("9999-12-31")]
    assert result["warnings"] == [
        normalized_warning("9999-12-31", "invalid_provider_response", INVALID_DTO_WARNING)
    ]
    assert str(timestamp_ms) not in json.dumps(result, separators=(",", ":"), ensure_ascii=False)


def test_binned_null_boundary_sample_is_kept_as_summary_only_data():
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={
            "9999-12-31": canonical_payload(
                heart_rate_values=[[253402300799999, None]],
                startTimestampGMT="9999-12-31T00:00:00.0",
                endTimestampGMT="9999-12-31T00:00:00.0",
                startTimestampLocal="9999-12-31T00:00:00.0",
                endTimestampLocal="9999-12-31T00:00:00.0",
            ),
        }),
        "9999-12-31",
        resolution="5m",
    )

    assert result["status"] == "success"
    assert result["availability"] == {"9999-12-31": True}
    assert result["days"][0]["points"] == []
    assert result["days"][0]["sampling"] == {
        "source_points": 1,
        "valid_bpm_points": 0,
        "null_bpm_points": 1,
        "returned_points": 0,
        "observed_median_interval_seconds": None,
        "duration_from_sample_count_valid": False,
    }


def test_binned_out_of_window_boundary_sample_remains_valid_summary_only_data():
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={
            "9999-12-31": canonical_payload(
                heart_rate_values=[[253402300799999, 48]],
                startTimestampGMT="9999-12-31T00:00:00.0",
                endTimestampGMT="9999-12-31T00:00:00.0",
                startTimestampLocal="9999-12-31T00:00:00.0",
                endTimestampLocal="9999-12-31T00:00:00.0",
            ),
        }),
        "9999-12-31",
        resolution="5m",
        start_time="00:00",
        end_time="00:01",
    )

    assert result["status"] == "success"
    assert result["availability"] == {"9999-12-31": True}
    assert result["days"][0]["points"] == []
    assert result["days"][0]["sampling"] == {
        "source_points": 1,
        "valid_bpm_points": 0,
        "null_bpm_points": 0,
        "returned_points": 0,
        "observed_median_interval_seconds": None,
        "duration_from_sample_count_valid": False,
    }


def test_trusted_bin_boundary_runtime_error_is_not_sanitized(
    monkeypatch: pytest.MonkeyPatch,
):
    def unexpected_runtime_error(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("trusted bin-bound fault")

    monkeypatch.setattr(heart_rate, "_bin_bounds", unexpected_runtime_error, raising=False)

    with pytest.raises(RuntimeError, match="trusted bin-bound fault"):
        get_wellness_heart_rate_service(
            RecordingClient(payloads={"2026-08-14": canonical_payload()}),
            "2026-08-14",
            resolution="5m",
        )


@pytest.mark.parametrize("target", ["bin", "gap", "compact", "dumps"])
def test_local_reducer_and_serializer_runtime_errors_are_not_sanitized(
    monkeypatch: pytest.MonkeyPatch, target: str,
):
    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f"trusted {target} fault")

    kwargs: dict[str, Any] = {}
    if target == "bin":
        monkeypatch.setattr(heart_rate, "_binned_points", fail, raising=False)
        kwargs["resolution"] = "5m"
    elif target == "gap":
        monkeypatch.setattr(heart_rate, "_gap_points", fail, raising=False)
    elif target == "compact":
        monkeypatch.setattr(heart_rate, "_compact_size", fail, raising=False)
    else:
        monkeypatch.setattr(heart_rate.json, "dumps", fail)

    with pytest.raises(RuntimeError, match=f"trusted {target} fault"):
        get_wellness_heart_rate_service(
            RecordingClient(payloads={"2026-08-14": canonical_payload()}), "2026-08-14", **kwargs
        )
