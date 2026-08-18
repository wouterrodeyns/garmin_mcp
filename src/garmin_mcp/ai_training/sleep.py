"""Strict normalization of one untrusted Garmin sleep-night response."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from typing import Any

from .providers import get_sleep_night


DEFAULT_SLEEP_DAYS = 7
MAX_SLEEP_DAYS = 30
MAX_SLEEP_TEXT_LENGTH = 64
# Sleep boundary epoch-millisecond bounds: 2000-01-01Z through 2100-01-01Z.
MIN_SLEEP_TIMESTAMP_MS = 946_684_800_000
MAX_SLEEP_TIMESTAMP_MS = 4_102_444_800_000
MAX_SLEEP_UTC_OFFSET_MINUTES = 1439

PUBLIC_SLEEP_ERRORS = {
    "invalid_days": "days must be an integer from 1 through 30.",
    "client_unavailable": "Garmin client is unavailable.",
    "sleep_trend_unavailable": "Sleep trend is unavailable for the requested period.",
}

SLEEP_WARNINGS = {
    "sleep_data_unavailable": "Sleep data is unavailable for this date.",
    "provider_unavailable": "Sleep data could not be retrieved for this date.",
    "invalid_provider_response": "Sleep data returned an invalid response for this date.",
}


class InvalidSleepResponse(ValueError):
    """Raised when a Garmin sleep response violates the DTO contract."""


@dataclass(frozen=True, slots=True)
class SleepNightFacts:
    """Validated facts from exactly one Garmin sleep night."""

    date: str
    sleep_seconds: int | float | None
    nap_seconds: int | float | None
    score: int | float | None
    score_qualifier: str | None
    deep_seconds: int | float | None
    light_seconds: int | float | None
    rem_seconds: int | float | None
    awake_seconds: int | float | None
    resting_hr_bpm: int | float | None
    overnight_hrv_ms: int | float | None
    average_sleep_stress: int | float | None
    awake_count: int | None
    restless_moments_count: int | None
    average_spo2_percent: int | float | None
    lowest_spo2_percent: int | float | None
    sleep_start_gmt_ms: int | float | None
    sleep_end_gmt_ms: int | float | None
    sleep_start_local_ms: int | float | None
    sleep_end_local_ms: int | float | None


def empty_sleep_night(date_text: str) -> dict[str, Any]:
    """Return the stable public representation for an unavailable night."""
    return {
        "date": date_text,
        "available": False,
        "duration_hours": None,
        "nap_minutes": None,
        "score": None,
        "score_qualifier": None,
        "stages": {
            "deep_minutes": None,
            "light_minutes": None,
            "rem_minutes": None,
            "awake_minutes": None,
        },
        "resting_hr_bpm": None,
        "overnight_hrv_ms": None,
        "average_sleep_stress": None,
        "awake_count": None,
        "restless_moments_count": None,
        "spo2": {"average_percent": None, "lowest_percent": None},
        "sleep_times": {
            "bedtime_local": None,
            "bedtime_utc": None,
            "bedtime_utc_offset_minutes": None,
            "wake_time_local": None,
            "wake_time_utc": None,
            "wake_time_utc_offset_minutes": None,
        },
    }


def _minutes(seconds: int | float | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


def _hours(seconds: int | float | None) -> float | None:
    return None if seconds is None else round(seconds / 3600, 1)


def _whole_seconds(timestamp_ms: int | float) -> int:
    """Truncate a validated positive epoch-millisecond value to whole seconds."""
    return int(timestamp_ms) // 1000


def _utc_iso(timestamp_ms: int | float | None) -> str | None:
    """Render a validated GMT boundary as an unambiguous UTC instant."""
    if timestamp_ms is None:
        return None
    moment = datetime.fromtimestamp(_whole_seconds(timestamp_ms), timezone.utc)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _local_iso(timestamp_ms: int | float | None) -> str | None:
    """Render a validated Local boundary as naive local wall-clock text.

    Garmin pre-shifts the ``*TimestampLocal`` epoch by the local UTC offset, so
    reading it in UTC yields the wall clock the watch displayed. The offset is
    never encoded here; it is reported separately only when both frames exist.
    """
    if timestamp_ms is None:
        return None
    moment = datetime.fromtimestamp(_whole_seconds(timestamp_ms), timezone.utc)
    return moment.replace(tzinfo=None).isoformat(timespec="seconds")


def _utc_offset_minutes(
    gmt_ms: int | float | None, local_ms: int | float | None
) -> int | None:
    """Derive one boundary's UTC offset, refusing to invent an absent frame."""
    if gmt_ms is None or local_ms is None:
        return None
    delta = local_ms - gmt_ms
    if delta % 60_000:
        raise InvalidSleepResponse
    minutes = int(delta // 60_000)
    if abs(minutes) > MAX_SLEEP_UTC_OFFSET_MINUTES:
        raise InvalidSleepResponse
    return minutes


def _sleep_times(facts: SleepNightFacts) -> dict[str, Any]:
    """Project both sleep boundaries without ever mixing or fabricating frames."""
    return {
        "bedtime_local": _local_iso(facts.sleep_start_local_ms),
        "bedtime_utc": _utc_iso(facts.sleep_start_gmt_ms),
        "bedtime_utc_offset_minutes": _utc_offset_minutes(
            facts.sleep_start_gmt_ms, facts.sleep_start_local_ms
        ),
        "wake_time_local": _local_iso(facts.sleep_end_local_ms),
        "wake_time_utc": _utc_iso(facts.sleep_end_gmt_ms),
        "wake_time_utc_offset_minutes": _utc_offset_minutes(
            facts.sleep_end_gmt_ms, facts.sleep_end_local_ms
        ),
    }


def project_sleep_night(facts: SleepNightFacts) -> dict[str, Any]:
    """Project validated sleep facts into the stable public night DTO."""
    return {
        "date": facts.date,
        "available": True,
        "duration_hours": _hours(facts.sleep_seconds),
        "nap_minutes": _minutes(facts.nap_seconds),
        "score": facts.score,
        "score_qualifier": facts.score_qualifier,
        "stages": {
            "deep_minutes": _minutes(facts.deep_seconds),
            "light_minutes": _minutes(facts.light_seconds),
            "rem_minutes": _minutes(facts.rem_seconds),
            "awake_minutes": _minutes(facts.awake_seconds),
        },
        "resting_hr_bpm": facts.resting_hr_bpm,
        "overnight_hrv_ms": facts.overnight_hrv_ms,
        "average_sleep_stress": facts.average_sleep_stress,
        "awake_count": facts.awake_count,
        "restless_moments_count": facts.restless_moments_count,
        "spo2": {
            "average_percent": facts.average_spo2_percent,
            "lowest_percent": facts.lowest_spo2_percent,
        },
        "sleep_times": _sleep_times(facts),
    }


def _average(values: list[int | float], divisor: int = 1) -> dict[str, int | float | None]:
    if not values:
        return {"value": None, "nights": 0}
    return {"value": round(sum(values) / len(values) / divisor, 1), "nights": len(values)}


def aggregate_sleep_facts(
    facts: list[SleepNightFacts], nights_requested: int
) -> dict[str, Any]:
    """Aggregate raw validated values, delaying conversion and rounding."""
    return {
        "nights_requested": nights_requested,
        "nights_available": len(facts),
        "averages": {
            "duration_hours": _average(
                [fact.sleep_seconds for fact in facts if fact.sleep_seconds is not None],
                3600,
            ),
            "score": _average([fact.score for fact in facts if fact.score is not None]),
            "resting_hr_bpm": _average(
                [fact.resting_hr_bpm for fact in facts if fact.resting_hr_bpm is not None]
            ),
            "overnight_hrv_ms": _average(
                [fact.overnight_hrv_ms for fact in facts if fact.overnight_hrv_ms is not None]
            ),
            "spo2_percent": _average(
                [fact.average_spo2_percent for fact in facts if fact.average_spo2_percent is not None]
            ),
        },
    }


def _warning(date_text: str, code: str) -> dict[str, str]:
    return {
        "provider": "sleep",
        "date": date_text,
        "code": code,
        "message": SLEEP_WARNINGS[code],
    }


def _error(code: str) -> dict[str, str]:
    return {"code": code, "message": PUBLIC_SLEEP_ERRORS[code]}


def get_sleep_trend_service(
    client: Any, days: Any = DEFAULT_SLEEP_DAYS, *, today: date | None = None
) -> dict[str, Any]:
    """Read one sleep DTO per requested date and return a stable trend envelope."""
    if type(days) is not int or days < 1 or days > MAX_SLEEP_DAYS:
        return {
            "status": "error",
            "error": _error("invalid_days"),
            "period": {"days": None, "start_date": None, "end_date": None},
            "availability": {},
            "summary": aggregate_sleep_facts([], 0),
            "nights": [],
            "warnings": [],
        }

    if today is None:
        today = date.today()
    elif type(today) is not date:
        raise TypeError("today must be an exact date")

    try:
        oldest_date = today - timedelta(days=days - 1)
    except OverflowError:
        raise TypeError("today cannot represent the requested sleep period") from None
    dates = [oldest_date + timedelta(days=offset) for offset in range(days)]
    date_texts = [item.isoformat() for item in dates]
    period = {"days": days, "start_date": date_texts[0], "end_date": date_texts[-1]}
    if client is None:
        return {
            "status": "error",
            "error": _error("client_unavailable"),
            "period": period,
            "availability": {date_text: False for date_text in date_texts},
            "summary": aggregate_sleep_facts([], days),
            "nights": [empty_sleep_night(date_text) for date_text in date_texts],
            "warnings": [],
        }

    available_facts: list[SleepNightFacts] = []
    availability: dict[str, bool] = {}
    nights: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for date_text in date_texts:
        provider_result = get_sleep_night(client, date_text)
        if provider_result.failed:
            availability[date_text] = False
            nights.append(empty_sleep_night(date_text))
            warnings.append(_warning(date_text, "provider_unavailable"))
            continue
        try:
            facts = normalize_sleep_night(provider_result.data, date_text)
        except InvalidSleepResponse:
            availability[date_text] = False
            nights.append(empty_sleep_night(date_text))
            warnings.append(_warning(date_text, "invalid_provider_response"))
            continue
        if facts is None:
            availability[date_text] = False
            nights.append(empty_sleep_night(date_text))
            warnings.append(_warning(date_text, "sleep_data_unavailable"))
            continue
        available_facts.append(facts)
        availability[date_text] = True
        nights.append(project_sleep_night(facts))

    summary = aggregate_sleep_facts(available_facts, days)
    if summary["nights_available"] == days:
        status, error = "success", None
    elif summary["nights_available"]:
        status, error = "partial_success", None
    else:
        status, error = "error", _error("sleep_trend_unavailable")
    return {
        "status": status,
        "error": error,
        "period": period,
        "availability": availability,
        "summary": summary,
        "nights": nights,
        "warnings": warnings,
    }


_MISSING = object()


def _require_string_keys(raw: dict[Any, Any]) -> None:
    """Check keys before any name lookup can touch arbitrary key objects."""
    for key in raw:
        if type(key) is not str:
            raise InvalidSleepResponse


def _optional_dict(parent: dict[Any, Any], key: str) -> dict[Any, Any]:
    """Return a validated optional object, treating only ``None`` as empty."""
    value = parent.get(key)
    if value is None:
        return {}
    if type(value) is not dict:
        raise InvalidSleepResponse
    _require_string_keys(value)
    return value


def _optional_number(
    parent: dict[Any, Any], key: str, minimum: int, maximum: int
) -> int | float | None:
    value = parent.get(key)
    if value is None:
        return None
    if type(value) is float and not isfinite(value):
        raise InvalidSleepResponse
    if type(value) not in (int, float):
        raise InvalidSleepResponse
    if value < minimum or value > maximum:
        raise InvalidSleepResponse
    return value


def _compatible_number(
    sources: tuple[tuple[dict[Any, Any], str], ...], minimum: int, maximum: int
) -> int | float | None:
    """Coalesce equivalent validated Garmin field aliases without ambiguity."""
    values = [
        value
        for parent, key in sources
        if (value := _optional_number(parent, key, minimum, maximum)) is not None
    ]
    if not values:
        return None
    if any(value != values[0] for value in values[1:]):
        raise InvalidSleepResponse
    return values[0]


def _optional_count(parent: dict[Any, Any], key: str) -> int | None:
    value = parent.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 0 or value > 10_000:
        raise InvalidSleepResponse
    return value


def _boundary_pair(
    daily: dict[Any, Any], start_key: str, end_key: str
) -> tuple[int | float | None, int | float | None]:
    """Validate one frame's sleep boundary pair against the DTO contract."""
    start = _optional_number(
        daily, start_key, MIN_SLEEP_TIMESTAMP_MS, MAX_SLEEP_TIMESTAMP_MS
    )
    end = _optional_number(
        daily, end_key, MIN_SLEEP_TIMESTAMP_MS, MAX_SLEEP_TIMESTAMP_MS
    )
    if start is not None and end is not None and end < start:
        raise InvalidSleepResponse
    return start, end


def _canonical_date(value: Any) -> str:
    """Return an exact canonical ISO calendar date from untrusted text."""
    if type(value) is not str:
        raise InvalidSleepResponse
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise InvalidSleepResponse from None
    if parsed.isoformat() != value:
        raise InvalidSleepResponse
    return value


def _calendar_date(parent: dict[Any, Any]) -> str | None:
    value = parent.get("calendarDate", _MISSING)
    if value is _MISSING:
        return None
    return _canonical_date(value)


def _qualifier(overall: dict[Any, Any]) -> str | None:
    value = overall.get("qualifierKey")
    if value is None:
        return None
    if type(value) is not str:
        raise InvalidSleepResponse
    if value == "":
        return None
    if len(value) > MAX_SLEEP_TEXT_LENGTH:
        raise InvalidSleepResponse
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_SLEEP_TEXT_LENGTH:
        raise InvalidSleepResponse
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidSleepResponse from None
    return normalized


def _effective_date(
    requested_date: str | None, daily_date: str | None, spo2_date: str | None
) -> str | None:
    if requested_date is not None:
        if daily_date is not None and daily_date != requested_date:
            raise InvalidSleepResponse
        if spo2_date is not None and spo2_date != requested_date:
            raise InvalidSleepResponse
        return requested_date
    if daily_date is not None and spo2_date is not None and daily_date != spo2_date:
        raise InvalidSleepResponse
    return daily_date if daily_date is not None else spo2_date


def normalize_sleep_night(raw: Any, requested_date: str | None) -> SleepNightFacts | None:
    """Normalize one untrusted Garmin response without retaining source objects."""
    if requested_date is not None:
        requested_date = _canonical_date(requested_date)
    if raw is None:
        return None
    if type(raw) is list:
        if len(raw) == 0:
            return None
        raise InvalidSleepResponse
    if type(raw) is not dict:
        raise InvalidSleepResponse
    if len(raw) == 0:
        return None
    _require_string_keys(raw)

    daily = _optional_dict(raw, "dailySleepDTO")
    scores = _optional_dict(daily, "sleepScores")
    overall = _optional_dict(scores, "overall")
    spo2 = _optional_dict(raw, "wellnessSpO2SleepSummaryDTO")

    daily_date = _calendar_date(daily)
    spo2_date = _calendar_date(spo2)
    effective_date = _effective_date(requested_date, daily_date, spo2_date)

    sleep_seconds = _optional_number(daily, "sleepTimeSeconds", 0, 86_400)
    nap_seconds = _optional_number(daily, "napTimeSeconds", 0, 86_400)
    score = _optional_number(overall, "value", 0, 100)
    score_qualifier = _qualifier(overall)
    deep_seconds = _optional_number(daily, "deepSleepSeconds", 0, 86_400)
    light_seconds = _optional_number(daily, "lightSleepSeconds", 0, 86_400)
    rem_seconds = _optional_number(daily, "remSleepSeconds", 0, 86_400)
    awake_seconds = _optional_number(daily, "awakeSleepSeconds", 0, 86_400)
    resting_hr_bpm = _compatible_number(
        ((daily, "restingHeartRate"), (raw, "restingHeartRate")), 1, 300
    )
    overnight_hrv_ms = _optional_number(raw, "avgOvernightHrv", 1, 1000)
    average_sleep_stress = _optional_number(daily, "avgSleepStress", 0, 100)
    awake_count = _optional_count(daily, "awakeCount")
    restless_moments_count = _optional_count(daily, "restlessMomentsCount")
    average_spo2_percent = _compatible_number(
        ((spo2, "averageSpo2"), (spo2, "averageSPO2")), 0, 100
    )
    lowest_spo2_percent = _compatible_number(
        ((spo2, "lowestSpo2"), (spo2, "lowestSPO2")), 0, 100
    )
    sleep_start_gmt_ms, sleep_end_gmt_ms = _boundary_pair(
        daily, "sleepStartTimestampGMT", "sleepEndTimestampGMT"
    )
    sleep_start_local_ms, sleep_end_local_ms = _boundary_pair(
        daily, "sleepStartTimestampLocal", "sleepEndTimestampLocal"
    )
    _utc_offset_minutes(sleep_start_gmt_ms, sleep_start_local_ms)
    _utc_offset_minutes(sleep_end_gmt_ms, sleep_end_local_ms)

    facts = (
        sleep_seconds,
        nap_seconds,
        score,
        score_qualifier,
        deep_seconds,
        light_seconds,
        rem_seconds,
        awake_seconds,
        resting_hr_bpm,
        overnight_hrv_ms,
        average_sleep_stress,
        awake_count,
        restless_moments_count,
        average_spo2_percent,
        lowest_spo2_percent,
        sleep_start_gmt_ms,
        sleep_end_gmt_ms,
        sleep_start_local_ms,
        sleep_end_local_ms,
    )
    if not any(value is not None for value in facts):
        return None
    if effective_date is None:
        raise InvalidSleepResponse

    return SleepNightFacts(
        date=effective_date,
        sleep_seconds=sleep_seconds,
        nap_seconds=nap_seconds,
        score=score,
        score_qualifier=score_qualifier,
        deep_seconds=deep_seconds,
        light_seconds=light_seconds,
        rem_seconds=rem_seconds,
        awake_seconds=awake_seconds,
        resting_hr_bpm=resting_hr_bpm,
        overnight_hrv_ms=overnight_hrv_ms,
        average_sleep_stress=average_sleep_stress,
        awake_count=awake_count,
        restless_moments_count=restless_moments_count,
        average_spo2_percent=average_spo2_percent,
        lowest_spo2_percent=lowest_spo2_percent,
        sleep_start_gmt_ms=sleep_start_gmt_ms,
        sleep_end_gmt_ms=sleep_end_gmt_ms,
        sleep_start_local_ms=sleep_start_local_ms,
        sleep_end_local_ms=sleep_end_local_ms,
    )
