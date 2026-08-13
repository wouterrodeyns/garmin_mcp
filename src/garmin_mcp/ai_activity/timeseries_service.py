"""Strict, bounded orchestration for original-FIT activity time series."""

from __future__ import annotations

from typing import Any

from .providers import download_original_fit
from .timeseries import MAX_FIT_ELAPSED_SECONDS, WindowResult, parse_original_fit, reduce_records


MAX_ACTIVITY_ID = 9_007_199_254_740_991
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


def _activity_id(value: Any) -> int | None:
    if type(value) is int:
        return value if 1 <= value <= MAX_ACTIVITY_ID else None
    if type(value) is not str:
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


def _copy_reduction(result: WindowResult) -> tuple[dict[str, Any], dict[str, bool], dict[str, Any]]:
    """Copy the known reducer shape so its mutable arrays never escape by alias."""
    sampling = {
        "source_records": result.sampling["source_records"],
        "returned_points": result.sampling["returned_points"],
        "observed_median_interval_seconds": result.sampling["observed_median_interval_seconds"],
        "irregular": result.sampling["irregular"],
    }
    availability = {key: result.availability[key] for key in _AVAILABILITY_KEYS}
    series = {
        "elapsed_seconds": list(result.series["elapsed_seconds"]),
        "timestamp": list(result.series["timestamp"]),
        "sample_count": list(result.series["sample_count"]),
        "heart_rate_bpm": {
            "average": list(result.series["heart_rate_bpm"]["average"]),
            "minimum": list(result.series["heart_rate_bpm"]["minimum"]),
            "maximum": list(result.series["heart_rate_bpm"]["maximum"]),
        },
        "speed_mps": {"average": list(result.series["speed_mps"]["average"])},
        "pace_seconds_per_km": {
            "average": list(result.series["pace_seconds_per_km"]["average"]),
            "fastest": list(result.series["pace_seconds_per_km"]["fastest"]),
            "slowest": list(result.series["pace_seconds_per_km"]["slowest"]),
        },
        "cadence_rpm": {"average": list(result.series["cadence_rpm"]["average"])},
        "power_w": {"average": list(result.series["power_w"]["average"])},
        "altitude_m": {"average": list(result.series["altitude_m"]["average"])},
        "grade_pct": {"average": list(result.series["grade_pct"]["average"])},
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
    if reduced.next_start_seconds is not None:
        envelope["window"]["next_start_seconds"] = reduced.next_start_seconds

    malformed_count = parsed.malformed_record_count
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
    "MAX_DURATION_SECONDS",
    "MAX_FIT_ELAPSED_SECONDS",
    "MAX_RESOLUTION_SECONDS",
    "MAX_RETURNED_POINTS",
    "get_activity_timeseries_service",
]
