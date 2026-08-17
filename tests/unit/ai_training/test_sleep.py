"""Strict normalization tests for one Garmin sleep-night DTO."""

from __future__ import annotations

from dataclasses import replace
from math import inf, nan
from typing import Any

import pytest

from garmin_mcp.ai_training.sleep import (
    DEFAULT_SLEEP_DAYS,
    MAX_SLEEP_DAYS,
    MAX_SLEEP_TEXT_LENGTH,
    InvalidSleepResponse,
    SleepNightFacts,
    normalize_sleep_night,
)


def complete_sleep_payload(date_text: str = "2026-08-17") -> dict[str, Any]:
    """Return a complete Garmin DTO using every currently supported fact."""
    return {
        "dailySleepDTO": {
            "calendarDate": date_text,
            "sleepTimeSeconds": 26641,
            "napTimeSeconds": 900,
            "sleepScores": {"overall": {"value": 82, "qualifierKey": " GOOD "}},
            "deepSleepSeconds": 5281,
            "lightSleepSeconds": 15061,
            "remSleepSeconds": 6301,
            "awakeSleepSeconds": 1201,
            "restingHeartRate": 44,
            "avgSleepStress": 14,
            "awakeCount": 3,
            "restlessMomentsCount": 12,
        },
        "avgOvernightHrv": 94,
        "wellnessSpO2SleepSummaryDTO": {
            "calendarDate": date_text,
            "averageSpo2": 96,
            "lowestSpo2": 93,
        },
    }


def normalized_facts(**changes: Any) -> SleepNightFacts:
    """Return canonical expected facts, with focused per-test overrides."""
    base = SleepNightFacts(
        date="2026-08-17",
        sleep_seconds=26641,
        nap_seconds=900,
        score=82,
        score_qualifier="GOOD",
        deep_seconds=5281,
        light_seconds=15061,
        rem_seconds=6301,
        awake_seconds=1201,
        resting_hr_bpm=44,
        overnight_hrv_ms=94,
        average_sleep_stress=14,
        awake_count=3,
        restless_moments_count=12,
        average_spo2_percent=96,
        lowest_spo2_percent=93,
    )
    return replace(base, **changes)


def test_normalize_maps_complete_payload_and_trims_qualifier() -> None:
    assert DEFAULT_SLEEP_DAYS == 7
    assert MAX_SLEEP_DAYS == 30
    assert MAX_SLEEP_TEXT_LENGTH == 64

    facts = normalize_sleep_night(complete_sleep_payload(), "2026-08-17")

    assert facts == normalized_facts()
    assert facts is not None
    assert tuple(facts.__dataclass_fields__) == (
        "date", "sleep_seconds", "nap_seconds", "score", "score_qualifier",
        "deep_seconds", "light_seconds", "rem_seconds", "awake_seconds",
        "resting_hr_bpm", "overnight_hrv_ms", "average_sleep_stress",
        "awake_count", "restless_moments_count", "average_spo2_percent",
        "lowest_spo2_percent",
    )


@pytest.mark.parametrize("raw", [None, [], {}])
def test_normalize_empty_roots_return_none(raw: Any) -> None:
    assert normalize_sleep_night(raw, "2026-08-17") is None


@pytest.mark.parametrize("raw", [None, [], {}])
def test_empty_roots_keep_a_valid_requested_date_empty(raw: Any) -> None:
    assert normalize_sleep_night(raw, "2026-08-17") is None


@pytest.mark.parametrize("raw", [None, [], {}])
@pytest.mark.parametrize("requested_date", ["not-a-date", "2026-02-30", "2026-8-7"])
def test_empty_roots_reject_invalid_requested_dates(raw: Any, requested_date: str) -> None:
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(raw, requested_date)


def test_missing_supported_values_are_null_or_an_empty_night() -> None:
    payload = complete_sleep_payload()
    payload["dailySleepDTO"] = {"calendarDate": "2026-08-17", "sleepTimeSeconds": 1}
    payload["avgOvernightHrv"] = None
    payload["wellnessSpO2SleepSummaryDTO"] = None

    assert normalize_sleep_night(payload, "2026-08-17") == normalized_facts(
        sleep_seconds=1,
        nap_seconds=None,
        score=None,
        score_qualifier=None,
        deep_seconds=None,
        light_seconds=None,
        rem_seconds=None,
        awake_seconds=None,
        resting_hr_bpm=None,
        overnight_hrv_ms=None,
        average_sleep_stress=None,
        awake_count=None,
        restless_moments_count=None,
        average_spo2_percent=None,
        lowest_spo2_percent=None,
    )
    assert normalize_sleep_night(
        {"dailySleepDTO": {"calendarDate": "2026-08-17"}}, "2026-08-17"
    ) is None


