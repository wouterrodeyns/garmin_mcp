"""Validated, bounded orchestration for wellness heart-rate requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import ceil
from statistics import median
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


class InvalidProviderResponse(Exception):
    """Raised only when an untrusted wellness-HR DTO violates its contract."""


@dataclass(frozen=True)
class Sample:
    """One fully validated Garmin heart-rate sample."""

    timestamp_ms: int
    bpm: int | None


@dataclass(frozen=True)
class DayFacts:
    """Validated source facts, isolated from DTO containers."""

    date: str
    summary: dict[str, int | None]
    offset_minutes: int | None
    samples: tuple[Sample, ...]
    source_points: int


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

    requested_day_count = (parsed_end - parsed_start).days + 1
    if requested_day_count > MAX_DAYS:
        return "date_range_too_large", None
    requested_dates = _requested_dates(parsed_start, parsed_end)

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


_SUMMARY_FIELDS = {
    "restingHeartRate": "resting_hr_bpm",
    "minHeartRate": "min_hr_bpm",
    "maxHeartRate": "max_hr_bpm",
    "lastSevenDaysAvgRestingHeartRate": "seven_day_avg_resting_hr_bpm",
}
_LOCAL_TIME_WARNING = "Local wellness heart-rate time is unavailable for this date."
_INVALID_DTO_WARNING = "Wellness heart-rate data had an unexpected shape for this date."


def _summary_facts(raw: dict[Any, Any]) -> dict[str, int | None]:
    """Read Garmin's summary scalars without deriving any values from samples."""
    summary: dict[str, int | None] = {}
    for source_key, output_key in _SUMMARY_FIELDS.items():
        value = raw.get(source_key)
        if value is None:
            summary[output_key] = None
        elif type(value) is int and 1 <= value <= 300:
            summary[output_key] = value
        else:
            raise InvalidProviderResponse
    return summary


def _parse_naive_bound(raw: dict[Any, Any], key: str) -> datetime | None:
    """Parse one exact-string naive Garmin daily bound, or decline provenance."""
    value = raw.get(key)
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is None else None


def _local_offset_minutes(raw: dict[Any, Any]) -> int | None:
    """Establish a stable offset only when both Garmin daily bounds agree."""
    start_gmt = _parse_naive_bound(raw, "startTimestampGMT")
    end_gmt = _parse_naive_bound(raw, "endTimestampGMT")
    start_local = _parse_naive_bound(raw, "startTimestampLocal")
    end_local = _parse_naive_bound(raw, "endTimestampLocal")
    if None in (start_gmt, end_gmt, start_local, end_local):
        return None

    assert start_gmt is not None
    assert end_gmt is not None
    assert start_local is not None
    assert end_local is not None
    start_delta = start_local.replace(tzinfo=timezone.utc) - start_gmt.replace(tzinfo=timezone.utc)
    end_delta = end_local.replace(tzinfo=timezone.utc) - end_gmt.replace(tzinfo=timezone.utc)
    start_microseconds = (
        (start_delta.days * 86_400 + start_delta.seconds) * 1_000_000
        + start_delta.microseconds
    )
    end_microseconds = (
        (end_delta.days * 86_400 + end_delta.seconds) * 1_000_000
        + end_delta.microseconds
    )
    if start_microseconds != end_microseconds or start_microseconds % 60_000_000:
        return None
    minutes = start_microseconds // 60_000_000
    return minutes if -1439 <= minutes <= 1439 else None


def _validate_timestamp(timestamp_ms: Any) -> int:
    """Return one datetime-representable integer epoch millisecond timestamp."""
    if type(timestamp_ms) is not int:
        raise InvalidProviderResponse
    try:
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise InvalidProviderResponse from None
    return timestamp_ms


def _validate_bpm(bpm: Any) -> int | None:
    if bpm is None:
        return None
    if type(bpm) is int and 1 <= bpm <= 300:
        return bpm
    raise InvalidProviderResponse


def _normalize_day_facts(raw: Any, date_text: str, resolution: str) -> DayFacts:
    """Copy a strictly valid Garmin DTO into immutable local facts."""
    if type(raw) is not dict:
        raise InvalidProviderResponse

    summary = _summary_facts(raw)
    values = raw.get("heartRateValues")
    if values is None:
        source_points = 0
        samples: tuple[Sample, ...] = ()
    else:
        if type(values) is not list:
            raise InvalidProviderResponse
        source_points = len(values)
        if source_points > MAX_SOURCE_POINTS_PER_DAY:
            raise InvalidProviderResponse
        if resolution == "daily":
            samples = ()
        else:
            indexed_samples: list[tuple[int, int, Sample]] = []
            for source_index, item in enumerate(values):
                if type(item) is not list or len(item) != 2:
                    raise InvalidProviderResponse
                timestamp_ms = _validate_timestamp(item[0])
                bpm = _validate_bpm(item[1])
                indexed_samples.append((timestamp_ms, source_index, Sample(timestamp_ms, bpm)))
            indexed_samples.sort(key=lambda item: (item[0], item[1]))
            samples = tuple(item[2] for item in indexed_samples)

    return DayFacts(
        date=date_text,
        summary=summary,
        offset_minutes=_local_offset_minutes(raw),
        samples=samples,
        source_points=source_points,
    )


