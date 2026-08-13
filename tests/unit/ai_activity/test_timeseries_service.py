"""Direct-call contract tests for bounded activity time-series orchestration."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import json
from typing import Any

import pytest

from garmin_mcp.ai_activity.providers import OriginalFitDownload
from garmin_mcp.ai_activity.timeseries import FIT_EPOCH, ParseResult, RecordFact, WindowResult


MAX_ACTIVITY_ID = 9_007_199_254_740_991
MAX_FIT_ELAPSED_SECONDS = 4_026_531_838
MAX_RECORD_MESSAGES = 100_000
MAX_RETURNED_POINTS = 600


ERRORS = {
    "invalid_activity_id": {
        "provider": "input",
        "code": "invalid_activity_id",
        "message": "activity_id must be a positive integer or ASCII decimal string from 1 through 9007199254740991.",
    },
    "invalid_start_seconds": {
        "provider": "input",
        "code": "invalid_start_seconds",
        "message": "start_seconds must be an integer from 0 through 4026531838.",
    },
    "invalid_duration_seconds": {
        "provider": "input",
        "code": "invalid_duration_seconds",
        "message": "duration_seconds must be an integer from 1 through 86400.",
    },
    "invalid_resolution_seconds": {
        "provider": "input",
        "code": "invalid_resolution_seconds",
        "message": "resolution_seconds must be an integer from 1 through 300.",
    },
    "point_limit_exceeded": {
        "provider": "input",
        "code": "point_limit_exceeded",
        "message": "ceil(duration_seconds / resolution_seconds) must not exceed 600.",
    },
    "client_unavailable": {
        "provider": "client",
        "code": "client_unavailable",
        "message": "Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.",
    },
    "download_failed": {
        "provider": "garmin",
        "code": "download_failed",
        "message": "Original FIT download is unavailable. Retry later or re-authenticate.",
    },
    "invalid_download_payload": {
        "provider": "garmin",
        "code": "invalid_download_payload",
        "message": "Original FIT download returned an invalid payload.",
    },
    "fit_download_too_large": {
        "provider": "garmin",
        "code": "fit_download_too_large",
        "message": "Original FIT download exceeds the 25 MB limit.",
    },
    "invalid_fit_payload": {
        "provider": "fit",
        "code": "invalid_fit_payload",
        "message": "Original FIT data is invalid or unavailable.",
    },
    "unsafe_fit_archive": {
        "provider": "fit",
        "code": "unsafe_fit_archive",
        "message": "Original FIT archive violates safety limits.",
    },
    "fit_member_too_large": {
        "provider": "fit",
        "code": "fit_member_too_large",
        "message": "Original FIT member exceeds the 25 MB limit.",
    },
    "fit_parse_failed": {
        "provider": "fit",
        "code": "fit_parse_failed",
        "message": "Original FIT data could not be parsed.",
    },
    "chained_fit_unsupported": {
        "provider": "fit",
        "code": "chained_fit_unsupported",
        "message": "Chained FIT files are not supported.",
    },
    "frame_limit_exceeded": {
        "provider": "fit",
        "code": "frame_limit_exceeded",
        "message": "Original FIT data exceeds the 200000-frame limit.",
    },
    "definition_field_limit_exceeded": {
        "provider": "fit",
        "code": "definition_field_limit_exceeded",
        "message": "Original FIT data exceeds the 128-field definition limit.",
    },
    "record_limit_exceeded": {
        "provider": "fit",
        "code": "record_limit_exceeded",
        "message": "Original FIT data exceeds the 100000-record limit.",
    },
    "no_timestamped_records": {
        "provider": "fit",
        "code": "no_timestamped_records",
        "message": "Original FIT data contains no usable timestamped record messages.",
    },
}


def _empty_series() -> dict[str, Any]:
    return {
        "elapsed_seconds": [],
        "timestamp": [],
        "sample_count": [],
        "heart_rate_bpm": {"average": [], "minimum": [], "maximum": []},
        "speed_mps": {"average": []},
        "pace_seconds_per_km": {"average": [], "fastest": [], "slowest": []},
        "cadence_rpm": {"average": []},
        "power_w": {"average": []},
        "altitude_m": {"average": []},
        "grade_pct": {"average": []},
    }


def _empty_window_result(*, next_start_seconds: int | None = None) -> WindowResult:
    return WindowResult(
        sampling={
            "source_records": 0,
            "returned_points": 0,
            "observed_median_interval_seconds": None,
            "irregular": False,
        },
        availability={
            "heart_rate_bpm": False,
            "speed_mps": False,
            "pace_seconds_per_km": False,
            "cadence_rpm": False,
            "power_w": False,
            "altitude_m": False,
            "grade_pct": False,
        },
        series=_empty_series(),
        next_start_seconds=next_start_seconds,
    )


def _one_point_window_result(*, next_start_seconds: int | None = None) -> WindowResult:
    result = _empty_window_result(next_start_seconds=next_start_seconds)
    result.sampling.update(
        {
            "source_records": 1,
            "returned_points": 1,
            "observed_median_interval_seconds": 1.0,
            "irregular": False,
        }
    )
    result.series["elapsed_seconds"] = [0]
    result.series["timestamp"] = ["1998-07-03T21:24:16.000000Z"]
    result.series["sample_count"] = [1]
    result.series["heart_rate_bpm"] = {"average": [120.0], "minimum": [120], "maximum": [120]}
    result.series["speed_mps"] = {"average": [2.0]}
    result.series["pace_seconds_per_km"] = {"average": [500], "fastest": [500], "slowest": [500]}
    result.series["cadence_rpm"] = {"average": [90.0]}
    result.series["power_w"] = {"average": [200.0]}
    result.series["altitude_m"] = {"average": [10.0]}
    result.series["grade_pct"] = {"average": [1.0]}
    return result


def _window_result_with_point_count(source_records: int, returned_points: int) -> WindowResult:
    result = _empty_window_result()
    result.sampling.update(
        {
            "source_records": source_records,
            "returned_points": returned_points,
            "observed_median_interval_seconds": 1.0,
            "irregular": False,
        }
    )
    result.series["elapsed_seconds"] = list(range(returned_points))
    result.series["timestamp"] = ["1998-07-03T21:24:16.000000Z"] * returned_points
    result.series["sample_count"] = [1] * returned_points
    result.series["heart_rate_bpm"] = {
        "average": [120.0] * returned_points,
        "minimum": [120] * returned_points,
        "maximum": [120] * returned_points,
    }
    result.series["speed_mps"] = {"average": [2.0] * returned_points}
    result.series["pace_seconds_per_km"] = {
        "average": [500] * returned_points,
        "fastest": [500] * returned_points,
        "slowest": [500] * returned_points,
    }
    result.series["cadence_rpm"] = {"average": [90.0] * returned_points}
    result.series["power_w"] = {"average": [200.0] * returned_points}
    result.series["altitude_m"] = {"average": [10.0] * returned_points}
    result.series["grade_pct"] = {"average": [1.0] * returned_points}
    return result


def _expected_empty(
    *,
    activity_id: int | None = None,
    requested_start_seconds: int | None = None,
    actual_end_seconds: int | None = None,
    resolution_seconds: int | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "error" if code else "success",
        "error": None if code is None else ERRORS[code],
        "activity_id": activity_id,
        "window": {
            "requested_start_seconds": requested_start_seconds,
            "actual_end_seconds": actual_end_seconds,
            "resolution_seconds": resolution_seconds,
        },
        "sampling": {
            "source_records": 0,
            "returned_points": 0,
            "observed_median_interval_seconds": None,
            "irregular": False,
        },
        "availability": {
            "heart_rate_bpm": False,
            "speed_mps": False,
            "pace_seconds_per_km": False,
            "cadence_rpm": False,
            "power_w": False,
            "altitude_m": False,
            "grade_pct": False,
        },
        "series": _empty_series(),
        "warnings": [],
    }


@pytest.fixture
def service_module():
    from garmin_mcp.ai_activity import timeseries_service

    return timeseries_service


@pytest.fixture
def recorded_success_seams(monkeypatch: pytest.MonkeyPatch, service_module):
    calls: list[tuple[str, tuple[Any, ...]]] = []
    archive = b"safe-original-fit"
    parsed = ParseResult((object(),), 0, None)
    reduced = _empty_window_result()

    def download(client: object, activity_id: int) -> OriginalFitDownload:
        calls.append(("download", (client, activity_id)))
        return OriginalFitDownload(archive, None)

    def parse(payload: bytes) -> ParseResult:
        calls.append(("parse", (payload,)))
        return parsed

    def reduce(records: tuple[object, ...], start: int, duration: int, resolution: int) -> WindowResult:
        calls.append(("reduce", (records, start, duration, resolution)))
        return reduced

    monkeypatch.setattr(service_module, "download_original_fit", download)
    monkeypatch.setattr(service_module, "parse_original_fit", parse)
    monkeypatch.setattr(service_module, "reduce_records", reduce)
    return calls, archive, parsed, reduced


@pytest.mark.parametrize(
    ("activity_id", "normalized"),
    [(1, 1), (MAX_ACTIVITY_ID, MAX_ACTIVITY_ID), (" 00042 ", 42), ("9007199254740991", MAX_ACTIVITY_ID)],
)
def test_activity_id_accepts_exact_bounded_int_or_ascii_decimal_string(
    service_module, recorded_success_seams, activity_id: object, normalized: int
):
    result = service_module.get_activity_timeseries_service(object(), activity_id, 0, 1, 1)

    assert result["activity_id"] == normalized
    assert result["status"] == "success"
    assert recorded_success_seams[0][0][1][1] == normalized


class _HostileInt(int):
    def __int__(self):  # pragma: no cover - called only by an incorrect implementation
        raise AssertionError("hostile __int__ invoked")

    def __index__(self):  # pragma: no cover - called only by an incorrect implementation
        raise AssertionError("hostile __index__ invoked")

    def __lt__(self, other):  # pragma: no cover - called only by an incorrect implementation
        raise AssertionError("hostile comparison invoked")

    def __le__(self, other):  # pragma: no cover - called only by an incorrect implementation
        raise AssertionError("hostile comparison invoked")

    def __gt__(self, other):  # pragma: no cover - called only by an incorrect implementation
        raise AssertionError("hostile comparison invoked")

    def __ge__(self, other):  # pragma: no cover - called only by an incorrect implementation
        raise AssertionError("hostile comparison invoked")


class _HostileStr(str):
    def strip(self, *args, **kwargs):  # pragma: no cover - called only by an incorrect implementation
        raise AssertionError("hostile strip invoked")


@pytest.mark.parametrize(
    "activity_id",
    [
        True,
        1.0,
        Decimal("1"),
        b"1",
        [1],
        {"id": 1},
        object(),
        _HostileInt(1),
        _HostileStr("1"),
        0,
        -1,
        MAX_ACTIVITY_ID + 1,
        "",
        " ",
        "0",
        "-1",
        "+1",
        "1.0",
        "1e2",
        "١٢",
        "9007199254740992",
    ],
)
def test_activity_id_rejects_non_exact_or_out_of_range_values_without_seams(
    service_module, recorded_success_seams, activity_id: object
):
    result = service_module.get_activity_timeseries_service(object(), activity_id, 0, 1, 1)

    assert result == _expected_empty(code="invalid_activity_id")
    assert recorded_success_seams[0] == []


@pytest.mark.parametrize(
    ("argument", "value", "code", "prefix"),
    [
        ("start_seconds", True, "invalid_start_seconds", {"activity_id": 42}),
        ("start_seconds", 1.0, "invalid_start_seconds", {"activity_id": 42}),
        ("start_seconds", "0", "invalid_start_seconds", {"activity_id": 42}),
        ("start_seconds", _HostileInt(0), "invalid_start_seconds", {"activity_id": 42}),
        ("start_seconds", -1, "invalid_start_seconds", {"activity_id": 42}),
        ("start_seconds", MAX_FIT_ELAPSED_SECONDS + 1, "invalid_start_seconds", {"activity_id": 42}),
        ("duration_seconds", True, "invalid_duration_seconds", {"activity_id": 42, "requested_start_seconds": 7}),
        ("duration_seconds", 0, "invalid_duration_seconds", {"activity_id": 42, "requested_start_seconds": 7}),
        ("duration_seconds", 86401, "invalid_duration_seconds", {"activity_id": 42, "requested_start_seconds": 7}),
        ("duration_seconds", "1", "invalid_duration_seconds", {"activity_id": 42, "requested_start_seconds": 7}),
        ("duration_seconds", _HostileInt(1), "invalid_duration_seconds", {"activity_id": 42, "requested_start_seconds": 7}),
        ("resolution_seconds", True, "invalid_resolution_seconds", {"activity_id": 42, "requested_start_seconds": 7, "actual_end_seconds": 17}),
        ("resolution_seconds", 0, "invalid_resolution_seconds", {"activity_id": 42, "requested_start_seconds": 7, "actual_end_seconds": 17}),
        ("resolution_seconds", 301, "invalid_resolution_seconds", {"activity_id": 42, "requested_start_seconds": 7, "actual_end_seconds": 17}),
        ("resolution_seconds", "1", "invalid_resolution_seconds", {"activity_id": 42, "requested_start_seconds": 7, "actual_end_seconds": 17}),
        ("resolution_seconds", _HostileInt(1), "invalid_resolution_seconds", {"activity_id": 42, "requested_start_seconds": 7, "actual_end_seconds": 17}),
    ],
)
def test_window_arguments_are_exact_bounded_ints_with_prefix_projection(
    service_module,
    recorded_success_seams,
    argument: str,
    value: object,
    code: str,
    prefix: dict[str, int],
):
    values: dict[str, object] = {"start_seconds": 7, "duration_seconds": 10, "resolution_seconds": 1}
    values[argument] = value

    result = service_module.get_activity_timeseries_service(object(), 42, **values)

    assert result == _expected_empty(
        activity_id=prefix.get("activity_id"),
        requested_start_seconds=prefix.get("requested_start_seconds"),
        actual_end_seconds=prefix.get("actual_end_seconds"),
        code=code,
    )
    assert recorded_success_seams[0] == []


@pytest.mark.parametrize(
    ("argument", "code", "expected_window"),
    [
        ("start_seconds", "invalid_start_seconds", (None, None, None)),
        ("duration_seconds", "invalid_duration_seconds", (7, None, None)),
        ("resolution_seconds", "invalid_resolution_seconds", (7, 17, None)),
    ],
)
@pytest.mark.parametrize("value", [True, 1.0, "1", [], {}, object(), _HostileInt(1)])
def test_each_window_argument_rejects_every_non_exact_int_without_invoking_hostile_hooks(
    service_module,
    recorded_success_seams,
    argument: str,
    code: str,
    expected_window: tuple[int | None, int | None, int | None],
    value: object,
):
    values: dict[str, object] = {"start_seconds": 7, "duration_seconds": 10, "resolution_seconds": 1}
    values[argument] = value

    result = service_module.get_activity_timeseries_service(object(), 42, **values)

    assert result == _expected_empty(
        activity_id=42,
        requested_start_seconds=expected_window[0],
        actual_end_seconds=expected_window[1],
        resolution_seconds=expected_window[2],
        code=code,
    )
    assert recorded_success_seams[0] == []


@pytest.mark.parametrize(
    ("activity_id", "start_seconds", "duration_seconds", "resolution_seconds", "code", "window"),
    [
        (False, False, False, False, "invalid_activity_id", (None, None, None)),
        (42, False, False, False, "invalid_start_seconds", (None, None, None)),
        (42, 7, False, False, "invalid_duration_seconds", (7, None, None)),
        (42, 7, 10, False, "invalid_resolution_seconds", (7, 17, None)),
        (42, 7, 601, 1, "point_limit_exceeded", (7, 608, 1)),
    ],
)
def test_validation_precedence_advances_only_after_the_prior_input_is_valid(
    service_module,
    recorded_success_seams,
    activity_id: object,
    start_seconds: object,
    duration_seconds: object,
    resolution_seconds: object,
    code: str,
    window: tuple[int | None, int | None, int | None],
):
    result = service_module.get_activity_timeseries_service(
        object(), activity_id, start_seconds, duration_seconds, resolution_seconds
    )

    assert result == _expected_empty(
        activity_id=42 if code != "invalid_activity_id" else None,
        requested_start_seconds=window[0],
        actual_end_seconds=window[1],
        resolution_seconds=window[2],
        code=code,
    )
    assert recorded_success_seams[0] == []


def test_upper_request_bounds_delegate_exact_values_and_permit_an_end_after_fit_elapsed_maximum(
    service_module, recorded_success_seams
):
    calls, archive, parsed, _ = recorded_success_seams
    client = object()

    result = service_module.get_activity_timeseries_service(
        client,
        MAX_ACTIVITY_ID,
        MAX_FIT_ELAPSED_SECONDS,
        86_400,
        300,
    )

    assert result["status"] == "success"
    assert result["window"] == {
        "requested_start_seconds": MAX_FIT_ELAPSED_SECONDS,
        "actual_end_seconds": MAX_FIT_ELAPSED_SECONDS + 86_400,
        "resolution_seconds": 300,
    }
    assert calls == [
        ("download", (client, MAX_ACTIVITY_ID)),
        ("parse", (archive,)),
        ("reduce", (parsed.records, MAX_FIT_ELAPSED_SECONDS, 86_400, 300)),
    ]


@pytest.mark.parametrize(
    ("duration_seconds", "resolution_seconds", "expected_code"),
    [(600, 1, None), (601, 1, "point_limit_exceeded"), (86_400, 144, None), (86_400, 143, "point_limit_exceeded")],
)
def test_point_cap_uses_integer_ceiling_after_all_window_prefixes_are_valid(
    service_module, recorded_success_seams, duration_seconds: int, resolution_seconds: int, expected_code: str | None
):
    result = service_module.get_activity_timeseries_service(
        object(), 42, 7, duration_seconds, resolution_seconds
    )

    if expected_code is None:
        assert result["status"] == "success"
        assert recorded_success_seams[0]
    else:
        assert result == _expected_empty(
            activity_id=42,
            requested_start_seconds=7,
            actual_end_seconds=7 + duration_seconds,
            resolution_seconds=resolution_seconds,
            code=expected_code,
        )
        assert recorded_success_seams[0] == []


def test_empty_error_envelopes_have_exact_stable_order_and_no_partial_series(service_module, recorded_success_seams):
    result = service_module.get_activity_timeseries_service(object(), 42, 7, 0, 1)

    assert tuple(result) == (
        "status",
        "error",
        "activity_id",
        "window",
        "sampling",
        "availability",
        "series",
        "warnings",
    )
    assert result == _expected_empty(
        activity_id=42,
        requested_start_seconds=7,
        code="invalid_duration_seconds",
    )
    assert tuple(result["window"]) == (
        "requested_start_seconds",
        "actual_end_seconds",
        "resolution_seconds",
    )
    assert recorded_success_seams[0] == []


def _assert_complete_ordered_shape(result: dict[str, Any]) -> None:
    assert tuple(result) == (
        "status",
        "error",
        "activity_id",
        "window",
        "sampling",
        "availability",
        "series",
        "warnings",
    )
    assert tuple(result["window"]) == (
        "requested_start_seconds",
        "actual_end_seconds",
        "resolution_seconds",
    )
    assert tuple(result["sampling"]) == (
        "source_records",
        "returned_points",
        "observed_median_interval_seconds",
        "irregular",
    )
    assert tuple(result["availability"]) == (
        "heart_rate_bpm",
        "speed_mps",
        "pace_seconds_per_km",
        "cadence_rpm",
        "power_w",
        "altitude_m",
        "grade_pct",
    )
    assert tuple(result["series"]) == (
        "elapsed_seconds",
        "timestamp",
        "sample_count",
        "heart_rate_bpm",
        "speed_mps",
        "pace_seconds_per_km",
        "cadence_rpm",
        "power_w",
        "altitude_m",
        "grade_pct",
    )
    assert tuple(result["series"]["heart_rate_bpm"]) == ("average", "minimum", "maximum")
    assert tuple(result["series"]["speed_mps"]) == ("average",)
    assert tuple(result["series"]["pace_seconds_per_km"]) == ("average", "fastest", "slowest")
    assert tuple(result["series"]["cadence_rpm"]) == ("average",)
    assert tuple(result["series"]["power_w"]) == ("average",)
    assert tuple(result["series"]["altitude_m"]) == ("average",)
    assert tuple(result["series"]["grade_pct"]) == ("average",)


def test_error_and_populated_success_envelopes_preserve_the_complete_hard_coded_key_order(
    service_module, recorded_success_seams
):
    _, _, _, reduced = recorded_success_seams
    reduced.sampling.update({"source_records": 1, "returned_points": 1})
    reduced.series["elapsed_seconds"].append(0)
    reduced.series["timestamp"].append("1998-07-03T21:24:16.000000Z")
    reduced.series["sample_count"].append(1)
    reduced.series["heart_rate_bpm"] = {"average": [120.0], "minimum": [120], "maximum": [120]}
    reduced.series["speed_mps"] = {"average": [2.0]}
    reduced.series["pace_seconds_per_km"] = {"average": [500], "fastest": [500], "slowest": [500]}
    reduced.series["cadence_rpm"] = {"average": [90.0]}
    reduced.series["power_w"] = {"average": [200.0]}
    reduced.series["altitude_m"] = {"average": [10.0]}
    reduced.series["grade_pct"] = {"average": [1.0]}

    error = service_module.get_activity_timeseries_service(object(), 42, 7, 0, 1)
    success = service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)

    _assert_complete_ordered_shape(error)
    _assert_complete_ordered_shape(success)


def test_next_start_is_omitted_when_null_and_appended_last_when_available(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams
):
    no_cursor = service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)
    monkeypatch.setattr(
        service_module,
        "reduce_records",
        lambda records, start, duration, resolution: _empty_window_result(next_start_seconds=1),
    )
    with_cursor = service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)

    assert tuple(no_cursor["window"]) == (
        "requested_start_seconds",
        "actual_end_seconds",
        "resolution_seconds",
    )
    assert tuple(with_cursor["window"]) == (
        "requested_start_seconds",
        "actual_end_seconds",
        "resolution_seconds",
        "next_start_seconds",
    )
    assert with_cursor["window"]["next_start_seconds"] == 1


def test_client_none_is_reported_only_after_validating_every_input(service_module, recorded_success_seams):
    result = service_module.get_activity_timeseries_service(None, " 42 ", 7, 10, 2)

    assert result == _expected_empty(
        activity_id=42,
        requested_start_seconds=7,
        actual_end_seconds=17,
        resolution_seconds=2,
        code="client_unavailable",
    )
    assert recorded_success_seams[0] == []


def test_service_calls_the_three_seams_once_in_order_with_normalized_arguments(
    service_module, recorded_success_seams
):
    calls, archive, parsed, _ = recorded_success_seams
    client = object()

    result = service_module.get_activity_timeseries_service(client, " 42 ", 7, 10, 2)

    assert result == _expected_empty(
        activity_id=42,
        requested_start_seconds=7,
        actual_end_seconds=17,
        resolution_seconds=2,
    )
    assert calls == [
        ("download", (client, 42)),
        ("parse", (archive,)),
        ("reduce", (parsed.records, 7, 10, 2)),
    ]


@pytest.mark.parametrize("code", ["download_failed", "invalid_download_payload", "fit_download_too_large"])
def test_download_failure_codes_map_without_parsing_or_reducing(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams, code: str
):
    calls, _, _, _ = recorded_success_seams

    def download(client: object, activity_id: int) -> OriginalFitDownload:
        calls.append(("download", (client, activity_id)))
        return OriginalFitDownload(None, code)

    monkeypatch.setattr(service_module, "download_original_fit", download)

    result = service_module.get_activity_timeseries_service(object(), 42, 7, 10, 2)

    assert result == _expected_empty(
        activity_id=42,
        requested_start_seconds=7,
        actual_end_seconds=17,
        resolution_seconds=2,
        code=code,
    )
    assert calls == [("download", (calls[0][1][0], 42))]


@pytest.mark.parametrize(
    "code",
    [
        "invalid_fit_payload",
        "unsafe_fit_archive",
        "fit_member_too_large",
        "fit_parse_failed",
        "chained_fit_unsupported",
        "frame_limit_exceeded",
        "definition_field_limit_exceeded",
        "record_limit_exceeded",
        "no_timestamped_records",
    ],
)
def test_parser_failure_codes_map_without_reducing(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams, code: str
):
    calls, _, _, _ = recorded_success_seams

    def parse(payload: bytes) -> ParseResult:
        calls.append(("parse", (payload,)))
        return ParseResult((object(),), 9, code)

    monkeypatch.setattr(service_module, "parse_original_fit", parse)

    result = service_module.get_activity_timeseries_service(object(), 42, 7, 10, 2)

    assert result == _expected_empty(
        activity_id=42,
        requested_start_seconds=7,
        actual_end_seconds=17,
        resolution_seconds=2,
        code=code,
    )
    assert [name for name, _ in calls] == ["download", "parse"]


@pytest.mark.parametrize("seam", ["download_original_fit", "parse_original_fit", "reduce_records"])
def test_internal_seam_runtime_errors_propagate_unchanged(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams, seam: str
):
    def explode(*args: object) -> object:
        raise RuntimeError("internal test seam exploded")

    monkeypatch.setattr(service_module, seam, explode)

    with pytest.raises(RuntimeError, match="internal test seam exploded"):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


@pytest.mark.parametrize("seam", ["download", "parse"])
def test_unknown_trusted_failure_codes_are_programmer_defects(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams, seam: str
):
    if seam == "download":
        monkeypatch.setattr(
            service_module,
            "download_original_fit",
            lambda client, activity_id: OriginalFitDownload(None, "unexpected_internal_code"),
        )
    else:
        monkeypatch.setattr(
            service_module,
            "parse_original_fit",
            lambda archive: ParseResult((), 0, "unexpected_internal_code"),
        )

    with pytest.raises(AssertionError, match="unexpected_internal_code"):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


def test_success_empty_selection_ignores_global_malformed_record_count(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams
):
    calls, archive, _, _ = recorded_success_seams
    result = _empty_window_result(next_start_seconds=10)

    monkeypatch.setattr(service_module, "parse_original_fit", lambda payload: ParseResult((object(),), 5, None))
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: result)
    response = service_module.get_activity_timeseries_service(object(), 42, 0, 10, 1)

    expected = _expected_empty(
        activity_id=42,
        requested_start_seconds=0,
        actual_end_seconds=10,
        resolution_seconds=1,
    )
    expected["window"]["next_start_seconds"] = 10
    assert response == expected
    assert [name for name, _ in calls] == ["download"]


def test_selected_malformed_records_return_exact_partial_warning_and_fresh_copies(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams
):
    _, _, _, reduced = recorded_success_seams
    reduced.sampling.update({"source_records": 2, "returned_points": 1})
    reduced.availability["heart_rate_bpm"] = True
    reduced.series["elapsed_seconds"].append(0)
    reduced.series["timestamp"].append("1998-07-03T21:24:16.000000Z")
    reduced.series["sample_count"].append(2)
    reduced.series["heart_rate_bpm"]["average"].append(120.0)
    reduced.series["heart_rate_bpm"]["minimum"].append(100)
    reduced.series["heart_rate_bpm"]["maximum"].append(140)
    for name, values in reduced.series.items():
        if type(values) is dict and name != "heart_rate_bpm":
            for array in values.values():
                array.append(None)

    monkeypatch.setattr(service_module, "parse_original_fit", lambda payload: ParseResult((object(),), 3, None))

    response = service_module.get_activity_timeseries_service(object(), 42, 0, 10, 1)

    assert response["status"] == "partial_success"
    assert response["error"] is None
    assert response["warnings"] == [
        {
            "provider": "fit",
            "code": "malformed_records_discarded",
            "message": "Malformed FIT record messages were discarded.",
            "count": 3,
        }
    ]
    response["series"]["elapsed_seconds"].append(99)
    assert reduced.series["elapsed_seconds"] == [0]
    reduced.series["elapsed_seconds"].append(100)
    assert response["series"]["elapsed_seconds"] == [0, 99]


def test_selected_records_without_malformed_messages_are_success(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams
):
    reduced = _empty_window_result()
    reduced.sampling.update({"source_records": 1, "returned_points": 1})
    reduced.series["elapsed_seconds"].append(0)
    reduced.series["timestamp"].append("1998-07-03T21:24:16.000000Z")
    reduced.series["sample_count"].append(1)
    for values in reduced.series.values():
        if type(values) is dict:
            for array in values.values():
                array.append(None)
    monkeypatch.setattr(service_module, "parse_original_fit", lambda payload: ParseResult((object(),), 0, None))
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    response = service_module.get_activity_timeseries_service(object(), 42, 0, 10, 1)

    assert response["status"] == "success"
    assert response["warnings"] == []


_FORBIDDEN_TEXT = (
    "token=",
    "https://",
    "authorization",
    "request_id",
    "position",
    "latitude",
    "longitude",
    "coordinate",
    "location",
    "polyline",
    "untrusted-coordinate-sentinel",
)


def _assert_no_forbidden_text(value: object) -> None:
    if type(value) is dict:
        for key, nested in value.items():
            assert type(key) is str
            assert all(token not in key.lower() for token in _FORBIDDEN_TEXT)
            _assert_no_forbidden_text(nested)
        return
    if type(value) is list:
        for nested in value:
            _assert_no_forbidden_text(nested)
        return
    text = value if type(value) is str else repr(value)
    assert all(token not in text.lower() for token in _FORBIDDEN_TEXT)


class _FailingDownloadClient:
    def download_activity(self, activity_id: int, *, dl_fmt: object) -> bytes:
        raise RuntimeError(
            "token=private https://private.example authorization request_id=private "
            "untrusted-coordinate-sentinel"
        )


class _PayloadDownloadClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def download_activity(self, activity_id: int, *, dl_fmt: object) -> object:
        return self.payload


def test_real_provider_exception_boundary_returns_fixed_download_error_without_echo(service_module):
    response = service_module.get_activity_timeseries_service(_FailingDownloadClient(), 42, 0, 1, 1)

    assert response == _expected_empty(
        activity_id=42,
        requested_start_seconds=0,
        actual_end_seconds=1,
        resolution_seconds=1,
        code="download_failed",
    )
    _assert_no_forbidden_text(response)
    assert json.loads(json.dumps(response, allow_nan=False)) == response


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            "token=private https://private.example untrusted-coordinate-sentinel private-location-sentinel",
            "invalid_download_payload",
        ),
        (
            b"token=private https://private.example untrusted-coordinate-sentinel private-location-sentinel",
            "invalid_fit_payload",
        ),
    ],
)
def test_real_provider_payload_boundary_returns_fixed_error_without_echo(
    service_module, payload: object, code: str
):
    response = service_module.get_activity_timeseries_service(_PayloadDownloadClient(payload), 42, 0, 1, 1)

    assert response == _expected_empty(
        activity_id=42,
        requested_start_seconds=0,
        actual_end_seconds=1,
        resolution_seconds=1,
        code=code,
    )
    _assert_no_forbidden_text(response)
    assert json.loads(json.dumps(response, allow_nan=False)) == response


def test_real_reduction_of_safe_record_facts_produces_json_safe_non_echoing_output(
    monkeypatch: pytest.MonkeyPatch, service_module
):
    raw_timestamp_seconds = 0x10000000
    records = (
        RecordFact(
            raw_timestamp_seconds=raw_timestamp_seconds,
            timestamp_utc=FIT_EPOCH + timedelta(seconds=raw_timestamp_seconds),
            encounter_index=0,
            heart_rate_bpm=120.0,
            speed_mps=2.0,
            cadence_rpm=90.0,
            power_w=200.0,
            altitude_m=10.0,
            grade_pct=1.0,
        ),
    )
    monkeypatch.setattr(
        service_module,
        "download_original_fit",
        lambda client, activity_id: OriginalFitDownload(b"safe-original-fit", None),
    )
    monkeypatch.setattr(service_module, "parse_original_fit", lambda archive: ParseResult(records, 0, None))

    response = service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)

    assert response["status"] == "success"
    assert response["sampling"]["source_records"] == 1
    assert response["series"]["heart_rate_bpm"]["average"] == [120.0]
    _assert_no_forbidden_text(response)
    assert json.loads(json.dumps(response, allow_nan=False)) == response


@pytest.mark.parametrize("corruption", [object(), "untrusted-raw-string-sentinel"])
def test_corrupt_trusted_window_result_is_a_visible_contract_failure(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams, corruption: object
):
    _, _, _, reduced = recorded_success_seams
    reduced.series["elapsed_seconds"] = [corruption]
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    with pytest.raises((TypeError, ValueError)):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


@pytest.mark.parametrize(
    "next_start_seconds",
    [float("nan"), True, 1.0, "1", -1, MAX_FIT_ELAPSED_SECONDS + 1],
)
def test_corrupt_trusted_cursor_values_are_visible_contract_failures(
    monkeypatch: pytest.MonkeyPatch,
    service_module,
    recorded_success_seams,
    next_start_seconds: object,
):
    monkeypatch.setattr(
        service_module,
        "reduce_records",
        lambda records, start, duration, resolution: _one_point_window_result(
            next_start_seconds=next_start_seconds  # type: ignore[arg-type]
        ),
    )

    with pytest.raises((TypeError, ValueError)):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


@pytest.mark.parametrize("next_start_seconds", [None, 0, MAX_FIT_ELAPSED_SECONDS])
def test_trusted_cursor_accepts_only_none_or_exact_fit_elapsed_range(
    monkeypatch: pytest.MonkeyPatch,
    service_module,
    recorded_success_seams,
    next_start_seconds: int | None,
):
    monkeypatch.setattr(
        service_module,
        "reduce_records",
        lambda records, start, duration, resolution: _one_point_window_result(
            next_start_seconds=next_start_seconds
        ),
    )

    response = service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)

    if next_start_seconds is None:
        assert "next_start_seconds" not in response["window"]
    else:
        assert response["window"]["next_start_seconds"] == next_start_seconds
        assert type(response["window"]["next_start_seconds"]) is int


@pytest.mark.parametrize("malformed_record_count", [True, 1.0, "1", object(), -1, MAX_RECORD_MESSAGES + 1])
def test_invalid_trusted_malformed_record_counts_fail_before_reduction_or_warning_copy(
    monkeypatch: pytest.MonkeyPatch,
    service_module,
    recorded_success_seams,
    malformed_record_count: object,
):
    calls, _, _, _ = recorded_success_seams

    def parse(payload: bytes) -> ParseResult:
        calls.append(("parse", (payload,)))
        return ParseResult((object(),), malformed_record_count, None)  # type: ignore[arg-type]

    def reduce(records: tuple[object, ...], start: int, duration: int, resolution: int) -> WindowResult:
        calls.append(("reduce", (records, start, duration, resolution)))
        return _one_point_window_result()

    monkeypatch.setattr(service_module, "parse_original_fit", parse)
    monkeypatch.setattr(service_module, "reduce_records", reduce)

    with pytest.raises((TypeError, ValueError)):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)
    assert [name for name, _ in calls] == ["download", "parse"]


def test_valid_malformed_record_count_is_copied_to_the_warning_as_an_exact_int(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams
):
    monkeypatch.setattr(service_module, "parse_original_fit", lambda archive: ParseResult((object(),), 3, None))
    monkeypatch.setattr(
        service_module,
        "reduce_records",
        lambda records, start, duration, resolution: _one_point_window_result(),
    )

    response = service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)

    assert response["warnings"][0]["count"] == 3
    assert type(response["warnings"][0]["count"]) is int


@pytest.mark.parametrize(
    ("sampling_key", "value"),
    [
        ("source_records", True),
        ("source_records", 1.0),
        ("source_records", "1"),
        ("source_records", -1),
        ("returned_points", True),
        ("returned_points", 1.0),
        ("returned_points", "1"),
        ("returned_points", -1),
        ("returned_points", MAX_RETURNED_POINTS + 1),
    ],
)
def test_trusted_sampling_counts_must_be_exact_nonnegative_bounded_ints(
    monkeypatch: pytest.MonkeyPatch,
    service_module,
    recorded_success_seams,
    sampling_key: str,
    value: object,
):
    reduced = _one_point_window_result()
    reduced.sampling[sampling_key] = value
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    with pytest.raises((TypeError, ValueError)):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


@pytest.mark.parametrize(
    "path",
    [
        ("elapsed_seconds",),
        ("timestamp",),
        ("sample_count",),
        ("heart_rate_bpm", "average"),
        ("heart_rate_bpm", "minimum"),
        ("heart_rate_bpm", "maximum"),
        ("speed_mps", "average"),
        ("pace_seconds_per_km", "average"),
        ("pace_seconds_per_km", "fastest"),
        ("pace_seconds_per_km", "slowest"),
        ("cadence_rpm", "average"),
        ("power_w", "average"),
        ("altitude_m", "average"),
        ("grade_pct", "average"),
    ],
)
def test_every_trusted_series_leaf_array_must_match_returned_point_count(
    monkeypatch: pytest.MonkeyPatch,
    service_module,
    recorded_success_seams,
    path: tuple[str, ...],
):
    reduced = _one_point_window_result()
    leaf: Any = reduced.series
    for key in path:
        leaf = leaf[key]
    leaf.clear()
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    with pytest.raises(ValueError):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


def test_trusted_series_rejects_a_601_item_array_even_when_returned_points_is_bounded(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams
):
    reduced = _one_point_window_result()
    reduced.sampling["returned_points"] = MAX_RETURNED_POINTS
    reduced.series["elapsed_seconds"] = list(range(MAX_RETURNED_POINTS + 1))
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    with pytest.raises(ValueError):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


@pytest.mark.parametrize(
    ("sampling_key", "value"),
    [
        ("irregular", 1),
        ("observed_median_interval_seconds", True),
        ("observed_median_interval_seconds", "1"),
        ("observed_median_interval_seconds", -1),
        ("observed_median_interval_seconds", -1.0),
        ("observed_median_interval_seconds", float("nan")),
    ],
)
def test_trusted_sampling_booleans_and_median_interval_have_exact_bounded_types(
    monkeypatch: pytest.MonkeyPatch,
    service_module,
    recorded_success_seams,
    sampling_key: str,
    value: object,
):
    reduced = _one_point_window_result()
    reduced.sampling[sampling_key] = value
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    with pytest.raises((TypeError, ValueError)):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


@pytest.mark.parametrize("median", [None, 0, 0.0, 1, 1.0])
def test_trusted_sampling_median_accepts_none_or_finite_nonnegative_exact_numbers(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams, median: int | float | None
):
    reduced = _one_point_window_result()
    reduced.sampling["observed_median_interval_seconds"] = median
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    response = service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)

    assert response["sampling"]["observed_median_interval_seconds"] == median
    assert type(response["sampling"]["observed_median_interval_seconds"]) is type(median)


def test_trusted_availability_values_must_be_exact_bools(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams
):
    reduced = _one_point_window_result()
    reduced.availability["heart_rate_bpm"] = 1
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    with pytest.raises(TypeError):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


@pytest.mark.parametrize(
    "source_records",
    [
        pytest.param(MAX_RECORD_MESSAGES + 1, id="over-record-limit"),
        pytest.param(10**5000, id="huge-int"),
    ],
)
def test_trusted_source_record_count_cannot_exceed_the_record_limit(
    monkeypatch: pytest.MonkeyPatch,
    service_module,
    recorded_success_seams,
    source_records: int,
):
    reduced = _one_point_window_result()
    reduced.sampling["source_records"] = source_records
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    with pytest.raises(ValueError):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


def test_trusted_returned_points_cannot_exceed_source_records(
    monkeypatch: pytest.MonkeyPatch, service_module, recorded_success_seams
):
    reduced = _one_point_window_result()
    reduced.sampling["source_records"] = 0
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    with pytest.raises(ValueError):
        service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)


@pytest.mark.parametrize("source_records", [MAX_RETURNED_POINTS, MAX_RECORD_MESSAGES])
def test_trusted_sampling_count_upper_boundaries_are_accepted_when_returned_points_fit_source_records(
    monkeypatch: pytest.MonkeyPatch,
    service_module,
    recorded_success_seams,
    source_records: int,
):
    reduced = _window_result_with_point_count(source_records, MAX_RETURNED_POINTS)
    monkeypatch.setattr(service_module, "reduce_records", lambda records, start, duration, resolution: reduced)

    response = service_module.get_activity_timeseries_service(object(), 42, 0, 600, 1)

    assert response["status"] == "success"
    assert response["sampling"]["source_records"] == source_records
    assert response["sampling"]["returned_points"] == MAX_RETURNED_POINTS
    assert len(response["series"]["elapsed_seconds"]) == MAX_RETURNED_POINTS


def test_successful_output_is_json_safe_and_contains_no_sensitive_or_raw_content(service_module, recorded_success_seams):
    response = service_module.get_activity_timeseries_service(object(), 42, 0, 1, 1)
    forbidden = (
        "token=",
        "authorization",
        "request_id",
        "http://",
        "https://",
        "position",
        "latitude",
        "longitude",
        "coordinate",
        "polyline",
        "raw",
        "exception",
        "sentinel",
    )

    def assert_safe(value: object) -> None:
        assert type(value) in {dict, list, str, int, float, bool, type(None)}
        if type(value) is dict:
            for key, nested in value.items():
                assert all(word not in key.lower() for word in forbidden)
                assert_safe(nested)
        elif type(value) is list:
            for nested in value:
                assert_safe(nested)
        elif type(value) is str:
            assert all(word not in value.lower() for word in forbidden)

    assert_safe(response)
    assert json.loads(json.dumps(response, allow_nan=False)) == response


def test_package_reexports_service_and_documented_limits():
    from garmin_mcp import ai_activity

    assert ai_activity.MAX_ACTIVITY_ID == MAX_ACTIVITY_ID
    assert ai_activity.MAX_FIT_ELAPSED_SECONDS == MAX_FIT_ELAPSED_SECONDS
    assert ai_activity.get_activity_timeseries_service is not None
