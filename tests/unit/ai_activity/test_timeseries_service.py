"""Direct-call contract tests for bounded activity time-series orchestration."""

from __future__ import annotations

from decimal import Decimal
import json
from typing import Any

import pytest

from garmin_mcp.ai_activity.providers import OriginalFitDownload
from garmin_mcp.ai_activity.timeseries import ParseResult, WindowResult


MAX_ACTIVITY_ID = 9_007_199_254_740_991
MAX_FIT_ELAPSED_SECONDS = 4_026_531_838


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
