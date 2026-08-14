"""Validated, bounded orchestration for wellness heart-rate requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
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
_MAX_RESOLUTION_TEXT_LENGTH = max(len(value) for value in RESOLUTIONS)

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


def _utf8_bytes(value: str) -> bytes:
    return value.encode("utf-8", "strict")


def _safe_text(value: Any, max_length: int) -> str | None:
    if type(value) is not str or len(value) > max_length:
        return None
    try:
        _utf8_bytes(value)
    except UnicodeEncodeError:
        return None
    return value


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
            "start_date": _safe_text(start_date, 10),
            "end_date": _safe_text(end_date, 10),
            "start_time": _safe_text(start_time, 5),
            "end_time": _safe_text(end_time, 5),
        },
        "resolution": _safe_text(resolution, _MAX_RESOLUTION_TEXT_LENGTH),
        "availability": {},
        "days": [],
        "warnings": [],
    }


def _error(result: dict[str, Any], code: str) -> dict[str, Any]:
    result["status"] = "error"
    result["error"] = {"code": code, "message": ERROR_MESSAGES[code]}
    return result


def _global_error(result: dict[str, Any], code: str) -> dict[str, Any]:
    """Return a global refusal without retaining a partial normalized series."""
    result["availability"] = {}
    result["days"] = []
    result["warnings"] = []
    return _error(result, code)


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
_PROVIDER_UNAVAILABLE_WARNING = "Wellness heart-rate data is unavailable for this date."
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _utc_datetime(timestamp_ms: int) -> datetime:
    """Convert exact epoch milliseconds without a floating-point round trip."""
    seconds, milliseconds = divmod(timestamp_ms, 1000)
    return _UTC_EPOCH + timedelta(seconds=seconds, milliseconds=milliseconds)


def _local_datetime(timestamp_ms: int, offset_minutes: int) -> datetime:
    """Project a validated UTC instant into one fixed Garmin-local offset."""
    zone = timezone(timedelta(minutes=offset_minutes))
    return (_utc_datetime(timestamp_ms) + timedelta(minutes=offset_minutes)).replace(tzinfo=zone)


def _bin_bounds(
    timestamp_ms: int, offset_minutes: int, bin_minutes: int
) -> tuple[datetime, datetime, datetime, datetime]:
    """Return exact fixed-offset local and UTC boundaries for one source timestamp."""
    local = _local_datetime(timestamp_ms, offset_minutes)
    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    local_minute = local.hour * 60 + local.minute
    start_local = local_midnight + timedelta(
        minutes=(local_minute // bin_minutes) * bin_minutes
    )
    end_local = start_local + timedelta(minutes=bin_minutes)
    return (
        start_local,
        end_local,
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def _require_exact_string_keys(raw: dict[Any, Any]) -> None:
    """Reject non-string keys before any string-key lookup can compare them."""
    for key in raw:
        if type(key) is not str:
            raise InvalidProviderResponse


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
        _utc_datetime(timestamp_ms)
    except OverflowError:
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

    _require_exact_string_keys(raw)
    if "calendarDate" in raw and (
        type(raw["calendarDate"]) is not str or raw["calendarDate"] != date_text
    ):
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

    offset_minutes = _local_offset_minutes(raw)
    if offset_minutes is not None:
        for sample in samples:
            try:
                _local_datetime(sample.timestamp_ms, offset_minutes)
            except OverflowError:
                raise InvalidProviderResponse from None

    return DayFacts(
        date=date_text,
        summary=summary,
        offset_minutes=offset_minutes,
        samples=samples,
        source_points=source_points,
    )


def _utc_iso(timestamp_ms: int) -> str:
    return _utc_datetime(timestamp_ms).isoformat().replace("+00:00", "Z")


def _local_iso(timestamp_ms: int, offset_minutes: int | None) -> str | None:
    if offset_minutes is None:
        return None
    return _local_datetime(timestamp_ms, offset_minutes).isoformat()


def _utc_datetime_iso(value: datetime) -> str:
    """Format an aware boundary as the stable UTC-Z public representation."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _selected_samples(
    samples: tuple[Sample, ...],
    offset_minutes: int,
    start_time: time | None,
    end_time: time | None,
) -> tuple[Sample, ...]:
    """Select complete validated samples by a Garmin-local wall-clock window."""
    if start_time is None or end_time is None:
        return samples
    selected: list[Sample] = []
    for sample in samples:
        local_wall_time = _local_datetime(sample.timestamp_ms, offset_minutes).replace(
            tzinfo=None
        ).time()
        if start_time <= local_wall_time < end_time:
            selected.append(sample)
    return tuple(selected)


