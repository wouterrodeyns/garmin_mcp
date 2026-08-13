from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from garmin_mcp.ai_activity.timeseries import (
    FIT_EPOCH,
    MAX_FIT_ELAPSED_SECONDS,
    RecordFact,
    WindowResult,
    reduce_records,
)


BASE = 0x10000000


def fact(raw: int, index: int, **metrics: float | None) -> RecordFact:
    values = {
        "heart_rate_bpm": None,
        "speed_mps": None,
        "cadence_rpm": None,
        "power_w": None,
        "altitude_m": None,
        "grade_pct": None,
    }
    values.update(metrics)
    return RecordFact(
        raw_timestamp_seconds=raw,
        timestamp_utc=FIT_EPOCH + timedelta(seconds=raw),
        encounter_index=index,
        **values,
    )


def test_default_window_is_half_open_and_coarse_bins_are_sparse():
    records = [
        fact(BASE, 0, heart_rate_bpm=100),
        fact(BASE + 4, 1, heart_rate_bpm=110),
        fact(BASE + 600, 2, heart_rate_bpm=120),
    ]

    result = reduce_records(records, 0, 600, 5)

    assert result.series["elapsed_seconds"] == [0]
    assert result.series["timestamp"] == ["1998-07-03T21:24:16.000000Z"]
    assert result.series["sample_count"] == [2]
    assert result.series["heart_rate_bpm"] == {
        "average": [105.0],
        "minimum": [100],
        "maximum": [110],
    }
    assert result.sampling == {
        "source_records": 2,
        "returned_points": 1,
        "observed_median_interval_seconds": 4.0,
        "irregular": False,
    }
    assert result.next_start_seconds == 600


def test_out_of_order_and_duplicate_timestamps_are_sorted_deterministically():
    records = [
        fact(BASE + 2, 9, heart_rate_bpm=130),
        fact(BASE, 4, heart_rate_bpm=100),
        fact(BASE + 2, 1, heart_rate_bpm=110),
    ]

    result = reduce_records(records, 0, 10, 10)

    assert result.series["heart_rate_bpm"] == {
        "average": [113.3],
        "minimum": [100],
        "maximum": [130],
    }
    assert result.sampling["observed_median_interval_seconds"] == 2.0
    assert result.sampling["irregular"] is False


def test_all_series_arrays_align_and_missing_metrics_are_null():
    result = reduce_records([fact(BASE, 0, heart_rate_bpm=140)], 0, 10, 1)

    assert result.sampling["returned_points"] == 1
    for value in result.series.values():
        if isinstance(value, dict):
            assert all(len(array) == 1 for array in value.values())
        else:
            assert len(value) == 1
    assert result.series["speed_mps"] == {"average": [None]}
    assert result.series["pace_seconds_per_km"] == {
        "average": [None],
        "fastest": [None],
        "slowest": [None],
    }
    assert result.availability["heart_rate_bpm"] is True
    assert result.availability["speed_mps"] is False
    assert result.availability["pace_seconds_per_km"] is False


def test_paging_uses_half_open_boundaries_without_repeat_or_skip():
    records = [fact(BASE + 599, 0), fact(BASE + 600, 1), fact(BASE + 1200, 2)]

    first = reduce_records(records, 0, 600, 1)
    second = reduce_records(records, 600, 600, 1)

    assert first.series["elapsed_seconds"] == [0, 1]
    assert first.next_start_seconds == 600
    assert second.series["elapsed_seconds"] == [601]
    assert second.next_start_seconds is None


def test_metric_aggregation_includes_zero_speed_but_pace_uses_positive_speed():
    result = reduce_records(
        [
            fact(BASE, 0, heart_rate_bpm=100.4, speed_mps=0.0, cadence_rpm=90.05),
            fact(BASE + 1, 1, heart_rate_bpm=101.5, speed_mps=2.0, cadence_rpm=90.15),
            fact(BASE + 2, 2, heart_rate_bpm=101.6, speed_mps=4.0, cadence_rpm=90.25),
        ],
        0,
        5,
        5,
    )

    assert result.series["heart_rate_bpm"] == {
        "average": [101.2],
        "minimum": [100],
        "maximum": [102],
    }
    assert result.series["speed_mps"] == {"average": [2.000]}
    assert result.series["pace_seconds_per_km"] == {
        "average": [333],
        "fastest": [250],
        "slowest": [500],
    }
    assert result.series["cadence_rpm"] == {"average": [90.1]}
    assert result.availability["speed_mps"] is True
    assert result.availability["pace_seconds_per_km"] is True


