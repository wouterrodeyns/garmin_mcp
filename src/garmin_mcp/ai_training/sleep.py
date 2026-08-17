"""Strict normalization of one untrusted Garmin sleep-night response."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any


DEFAULT_SLEEP_DAYS = 7
MAX_SLEEP_DAYS = 30
MAX_SLEEP_TEXT_LENGTH = 64


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
    if type(value) not in (int, float) or not isfinite(value):
        raise InvalidSleepResponse
    if value < minimum or value > maximum:
        raise InvalidSleepResponse
    return value


def _optional_count(parent: dict[Any, Any], key: str) -> int | None:
    value = parent.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 0 or value > 10_000:
        raise InvalidSleepResponse
    return value


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
    if requested_date is not None:
        requested_date = _canonical_date(requested_date)

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
    resting_hr_bpm = _optional_number(daily, "restingHeartRate", 1, 300)
    overnight_hrv_ms = _optional_number(raw, "avgOvernightHrv", 1, 1000)
    average_sleep_stress = _optional_number(daily, "avgSleepStress", 0, 100)
    awake_count = _optional_count(daily, "awakeCount")
    restless_moments_count = _optional_count(daily, "restlessMomentsCount")
    average_spo2_percent = _optional_number(spo2, "averageSpo2", 0, 100)
    lowest_spo2_percent = _optional_number(spo2, "lowestSpo2", 0, 100)

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
    )