def _validate_bin_contributors(
    selected: tuple[Sample, ...], offset_minutes: int, bin_minutes: int
) -> None:
    """Reject only selected valid-bpm samples whose public bin bounds overflow."""
    for sample in selected:
        if sample.bpm is None:
            continue
        try:
            _bin_bounds(sample.timestamp_ms, offset_minutes, bin_minutes)
        except OverflowError:
            raise InvalidProviderResponse from None


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
    returned_points: int,
) -> dict[str, int | float | bool | None]:
    if resolution == "daily":
        return {
            "source_points": source_points,
            "valid_bpm_points": None,
            "null_bpm_points": None,
            "returned_points": returned_points,
            "observed_median_interval_seconds": None,
            "duration_from_sample_count_valid": False,
        }
    valid_bpm_points = sum(sample.bpm is not None for sample in selected)
    null_bpm_points = len(selected) - valid_bpm_points
    return {
        "source_points": source_points,
        "valid_bpm_points": valid_bpm_points,
        "null_bpm_points": null_bpm_points,
        "returned_points": returned_points,
        "observed_median_interval_seconds": _median_interval_seconds(selected),
        "duration_from_sample_count_valid": False,
    }


def _binned_points(
    selected: tuple[Sample, ...], resolution: str, offset_minutes: int
) -> list[dict[str, str | int | float]]:
    """Reduce valid selected samples into fixed Garmin-local wall-clock bins."""
    bin_minutes = BIN_MINUTES[resolution]
    values_by_start: dict[datetime, list[int]] = {}
    bounds_by_start: dict[datetime, tuple[datetime, datetime, datetime]] = {}
    for sample in selected:
        if sample.bpm is None:
            continue
        start_local, end_local, start_utc, end_utc = _bin_bounds(
            sample.timestamp_ms, offset_minutes, bin_minutes
        )
        values_by_start.setdefault(start_local, []).append(sample.bpm)
        bounds_by_start.setdefault(start_local, (end_local, start_utc, end_utc))

    points: list[dict[str, str | int | float]] = []
    for start_local in sorted(values_by_start):
        values = values_by_start[start_local]
        end_local, start_utc, end_utc = bounds_by_start[start_local]
        points.append({
            "start_time_local": start_local.isoformat(),
            "end_time_local": end_local.isoformat(),
            "start_time_utc": _utc_datetime_iso(start_utc),
            "end_time_utc": _utc_datetime_iso(end_utc),
            "min_bpm": min(values),
            "mean_bpm": round(sum(values) / len(values), 1),
            "max_bpm": max(values),
            "sample_count": len(values),
        })
    return points


def _gap_points(
    selected: tuple[Sample, ...], offset_minutes: int | None
) -> list[dict[str, str | float | None]]:
    """Describe only observed 300-second-or-longer valid-bpm intervals."""
    valid_samples = tuple(sample for sample in selected if sample.bpm is not None)
    gaps: list[dict[str, str | float | None]] = []
    for previous, current in zip(valid_samples, valid_samples[1:]):
        elapsed_ms = current.timestamp_ms - previous.timestamp_ms
        if elapsed_ms < GAP_THRESHOLD_SECONDS * 1000:
            continue
        gaps.append({
            "start_time_local": _local_iso(previous.timestamp_ms, offset_minutes),
            "end_time_local": _local_iso(current.timestamp_ms, offset_minutes),
            "start_time_utc": _utc_iso(previous.timestamp_ms),
            "end_time_utc": _utc_iso(current.timestamp_ms),
            "elapsed_minutes": round(elapsed_ms / 60_000, 1),
        })
    return gaps


def _empty_day(date_text: str) -> dict[str, Any]:
    """Return the fixed no-data schema for one failed requested date."""
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