def test_zero_only_speed_has_speed_but_no_pace():
    result = reduce_records([fact(BASE, 0, speed_mps=0.0)], 0, 1, 1)

    assert result.series["speed_mps"] == {"average": [0.000]}
    assert result.series["pace_seconds_per_km"] == {
        "average": [None],
        "fastest": [None],
        "slowest": [None],
    }
    assert result.availability["speed_mps"] is True
    assert result.availability["pace_seconds_per_km"] is False


def test_half_up_fsum_rounding_is_used_for_display_values():
    result = reduce_records(
        [
            fact(BASE, 0, speed_mps=0.0005, altitude_m=0.05),
            fact(BASE + 1, 1, speed_mps=0.0015, altitude_m=0.15),
            fact(BASE + 2, 2, speed_mps=0.0025, altitude_m=0.25),
        ],
        0,
        3,
        3,
    )

    assert result.series["speed_mps"]["average"] == [0.002]
    assert result.series["altitude_m"]["average"] == [0.2]
    assert Decimal("0.002") == Decimal(str(result.series["speed_mps"]["average"][0]))


def test_all_metric_means_and_extrema_use_fixed_precision():
    result = reduce_records(
        [
            fact(
                BASE,
                0,
                cadence_rpm=1.04,
                power_w=2.04,
                altitude_m=3.04,
                grade_pct=4.04,
            ),
            fact(
                BASE + 1,
                1,
                cadence_rpm=1.06,
                power_w=2.06,
                altitude_m=3.06,
                grade_pct=4.06,
            ),
        ],
        0,
        2,
        2,
    )

    assert result.series["cadence_rpm"] == {"average": [1.1]}
    assert result.series["power_w"] == {"average": [2.1]}
    assert result.series["altitude_m"] == {"average": [3.1]}
    assert result.series["grade_pct"] == {"average": [4.1]}


def test_sampling_ignores_nonpositive_deltas_and_pins_irregularity():
    regular = reduce_records(
        [fact(BASE, 0), fact(BASE, 1), fact(BASE + 5, 2), fact(BASE + 10, 3)],
        0,
        20,
        1,
    )
    irregular = reduce_records(
        [fact(BASE, 0), fact(BASE + 1, 1), fact(BASE + 4, 2), fact(BASE + 10, 3)],
        0,
        20,
        1,
    )

    assert regular.sampling["observed_median_interval_seconds"] == 5.0
    assert regular.sampling["irregular"] is False
    assert irregular.sampling["observed_median_interval_seconds"] == 3.0
    assert irregular.sampling["irregular"] is True
    assert reduce_records([fact(BASE, 0), fact(BASE, 1)], 0, 1, 1).sampling == {
        "source_records": 2,
        "returned_points": 1,
        "observed_median_interval_seconds": None,
        "irregular": False,
    }


def test_cursor_is_limited_by_fit_elapsed_maximum():
    assert MAX_FIT_ELAPSED_SECONDS == 0xFFFFFFFE - 0x10000000
    records = [fact(BASE, 0), fact(0xFFFFFFFE, 1)]

    at_max = reduce_records(records, MAX_FIT_ELAPSED_SECONDS - 1, 1, 1)
    beyond_max = reduce_records(records, MAX_FIT_ELAPSED_SECONDS, 1, 1)

    assert at_max.next_start_seconds == MAX_FIT_ELAPSED_SECONDS
    assert beyond_max.next_start_seconds is None


def test_empty_records_and_empty_selected_window_have_stable_shapes():
    for records, expected_next in [([], None), ([fact(BASE, 0)], None)]:
        result = reduce_records(records, 0 if not records else 10, 10, 1)
        assert isinstance(result, WindowResult)
        assert result.sampling == {
            "source_records": 0,
            "returned_points": 0,
            "observed_median_interval_seconds": None,
            "irregular": False,
        }
        assert all(value is False for value in result.availability.values())
        assert result.series["elapsed_seconds"] == []
        assert result.series["timestamp"] == []
        assert result.series["sample_count"] == []
        assert all(all(not values for values in group.values()) for group in result.series.values() if isinstance(group, dict))
        assert result.next_start_seconds == expected_next


def test_reducer_does_not_mutate_records_and_has_no_forbidden_output_fields():
    records = [fact(BASE + 2, 1, heart_rate_bpm=100), fact(BASE, 0, heart_rate_bpm=90)]
    before = tuple(records)

    first = reduce_records(records, 0, 5, 1)
    second = reduce_records(records, 0, 5, 1)

    assert tuple(records) == before
    assert first == second
    assert "coordinate" not in repr(first).lower()
    assert "raw" not in repr(first).lower()
    assert "source" not in repr(first.series).lower()
