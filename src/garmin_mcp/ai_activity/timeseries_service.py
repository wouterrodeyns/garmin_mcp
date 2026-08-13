"""Strict, bounded orchestration for original-FIT activity time series."""

from __future__ import annotations

import math
from typing import Any

from .providers import download_original_fit
from .timeseries import (
    MAX_FIT_ELAPSED_SECONDS,
    MAX_RECORD_MESSAGES,
    WindowResult,
    parse_original_fit,
    reduce_records,
)


MAX_ACTIVITY_ID = 9_007_199_254_740_991
MAX_ACTIVITY_ID_TEXT_LENGTH = 64
MAX_DURATION_SECONDS = 86_400
MAX_RESOLUTION_SECONDS = 300
MAX_RETURNED_POINTS = 600

_ERRORS = {
    "invalid_activity_id": (
        "input",
        "activity_id must be a positive integer or ASCII decimal string from 1 through 9007199254740991.",
    ),
    "invalid_start_seconds": (
        "input",
        "start_seconds must be an integer from 0 through 4026531838.",
    ),
    "invalid_duration_seconds": (
        "input",
        "duration_seconds must be an integer from 1 through 86400.",
    ),
    "invalid_resolution_seconds": (
        "input",
        "resolution_seconds must be an integer from 1 through 300.",
    ),
    "point_limit_exceeded": (
        "input",
        "ceil(duration_seconds / resolution_seconds) must not exceed 600.",
    ),
    "client_unavailable": (
        "client",
        "Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.",
    ),
    "download_failed": (
        "garmin",
        "Original FIT download is unavailable. Retry later or re-authenticate.",
    ),
    "invalid_download_payload": (
        "garmin",
        "Original FIT download returned an invalid payload.",
    ),
    "fit_download_too_large": (
        "garmin",
        "Original FIT download exceeds the 25 MB limit.",
    ),
    "invalid_fit_payload": (
        "fit",
        "Original FIT data is invalid or unavailable.",
    ),
    "unsafe_fit_archive": (
        "fit",
        "Original FIT archive violates safety limits.",
    ),
    "fit_member_too_large": (
        "fit",
        "Original FIT member exceeds the 25 MB limit.",
    ),
    "fit_parse_failed": (
        "fit",
        "Original FIT data could not be parsed.",
    ),
    "chained_fit_unsupported": ("fit", "Chained FIT files are not supported."),
    "frame_limit_exceeded": (
        "fit",
        "Original FIT data exceeds the 200000-frame limit.",
    ),
    "definition_field_limit_exceeded": (
        "fit",
        "Original FIT data exceeds the 128-field definition limit.",
    ),
    "record_limit_exceeded": (
        "fit",
        "Original FIT data exceeds the 100000-record limit.",
    ),
    "no_timestamped_records": (
        "fit",
        "Original FIT data contains no usable timestamped record messages.",
    ),
}

_AVAILABILITY_KEYS = (
    "heart_rate_bpm",
    "speed_mps",
    "pace_seconds_per_km",
    "cadence_rpm",
    "power_w",
    "altitude_m",
    "grade_pct",
)


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


def _empty_envelope() -> dict[str, Any]:
    """Create the public shape afresh, without aliasing a prior response."""
    return {
        "status": "error",
        "error": None,
        "activity_id": None,
        "window": {
            "requested_start_seconds": None,
            "actual_end_seconds": None,
            "resolution_seconds": None,
        },
        "sampling": {
            "source_records": 0,
            "returned_points": 0,
            "observed_median_interval_seconds": None,
            "irregular": False,
        },
        "availability": {key: False for key in _AVAILABILITY_KEYS},
        "series": _empty_series(),
        "warnings": [],
    }


def _error(envelope: dict[str, Any], code: str) -> dict[str, Any]:
    """Attach one trusted, fixed error vocabulary entry."""
    assert code in _ERRORS, f"unknown trusted time-series failure code: {code}"
    provider, message = _ERRORS[code]
    envelope["error"] = {"provider": provider, "code": code, "message": message}
    return envelope


def _unexpected_error_envelope() -> dict[str, Any]:
    """Return the stable public response for an unexpected adapter failure."""
    envelope = _empty_envelope()
    envelope["error"] = {
        "provider": "internal",
        "code": "internal_error",
        "message": "Activity time series is temporarily unavailable.",
    }
    return envelope


def _activity_id(value: Any) -> int | None:
    if type(value) is int:
        return value if 1 <= value <= MAX_ACTIVITY_ID else None
    if type(value) is not str:
        return None
    if len(value) > MAX_ACTIVITY_ID_TEXT_LENGTH:
        return None
    text = value.strip()
    if not text or not text.isascii() or not text.isdecimal():
        return None
    significant = text.lstrip("0")
    if not significant or len(significant) > len(str(MAX_ACTIVITY_ID)):
        return None
    parsed = int(significant)
    return parsed if parsed <= MAX_ACTIVITY_ID else None