def _day_result(
    facts: DayFacts,
    resolution: str,
    selected: tuple[Sample, ...],
) -> dict[str, Any]:
    """Build a complete public day from trusted normalized source facts."""
    summary_available = any(value is not None for value in facts.summary.values())
    if resolution == "raw":
        points: list[dict[str, Any]] = [
            {
                "time_local": _local_iso(sample.timestamp_ms, facts.offset_minutes),
                "time_utc": _utc_iso(sample.timestamp_ms),
                "bpm": sample.bpm,
            }
            for sample in selected
        ]
    elif resolution in BIN_MINUTES:
        assert facts.offset_minutes is not None
        points = _binned_points(selected, resolution, facts.offset_minutes)
    else:
        points = []

    if resolution == "daily":
        available = summary_available
        gaps: list[dict[str, Any]] = []
    elif resolution == "raw":
        available = bool(selected) or summary_available
        gaps = _gap_points(selected, facts.offset_minutes)
    else:
        available = bool(points) or summary_available
        gaps = _gap_points(selected, facts.offset_minutes)
    return {
        "date": facts.date,
        "available": available,
        "summary": facts.summary,
        "time_provenance": {
            "local_offset_minutes": facts.offset_minutes,
            "local_time_available": facts.offset_minutes is not None,
        },
        "sampling": _sampling(facts.source_points, selected, resolution, len(points)),
        "points": points,
        "gaps": gaps,
    }


def _dated_warning(date_text: str, code: str, message: str) -> dict[str, str]:
    return {
        "provider": "wellness_heart_rate",
        "date": date_text,
        "code": code,
        "message": message,
    }


def _compact_size(result: dict[str, Any]) -> int:
    """Measure the exact compact UTF-8 wire representation without suppressing errors."""
    return len(json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


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
    returned_bin_count = 0
    for date_text in dates:
        provider_result = get_wellness_heart_rate_day(client, date_text)
        if provider_result.failed:
            failed_dates += 1
            day = _empty_day(date_text)
            result["days"].append(day)
            result["availability"][date_text] = day["available"]
            result["warnings"].append(
                _dated_warning(
                    date_text, "provider_unavailable", _PROVIDER_UNAVAILABLE_WARNING
                )
            )
            continue

        try:
            facts = _normalize_day_facts(provider_result.data, date_text, resolution)
        except InvalidProviderResponse:
            failed_dates += 1
            day = _empty_day(date_text)
            result["days"].append(day)
            result["availability"][date_text] = day["available"]
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
                day = _empty_day(date_text)
                result["days"].append(day)
                result["availability"][date_text] = day["available"]
                continue
            selected = facts.samples
        else:
            selected = _selected_samples(
                facts.samples, facts.offset_minutes, parsed_start_time, parsed_end_time
            )

        if resolution in BIN_MINUTES:
            assert facts.offset_minutes is not None
            try:
                _validate_bin_contributors(
                    selected, facts.offset_minutes, BIN_MINUTES[resolution]
                )
            except InvalidProviderResponse:
                failed_dates += 1
                day = _empty_day(date_text)
                result["days"].append(day)
                result["availability"][date_text] = day["available"]
                result["warnings"].append(
                    _dated_warning(date_text, "invalid_provider_response", _INVALID_DTO_WARNING)
                )
                continue

        if resolution == "raw" and len(selected) > MAX_RAW_POINTS:
            return _global_error(result, "raw_response_too_large")

        day = _day_result(facts, resolution, selected)
        if resolution in BIN_MINUTES and day["sampling"]["returned_points"] > MAX_RETURNED_BINS:
            return _global_error(result, "request_too_large")
        result["availability"][date_text] = day["available"]
        result["days"].append(day)
        if resolution in BIN_MINUTES:
            returned_bin_count += day["sampling"]["returned_points"]
            if returned_bin_count > MAX_RETURNED_BINS:
                return _global_error(result, "request_too_large")

    if failed_dates == len(dates):
        return _error(result, "wellness_heart_rate_unavailable")
    if failed_dates:
        result["status"] = "partial_success"
    if _compact_size(result) > MAX_SERIALIZED_BYTES:
        return _global_error(result, "response_too_large")
    return result