def _set_source_value(payload: dict[str, Any], source: str, value: Any) -> None:
    if source == "hrv":
        payload["avgOvernightHrv"] = value
    elif source.startswith("spo2."):
        payload["wellnessSpO2SleepSummaryDTO"][source.removeprefix("spo2.")] = value
    else:
        payload["dailySleepDTO"][source] = value


@pytest.mark.parametrize(
    ("source", "minimum", "maximum"),
    [
        ("sleepTimeSeconds", 0, 86400), ("napTimeSeconds", 0, 86400),
        ("deepSleepSeconds", 0, 86400), ("lightSleepSeconds", 0, 86400),
        ("remSleepSeconds", 0, 86400), ("awakeSleepSeconds", 0, 86400),
        ("sleepScores.overall.value", 0, 100), ("avgSleepStress", 0, 100),
        ("spo2.averageSpo2", 0, 100), ("spo2.lowestSpo2", 0, 100),
        ("restingHeartRate", 1, 300), ("hrv", 1, 1000),
        ("awakeCount", 0, 10000), ("restlessMomentsCount", 0, 10000),
    ],
)
def test_numeric_ranges_accept_boundaries_and_reject_just_outside(
    source: str, minimum: int, maximum: int
) -> None:
    source_key = source
    if source == "sleepScores.overall.value":
        for value in (minimum, maximum):
            payload = complete_sleep_payload()
            payload["dailySleepDTO"]["sleepScores"]["overall"]["value"] = value
            assert normalize_sleep_night(payload, "2026-08-17") is not None
        for value in (minimum - 1, maximum + 1):
            payload = complete_sleep_payload()
            payload["dailySleepDTO"]["sleepScores"]["overall"]["value"] = value
            with pytest.raises(InvalidSleepResponse):
                normalize_sleep_night(payload, "2026-08-17")
        return

    for value in (minimum, maximum):
        payload = complete_sleep_payload()
        _set_source_value(payload, source_key, value)
        assert normalize_sleep_night(payload, "2026-08-17") is not None
    for value in (minimum - 1, maximum + 1):
        payload = complete_sleep_payload()
        _set_source_value(payload, source_key, value)
        with pytest.raises(InvalidSleepResponse):
            normalize_sleep_night(payload, "2026-08-17")


@pytest.mark.parametrize("value", [nan, inf, -inf, True, "82"])
def test_numeric_values_reject_nonfinite_bool_and_strings(value: Any) -> None:
    payload = complete_sleep_payload()
    payload["dailySleepDTO"]["sleepTimeSeconds"] = value
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, "2026-08-17")


def test_counts_reject_fractional_values() -> None:
    payload = complete_sleep_payload()
    payload["dailySleepDTO"]["awakeCount"] = 1.5
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, "2026-08-17")


@pytest.mark.parametrize("qualifier", ["x" * 65, " " * 65, "   "])
def test_qualifier_rejects_oversized_raw_and_all_whitespace_text(qualifier: str) -> None:
    payload = complete_sleep_payload()
    payload["dailySleepDTO"]["sleepScores"]["overall"]["qualifierKey"] = qualifier
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, "2026-08-17")


@pytest.mark.parametrize("surrogate", [chr(0xD800), chr(0xDC00)])
def test_qualifier_rejects_lone_utf16_surrogates(surrogate: str) -> None:
    payload = complete_sleep_payload()
    payload["dailySleepDTO"]["sleepScores"]["overall"]["qualifierKey"] = f"good{surrogate}"
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, "2026-08-17")


def test_qualifier_preserves_valid_unicode_text() -> None:
    payload = complete_sleep_payload()
    payload["dailySleepDTO"]["sleepScores"]["overall"]["qualifierKey"] = "  bonne nuit 🌙  "

    assert normalize_sleep_night(payload, "2026-08-17") == normalized_facts(
        score_qualifier="bonne nuit 🌙"
    )


