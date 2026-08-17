"""Documentation contracts for the explicit AI sleep-trend evidence tool."""

from __future__ import annotations

import json
import re
from pathlib import Path

from garmin_mcp import TOOL_PROFILES


ROOT = Path(__file__).parents[2]
GUIDE_PATH = ROOT / "docs" / "ai-sleep-trend.md"
README_PATH = ROOT / "README.md"
PUBLIC_DOC_PATHS = (
    README_PATH,
    ROOT / "docs" / "ai-training.md",
    ROOT / "docs" / "ai-workouts.md",
    ROOT / "docs" / "ai-wellness-heart-rate.md",
    ROOT / "docs" / "setup.md",
    GUIDE_PATH,
)

TOP_KEYS = [
    "status",
    "error",
    "period",
    "availability",
    "summary",
    "nights",
    "warnings",
]
PERIOD_KEYS = ["days", "start_date", "end_date"]
SUMMARY_KEYS = ["nights_requested", "nights_available", "averages"]
AVERAGE_KEYS = ["duration_hours", "score", "resting_hr_bpm", "overnight_hrv_ms", "spo2_percent"]
NIGHT_KEYS = [
    "date",
    "available",
    "duration_hours",
    "nap_minutes",
    "score",
    "score_qualifier",
    "stages",
    "resting_hr_bpm",
    "overnight_hrv_ms",
    "average_sleep_stress",
    "awake_count",
    "restless_moments_count",
    "spo2",
]
STAGE_KEYS = ["deep_minutes", "light_minutes", "rem_minutes", "awake_minutes"]
SPO2_KEYS = ["average_percent", "lowest_percent"]
WARNING_KEYS = ["provider", "date", "code", "message"]
ERROR_KEYS = ["code", "message"]

EXPECTED_PROFILE = {
    "get_training_context",
    "get_sleep_trend",
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


def _guide() -> str:
    assert GUIDE_PATH.is_file()
    return GUIDE_PATH.read_text()


def _json_examples() -> list[dict[str, object]]:
    blocks = re.findall(
        r"^```json\s*\n(.*?)^```\s*$",
        _guide(),
        re.MULTILINE | re.DOTALL,
    )
    assert blocks, "the public guide must contain a JSON response example"
    examples = [json.loads(block) for block in blocks]
    assert all(type(example) is dict for example in examples)
    return examples  # type: ignore[return-value]


def test_guide_pins_call_bounds_cost_and_interpretation_guardrails() -> None:
    lower = " ".join(_guide().lower().split())
    for phrase in (
        "get_sleep_trend(days=7)",
        "fixed inclusive period",
        "ends today",
        "one sequential garmin read per requested date",
        "maximum 30",
        "today's sleep may be unavailable until the watch synchronizes",
        "missing dates remain visible",
        "per-metric denominator",
        "does not establish causation, readiness, recovery",
        "read-only",
        "sleep timestamps are not returned",
    ):
        assert phrase in lower


def test_guide_examples_parse_and_pin_exact_stable_shapes_and_types() -> None:
    examples = _json_examples()
    assert any(example["status"] == "partial_success" for example in examples)
    for example in examples:
        assert list(example) == TOP_KEYS
        assert example["status"] in {"success", "partial_success", "error"}
        assert example["error"] is None or list(example["error"]) == ERROR_KEYS  # type: ignore[index]
        assert list(example["period"]) == PERIOD_KEYS  # type: ignore[arg-type]
        period = example["period"]
        assert type(period["days"]) is int  # type: ignore[index]
        assert type(period["start_date"]) is str  # type: ignore[index]
        assert type(period["end_date"]) is str  # type: ignore[index]
        assert list(example["summary"]) == SUMMARY_KEYS  # type: ignore[arg-type]
        summary = example["summary"]
        assert type(summary["nights_requested"]) is int  # type: ignore[index]
        assert type(summary["nights_available"]) is int  # type: ignore[index]
        assert list(summary["averages"]) == AVERAGE_KEYS  # type: ignore[index]
        for average in summary["averages"].values():  # type: ignore[union-attr]
            assert list(average) == ["value", "nights"]  # type: ignore[arg-type]
            assert average["value"] is None or type(average["value"]) in (int, float)  # type: ignore[index]
            assert type(average["nights"]) is int  # type: ignore[index]
        assert isinstance(example["availability"], dict)
        assert all(type(value) is bool for value in example["availability"].values())  # type: ignore[union-attr]
        assert isinstance(example["nights"], list)
        assert len(example["nights"]) == period["days"]  # type: ignore[index]
        dates = []
        for night in example["nights"]:  # type: ignore[union-attr]
            assert list(night) == NIGHT_KEYS
            dates.append(night["date"])
            assert type(night["date"]) is str
            assert type(night["available"]) is bool
            assert list(night["stages"]) == STAGE_KEYS
            assert list(night["spo2"]) == SPO2_KEYS
            for key, value in night.items():
                if key in {"date", "available", "score_qualifier", "stages", "spo2"}:
                    continue
                assert value is None or type(value) in (int, float)
            assert all(value is None or type(value) in (int, float) for value in night["stages"].values())
            assert all(value is None or type(value) in (int, float) for value in night["spo2"].values())
            if night["available"] is False:
                assert all(
                    value is None
                    for key, value in night.items()
                    if key not in {"date", "available", "stages", "spo2"}
                )
                assert all(value is None for value in night["stages"].values())
                assert all(value is None for value in night["spo2"].values())
        assert dates == sorted(dates)
        for warning in example["warnings"]:  # type: ignore[union-attr]
            assert list(warning) == WARNING_KEYS
            assert warning["provider"] == "sleep"
            assert warning["code"] in {
                "sleep_data_unavailable",
                "provider_unavailable",
                "invalid_provider_response",
            }


def test_documented_profile_matches_runtime_exactly_and_has_no_stale_count() -> None:
    assert TOOL_PROFILES["ai-coach"] == EXPECTED_PROFILE
    readme = README_PATH.read_text()
    profile = re.search(
        r"^## AI-coach tool profile\s*$([\s\S]*?)(?=^## |\Z)",
        readme,
        re.MULTILINE,
    )
    assert profile is not None
    names = re.findall(r"^`([^`]+)`$", profile.group(1), re.MULTILINE)
    assert len(names) == 16
    assert set(names) == TOOL_PROFILES["ai-coach"]
    combined = "\n".join(path.read_text() for path in PUBLIC_DOC_PATHS).lower()
    assert "15-tool surface" not in combined
    assert "exactly 15 tools" not in combined
    assert "exactly these 15 tools" not in combined


def test_guide_pins_metrics_units_availability_status_and_read_only_boundary() -> None:
    lower = " ".join(_guide().lower().split())
    for phrase in (
        "duration_hours",
        "nap_minutes",
        "deep_minutes",
        "average_sleep_stress",
        "overnight_hrv_ms",
        "spo2",
        "one decimal",
        "null, never zero",
        "actual source values",
        "status",
        "partial_success",
        "sleep_trend_unavailable",
        "provider_unavailable",
        "invalid_provider_response",
        "device, account, and sync state",
        "does not invoke another mcp tool",
        "tokens",
        "credentials",
        "china",
    ):
        assert phrase in lower
