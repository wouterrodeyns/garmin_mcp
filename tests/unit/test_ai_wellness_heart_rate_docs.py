"""Current-facing documentation contracts for wellness heart-rate evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path

from garmin_mcp import TOOL_PROFILES


ROOT = Path(__file__).parents[2]
DOCS_PATH = ROOT / "docs" / "ai-wellness-heart-rate.md"
CURRENT_DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "setup.md",
    ROOT / "docs" / "ai-training.md",
    ROOT / "docs" / "ai-activity.md",
    ROOT / "docs" / "ai-activity-timeseries.md",
    ROOT / "docs" / "ai-workouts.md",
)

PROFILE_TOOLS = {
    "get_training_context",
    "get_wellness_heart_rate",
    "analyze_activity",
    "get_activity_timeseries",
    "create_workout",
    "update_workout",
    "get_activities",
    "get_activities_by_date",
    "get_activity",
    "get_workouts",
    "get_workout_by_id",
    "get_scheduled_workouts",
    "schedule_workout",
    "unschedule_workout",
    "delete_workout",
}

TOP_KEYS = [
    "status",
    "error",
    "period",
    "resolution",
    "availability",
    "days",
    "warnings",
]
PERIOD_KEYS = ["start_date", "end_date", "start_time", "end_time"]
DAY_KEYS = [
    "date",
    "available",
    "summary",
    "time_provenance",
    "sampling",
    "points",
    "gaps",
]
SUMMARY_KEYS = [
    "resting_hr_bpm",
    "min_hr_bpm",
    "max_hr_bpm",
    "seven_day_avg_resting_hr_bpm",
]
PROVENANCE_KEYS = ["local_offset_minutes", "local_time_available"]
SAMPLING_KEYS = [
    "source_points",
    "valid_bpm_points",
    "null_bpm_points",
    "returned_points",
    "observed_median_interval_seconds",
    "duration_from_sample_count_valid",
]
RAW_POINT_KEYS = ["time_local", "time_utc", "bpm"]
BIN_KEYS = [
    "start_time_local",
    "end_time_local",
    "start_time_utc",
    "end_time_utc",
    "min_bpm",
    "mean_bpm",
    "max_bpm",
    "sample_count",
]
GAP_KEYS = [
    "start_time_local",
    "end_time_local",
    "start_time_utc",
    "end_time_utc",
    "elapsed_minutes",
]


def _docs() -> str:
    assert DOCS_PATH.is_file()
    return DOCS_PATH.read_text()


def _json_examples() -> list[dict[str, object]]:
    blocks = re.findall(r"^```json\s*\n(.*?)^```\s*$", _docs(), re.MULTILINE | re.DOTALL)
    assert len(blocks) >= 4, "daily, raw, binned, and partial-success examples required"
    values = [json.loads(block) for block in blocks]
    assert all(isinstance(value, dict) for value in values)
    return values  # type: ignore[return-value]


def _assert_day_shape(day: dict[str, object]) -> None:
    assert list(day) == DAY_KEYS
    assert list(day["summary"]) == SUMMARY_KEYS  # type: ignore[arg-type]
    assert list(day["time_provenance"]) == PROVENANCE_KEYS  # type: ignore[arg-type]
    assert list(day["sampling"]) == SAMPLING_KEYS  # type: ignore[arg-type]
    assert isinstance(day["points"], list)
    assert isinstance(day["gaps"], list)


def test_guide_exists_and_pins_signature_modes_and_product_bounds():
    docs = _docs()
    lower = " ".join(docs.lower().split())
    for heading in (
        "Purpose",
        "Call signature and request rules",
        "Response contract",
        "Time provenance",
        "Interpretation guardrails",
        "Statuses, warnings, and missing dates",
        "Read-only and security boundary",
        "Choosing the tool",
    ):
        assert re.search(rf"^## {re.escape(heading)}\s*$", docs, re.MULTILINE)
    assert "get_wellness_heart_rate(start_date, end_date=None, resolution=\"raw\", start_time=None, end_time=None)" in docs
    for mode in ("daily", "raw", "5m", "15m", "30m", "60m"):
        assert f"`{mode}`" in docs
    for bound in ("7 dates", "10,000", "1,000", "262,144", "300 seconds"):
        assert bound in docs
    for phrase in (
        "explicit",
        "read-only",
        "not embedded in `get_training_context`",
        "broad raw `get_heart_rates` remains outside `ai-coach`",
        "inclusive",
        "start-inclusive",
        "end-exclusive",
        "same-day",
        "cross-midnight",
        "daily rejects",
        "never truncates",
        "product safety limits, not claimed garmin api limits",
    ):
        assert phrase in lower


def test_guide_examples_parse_and_pin_exact_stable_shapes_and_types():
    examples = _json_examples()
    resolutions = {example["resolution"] for example in examples}
    assert {"daily", "raw", "5m"}.issubset(resolutions)
    assert any(example["status"] == "partial_success" for example in examples)
    for example in examples:
        assert list(example) == TOP_KEYS
        assert example["status"] in {"success", "partial_success", "error"}
        assert list(example["period"]) == PERIOD_KEYS  # type: ignore[arg-type]
        assert isinstance(example["availability"], dict)
        assert isinstance(example["days"], list)
        assert isinstance(example["warnings"], list)
        for day in example["days"]:  # type: ignore[union-attr]
            _assert_day_shape(day)
            assert type(day["date"]) is str
            assert type(day["available"]) is bool
            sampling = day["sampling"]
            assert type(sampling["source_points"]) is int
            assert type(sampling["returned_points"]) is int
            assert type(sampling["duration_from_sample_count_valid"]) is bool
            assert sampling["duration_from_sample_count_valid"] is False
            for point in day["points"]:
                if "bpm" in point:
                    assert list(point) == RAW_POINT_KEYS
                    assert type(point["time_utc"]) is str
                    assert type(point["time_local"]) is (str if point["time_local"] else type(None))
                    assert point["bpm"] is None or type(point["bpm"]) is int
                else:
                    assert list(point) == BIN_KEYS
                    assert type(point["sample_count"]) is int
                    assert type(point["min_bpm"]) is int
                    assert type(point["mean_bpm"]) is float
                    assert type(point["max_bpm"]) is int
                    assert "coverage" not in point
            for gap in day["gaps"]:
                assert list(gap) == GAP_KEYS
                assert type(gap["elapsed_minutes"]) is float
        for warning in example["warnings"]:
            assert list(warning) == ["provider", "date", "code", "message"]
            assert warning["provider"] == "wellness_heart_rate"
        if example["error"] is not None:
            assert list(example["error"]) == ["code", "message"]  # type: ignore[arg-type]


def test_guide_covers_nulls_provenance_statuses_and_sync_caveat():
    lower = " ".join(_docs().lower().split())
    for phrase in (
        "missing values are null, never zero",
        "null bpm",
        "local iso 8601",
        "numeric offset",
        "utc always",
        "local_time_unavailable",
        "offset transition",
        "daily mode is sample-free",
        "success",
        "partial_success",
        "error",
        "per-date failures continue sequentially",
        "legitimate empty",
        "watch/device has not synced to garmin connect yet",
        "sync then retry",
        "does not establish unsupported account/device",
        "fixed",
        "sanitized",
    ):
        assert phrase in lower


def test_guide_states_interpretation_guardrails_without_unsupported_inference():
    lower = " ".join(_docs().lower().split())
    for phrase in (
        "irregular",
        "missing sampling",
        "sample_count",
        "never a duration",
        "time in zone",
        "distinct from fit activity",
        "sensor",
        "smoothing",
        "zones",
        "only returned samples",
        "do not prove",
        "watch removal",
        "charging",
        "sleep",
        "illness",
        "exercise",
        "drift",
        "recovery",
        "stress",
        "coaching conclusions",
        "no coverage",
    ):
        assert phrase in lower
    for forbidden in (
        "compute duration from sample_count",
        "calculate time in zone",
        "assume continuous coverage",
        "gap proves charging",
        "empty day proves unsupported",
    ):
        assert forbidden not in lower


def test_guide_pins_read_only_calls_and_explicit_workflow_distinctions():
    lower = " ".join(_docs().lower().split())
    for phrase in (
        "only `client.get_heart_rates(date)`",
        "at most seven sequential reads",
        "does not call `get_rhr_day`",
        "does not call `connectapi`",
        "normalized response is not a garmin dto",
        "get_training_context",
        "compact automatic context",
        "explicit all-day evidence",
        "analyze_activity",
        "completed activity",
        "create_workout` / `update_workout",
        "only after user confirmation",
        "get_activity_timeseries",
        "completed activity/fit evidence",
        "get_heart_rates_summary",
    ):
        assert phrase in lower


def test_current_docs_publish_exact_fifteen_tool_profile_and_no_stale_count():
    assert PROFILE_TOOLS == TOOL_PROFILES["ai-coach"]
    assert len(PROFILE_TOOLS) == 15
    for path in CURRENT_DOCS:
        text = path.read_text().lower()
        for stale in ("exactly 14", "14-tool", "exact 14", "14 tools"):
            assert stale not in text
    readme = (ROOT / "README.md").read_text()
    profile = re.search(r"^## AI-coach tool profile\s*$([\s\S]*?)(?=^## |\Z)", readme, re.MULTILINE)
    assert profile is not None
    assert set(re.findall(r"^`([^`]+)`$", profile.group(1), re.MULTILINE)) == PROFILE_TOOLS


def test_current_docs_link_wellness_guide_and_distinguish_activity_evidence():
    readme = (ROOT / "README.md").read_text()
    setup = (ROOT / "docs" / "setup.md").read_text()
    assert "docs/ai-wellness-heart-rate.md" in readme
    assert "ai-wellness-heart-rate.md" in setup
    assert "ai-wellness-heart-rate.md" in (ROOT / "docs/ai-training.md").read_text()
    assert "wellness" in (ROOT / "docs/ai-activity.md").read_text().lower()
    assert "wellness" in (ROOT / "docs/ai-activity-timeseries.md").read_text().lower()
