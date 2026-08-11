"""Live documentation contracts for the AI activity analysis feature.

These tests intentionally read only current-facing documentation.  Historical
specifications and implementation plans are not documentation sources.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import garmin_mcp


ROOT = Path(__file__).parents[2]
DOCS_PATH = ROOT / "docs" / "ai-activity.md"
README_PATH = ROOT / "README.md"
TRAINING_PATH = ROOT / "docs" / "ai-training.md"
WORKOUTS_PATH = ROOT / "docs" / "ai-workouts.md"
SETUP_PATH = ROOT / "docs" / "setup.md"

PROFILE_TOOLS = {
    "get_training_context",
    "analyze_activity",
    "create_workout",
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


def _read(path: Path) -> str:
    assert path.is_file(), f"missing live documentation: {path.relative_to(ROOT)}"
    return path.read_text()


def _example_json() -> dict[str, object]:
    docs = _read(DOCS_PATH)
    match = re.search(r"```json\n(.+?)\n```", docs, re.DOTALL)
    assert match is not None, "ai-activity.md must contain one concise JSON example"
    value = json.loads(match.group(1))
    assert isinstance(value, dict)
    return value


def _profile_list(markdown: str) -> set[str]:
    section = re.search(
        r"^## AI-coach tool profile\s*$([\s\S]*?)(?=^## |\Z)",
        markdown,
        re.MULTILINE,
    )
    assert section is not None
    return set(re.findall(r"^`([^`]+)`$", section.group(1), re.MULTILINE))


def test_activity_docs_pin_scope_and_exact_supported_call_budget():
    lower = " ".join(_read(DOCS_PATH).lower().split())
    for phrase in (
        "completed garmin activity",
        "feedback loop",
        "run/walk: splits + heart-rate zones when a heart-rate signal exists",
        "cycling: splits + heart-rate zones + power zones when the corresponding signals exist",
        "strength: exercise sets",
        "generic: base activity summary only",
        "fixed call budget",
        "after a valid activity_id and configured client, the service makes one base activity read",
        "no optional provider calls",
    ):
        assert phrase in lower
    assert "the service always makes one base activity read" not in lower
    assert "exactly these sport families" in lower


def test_activity_docs_pin_stable_envelope_availability_and_statuses():
    docs = _read(DOCS_PATH)
    lower = " ".join(docs.lower().split())
    expected = {
        "status",
        "error",
        "activity",
        "availability",
        "splits",
        "heart_rate_zones",
        "power_zones",
        "strength",
        "derived",
        "warnings",
    }
    envelope = re.search(r"```text\n(.+?)\n```", docs, re.DOTALL)
    assert envelope is not None
    assert set(re.findall(r"[a-z_]+", envelope.group(1))) == expected
    for phrase in (
        "stable top-level envelope",
        "availability is section-level",
        "success",
        "partial_success",
        "error",
        "null, not zero",
        "device, account, and sync state",
        "optional sections are always present in the top-level envelope",
        "unavailable optional sections are null",
    ):
        assert phrase in lower
    assert "optional sections are omitted or null" not in lower


def test_activity_docs_pin_units_raw_first_rounding_bounds_and_truncation():
    lower = " ".join(_read(DOCS_PATH).lower().split())
    for phrase in (
        "meters to kilometers",
        "seconds to minutes",
        "meters per second to kilometers per hour",
        "raw source values before rounding",
        "duration_minutes: one decimal",
        "distance_km: two decimals",
        "100 source laps",
        "total_count",
        "returned_count",
        "derived comparisons are null when truncation occurs",
        "mechanical facts",
        "not coaching quality or compliance",
    ):
        assert phrase in lower


def test_activity_docs_pin_garmin_set_centric_strength_contract():
    lower = " ".join(_read(DOCS_PATH).lower().split())
    for phrase in (
        "set-centric `exercisesets` response",
        "`active` records are work sets",
        "`rest` records are excluded",
        "first exercise candidate's full trimmed name and category",
        "only the displayed name is capped at 120",
        "category is never returned",
        "`set_number` is null",
        "probability, category, weight, resistance, duration, and volume are not returned",
    ):
        assert phrase in lower


def test_activity_docs_pin_warning_security_and_bounded_field_contracts():
    lower = " ".join(_read(DOCS_PATH).lower().split())
    for phrase in (
        "fixed warning codes",
        "provider_unavailable",
        "invalid_provider_response",
        "splits_truncated",
        "read-only guarantee",
        "never performs writes",
        "fixed error and warning objects never include exception text, raw provider responses, tokens, credentials, urls, headers, or request ids",
        "discarded malformed payloads are not echoed",
        "successful responses return bounded user-authored names, descriptions, and exercise names",
        "those fields may contain arbitrary text",
        "workout_feedback.rpe is a human 0-10 value",
        "normalized from garmin directworkoutrpe x10 storage",
        "raw source semantics",
        "activity name is bounded to 200",
        "description is bounded to 500",
        "strength exercise names are bounded to 120",
        "other returned strings are bounded to 100",
    ):
        assert phrase in lower
    assert "never includes raw responses, tokens, credentials, urls, or headers" not in lower


def test_activity_docs_pin_argument_availability_and_sport_vocabularies():
    lower = " ".join(_read(DOCS_PATH).lower().split())
    for phrase in (
        "activity_id",
        "positive integer or decimal string",
        "fastmcp rejects booleans and floats before any garmin read",
        "detail is not an argument",
        "optional detail may be absent",
        "unavailable snapshot or sync",
        "does not mean the device or account is unsupported",
        "garmin raw activity type keys",
        "create_workout normalized sport vocabulary",
        "running, cycling, walking, or strength",
        "low-level get_activity remains a compatibility and targeted read",
    ):
        assert phrase in lower


def test_activity_docs_pin_current_workflow_and_explicit_v1_exclusions():
    lower = " ".join(_read(DOCS_PATH).lower().split())
    for phrase in (
        "identify the completed activity",
        "analyze it",
        "ai interprets the evidence",
        "user confirms",
        "create the next workout",
        "fit files",
        "second-by-second records",
        "details, maps, weather, and gear",
        "planned or scheduled workout linkage",
        "step comparison",
        "coaching judgment",
        "compliance, pass/fail, or recommendations",
        "heart-rate drift or decoupling",
        "strength weight or volume",
        "swimming and other sport-specific detail",
        "thresholds, lactate threshold, and ftp",
    ):
        assert phrase in lower


def test_activity_docs_pin_zone_aliases_and_interpretation_boundary():
    lower = " ".join(_read(DOCS_PATH).lower().split())
    for phrase in (
        "zone or zonenumber",
        "timeinzone or secsinzone",
        "zero-second zones are retained",
        "percentage and upper boundary remain null when garmin omits them",
        "never estimate time in zone from split-average heart rate",
        "split averages do not establish heart-rate drift or cardiovascular decoupling",
    ):
        assert phrase in lower


def test_activity_docs_example_is_compact_current_and_explicitly_raw_backed():
    example = _example_json()
    assert set(example) == {
        "status",
        "error",
        "activity",
        "availability",
        "splits",
        "heart_rate_zones",
        "power_zones",
        "strength",
        "derived",
        "warnings",
    }
    assert example["status"] == "success"
    assert example["error"] is None
    activity = example["activity"]
    assert isinstance(activity, dict)
    assert set(activity) == {
        "id",
        "name",
        "description",
        "sport",
        "sport_family",
        "event_type",
        "start_time_local",
        "duration_minutes",
        "moving_duration_minutes",
        "elapsed_duration_minutes",
        "distance_km",
        "average_speed_kph",
        "max_speed_kph",
        "average_pace",
        "heart_rate",
        "power",
        "cadence",
        "elevation",
        "calories",
        "training_effect",
        "workout_feedback",
        "recovery",
        "reported_lap_count",
    }
    assert set(activity["heart_rate"]) == {"average_bpm", "max_bpm", "min_bpm"}
    assert set(activity["power"]) == {"average_watts", "max_watts", "normalized_watts"}
    assert set(activity["cadence"]) == {"average_spm", "max_spm"}
    assert set(activity["elevation"]) == {
        "gain_meters", "loss_meters", "minimum_meters", "maximum_meters"
    }
    assert set(activity["training_effect"]) == {"aerobic", "anaerobic", "label", "load"}
    assert set(activity["workout_feedback"]) == {"rpe", "feel"}
    assert set(activity["recovery"]) == {"heart_rate_bpm", "body_battery_impact"}
    assert set(example["availability"]) == {
        "activity", "splits", "heart_rate_zones", "power_zones", "strength"
    }
    assert set(example["derived"]) == {
        "scope", "fastest_split_number", "fastest_pace",
        "slowest_split_number", "slowest_pace", "pace_range_seconds_per_km"
    }
    assert example["splits"] is None
    assert example["power_zones"] is None
    assert example["strength"] is None
    lower = " ".join(_read(DOCS_PATH).lower().split())
    assert "illustrative values are copied from normalized source fields" in lower
    assert "no metrics are inferred" in lower
    assert "optional sections are null when unavailable" in lower
    assert "optional sections are omitted or null" not in lower


def test_current_docs_publish_the_exact_profile_without_stale_eleven_claims():
    readme = _read(README_PATH)
    training = _read(TRAINING_PATH)
    workouts = _read(WORKOUTS_PATH)
    setup = _read(SETUP_PATH)
    assert _profile_list(readme) == PROFILE_TOOLS
    assert set(garmin_mcp.TOOL_PROFILES["ai-coach"]) == PROFILE_TOOLS
    combined = " ".join("\n".join((readme, training, workouts, setup)).lower().split())
    assert "exactly 11" not in combined
    assert "no existing upstream tool is removed" in combined
    for tool in sorted(PROFILE_TOOLS):
        assert tool in combined
    assert "docs/ai-activity.md" in readme
    assert "ai-activity.md" in setup
    assert "ai-activity.md" in training
    assert "ai-activity.md" in workouts
    assert "ai_training, ai_workouts, and ai_activity packages" in readme.lower()


def test_current_docs_describe_three_high_level_coaching_roles():
    readme = " ".join(_read(README_PATH).lower().split())
    training = " ".join(_read(TRAINING_PATH).lower().split())
    for phrase in (
        "three high-level coaching roles",
        "get_training_context",
        "analyze_activity",
        "create_workout",
        "context eyes",
        "completed-session feedback",
        "workout hands",
    ):
        assert phrase in readme
    assert "two high-level tools" not in readme
    assert "two flagship tools" not in training