def _utc_iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _local_iso(timestamp_ms: int, offset_minutes: int | None) -> str | None:
    if offset_minutes is None:
        return None
    zone = timezone(timedelta(minutes=offset_minutes))
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).astimezone(zone).isoformat()


def _selected_samples(
    samples: tuple[Sample, ...],
    offset_minutes: int,
    start_time: time | None,
    end_time: time | None,
) -> tuple[Sample, ...]:
    """Select complete validated samples by a Garmin-local wall-clock window."""
    if start_time is None or end_time is None:
        return samples
    zone = timezone(timedelta(minutes=offset_minutes))
    selected: list[Sample] = []
    for sample in samples:
        local_wall_time = datetime.fromtimestamp(
            sample.timestamp_ms / 1000, timezone.utc
        ).astimezone(zone).replace(tzinfo=None).time()
        if start_time <= local_wall_time < end_time:
            selected.append(sample)
    return tuple(selected)


def _median_interval_seconds(samples: tuple[Sample, ...]) -> int | float | None:
    positive_intervals = [
        (current.timestamp_ms - previous.timestamp_ms) / 1000
        for previous, current in zip(samples, samples[1:])
        if current.timestamp_ms > previous.timestamp_ms
    ]
    if not positive_intervals:
        return None
    value = median(positive_intervals)
    return int(value) if value.is_integer() else value


def _sampling(
    source_points: int,
    selected: tuple[Sample, ...],
    resolution: str,
) -> dict[str, int | float | bool | None]:
    if resolution == "daily":
        return {
            "source_points": source_points,
            "valid_bpm_points": None,
            "null_bpm_points": None,
            "returned_points": 0,
            "observed_median_interval_seconds": None,
            "duration_from_sample_count_valid": False,
        }
    valid_bpm_points = sum(sample.bpm is not None for sample in selected)
    null_bpm_points = len(selected) - valid_bpm_points
    return {
        "source_points": source_points,
        "valid_bpm_points": valid_bpm_points,
        "null_bpm_points": null_bpm_points,
        "returned_points": len(selected) if resolution == "raw" else 0,
        "observed_median_interval_seconds": _median_interval_seconds(selected),
        "duration_from_sample_count_valid": False,
    }


def _day_result(
    facts: DayFacts,
    resolution: str,
    selected: tuple[Sample, ...],
) -> dict[str, Any]:
    summary_available = any(value is not None for value in facts.summary.values())
    if resolution == "daily":
        available = summary_available
    elif resolution == "raw":
        available = bool(selected) or summary_available
    else:
        available = summary_available
    points = [
        {
            "time_local": _local_iso(sample.timestamp_ms, facts.offset_minutes),
            "time_utc": _utc_iso(sample.timestamp_ms),
            "bpm": sample.bpm,
        }
        for sample in selected
    ] if resolution == "raw" else []
    return {
        "date": facts.date,
        "available": available,
        "summary": facts.summary,
        "time_provenance": {
            "local_offset_minutes": facts.offset_minutes,
            "local_time_available": facts.offset_minutes is not None,
        },
        "sampling": _sampling(facts.source_points, selected, resolution),
        "points": points,
        "gaps": [],
    }


def _dated_warning(date_text: str, code: str, message: str) -> dict[str, str]:
    return {
        "provider": "wellness_heart_rate",
        "date": date_text,
        "code": code,
        "message": message,
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

    parsed_start_time = _strict_time(start_time) if start_time is not None else None
    parsed_end_time = _strict_time(end_time) if end_time is not None else None
    has_window = parsed_start_time is not None and parsed_end_time is not None
    failed_dates = 0
    for date_text in dates:
        provider_result = get_wellness_heart_rate_day(client, date_text)
        result["availability"][date_text] = False
        if provider_result.failed:
            failed_dates += 1
            _append_provider_warnings(result, provider_result, date_text)
            continue

        try:
            facts = _normalize_day_facts(provider_result.data, date_text, resolution)
        except InvalidProviderResponse:
            failed_dates += 1
            result["warnings"].append(
                _dated_warning(date_text, "invalid_provider_response", _INVALID_DTO_WARNING)
            )
            continue

        requires_local_time = has_window or resolution in BIN_MINUTES
        if facts.offset_minutes is None:
            result["warnings"].append(
                _dated_warning(date_text, "local_time_unavailable", _LOCAL_TIME_WARNING)
            )
            if requires_local_time:
                failed_dates += 1
                continue
            selected = facts.samples
        else:
            selected = _selected_samples(
                facts.samples, facts.offset_minutes, parsed_start_time, parsed_end_time
            )

        if resolution == "raw" and len(selected) > MAX_RAW_POINTS:
            result["availability"] = {}
            result["days"] = []
            result["warnings"] = []
            return _error(result, "raw_response_too_large")

        day = _day_result(facts, resolution, selected)
        result["availability"][date_text] = day["available"]
        result["days"].append(day)

    if failed_dates == len(dates):
        return _error(result, "wellness_heart_rate_unavailable")
    if failed_dates:
        result["status"] = "partial_success"
    return result
