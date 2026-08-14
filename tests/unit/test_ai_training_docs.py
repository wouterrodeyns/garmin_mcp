import json
from pathlib import Path
import re

from garmin_mcp import TOOL_PROFILES


ROOT = Path(__file__).parents[2]
DOCS_PATH = ROOT / "docs/ai-training.md"
DOCS = DOCS_PATH.read_text() if DOCS_PATH.exists() else ""


def _example_json() -> dict[str, object]:
    match = re.search(r"```json\n(.+?)\n```", DOCS, re.DOTALL)
    assert match is not None
    return json.loads(match.group(1))


def test_docs_pin_purpose_dependency_bounds_and_windows():
    lower = DOCS.lower()
    for text in (
        "get_training_context",
        "read-only",
        "garminconnect==0.3.10",
        "1 through 90",
        "inclusive retrospective",
        "today through the following six days",
        "fixed seven-day schedule window",
    ):
        assert text in lower


def test_docs_pin_metric_groups_optionality_and_device_variability():
    lower = DOCS.lower()
    for text in (
        "recent activities",
        "scheduled workouts",
        "sleep",
        "hrv",
        "resting heart rate",
        "body battery",
        "training readiness",
        "recovery time",
        "training status",
        "training load",
        "load focus",
        "vo2 max",
        "optional",
        "device and account",
    ):
        assert text in lower


def test_docs_pin_availability_null_and_overnight_date_semantics():
    lower = DOCS.lower()
    for text in (
        "availability",
        "null, not zero",
        "previous local calendar day",
        "garmin's `calendardate` when supplied",
        "requested query date",
        "date provenance",
        "athlete's local timezone",
    ):
        assert text in lower


def test_docs_pin_snapshot_scoped_missing_metric_interpretation_and_query_windows():
    lower = " ".join(DOCS.lower().split())
    for text in (
        "| activities | `days` retrospective activity lookback |",
        "latest run is searched independently across up to 1,000 activity records "
        "and may be older than the requested period",
        "| scheduled workouts | today through the following six days |",
        "| daily recovery and fitness metrics | today |",
        "| sleep, hrv, and readiness | today, then yesterday only for a legitimately empty response |",
        "null optional metric with no warning means the metric was not available in this snapshot",
        "does not prove the account or device does not support it",
        "provider failures are reported in structured warnings",
        "old recovery or fitness metric dates must not be used to infer today's recovery state",
    ):
        assert text in lower


def test_docs_pin_request_caps_paging_and_truncation():
    lower = DOCS.lower()
    for text in (
        "200-record pages",
        "1,000 records",
        "days * 10",
        "20 recent activities",
        "mid-page",
        "lower bounds",
        "first page containing a running match",
        "newest timestamped running item",
    ):
        assert text in lower
    assert "stops at the first local running match" not in lower


def test_docs_pin_status_boundary_error_codes_and_warning_vocabulary():
    lower = DOCS.lower()
    for text in (
        "success",
        "partial_success",
        "context_unavailable",
        "invalid_days",
        "client_unavailable",
        "period activities and scheduled workouts",
        "provider_unavailable",
        "invalid_provider_response",
        "activities_truncated",
        "warnings alone do not imply",
    ):
        assert text in lower
    assert "exactly three warning codes" in lower
    assert "malformed scheduled-workout entries" in lower


def test_docs_pin_profile_and_sport_translation():
    lower = DOCS.lower()
    assert "exactly 14 tools" in lower
    assert "analyze_activity" in lower
    assert "recent_activities[].sport" in lower
    assert "garmin activity type keys" in lower
    assert "trail_running" in lower
    assert "create_workout.sport" in lower
    assert "running, cycling, walking, or strength" in lower


def test_docs_pin_exact_ai_coach_profile_and_three_high_level_roles():
    assert "14-tool surface" in DOCS.lower() or "exactly 14 tools" in DOCS.lower()
    for expected in (
        "context eyes",
        "completed-session feedback",
        "workout hands",
        "create_workout",
        "update_workout",
        "in-place",
    ):
        assert expected in DOCS.lower()
    expected_profile = {
        "get_training_context",
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
    assert TOOL_PROFILES["ai-coach"] == expected_profile


def test_docs_pin_no_inference_and_deliberate_omissions():
    lower = DOCS.lower()
    assert "never derives acwr" in lower
    assert "lactate threshold" in lower and "omitted" in lower
    assert "last-hard-session" in lower and "omitted" in lower
    assert "does not provide coaching advice" in lower


def test_docs_pin_two_tool_conversational_workflow():
    lower = DOCS.lower()
    assert "eyes" in lower and "hands" in lower
    assert "get_training_context(days=30)" in lower
    assert "create_workout" in lower
    assert "put that workout on garmin for tomorrow" in lower


def test_docs_example_is_compact_and_distinguishes_schedule_and_workout_ids():
    example = _example_json()
    assert example["training"]["total_training_minutes"] == 245.0  # type: ignore[index]
    assert example["training"]["running_distance_km"] == 0.0  # type: ignore[index]
    assert example["fitness"]["acute_load"] == 247  # type: ignore[index]
    assert example["fitness"]["chronic_load"] == 193  # type: ignore[index]
    assert example["fitness"]["acute_chronic_ratio"] == 1.14  # type: ignore[index]
    assert len(example["recent_activities"]) <= 20  # type: ignore[arg-type]
    scheduled = example["scheduled_workouts"][0]  # type: ignore[index]
    assert scheduled["scheduled_workout_id"] != scheduled["workout_id"]
