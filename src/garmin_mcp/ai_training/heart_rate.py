"""Validated, bounded orchestration for wellness heart-rate requests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from math import ceil
from typing import Any

from garmin_mcp.ai_training.providers import ProviderResult, get_wellness_heart_rate_day


MAX_DAYS = 7
MAX_SOURCE_POINTS_PER_DAY = 10_000
MAX_RAW_POINTS = 1_000
MAX_RETURNED_BINS = 1_000
MAX_SERIALIZED_BYTES = 262_144
GAP_THRESHOLD_SECONDS = 300
RESOLUTIONS = ("daily", "raw", "5m", "15m", "30m", "60m")
BIN_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "60m": 60}

ERROR_MESSAGES = {
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


def _strict_date(value: Any) -> date | None:
    """Parse only canonical, built-in-string calendar dates."""
    if type(value) is not str or len(value) != 10:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _strict_time(value: Any) -> time | None:
    """Parse only canonical, built-in-string 24-hour clock times."""
    if type(value) is not str or len(value) != 5:
        return None
    try:
        parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None
    return parsed if parsed.strftime("%H:%M") == value else None


def _safe_text(value: Any) -> str | None:
    return value if type(value) is str else None


def _base_envelope(
    start_date: Any,
    end_date: Any,
    resolution: Any,
    start_time: Any,
    end_time: Any,
) -> dict[str, Any]:
    """Return the public response shape before validation or provider reads."""
    return {
        "status": "success",
        "error": None,
        "period": {
            "start_date": _safe_text(start_date),
            "end_date": _safe_text(end_date),
            "start_time": _safe_text(start_time),
            "end_time": _safe_text(end_time),
        },
        "resolution": _safe_text(resolution),
        "availability": {},
        "days": [],
        "warnings": [],
    }


def _error(result: dict[str, Any], code: str) -> dict[str, Any]:
    result["status"] = "error"
    result["error"] = {"code": code, "message": ERROR_MESSAGES[code]}
    return result


def _requested_dates(start_date: date, end_date: date) -> list[str]:
    days = (end_date - start_date).days + 1
    return [(start_date + timedelta(days=offset)).isoformat() for offset in range(days)]


def _validate_request(
    start_date: Any,
    end_date: Any,
    resolution: Any,
    start_time: Any,
    end_time: Any,
) -> tuple[str | None, list[str] | None]:
    """Validate inputs in public-contract order, without contacting the provider."""
    parsed_start = _strict_date(start_date)
    if parsed_start is None:
        return "invalid_start_date", None

    resolved_end = start_date if end_date is None else end_date
    parsed_end = _strict_date(resolved_end)
    if parsed_end is None:
        return "invalid_end_date", None
    if parsed_start > parsed_end:
        return "invalid_date_range", None

    requested_dates = _requested_dates(parsed_start, parsed_end)
    if len(requested_dates) > MAX_DAYS:
        return "date_range_too_large", None

    if type(resolution) is not str or resolution not in RESOLUTIONS:
        return "invalid_resolution", None
    if resolution == "raw" and len(requested_dates) != 1:
        return "raw_requires_single_date", None

    parsed_start_time = _strict_time(start_time) if start_time is not None else None
    parsed_end_time = _strict_time(end_time) if end_time is not None else None
    has_window = start_time is not None or end_time is not None
    if (start_time is None) != (end_time is None):
        return "invalid_time_window", None
    if has_window and (parsed_start_time is None or parsed_end_time is None):
        return "invalid_time_window", None
    if has_window and parsed_start_time >= parsed_end_time:
        return "invalid_time_window", None
    if resolution == "daily" and has_window:
        return "invalid_time_window", None

    if resolution in BIN_MINUTES:
        window_minutes = (
            (parsed_end_time.hour * 60 + parsed_end_time.minute)
            - (parsed_start_time.hour * 60 + parsed_start_time.minute)
            if has_window and parsed_start_time is not None and parsed_end_time is not None
            else 24 * 60
        )
        projected_bins = ceil(window_minutes / BIN_MINUTES[resolution]) * len(requested_dates)
        if projected_bins > MAX_RETURNED_BINS:
            return "request_too_large", None

    return None, requested_dates


def _empty_day(date_text: str) -> dict[str, Any]:
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


def _append_provider_warnings(
    result: dict[str, Any], provider_result: ProviderResult, date_text: str
) -> None:
    for warning in provider_result.warnings:
        if not isinstance(warning, dict):
            continue
        provider = warning.get("provider")
        code = warning.get("code")
        message = warning.get("message")
        if all(type(value) is str for value in (provider, code, message)):
            result["warnings"].append(
                {"provider": provider, "code": code, "message": message, "date": date_text}
            )


def get_wellness_heart_rate_service(
    client: Any,
    start_date: Any,
    end_date: Any = None,
    resolution: Any = "raw",
    start_time: Any = None,
    end_time: Any = None,
) -> dict[str, Any]:
    """Validate and orchestrate bounded daily wellness-HR reads."""
    result = _base_envelope(start_date, end_date, resolution, start_time, end_time)
    error_code, dates = _validate_request(start_date, end_date, resolution, start_time, end_time)
    if error_code is not None:
        return _error(result, error_code)

    assert dates is not None
    result["period"]["end_date"] = dates[-1]
    if client is None:
        return _error(result, "client_unavailable")

    failed_dates = 0
    for date_text in dates:
        provider_result = get_wellness_heart_rate_day(client, date_text)
        result["availability"][date_text] = False
        if provider_result.failed:
            failed_dates += 1
            _append_provider_warnings(result, provider_result, date_text)
            continue
        result["days"].append(_empty_day(date_text))

    if failed_dates == len(dates):
        return _error(result, "wellness_heart_rate_unavailable")
    if failed_dates:
        result["status"] = "partial_success"
    return result
