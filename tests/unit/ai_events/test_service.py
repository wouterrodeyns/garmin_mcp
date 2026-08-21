"""Tests for target-event normalization primitives."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime

import pytest

from garmin_mcp.ai_events.service import (
    DEFAULT_LOOKAHEAD_DAYS,
    MAX_EVENTS,
    MAX_LOCATION_LENGTH,
    MAX_LOOKAHEAD_DAYS,
    MAX_TIME_ZONE_LENGTH,
    MAX_TITLE_LENGTH,
    EventFacts,
    event_months,
    normalize_event,
)


class DateSubclass(date):
    pass


class DictSubclass(dict[str, object]):
    pass


class FloatSubclass(float):
    pass


class IntSubclass(int):
    pass


class StringSubclass(str):
    pass


def event_raw(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "itemType": "event",
        "title": "Spring Marathon",
        "date": "2026-05-03",
    }
    raw.update(overrides)
    return raw


def test_public_normalization_constants() -> None:
    assert (DEFAULT_LOOKAHEAD_DAYS, MAX_LOOKAHEAD_DAYS, MAX_EVENTS) == (180, 366, 100)
    assert (MAX_TITLE_LENGTH, MAX_LOCATION_LENGTH, MAX_TIME_ZONE_LENGTH) == (256, 256, 128)


def test_event_facts_is_frozen_with_exact_public_fields() -> None:
    facts = EventFacts(
        title="Spring Marathon",
        date=date(2026, 5, 3),
        is_race=None,
        primary_event=None,
        distance_km=None,
        start_time_local=None,
        time_zone=None,
        location=None,
        source_uuid=None,
    )

    assert set(facts.__dataclass_fields__) == {
        "title",
        "date",
        "is_race",
        "primary_event",
        "distance_km",
        "start_time_local",
        "time_zone",
        "location",
        "source_uuid",
    }
    with pytest.raises(FrozenInstanceError):
        facts.title = "Changed"


def test_event_months_enumerates_inclusive_cross_year_months() -> None:
    assert event_months(date(2026, 1, 31), date(2027, 1, 31)) == (
        (2026, 1),
        (2026, 2),
        (2026, 3),
        (2026, 4),
        (2026, 5),
        (2026, 6),
        (2026, 7),
        (2026, 8),
        (2026, 9),
        (2026, 10),
        (2026, 11),
        (2026, 12),
        (2027, 1),
    )


@pytest.mark.parametrize(
    ("invalid", "valid"),
    [
        (datetime(2026, 1, 31, tzinfo=UTC), date(2026, 1, 31)),
        (date(2026, 1, 31), datetime(2026, 1, 31, tzinfo=UTC)),
        (DateSubclass(2026, 1, 31), date(2026, 1, 31)),
        (date(2026, 1, 31), DateSubclass(2026, 1, 31)),
        ("2026-01-31", date(2026, 1, 31)),
        (date(2026, 1, 31), "2026-01-31"),
    ],
)
def test_event_months_requires_exact_builtin_dates(
    invalid: object, valid: object
) -> None:
    with pytest.raises(TypeError):
        event_months(invalid, valid)


def test_normalize_and_project_happy_event_without_mutating_or_exposing_uuid() -> None:
    raw = event_raw(
        title="  Spring Marathon  ",
        isRace=True,
        primaryEvent=False,
        completionTarget={"unitType": "distance", "value": 42195},
        eventTimeLocal={"start": "07:30", "timeZone": " Europe/Brussels "},
        location=" Antwerp ",
        uuid=" private-event-id ",
    )
    original = deepcopy(raw)

    facts, malformed = normalize_event(raw)

    assert malformed is False
    assert facts == EventFacts(
        title="Spring Marathon",
        date=date(2026, 5, 3),
        is_race=True,
        primary_event=False,
        distance_km=42.195,
        start_time_local="07:30",
        time_zone="Europe/Brussels",
        location="Antwerp",
        source_uuid="private-event-id",
    )
    assert raw == original
    assert facts.to_public_dict(date(2026, 5, 1)) == {
        "title": "Spring Marathon",
        "date": "2026-05-03",
        "days_until": 2,
        "is_race": True,
        "primary_event": False,
        "distance_km": 42.195,
        "start_time_local": "07:30",
        "time_zone": "Europe/Brussels",
        "location": "Antwerp",
    }


@pytest.mark.parametrize("raw", [None, [], "event", 7, DictSubclass()])
def test_normalize_rejects_non_exact_dict_entries(raw: object) -> None:
    assert normalize_event(raw) == (None, True)


@pytest.mark.parametrize(
    "item_type", [None, "Event", "workout", 1, True, StringSubclass("event")]
)
def test_normalize_ignores_non_event_mapping_entries(item_type: object) -> None:
    assert normalize_event(event_raw(itemType=item_type)) == (None, False)


@pytest.mark.parametrize(
    "title", [None, "", "   ", 1, StringSubclass("Spring Marathon"), "x" * 257]
)
def test_normalize_drops_invalid_required_titles(title: object) -> None:
    assert normalize_event(event_raw(title=title)) == (None, True)


def test_normalize_accepts_title_at_maximum_length() -> None:
    title = "x" * 256

    facts, malformed = normalize_event(event_raw(title=title))

    assert malformed is False
    assert facts is not None
    assert facts.title == title


@pytest.mark.parametrize(
    "raw_date",
    [
        None,
        "",
        " 2026-05-03",
        "2026-5-03",
        "2026-05-3",
        "2026-02-30",
        "20260503",
        datetime(2026, 5, 3, tzinfo=UTC),
        date(2026, 5, 3),
        StringSubclass("2026-05-03"),
    ],
)
def test_normalize_drops_invalid_or_noncanonical_required_dates(raw_date: object) -> None:
    assert normalize_event(event_raw(date=raw_date)) == (None, True)


def test_normalize_keeps_valid_date_even_when_outside_a_future_period() -> None:
    facts, malformed = normalize_event(event_raw(date="2020-01-01"))

    assert malformed is False
    assert facts is not None
    assert facts.date == date(2020, 1, 1)


def test_normalize_treats_missing_optional_fields_as_clean_nulls() -> None:
    facts, malformed = normalize_event(event_raw())

    assert malformed is False
    assert facts is not None
    assert facts == EventFacts(
        title="Spring Marathon",
        date=date(2026, 5, 3),
        is_race=None,
        primary_event=None,
        distance_km=None,
        start_time_local=None,
        time_zone=None,
        location=None,
        source_uuid=None,
    )


@pytest.mark.parametrize(
    ("field", "value", "attribute"),
    [
        ("isRace", 1, "is_race"),
        ("isRace", "true", "is_race"),
        ("isRace", StringSubclass("true"), "is_race"),
        ("primaryEvent", 0, "primary_event"),
        ("primaryEvent", "false", "primary_event"),
    ],
)
def test_normalize_marks_invalid_boolean_options_malformed(
    field: str, value: object, attribute: str
) -> None:
    facts, malformed = normalize_event(event_raw(**{field: value}))

    assert malformed is True
    assert facts is not None
    assert getattr(facts, attribute) is None


@pytest.mark.parametrize("target", [None, {"unitType": "pace"}, {"unitType": None}])
def test_normalize_treats_missing_or_non_distance_target_as_clean_null(
    target: object,
) -> None:
    facts, malformed = normalize_event(event_raw(completionTarget=target))

    assert malformed is False
    assert facts is not None
    assert facts.distance_km is None


@pytest.mark.parametrize(
    "target",
    [
        [],
        DictSubclass(unitType="distance", value=5000),
        {"unitType": "distance"},
        {"unitType": "distance", "value": None},
        {"unitType": "distance", "value": True},
        {"unitType": "distance", "value": "5000"},
        {"unitType": "distance", "value": float("nan")},
        {"unitType": "distance", "value": float("inf")},
        {"unitType": "distance", "value": float("-inf")},
        {"unitType": "distance", "value": -1},
        {"unitType": "distance", "value": IntSubclass(5000)},
        {"unitType": "distance", "value": FloatSubclass(5000)},
    ],
)
def test_normalize_marks_invalid_distance_target_malformed(target: object) -> None:
    facts, malformed = normalize_event(event_raw(completionTarget=target))

    assert malformed is True
    assert facts is not None
    assert facts.distance_km is None


def test_normalize_accepts_zero_distance_target() -> None:
    facts, malformed = normalize_event(
        event_raw(completionTarget={"unitType": "distance", "value": 0})
    )

    assert malformed is False
    assert facts is not None
    assert facts.distance_km == 0.0


@pytest.mark.parametrize("start", ["00:00", "23:59"])
def test_normalize_accepts_hhmm_time_boundaries(start: str) -> None:
    facts, malformed = normalize_event(event_raw(eventTimeLocal={"start": start}))

    assert malformed is False
    assert facts is not None
    assert facts.start_time_local == start


@pytest.mark.parametrize(
    "event_time",
    [
        [],
        DictSubclass(start="07:30"),
        {"start": 1},
        {"start": True},
        {"start": StringSubclass("07:30")},
        {"start": "7:30"},
        {"start": "07:3"},
        {"start": "07:30:00"},
        {"start": "07.30"},
        {"start": "24:00"},
        {"start": "23:60"},
    ],
)
def test_normalize_marks_invalid_event_time_malformed(event_time: object) -> None:
    facts, malformed = normalize_event(event_raw(eventTimeLocal=event_time))

    assert malformed is True
    assert facts is not None
    assert facts.start_time_local is None
    assert facts.time_zone is None


@pytest.mark.parametrize(
    ("event_time", "expected_time_zone"),
    [({}, None), ({"start": None}, None), ({"timeZone": " UTC "}, "UTC"), (None, None)],
)
def test_normalize_treats_missing_time_start_as_clean(
    event_time: object, expected_time_zone: str | None
) -> None:
    facts, malformed = normalize_event(event_raw(eventTimeLocal=event_time))

    assert malformed is False
    assert facts is not None
    assert facts.start_time_local is None
    assert facts.time_zone == expected_time_zone


@pytest.mark.parametrize(
    ("time_zone", "expected_malformed"),
    [
        (None, False),
        (" UTC ", False),
        ("", True),
        ("   ", True),
        (1, True),
        (StringSubclass("UTC"), True),
        ("x" * 129, True),
    ],
)
def test_normalize_validates_optional_time_zone(
    time_zone: object, expected_malformed: bool
) -> None:
    facts, malformed = normalize_event(
        event_raw(eventTimeLocal={"start": "07:30", "timeZone": time_zone})
    )

    assert malformed is expected_malformed
    assert facts is not None
    assert facts.time_zone == ("UTC" if time_zone == " UTC " else None)


def test_normalize_accepts_time_zone_at_maximum_length() -> None:
    time_zone = "x" * 128

    facts, malformed = normalize_event(
        event_raw(eventTimeLocal={"start": "07:30", "timeZone": time_zone})
    )

    assert malformed is False
    assert facts is not None
    assert facts.time_zone == time_zone


@pytest.mark.parametrize(
    ("location", "expected_malformed"),
    [
        (None, False),
        ("", False),
        ("   ", False),
        (1, True),
        (StringSubclass("Antwerp"), True),
        ("x" * 257, True),
    ],
)
def test_normalize_validates_optional_location(
    location: object, expected_malformed: bool
) -> None:
    facts, malformed = normalize_event(event_raw(location=location))

    assert malformed is expected_malformed
    assert facts is not None
    assert facts.location is None


def test_normalize_accepts_location_at_maximum_length() -> None:
    location = "x" * 256

    facts, malformed = normalize_event(event_raw(location=location))

    assert malformed is False
    assert facts is not None
    assert facts.location == location


@pytest.mark.parametrize(
    "uuid", [None, "", "   ", 1, StringSubclass("uuid"), "x" * 257]
)
def test_normalize_ignores_invalid_private_uuid_cleanly(uuid: object) -> None:
    facts, malformed = normalize_event(event_raw(uuid=uuid))

    assert malformed is False
    assert facts is not None
    assert facts.source_uuid is None


def test_normalize_accepts_private_uuid_at_maximum_length() -> None:
    private_uuid = "x" * 256

    facts, malformed = normalize_event(event_raw(uuid=private_uuid))

    assert malformed is False
    assert facts is not None
    assert facts.source_uuid == private_uuid