def _bounded_integer(value: Any, minimum: int, maximum: int) -> int | None:
    if type(value) is not int:
        return None
    return value if minimum <= value <= maximum else None


def _trusted_value(value: Any, expected_types: tuple[type, ...], name: str) -> Any:
    """Fail visibly when a trusted local reduction violates its public contract."""
    if type(value) not in expected_types:
        raise TypeError(f"WindowResult {name} has an invalid type")
    if type(value) is float and not math.isfinite(value):
        raise TypeError(f"WindowResult {name} must be finite")
    return value


def _trusted_nonnegative_int(value: Any, name: str, maximum: int | None = None) -> int:
    """Require an exact trusted nonnegative integer, optionally with a cap."""
    if type(value) is not int:
        raise TypeError(f"{name} has an invalid type")
    if value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is out of range")
    return value


def _trusted_median_interval(value: Any) -> int | float | None:
    """Require the reducer's finite, nonnegative median contract."""
    if value is None:
        return None
    if type(value) not in (int, float):
        raise TypeError("WindowResult sampling.observed_median_interval_seconds has an invalid type")
    if value < 0 or (type(value) is float and not math.isfinite(value)):
        raise ValueError("WindowResult sampling.observed_median_interval_seconds is out of range")
    return value


def _trusted_cursor(value: Any) -> int | None:
    """Require an exact bounded local cursor before exposing it publicly."""
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError("WindowResult next_start_seconds has an invalid type")
    if not 0 <= value <= MAX_FIT_ELAPSED_SECONDS:
        raise ValueError("WindowResult next_start_seconds is out of range")
    return value


def _trusted_array(
    values: Any,
    expected_types: tuple[type, ...],
    name: str,
    expected_length: int,
) -> list[Any]:
    """Copy one known reducer array while retaining type-contract failures."""
    if type(values) is not list:
        raise TypeError(f"WindowResult {name} must be a list")
    if len(values) != expected_length:
        raise ValueError(f"WindowResult {name} length does not match returned_points")
    return [
        _trusted_value(value, expected_types, f"{name} item")
        for value in values
    ]


def _copy_reduction(result: WindowResult) -> tuple[dict[str, Any], dict[str, bool], dict[str, Any]]:
    """Copy the known reducer shape so its mutable arrays never escape by alias."""
    source_records = _trusted_nonnegative_int(
        result.sampling["source_records"],
        "WindowResult sampling.source_records",
        MAX_RECORD_MESSAGES,
    )
    returned_points = _trusted_nonnegative_int(
        result.sampling["returned_points"],
        "WindowResult sampling.returned_points",
        MAX_RETURNED_POINTS,
    )
    if returned_points > source_records:
        raise ValueError("WindowResult sampling.returned_points exceeds source_records")
    sampling = {
        "source_records": source_records,
        "returned_points": returned_points,
        "observed_median_interval_seconds": _trusted_median_interval(
            result.sampling["observed_median_interval_seconds"]
        ),
        "irregular": _trusted_value(result.sampling["irregular"], (bool,), "sampling.irregular"),
    }
    availability = {
        key: _trusted_value(result.availability[key], (bool,), f"availability.{key}")
        for key in _AVAILABILITY_KEYS
    }
    series = {
        "elapsed_seconds": _trusted_array(
            result.series["elapsed_seconds"], (int,), "series.elapsed_seconds", returned_points
        ),
        "timestamp": _trusted_array(
            result.series["timestamp"], (str,), "series.timestamp", returned_points
        ),
        "sample_count": _trusted_array(
            result.series["sample_count"], (int,), "series.sample_count", returned_points
        ),
        "heart_rate_bpm": {
            "average": _trusted_array(
                result.series["heart_rate_bpm"]["average"],
                (float, type(None)),
                "series.heart_rate_bpm.average",
                returned_points,
            ),
            "minimum": _trusted_array(
                result.series["heart_rate_bpm"]["minimum"],
                (int, type(None)),
                "series.heart_rate_bpm.minimum",
                returned_points,
            ),
            "maximum": _trusted_array(
                result.series["heart_rate_bpm"]["maximum"],
                (int, type(None)),
                "series.heart_rate_bpm.maximum",
                returned_points,
            ),
        },
        "speed_mps": {
            "average": _trusted_array(
                result.series["speed_mps"]["average"],
                (float, type(None)),
                "series.speed_mps.average",
                returned_points,
            )
        },
        "pace_seconds_per_km": {
            "average": _trusted_array(
                result.series["pace_seconds_per_km"]["average"],
                (int, type(None)),
                "series.pace_seconds_per_km.average",
                returned_points,
            ),
            "fastest": _trusted_array(
                result.series["pace_seconds_per_km"]["fastest"],
                (int, type(None)),
                "series.pace_seconds_per_km.fastest",
                returned_points,
            ),
            "slowest": _trusted_array(
                result.series["pace_seconds_per_km"]["slowest"],
                (int, type(None)),
                "series.pace_seconds_per_km.slowest",
                returned_points,
            ),
        },
        "cadence_rpm": {
            "average": _trusted_array(
                result.series["cadence_rpm"]["average"],
                (float, type(None)),
                "series.cadence_rpm.average",
                returned_points,
            )
        },
        "power_w": {
            "average": _trusted_array(
                result.series["power_w"]["average"],
                (float, type(None)),
                "series.power_w.average",
                returned_points,
            )
        },
        "altitude_m": {
            "average": _trusted_array(
                result.series["altitude_m"]["average"],
                (float, type(None)),
                "series.altitude_m.average",
                returned_points,
            )
        },
        "grade_pct": {
            "average": _trusted_array(
                result.series["grade_pct"]["average"],
                (float, type(None)),
                "series.grade_pct.average",
                returned_points,
            )
        },
    }
    return sampling, availability, series


