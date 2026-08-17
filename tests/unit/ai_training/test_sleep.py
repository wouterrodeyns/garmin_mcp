"""Strict normalization tests for one Garmin sleep-night DTO."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
import json
from math import inf, nan
from typing import Any

import pytest
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

import garmin_mcp.ai_training.sleep as sleep_module
from garmin_mcp.ai_training.sleep import (
    DEFAULT_SLEEP_DAYS,
    MAX_SLEEP_DAYS,
    MAX_SLEEP_TEXT_LENGTH,
    InvalidSleepResponse,
    PUBLIC_SLEEP_ERRORS,
    SLEEP_WARNINGS,
    SleepNightFacts,
    aggregate_sleep_facts,
    empty_sleep_night,
    get_sleep_trend_service,
    normalize_sleep_night,
    project_sleep_night,
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


def test_normalize_accepts_observed_root_hr_and_uppercase_spo2_shape() -> None:
    payload = complete_sleep_payload()
    payload["dailySleepDTO"].pop("restingHeartRate")
    payload["restingHeartRate"] = 42
    payload["wellnessSpO2SleepSummaryDTO"] = {
        "averageSPO2": 97.0,
        "lowestSPO2": 86,
    }

    assert normalize_sleep_night(payload, "2026-08-17") == normalized_facts(
        resting_hr_bpm=42,
        average_spo2_percent=97.0,
        lowest_spo2_percent=86,
    )


def test_normalize_accepts_compatible_alias_agreement() -> None:
    payload = complete_sleep_payload()
    payload["restingHeartRate"] = 44
    payload["wellnessSpO2SleepSummaryDTO"]["averageSPO2"] = 96
    payload["wellnessSpO2SleepSummaryDTO"]["lowestSPO2"] = 93

    assert normalize_sleep_night(payload, "2026-08-17") == normalized_facts()


@pytest.mark.parametrize(
    ("parent", "first_key", "second_key", "second_value"),
    [
        ("dailySleepDTO", "restingHeartRate", "root.restingHeartRate", 45),
        ("wellnessSpO2SleepSummaryDTO", "averageSpo2", "averageSPO2", 95),
        ("wellnessSpO2SleepSummaryDTO", "lowestSpo2", "lowestSPO2", 92),
    ],
)
def test_normalize_rejects_conflicting_aliases(
    parent: str, first_key: str, second_key: str, second_value: int
) -> None:
    payload = complete_sleep_payload()
    assert payload[parent][first_key] is not None
    if second_key.startswith("root."):
        payload[second_key.removeprefix("root.")] = second_value
    else:
        payload[parent][second_key] = second_value

    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, "2026-08-17")


@pytest.mark.parametrize(
    ("parent", "key", "value"),
    [
        ("root", "restingHeartRate", True),
        ("wellnessSpO2SleepSummaryDTO", "averageSPO2", "96"),
        ("wellnessSpO2SleepSummaryDTO", "lowestSPO2", 101),
    ],
)
def test_normalize_rejects_invalid_compatible_alias(
    parent: str, key: str, value: Any
) -> None:
    payload = complete_sleep_payload()
    target = payload if parent == "root" else payload[parent]
    target[key] = value

    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, "2026-08-17")


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


def test_numeric_values_reject_an_oversized_exact_integer_without_float_coercion() -> None:
    payload = complete_sleep_payload()
    payload["dailySleepDTO"]["sleepTimeSeconds"] = 10**1000

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


class RecordingSleepClient:
    """A small real provider seam that records sequential Garmin calls."""

    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[str] = []

    def get_sleep_data(self, date_text: str) -> Any:
        self.calls.append(date_text)
        response = self.responses.get(date_text)
        if isinstance(response, Exception):
            raise response
        return response


def expected_empty_summary(requested: int) -> dict[str, Any]:
    return {
        "nights_requested": requested,
        "nights_available": 0,
        "averages": {
            "duration_hours": {"value": None, "nights": 0},
            "score": {"value": None, "nights": 0},
            "resting_hr_bpm": {"value": None, "nights": 0},
            "overnight_hrv_ms": {"value": None, "nights": 0},
            "spo2_percent": {"value": None, "nights": 0},
        },
    }


def test_public_sleep_errors_and_empty_night_have_stable_contract() -> None:
    assert PUBLIC_SLEEP_ERRORS == {
        "invalid_days": "days must be an integer from 1 through 30.",
        "client_unavailable": "Garmin client is unavailable.",
        "sleep_trend_unavailable": "Sleep trend is unavailable for the requested period.",
    }
    assert SLEEP_WARNINGS == {
        "sleep_data_unavailable": "Sleep data is unavailable for this date.",
        "provider_unavailable": "Sleep data could not be retrieved for this date.",
        "invalid_provider_response": "Sleep data returned an invalid response for this date.",
    }
    assert empty_sleep_night("2026-08-17") == {
        "date": "2026-08-17", "available": False, "duration_hours": None,
        "nap_minutes": None, "score": None, "score_qualifier": None,
        "stages": {"deep_minutes": None, "light_minutes": None, "rem_minutes": None, "awake_minutes": None},
        "resting_hr_bpm": None, "overnight_hrv_ms": None,
        "average_sleep_stress": None, "awake_count": None,
        "restless_moments_count": None,
        "spo2": {"average_percent": None, "lowest_percent": None},
    }


class _DaysSubclass(int):
    pass


@pytest.mark.parametrize(
    "invalid_days", [True, False, "7", 0, -1, 31, 1.0, None, _DaysSubclass(7)]
)
def test_sleep_trend_rejects_invalid_days_before_client_or_date_reads(invalid_days: Any) -> None:
    client = RecordingSleepClient({})

    result = get_sleep_trend_service(client, invalid_days, today="not a date")

    assert result == {
        "status": "error",
        "error": {"code": "invalid_days", "message": PUBLIC_SLEEP_ERRORS["invalid_days"]},
        "period": {"days": None, "start_date": None, "end_date": None},
        "availability": {}, "summary": expected_empty_summary(0), "nights": [], "warnings": [],
    }
    assert tuple(result) == ("status", "error", "period", "availability", "summary", "nights", "warnings")
    assert client.calls == []


class _TodaySubclass(date):
    pass


@pytest.mark.parametrize("invalid_today", [datetime(2026, 8, 17), "2026-08-17", _TodaySubclass(2026, 8, 17)])
def test_sleep_trend_requires_an_exact_date_when_today_is_supplied(invalid_today: Any) -> None:
    client = RecordingSleepClient({})
    with pytest.raises(TypeError):
        get_sleep_trend_service(client, 1, today=invalid_today)
    assert client.calls == []


def test_sleep_trend_uses_default_seven_and_inclusive_chronological_dates() -> None:
    client = RecordingSleepClient({})
    result = get_sleep_trend_service(client, today=date(2026, 8, 17))

    assert client.calls == [f"2026-08-{day:02d}" for day in range(11, 18)]
    assert [night["date"] for night in result["nights"]] == client.calls
    assert list(result["availability"]) == client.calls


def test_sleep_trend_honors_the_thirty_day_bound_without_extra_reads() -> None:
    client = RecordingSleepClient({})
    result = get_sleep_trend_service(client, 30, today=date(2026, 8, 17))
    assert len(client.calls) == 30
    assert client.calls[0] == "2026-07-19"
    assert client.calls[-1] == "2026-08-17"
    assert result["period"] == {"days": 30, "start_date": "2026-07-19", "end_date": "2026-08-17"}


def test_sleep_trend_with_no_client_has_a_known_date_envelope_without_reads() -> None:
    result = get_sleep_trend_service(None, 2, today=date(2026, 8, 17))
    assert result == {
        "status": "error",
        "error": {"code": "client_unavailable", "message": PUBLIC_SLEEP_ERRORS["client_unavailable"]},
        "period": {"days": 2, "start_date": "2026-08-16", "end_date": "2026-08-17"},
        "availability": {"2026-08-16": False, "2026-08-17": False},
        "summary": expected_empty_summary(2),
        "nights": [empty_sleep_night("2026-08-16"), empty_sleep_night("2026-08-17")],
        "warnings": [],
    }


def test_project_sleep_night_has_exact_order_and_unit_conversions() -> None:
    night = project_sleep_night(normalized_facts())
    assert night == {
        "date": "2026-08-17", "available": True, "duration_hours": 7.4,
        "nap_minutes": 15.0, "score": 82, "score_qualifier": "GOOD",
        "stages": {"deep_minutes": 88.0, "light_minutes": 251.0, "rem_minutes": 105.0, "awake_minutes": 20.0},
        "resting_hr_bpm": 44, "overnight_hrv_ms": 94,
        "average_sleep_stress": 14, "awake_count": 3,
        "restless_moments_count": 12,
        "spo2": {"average_percent": 96, "lowest_percent": 93},
    }
    assert tuple(night) == tuple(empty_sleep_night("2026-08-17"))


def test_projected_unavailable_metrics_stay_null_while_valid_zeroes_are_preserved() -> None:
    night = project_sleep_night(normalized_facts(
        sleep_seconds=None, nap_seconds=0, score=0, deep_seconds=0,
        light_seconds=0, rem_seconds=0, awake_seconds=0, resting_hr_bpm=None,
        overnight_hrv_ms=None, average_sleep_stress=0, awake_count=0,
        restless_moments_count=0, average_spo2_percent=0, lowest_spo2_percent=0,
    ))
    assert night["duration_hours"] is None
    assert night["resting_hr_bpm"] is None
    assert night["overnight_hrv_ms"] is None
    assert night["nap_minutes"] == 0.0
    assert night["stages"] == {
        "deep_minutes": 0.0, "light_minutes": 0.0,
        "rem_minutes": 0.0, "awake_minutes": 0.0,
    }
    assert night["score"] == night["average_sleep_stress"] == 0
    assert night["awake_count"] == night["restless_moments_count"] == 0
    assert night["spo2"] == {"average_percent": 0, "lowest_percent": 0}


def test_empty_current_night_is_visible_without_shifting_or_an_extra_read() -> None:
    client = RecordingSleepClient({"2026-08-15": complete_sleep_payload("2026-08-15"), "2026-08-16": complete_sleep_payload("2026-08-16"), "2026-08-17": None})
    result = get_sleep_trend_service(client, 3, today=date(2026, 8, 17))
    assert client.calls == ["2026-08-15", "2026-08-16", "2026-08-17"]
    assert result["status"] == "partial_success"
    assert result["nights"][-1] == empty_sleep_night("2026-08-17")
    assert result["warnings"] == [{"provider": "sleep", "date": "2026-08-17", "code": "sleep_data_unavailable", "message": SLEEP_WARNINGS["sleep_data_unavailable"]}]


def test_all_successful_sleep_nights_return_the_success_envelope() -> None:
    client = RecordingSleepClient({
        "2026-08-15": complete_sleep_payload("2026-08-15"),
        "2026-08-16": complete_sleep_payload("2026-08-16"),
        "2026-08-17": complete_sleep_payload("2026-08-17"),
    })
    result = get_sleep_trend_service(client, 3, today=date(2026, 8, 17))

    assert result["status"] == "success"
    assert result["error"] is None
    assert result["availability"] == {
        "2026-08-15": True, "2026-08-16": True, "2026-08-17": True,
    }
    assert [night["date"] for night in result["nights"]] == [
        "2026-08-15", "2026-08-16", "2026-08-17",
    ]
    assert result["warnings"] == []
    assert client.calls == ["2026-08-15", "2026-08-16", "2026-08-17"]


def test_date_min_supports_one_day_but_rejects_an_unrepresentable_period() -> None:
    client = RecordingSleepClient({"0001-01-01": complete_sleep_payload("0001-01-01")})
    result = get_sleep_trend_service(client, 1, today=date.min)
    assert result["status"] == "success"
    assert client.calls == ["0001-01-01"]

    unavailable_period_client = RecordingSleepClient({})
    with pytest.raises(TypeError, match="^today cannot represent the requested sleep period$"):
        get_sleep_trend_service(unavailable_period_client, 2, today=date.min)
    assert unavailable_period_client.calls == []


def test_mixed_sleep_results_continue_and_never_serialize_provider_sentinels() -> None:
    client = RecordingSleepClient({
        "2026-08-15": complete_sleep_payload("2026-08-15"),
        "2026-08-16": GarminConnectConnectionError("private provider detail"),
        "2026-08-17": {"dailySleepDTO": {"sleepTimeSeconds": True}, "secret": object()},
    })
    result = get_sleep_trend_service(client, 3, today=date(2026, 8, 17))
    assert client.calls == ["2026-08-15", "2026-08-16", "2026-08-17"]
    assert result["status"] == "partial_success"
    assert result["availability"] == {"2026-08-15": True, "2026-08-16": False, "2026-08-17": False}
    assert result["warnings"] == [
        {"provider": "sleep", "date": "2026-08-16", "code": "provider_unavailable", "message": SLEEP_WARNINGS["provider_unavailable"]},
        {"provider": "sleep", "date": "2026-08-17", "code": "invalid_provider_response", "message": SLEEP_WARNINGS["invalid_provider_response"]},
    ]
    assert "private provider detail" not in repr(result)
    assert "object at" not in repr(result)


def test_sleep_trend_treats_an_oversized_exact_integer_as_a_sanitized_invalid_date() -> None:
    malformed = complete_sleep_payload("2026-08-16")
    malformed["dailySleepDTO"]["sleepTimeSeconds"] = 10**1000
    malformed["private_provider_detail"] = "token=private-provider-detail"
    client = RecordingSleepClient({
        "2026-08-16": malformed,
        "2026-08-17": complete_sleep_payload("2026-08-17"),
    })

    result = get_sleep_trend_service(client, 2, today=date(2026, 8, 17))

    assert client.calls == ["2026-08-16", "2026-08-17"]
    assert result["status"] == "partial_success"
    assert result["availability"] == {"2026-08-16": False, "2026-08-17": True}
    assert result["nights"][0] == empty_sleep_night("2026-08-16")
    assert result["nights"][1]["available"] is True
    assert result["warnings"] == [{
        "provider": "sleep",
        "date": "2026-08-16",
        "code": "invalid_provider_response",
        "message": SLEEP_WARNINGS["invalid_provider_response"],
    }]
    assert "token=private-provider-detail" not in json.dumps(result)


class SentinelHostileDict(dict[Any, Any]):
    """Explode if the untrusted-container protocol is ever invoked."""

    _PRIVATE_URL = "https://private.example/hostile"

    def __init__(self) -> None:
        super().__init__()
        self.protocol_attempts: list[str] = []

    def _explode(self, protocol: str) -> None:
        self.protocol_attempts.append(protocol)
        raise RuntimeError(f"token={protocol}-private {self._PRIVATE_URL}")

    def __bool__(self) -> bool:
        self._explode("truthiness")

    def get(self, key: Any, default: Any = None) -> Any:
        self._explode("get")

    def __len__(self) -> int:
        self._explode("length")

    def __iter__(self) -> Any:
        self._explode("iteration")

    def items(self) -> Any:
        self._explode("items")

    def values(self) -> Any:
        self._explode("values")

    def keys(self) -> Any:
        self._explode("keys")

    def __eq__(self, other: Any) -> bool:
        self._explode("equality")

    def __repr__(self) -> str:
        self._explode("repr")


def test_sleep_trend_sanitizes_untrusted_failure_sentinels_from_public_results() -> None:
    private_url = "https://private.example/garmin"
    oversized_qualifier = f"token=oversized-private {private_url} " + "x" * 65
    oversized_payload = complete_sleep_payload("2026-08-16")
    oversized_payload["dailySleepDTO"]["sleepScores"]["overall"]["qualifierKey"] = (
        oversized_qualifier
    )
    hostile_daily = SentinelHostileDict()
    client = RecordingSleepClient({
        "2026-08-10": complete_sleep_payload("2026-08-10"),
        "2026-08-11": None,
        "2026-08-12": GarminConnectAuthenticationError(
            f"token=provider-auth-private {private_url}"
        ),
        "2026-08-13": GarminConnectConnectionError(
            f"token=provider-connection-private {private_url}"
        ),
        "2026-08-14": GarminConnectTooManyRequestsError(
            f"token=provider-rate-private {private_url}"
        ),
        "2026-08-15": {
            "dailySleepDTO": {
                "sleepScores": f"token=payload-private {private_url}",
            },
        },
        "2026-08-16": oversized_payload,
        "2026-08-17": {"dailySleepDTO": hostile_daily},
    })

    result = get_sleep_trend_service(client, 8, today=date(2026, 8, 17))

    assert result["status"] == "partial_success"
    assert result["availability"] == {
        "2026-08-10": True,
        "2026-08-11": False,
        "2026-08-12": False,
        "2026-08-13": False,
        "2026-08-14": False,
        "2026-08-15": False,
        "2026-08-16": False,
        "2026-08-17": False,
    }
    assert [(warning["date"], warning["code"]) for warning in result["warnings"]] == [
        ("2026-08-11", "sleep_data_unavailable"),
        ("2026-08-12", "provider_unavailable"),
        ("2026-08-13", "provider_unavailable"),
        ("2026-08-14", "provider_unavailable"),
        ("2026-08-15", "invalid_provider_response"),
        ("2026-08-16", "invalid_provider_response"),
        ("2026-08-17", "invalid_provider_response"),
    ]
    assert len(result["warnings"]) == sum(
        not available for available in result["availability"].values()
    )
    assert hostile_daily.protocol_attempts == []

    serialized = json.dumps(result)
    for sentinel in (
        "token=provider-auth-private",
        "token=provider-connection-private",
        "token=provider-rate-private",
        "token=payload-private",
        "token=oversized-private",
        "token=truthiness-private",
        "token=get-private",
        "token=length-private",
        "token=iteration-private",
        "token=items-private",
        "token=values-private",
        "token=keys-private",
        "token=equality-private",
        "token=repr-private",
        private_url,
        SentinelHostileDict._PRIVATE_URL,
    ):
        assert sentinel not in serialized


def test_all_unavailable_sleep_nights_preserve_data_and_raise_trend_error() -> None:
    client = RecordingSleepClient({
        "2026-08-15": None,
        "2026-08-16": GarminConnectConnectionError("private"),
        "2026-08-17": {"dailySleepDTO": {"sleepTimeSeconds": True}},
    })
    result = get_sleep_trend_service(client, 3, today=date(2026, 8, 17))
    assert result["status"] == "error"
    assert result["error"] == {"code": "sleep_trend_unavailable", "message": PUBLIC_SLEEP_ERRORS["sleep_trend_unavailable"]}
    assert result["nights"] == [empty_sleep_night("2026-08-15"), empty_sleep_night("2026-08-16"), empty_sleep_night("2026-08-17")]
    assert [warning["code"] for warning in result["warnings"]] == ["sleep_data_unavailable", "provider_unavailable", "invalid_provider_response"]


def test_aggregate_sleep_facts_uses_raw_values_before_rounding_with_per_metric_counts() -> None:
    assert project_sleep_night(normalized_facts(sleep_seconds=30601))["duration_hours"] == 8.5
    first = normalized_facts(sleep_seconds=30384, score=0, resting_hr_bpm=1, overnight_hrv_ms=None, average_spo2_percent=0)
    second = normalized_facts(date="2026-08-16", sleep_seconds=30776, score=1, resting_hr_bpm=2, overnight_hrv_ms=101, average_spo2_percent=1)
    summary = aggregate_sleep_facts([first, second], 3)
    assert summary == {
        "nights_requested": 3, "nights_available": 2,
        "averages": {
            "duration_hours": {"value": 8.5, "nights": 2},
            "score": {"value": 0.5, "nights": 2},
            "resting_hr_bpm": {"value": 1.5, "nights": 2},
            "overnight_hrv_ms": {"value": 101.0, "nights": 1},
            "spo2_percent": {"value": 0.5, "nights": 2},
        },
    }
    assert round((8.4 + 8.5) / 2, 1) == 8.4
    assert tuple(summary) == ("nights_requested", "nights_available", "averages")


def test_sleep_trend_propagates_normalizer_defects(monkeypatch: pytest.MonkeyPatch) -> None:
    client = RecordingSleepClient({"2026-08-17": complete_sleep_payload()})
    defect = RuntimeError("normalizer internal defect")

    def explode(raw: Any, requested_date: str | None) -> SleepNightFacts | None:
        raise defect

    monkeypatch.setattr(sleep_module, "normalize_sleep_night", explode)
    with pytest.raises(RuntimeError) as excinfo:
        get_sleep_trend_service(client, 1, today=date(2026, 8, 17))
    assert excinfo.value is defect
    assert client.calls == ["2026-08-17"]


def test_sleep_trend_propagates_projection_defects(monkeypatch: pytest.MonkeyPatch) -> None:
    client = RecordingSleepClient({"2026-08-17": complete_sleep_payload()})
    defect = RuntimeError("projection internal defect")

    def explode(facts: SleepNightFacts) -> dict[str, Any]:
        raise defect

    monkeypatch.setattr(sleep_module, "project_sleep_night", explode)

    with pytest.raises(RuntimeError) as excinfo:
        get_sleep_trend_service(client, 1, today=date(2026, 8, 17))
    assert excinfo.value is defect
    assert client.calls == ["2026-08-17"]


def test_sleep_trend_propagates_aggregation_defects(monkeypatch: pytest.MonkeyPatch) -> None:
    client = RecordingSleepClient({"2026-08-17": complete_sleep_payload()})
    defect = RuntimeError("aggregation internal defect")

    def explode(
        facts: list[SleepNightFacts], nights_requested: int
    ) -> dict[str, Any]:
        raise defect

    monkeypatch.setattr(sleep_module, "aggregate_sleep_facts", explode)

    with pytest.raises(RuntimeError) as excinfo:
        get_sleep_trend_service(client, 1, today=date(2026, 8, 17))
    assert excinfo.value is defect
    assert client.calls == ["2026-08-17"]


def test_sleep_trend_propagates_unexpected_provider_seam_defects() -> None:
    defect = RuntimeError("unexpected provider seam defect")
    client = RecordingSleepClient({"2026-08-17": defect})

    with pytest.raises(RuntimeError) as excinfo:
        get_sleep_trend_service(client, 1, today=date(2026, 8, 17))

    assert excinfo.value is defect
    assert client.calls == ["2026-08-17"]
