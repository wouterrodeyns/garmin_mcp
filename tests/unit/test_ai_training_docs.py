import json
from pathlib import Path
import re


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
        "garminconnect==0.3.2",
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
    assert "exactly 11 tools" in lower
    assert "recent_activities[].sport" in lower
    assert "garmin activity type keys" in lower
    assert "trail_running" in lower
    assert "create_workout.sport" in lower
    assert "running, cycling, walking, or strength" in lower


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
