"""Strict frame-level FIT decoder contract tests using public-shaped fakes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import fitdecode
import pytest

from garmin_mcp.ai_activity import timeseries
from tests.unit.ai_activity.timeseries_fakes import (
    FakeBaseType,
    FakeFieldData,
    FakeFieldDef,
    crc,
    definition,
    fake_reader,
    fake_record,
    header,
    make_zip,
)


FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)


@pytest.fixture
def fit_archive() -> bytes:
    return make_zip({"activity.fit": b"frame-fake-input"})


def _install_reader(monkeypatch, reader):
    monkeypatch.setattr(timeseries, "fitdecode", fitdecode, raising=False)
    monkeypatch.setattr(timeseries.fitdecode, "FitReader", lambda *_args, **_kwargs: reader)


def _parse(monkeypatch, fit_archive: bytes, frames):
    reader = fake_reader(frames)
    _install_reader(monkeypatch, reader)
    return timeseries.parse_original_fit(fit_archive), reader


def direct_field(def_num, base_identifier, size, raw_value, value, **overrides):
    field_def = overrides.pop(
        "field_def", FakeFieldDef(def_num, FakeBaseType(base_identifier), size, overrides.pop("is_dev", False))
    )
    return FakeFieldData(
        field_def=field_def,
        field=overrides.pop("field", SimpleNamespace(name="deceptive-display-name")),
        parent_field=overrides.pop("parent_field", None),
        is_expanded=overrides.pop("is_expanded", False),
        raw_value=raw_value,
        value=value,
        **overrides,
    )


def direct_timestamp(raw_value, value=None, **overrides):
    if value is None and type(raw_value) is int:
        value = FIT_EPOCH + timedelta(seconds=raw_value)
    return direct_field(253, 0x86, 4, raw_value, value, **overrides)


def compressed_timestamp(raw_value, value=None, **overrides):
    if value is None and type(raw_value) is int:
        value = FIT_EPOCH + timedelta(seconds=raw_value)
    return FakeFieldData(
        field_def=overrides.pop("field_def", None),
        field=overrides.pop("field", fitdecode.profile.FIELD_TYPE_TIMESTAMP),
        parent_field=overrides.pop("parent_field", None),
        is_expanded=overrides.pop("is_expanded", False),
        raw_value=raw_value,
        value=value,
        **overrides,
    )


def test_standard_numeric_tuples_produce_only_normalized_record_facts(monkeypatch, fit_archive):
    raw_timestamp = 0x10000000
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [
            header(),
            fake_record(
                [
                    direct_timestamp(raw_timestamp),
                    direct_field(3, 0x02, 1, 171, 171),
                    direct_field(6, 0x84, 2, 12_500, 12.5),
                    direct_field(4, 0x02, 1, 88, 88),
                    direct_field(7, 0x84, 2, 234, 234),
                    direct_field(2, 0x84, 2, 1_234, 1234),
                    direct_field(9, 0x83, 2, 56, 5.6),
                ]
            ),
            crc(),
        ],
    )

    assert result.failure_code is None
    assert result.malformed_record_count == 0
    assert result.records == (
        timeseries.RecordFact(
            raw_timestamp_seconds=raw_timestamp,
            timestamp_utc=FIT_EPOCH + timedelta(seconds=raw_timestamp),
            encounter_index=0,
            heart_rate_bpm=171.0,
            speed_mps=12.5,
            cadence_rpm=88.0,
            power_w=234.0,
            altitude_m=1234.0,
            grade_pct=5.6,
        ),
    )


@pytest.mark.parametrize(
    "def_num,base_identifier,size",
    [(7, 0x84, 2), (6, 0x02, 2), (6, 0x84, 1)],
)
def test_wrong_numeric_field_metadata_is_not_an_allowlisted_speed(
    monkeypatch, fit_archive, def_num, base_identifier, size
):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [
            header(),
            fake_record(
                [
                    direct_timestamp(0x10000000),
                    direct_field(def_num, base_identifier, size, 12_345, 12.345),
                ]
            ),
        ],
    )

    assert result.failure_code is None
    assert result.records[0].speed_mps is None


def test_only_data_frames_with_exact_record_global_number_are_extracted(monkeypatch, fit_archive):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [
            header(),
            SimpleNamespace(frame_type=fitdecode.FIT_FRAME_DATA, global_mesg_num=19, fields=[]),
            SimpleNamespace(frame_type=fitdecode.FIT_FRAME_DEFINITION, field_defs=[], dev_field_defs=[]),
            crc(),
            fake_record([direct_timestamp(0x10000000)], global_mesg_num=20.0),
            fake_record([direct_timestamp(0x10000001)]),
        ],
    )

    assert result.failure_code is None
    assert [fact.raw_timestamp_seconds for fact in result.records] == [0x10000001]


def test_zero_or_multiple_valid_timestamps_discard_whole_records(monkeypatch, fit_archive):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [
            header(),
            fake_record([direct_field(6, 0x84, 2, 5_000, 5.0)]),
            fake_record([direct_timestamp(0x10000000), compressed_timestamp(0x10000000)], time_offset=0),
            fake_record([direct_timestamp(0x10000001)]),
        ],
    )

    assert result.failure_code is None
    assert result.malformed_record_count == 2
    assert [fact.raw_timestamp_seconds for fact in result.records] == [0x10000001]
    assert result.records[0].encounter_index == 2


def test_duplicate_optional_candidate_is_null_but_keeps_record(monkeypatch, fit_archive):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [
            header(),
            fake_record(
                [
                    direct_timestamp(0x10000000),
                    direct_field(6, 0x84, 2, 1_000, 1.0),
                    direct_field(6, 0x84, 2, 2_000, 2.0),
                ]
            ),
        ],
    )

    assert result.failure_code is None
    assert result.malformed_record_count == 0
    assert result.records[0].speed_mps is None


@pytest.mark.parametrize(
    "value",
    [True, False, float("nan"), float("inf"), float("-inf"), "5", object(), 100.00001, -0.00001],
)
def test_invalid_optional_metric_values_are_null(monkeypatch, fit_archive, value):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [header(), fake_record([direct_timestamp(0x10000000), direct_field(6, 0x84, 2, value, value)])],
    )

    assert result.failure_code is None
    assert result.records[0].speed_mps is None


@pytest.mark.parametrize(
    "raw_value",
    [0x10000000, 0xFFFFFFFE],
)
def test_timestamp_raw_bounds_are_inclusive(monkeypatch, fit_archive, raw_value):
    result, _reader = _parse(monkeypatch, fit_archive, [header(), fake_record([direct_timestamp(raw_value)])])

    assert result.failure_code is None
    assert result.records[0].raw_timestamp_seconds == raw_value


@pytest.mark.parametrize(
    "raw_value",
    [0x0FFFFFFF, 0xFFFFFFFF, True, False, float(0x10000000)],
)
def test_invalid_timestamp_raw_values_make_the_record_malformed(monkeypatch, fit_archive, raw_value):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [header(), fake_record([direct_timestamp(raw_value, value=FIT_EPOCH + timedelta(seconds=0x10000000))])],
    )

    assert result.records == ()
    assert result.malformed_record_count == 1
    assert result.failure_code == "no_timestamped_records"


@pytest.mark.parametrize(
    "value",
    [
        datetime(1998, 7, 14),
        datetime(1998, 7, 14, tzinfo=timezone(timedelta(hours=1))),
        FIT_EPOCH + timedelta(seconds=0x10000001),
    ],
)
def test_timestamp_value_must_be_exact_aware_zero_offset_fit_epoch_value(monkeypatch, fit_archive, value):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [header(), fake_record([direct_timestamp(0x10000000, value=value)])],
    )

    assert result.records == ()
    assert result.malformed_record_count == 1
    assert result.failure_code == "no_timestamped_records"


def test_encounter_order_and_duplicate_timestamps_are_preserved_without_sorting(monkeypatch, fit_archive):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [
            header(),
            fake_record([direct_timestamp(0x10000003)]),
            fake_record([direct_timestamp(0x10000001)]),
            fake_record([direct_timestamp(0x10000003)]),
        ],
    )

    assert result.failure_code is None
    assert [(fact.raw_timestamp_seconds, fact.encounter_index) for fact in result.records] == [
        (0x10000003, 0),
        (0x10000001, 1),
        (0x10000003, 2),
    ]


def test_no_record_fact_has_a_stable_no_timestamped_records_failure(monkeypatch, fit_archive):
    result, _reader = _parse(monkeypatch, fit_archive, [header(), crc()])

    assert result == timeseries.ParseResult((), 0, "no_timestamped_records")


def test_display_names_cannot_change_numeric_field_identity(monkeypatch, fit_archive):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [
            header(),
            fake_record(
                [
                    direct_timestamp(0x10000000, field=SimpleNamespace(name="position_lat")),
                    direct_field(6, 0x84, 2, 6_250, 6.25, field=SimpleNamespace(name="position_long")),
                    direct_field(1, 0x84, 2, 7_000, 7.0, field=SimpleNamespace(name="speed")),
                ]
            ),
        ],
    )

    assert result.failure_code is None
    assert result.records[0].speed_mps == 6.25


def test_developer_speed_named_like_standard_cannot_cross_numeric_boundary(monkeypatch, fit_archive):
    timestamp = direct_timestamp(0x10000000)
    developer_speed = FakeFieldData(
        FakeFieldDef(6, FakeBaseType(0x84), 2, is_dev=True),
        SimpleNamespace(name="speed"),
        None,
        False,
        12_345_678,
        12_345_678,
    )
    result, _reader = _parse(monkeypatch, fit_archive, [header(), fake_record([timestamp, developer_speed])])

    assert result.failure_code is None
    assert result.records[0].speed_mps is None
    assert "12345678" not in repr(result.records[0])


@pytest.mark.parametrize(
    "field",
    [
        direct_field(6, 0x84, 2, 4_000, 4.0, is_expanded=True),
        direct_field(6, 0x84, 2, 4_000, 4.0, parent_field=object()),
        direct_field(73, 0x84, 2, 4_000, 4.0, is_expanded=True),
        direct_field(78, 0x84, 2, 500, 500.0, parent_field=object()),
    ],
)
def test_expanded_component_and_enhanced_fields_are_never_retained(monkeypatch, fit_archive, field):
    result, _reader = _parse(
        monkeypatch, fit_archive, [header(), fake_record([direct_timestamp(0x10000000), field])]
    )

    assert result.failure_code is None
    assert result.records[0].speed_mps is None
    assert result.records[0].altitude_m is None


def test_record_fact_has_no_location_or_unapproved_field(monkeypatch, fit_archive):
    coordinate_sentinel = 12_345_678
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [
            header(),
            fake_record(
                [
                    direct_timestamp(0x10000000),
                    direct_field(0, 0x85, 4, coordinate_sentinel, coordinate_sentinel, field=SimpleNamespace(name="position_lat")),
                    direct_field(1, 0x85, 4, coordinate_sentinel, coordinate_sentinel, field=SimpleNamespace(name="position_long")),
                    direct_field(2, 0x84, 2, coordinate_sentinel, coordinate_sentinel, is_dev=True, field=SimpleNamespace(name="altitude")),
                ]
            ),
        ],
    )

    assert tuple(timeseries.RecordFact.__dataclass_fields__) == (
        "raw_timestamp_seconds",
        "timestamp_utc",
        "encounter_index",
        "heart_rate_bpm",
        "speed_mps",
        "cadence_rpm",
        "power_w",
        "altitude_m",
        "grade_pct",
    )
    assert str(coordinate_sentinel) not in repr(result.records[0])


def test_compressed_timestamp_is_accepted_only_via_exact_public_identity_path(monkeypatch, fit_archive):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [header(), fake_record([compressed_timestamp(0x10000000)], time_offset=0)],
    )

    assert result.failure_code is None
    assert result.records[0].raw_timestamp_seconds == 0x10000000


@pytest.mark.parametrize(
    "field,time_offset",
    [
        (compressed_timestamp(0x10000000, field=object()), 0),
        (compressed_timestamp(0x10000000, parent_field=object()), 0),
        (compressed_timestamp(0x10000000, is_expanded=True), 0),
        (compressed_timestamp(0x10000000, field_def=FakeFieldDef(1, FakeBaseType(0x86), 4)), 0),
        (compressed_timestamp(0x10000000), None),
    ],
)
def test_compressed_timestamp_near_misses_are_rejected(monkeypatch, fit_archive, field, time_offset):
    result, _reader = _parse(
        monkeypatch, fit_archive, [header(), fake_record([field], time_offset=time_offset)]
    )

    assert result.records == ()
    assert result.failure_code == "no_timestamped_records"


def test_reader_uses_exact_strict_options_and_is_closed_on_success(monkeypatch, fit_archive):
    reader = fake_reader([header(), fake_record([direct_timestamp(0x10000000)])])
    calls = []

    def construct(*args, **kwargs):
        calls.append((args, kwargs))
        return reader

    monkeypatch.setattr(timeseries, "fitdecode", fitdecode, raising=False)
    monkeypatch.setattr(timeseries.fitdecode, "FitReader", construct)
    result = timeseries.parse_original_fit(fit_archive)

    assert result.failure_code is None
    assert len(calls) == 1
    stream, = calls[0][0]
    assert isinstance(stream, timeseries.LimitedReader)
    assert calls[0][1] == {
        "check_crc": fitdecode.CrcCheck.RAISE,
        "error_handling": fitdecode.ErrorHandling.RAISE,
        "keep_raw_chunks": False,
    }
    assert reader.close_calls == 1


def test_foreign_reader_constructor_and_next_errors_are_sanitized_and_closed(monkeypatch, fit_archive):
    monkeypatch.setattr(timeseries, "fitdecode", fitdecode, raising=False)
    monkeypatch.setattr(timeseries.fitdecode, "FitReader", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("foreign")))
    assert timeseries.parse_original_fit(fit_archive).failure_code == "fit_parse_failed"

    reader = fake_reader([header()], next_error=ValueError("foreign"))
    _install_reader(monkeypatch, reader)
    assert timeseries.parse_original_fit(fit_archive).failure_code == "fit_parse_failed"
    assert reader.close_calls == 1


def test_local_frame_consumer_errors_propagate_without_being_sanitized(monkeypatch, fit_archive):
    reader = fake_reader([header()])
    _install_reader(monkeypatch, reader)

    def defect(*_args, **_kwargs):
        raise RuntimeError("local decoder defect")

    monkeypatch.setattr(timeseries, "_consume_frame", defect, raising=False)
    with pytest.raises(RuntimeError, match="local decoder defect"):
        timeseries.parse_original_fit(fit_archive)
    assert reader.close_calls == 1


def test_reader_state_is_fresh_for_each_parse_call(monkeypatch, fit_archive):
    readers = [
        fake_reader([header(), fake_record([direct_timestamp(0x10000000)])]),
        fake_reader([header(), fake_record([direct_timestamp(0x10000001)])]),
    ]
    _install_reader(monkeypatch, None)
    monkeypatch.setattr(timeseries.fitdecode, "FitReader", lambda *_args, **_kwargs: readers.pop(0))

    first = timeseries.parse_original_fit(fit_archive)
    second = timeseries.parse_original_fit(fit_archive)

    assert [fact.raw_timestamp_seconds for fact in first.records] == [0x10000000]
    assert [fact.raw_timestamp_seconds for fact in second.records] == [0x10000001]


def test_unknown_frame_type_is_safely_rejected(monkeypatch, fit_archive):
    result, _reader = _parse(monkeypatch, fit_archive, [header(), SimpleNamespace(frame_type=999)])

    assert result == timeseries.ParseResult((), 0, "fit_parse_failed")


def test_frame_limit_counts_all_known_frame_types_before_filtering(monkeypatch, fit_archive):
    monkeypatch.setattr(timeseries, "MAX_FIT_FRAMES", 4, raising=False)
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [header(), definition(), crc(), fake_record([], global_mesg_num=19), crc()],
    )

    assert result == timeseries.ParseResult((), 0, "frame_limit_exceeded")


def test_second_header_discards_collected_facts_as_chained_fit(monkeypatch, fit_archive):
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [header(), fake_record([direct_timestamp(0x10000000)]), header()],
    )

    assert result == timeseries.ParseResult((), 0, "chained_fit_unsupported")


def test_definition_field_limit_counts_standard_and_developer_defs(monkeypatch, fit_archive):
    monkeypatch.setattr(timeseries, "MAX_FIELDS_PER_DEFINITION", 2, raising=False)
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [header(), definition(field_defs=[object(), object()], dev_field_defs=[object()])],
    )

    assert result == timeseries.ParseResult((), 0, "definition_field_limit_exceeded")


def test_record_limit_counts_every_record_message_before_extraction(monkeypatch, fit_archive):
    monkeypatch.setattr(timeseries, "MAX_RECORD_MESSAGES", 2, raising=False)
    result, _reader = _parse(
        monkeypatch,
        fit_archive,
        [
            header(),
            fake_record([]),
            fake_record([direct_timestamp(0x10000000), direct_timestamp(0x10000000)]),
            fake_record([direct_timestamp(0x10000001)]),
        ],
    )

    assert result == timeseries.ParseResult((), 0, "record_limit_exceeded")


def test_production_decoder_limits_are_pinned():
    assert timeseries.MAX_FIT_FRAMES == 200_000
    assert timeseries.MAX_RECORD_MESSAGES == 100_000
    assert timeseries.MAX_FIELDS_PER_DEFINITION == 128