def get_activity_timeseries_service(
    client: Any,
    activity_id: Any,
    start_seconds: Any = 0,
    duration_seconds: Any = 600,
    resolution_seconds: Any = 1,
) -> dict[str, Any]:
    """Return a bounded, JSON-friendly activity time-series response."""
    envelope = _empty_envelope()

    normalized_activity_id = _activity_id(activity_id)
    if normalized_activity_id is None:
        return _error(envelope, "invalid_activity_id")
    envelope["activity_id"] = normalized_activity_id

    normalized_start = _bounded_integer(start_seconds, 0, MAX_FIT_ELAPSED_SECONDS)
    if normalized_start is None:
        return _error(envelope, "invalid_start_seconds")
    envelope["window"]["requested_start_seconds"] = normalized_start

    normalized_duration = _bounded_integer(duration_seconds, 1, MAX_DURATION_SECONDS)
    if normalized_duration is None:
        return _error(envelope, "invalid_duration_seconds")
    envelope["window"]["actual_end_seconds"] = normalized_start + normalized_duration

    normalized_resolution = _bounded_integer(resolution_seconds, 1, MAX_RESOLUTION_SECONDS)
    if normalized_resolution is None:
        return _error(envelope, "invalid_resolution_seconds")
    envelope["window"]["resolution_seconds"] = normalized_resolution

    if -(-normalized_duration // normalized_resolution) > MAX_RETURNED_POINTS:
        return _error(envelope, "point_limit_exceeded")

    if client is None:
        return _error(envelope, "client_unavailable")

    downloaded = download_original_fit(client, normalized_activity_id)
    if downloaded.failure_code is not None:
        return _error(envelope, downloaded.failure_code)
    if downloaded.archive is None:
        raise RuntimeError("download_original_fit succeeded without an archive")

    parsed = parse_original_fit(downloaded.archive)
    if parsed.failure_code is not None:
        return _error(envelope, parsed.failure_code)
    malformed_count = _trusted_nonnegative_int(
        parsed.malformed_record_count,
        "ParseResult malformed_record_count",
        MAX_RECORD_MESSAGES,
    )

    reduced = reduce_records(
        parsed.records,
        normalized_start,
        normalized_duration,
        normalized_resolution,
    )
    sampling, availability, series = _copy_reduction(reduced)
    envelope["sampling"] = sampling
    envelope["availability"] = availability
    envelope["series"] = series
    next_start_seconds = _trusted_cursor(reduced.next_start_seconds)
    if next_start_seconds is not None:
        envelope["window"]["next_start_seconds"] = next_start_seconds

    if sampling["source_records"] == 0:
        envelope["status"] = "success"
    elif malformed_count > 0:
        envelope["status"] = "partial_success"
        envelope["warnings"] = [
            {
                "provider": "fit",
                "code": "malformed_records_discarded",
                "message": "Malformed FIT record messages were discarded.",
                "count": malformed_count,
            }
        ]
    else:
        envelope["status"] = "success"
    return envelope


__all__ = [
    "MAX_ACTIVITY_ID",
    "MAX_ACTIVITY_ID_TEXT_LENGTH",
    "MAX_DURATION_SECONDS",
    "MAX_FIT_ELAPSED_SECONDS",
    "MAX_RESOLUTION_SECONDS",
    "MAX_RETURNED_POINTS",
    "get_activity_timeseries_service",
]
