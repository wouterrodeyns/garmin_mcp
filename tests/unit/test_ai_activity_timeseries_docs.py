"""Current documentation contracts for the bounded activity evidence read."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
DOCS_PATH = ROOT / "docs" / "ai-activity-timeseries.md"


def _docs() -> str:
    assert DOCS_PATH.is_file()
    return DOCS_PATH.read_text()


def _json_blocks() -> list[dict[str, object]]:
    blocks = re.findall(r"```json\n(.+?)\n```", _docs(), re.DOTALL)
    assert blocks, "the guide must contain a JSON response example"
    values = [json.loads(block) for block in blocks]
    assert all(isinstance(value, dict) for value in values)
    return values  # type: ignore[return-value]


def _example() -> dict[str, object]:
    values = _json_blocks()
    assert len(values) == 1, "keep one primary populated response example"
    return values[0]


def _normalized() -> str:
    return " ".join(_docs().lower().split())


def test_guide_has_findable_sections_for_tool_choice_and_boundaries():
    docs = _docs()
    for heading in (
        "Choosing the tool",
        "Arguments and paging",
        "Returned evidence",
        "Privacy and safety",
        "Limits and exclusions",
    ):
        assert re.search(rf"^## {re.escape(heading)}\s*$", docs, re.MULTILINE)


def test_guide_example_has_exact_ordered_envelope_and_aligned_series():
    example = _example()
    assert list(example) == [
        "status",
        "error",
        "activity_id",
        "window",
        "sampling",
        "availability",
        "series",
        "warnings",
    ]
    assert example["status"] == "success"
    assert example["error"] is None
    assert list(example["window"]) == [
        "requested_start_seconds",
        "actual_end_seconds",
        "resolution_seconds",
        "next_start_seconds",
    ]
    assert list(example["availability"]) == [
        "heart_rate_bpm",
        "speed_mps",
        "pace_seconds_per_km",
        "cadence_rpm",
        "power_w",
        "altitude_m",
        "grade_pct",
    ]
    assert set(example["sampling"]) == {
        "source_records",
        "returned_points",
        "observed_median_interval_seconds",
        "irregular",
    }
    series = example["series"]
    assert list(series) == [
        "elapsed_seconds",
        "timestamp",
        "sample_count",
        "heart_rate_bpm",
        "speed_mps",
        "pace_seconds_per_km",
        "cadence_rpm",
        "power_w",
        "altitude_m",
        "grade_pct",
    ]
    assert set(series["heart_rate_bpm"]) == {"average", "minimum", "maximum"}
    assert set(series["speed_mps"]) == {"average"}
    assert set(series["pace_seconds_per_km"]) == {
        "average",
        "fastest",
        "slowest",
    }
    for metric in ("cadence_rpm", "power_w", "altitude_m", "grade_pct"):
        assert set(series[metric]) == {"average"}
    returned_points = example["sampling"]["returned_points"]
    assert returned_points == 2
    arrays = [
        series["elapsed_seconds"],
        series["timestamp"],
        series["sample_count"],
        series["heart_rate_bpm"]["average"],
        series["heart_rate_bpm"]["minimum"],
        series["heart_rate_bpm"]["maximum"],
        series["speed_mps"]["average"],
        series["pace_seconds_per_km"]["average"],
        series["pace_seconds_per_km"]["fastest"],
        series["pace_seconds_per_km"]["slowest"],
        series["cadence_rpm"]["average"],
        series["power_w"]["average"],
        series["altitude_m"]["average"],
        series["grade_pct"]["average"],
    ]
    assert all(len(array) == returned_points for array in arrays)


def test_guide_example_uses_safe_plausible_values_and_utc_bin_anchors():
    example = _example()
    serialized = json.dumps(example).lower()
    for forbidden in (
        "gps",
        "location",
        "coordinate",
        "polyline",
        "raw_fit",
        "description",
        "secret",
        "password",
        "token",
    ):
        assert forbidden not in serialized
    assert example["activity_id"] == 123456
    assert example["window"] == {
        "requested_start_seconds": 0,
        "actual_end_seconds": 600,
        "resolution_seconds": 1,
        "next_start_seconds": 600,
    }
    assert example["sampling"]["source_records"] >= example["sampling"]["returned_points"]
    assert example["sampling"]["observed_median_interval_seconds"] == 1
    assert example["sampling"]["irregular"] is True
    assert all(value.endswith("Z") for value in example["series"]["timestamp"])


def test_guide_pins_workflow_arguments_and_exact_pagination_recipe():
    lower = _normalized()
    for phrase in (
        "analyze_activity(activity_id) first",
        "get_activity_timeseries only for concrete short interval evidence",
        "start_seconds=0",
        "duration_seconds=600",
        "resolution_seconds=1",
        "positive integer",
        "ascii decimal string",
        "half-open",
        "ceil(duration_seconds / resolution_seconds)",
        "600 non-empty bins",
        "do not create missing seconds, carry values forward, or assume a one-hz source stream",
    ):
        assert phrase in lower
    for phrase in (
        "1. call get_activity_timeseries(activity_id=123456, start_seconds=0, duration_seconds=600, resolution_seconds=1).",
        "2. if window.next_start_seconds is present, call the same tool with that integer as start_seconds.",
        "3. stop when next_start_seconds is absent.",
    ):
        assert phrase in lower


def test_guide_pins_sparse_sampling_units_rounding_and_availability_scope():
    lower = _normalized()
    for phrase in (
        "sparse bins",
        "gaps",
        "no fill",
        "no interpolation",
        "not exactly 1hz",
        "canonical utc z bin anchors",
        "not exact device sample claims",
        "elapsed seconds",
        "heart rate in bpm",
        "speed in m/s to 3 decimals",
        "pace in seconds/km to an integer",
        "cadence in rpm",
        "power in w",
        "altitude in m",
        "grade in %",
        "means to 1 decimal",
        "heart-rate extrema and pace values to integer seconds",
        "missing is null",
        "recorded zero remains 0",
        "returned-window only",
        "not device or account capability",
    ):
        assert phrase in lower


def test_guide_pins_download_privacy_errors_and_safety_limits():
    lower = _normalized()
    for phrase in (
        "one original fit download per valid call",
        "no caching",
        "never returns gps",
        "location",
        "coordinates",
        "polyline",
        "raw fit",
        "developer/raw fields",
        "names/descriptions",
        "archive/member 25mb",
        "entries 16",
        "cd/read chunk 65536",
        "auxiliary 65536",
        "frames 200000",
        "records 100000",
        "definition fields 128",
        "returned points 600",
        "strict classic zip/crc/chained fatal",
        "malformed warning",
        "fixed generic message",
        "fitdecode 0.11",
    ):
        assert phrase in lower
    assert "existing fitparse analyze path unchanged" in lower


def test_guide_excludes_coaching_mutation_and_unsafe_follow_ups():
    lower = _normalized()
    for phrase in (
        "no coaching recommendation",
        "no comparison",
        "no interpolation",
        "no gps",
        "no workout mutation",
        "read-only",
        "not a replacement for analyze_activity",
    ):
        assert phrase in lower