def test_mismatched_and_disagreeing_calendar_dates_are_rejected() -> None:
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(complete_sleep_payload("2026-08-16"), "2026-08-17")

    payload = complete_sleep_payload()
    payload["wellnessSpO2SleepSummaryDTO"]["calendarDate"] = "2026-08-16"
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, None)


_INVALID_CALENDAR_DATES = ("not-a-date", "2026-02-30", "2026-8-7")


@pytest.mark.parametrize("invalid_date", _INVALID_CALENDAR_DATES)
@pytest.mark.parametrize("source", ["dailySleepDTO", "wellnessSpO2SleepSummaryDTO"])
def test_invalid_source_calendar_dates_are_rejected_when_requested_date_matches(
    source: str, invalid_date: str
) -> None:
    payload = complete_sleep_payload()
    payload[source]["calendarDate"] = invalid_date
    other_source = (
        "wellnessSpO2SleepSummaryDTO"
        if source == "dailySleepDTO"
        else "dailySleepDTO"
    )
    payload[other_source] = None

    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, invalid_date)


@pytest.mark.parametrize("invalid_date", _INVALID_CALENDAR_DATES)
@pytest.mark.parametrize("source", ["dailySleepDTO", "wellnessSpO2SleepSummaryDTO"])
def test_invalid_source_calendar_dates_are_rejected_without_requested_date(
    source: str, invalid_date: str
) -> None:
    payload = complete_sleep_payload()
    payload[source]["calendarDate"] = invalid_date
    other_source = (
        "wellnessSpO2SleepSummaryDTO"
        if source == "dailySleepDTO"
        else "dailySleepDTO"
    )
    payload[other_source] = None

    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, None)


class _DateSubclass(str):
    pass


@pytest.mark.parametrize(
    "requested_date",
    ["not-a-date", "2026-02-30", "2026-8-7", 17, _DateSubclass("2026-08-17")],
)
def test_requested_date_must_be_an_exact_canonical_iso_date(requested_date: Any) -> None:
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night({"avgOvernightHrv": 94}, requested_date)


class _PrivateDictError(RuntimeError):
    pass


class _PrivateListError(RuntimeError):
    pass


class HostileDict(dict[Any, Any]):
    def __bool__(self) -> bool:
        raise _PrivateDictError

    def get(self, key: Any, default: Any = None) -> Any:
        raise _PrivateDictError

    def __len__(self) -> int:
        raise _PrivateDictError

    def __iter__(self) -> Any:
        raise _PrivateDictError

    def __eq__(self, other: Any) -> bool:
        raise _PrivateDictError


class HostileList(list[Any]):
    def __bool__(self) -> bool:
        raise _PrivateListError

    def __len__(self) -> int:
        raise _PrivateListError

    def __iter__(self) -> Any:
        raise _PrivateListError

    def __eq__(self, other: Any) -> bool:
        raise _PrivateListError


@pytest.mark.parametrize(
    "raw",
    [HostileDict(), HostileList(), {"dailySleepDTO": HostileDict()}, {"dailySleepDTO": HostileList()}],
)
def test_hostile_container_subclasses_raise_only_public_error(raw: Any) -> None:
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(raw, "2026-08-17")


@pytest.mark.parametrize(
    "raw",
    [
        {1: "not allowed"},
        {"dailySleepDTO": {1: "not allowed"}},
        {"dailySleepDTO": {"sleepScores": {1: "not allowed"}}},
        {"dailySleepDTO": {"sleepScores": {"overall": {1: "not allowed"}}}},
        {"wellnessSpO2SleepSummaryDTO": {1: "not allowed"}},
    ],
)
def test_nonstring_keys_in_every_inspected_dict_are_rejected(raw: Any) -> None:
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(raw, "2026-08-17")


def test_unknown_fields_are_not_retained_or_echoed() -> None:
    payload = complete_sleep_payload()
    payload["unknown_root"] = "secret"
    payload["dailySleepDTO"]["unknown_daily"] = {"nested": "secret"}
    payload["wellnessSpO2SleepSummaryDTO"]["unknown_spo2"] = "secret"

    facts = normalize_sleep_night(payload, "2026-08-17")

    assert facts == normalized_facts()
    assert "secret" not in repr(facts)
