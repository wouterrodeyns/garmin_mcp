from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
README = (ROOT / "README.md").read_text()
DOCS_PATH = ROOT / "docs/ai-workouts.md"
DOCS = DOCS_PATH.read_text() if DOCS_PATH.exists() else ""


def test_readme_points_ai_coaches_to_the_workout_docs_and_profile():
    for expected in (
        "GARMIN_TOOL_PROFILE",
        "ai-coach",
        "create_workout",
        "docs/ai-workouts.md",
    ):
        assert expected in README


def test_readme_guarantees_unset_profile_keeps_full_default_registration():
    readme = README.lower()
    assert "garmin_tool_profile" in readme
    assert "unset" in readme
    assert "full upstream tool registration" in readme
    assert "all tools" in readme or "full upstream tools" in readme


def test_ai_workouts_docs_covers_threshold_schema_and_partial_success():
    for expected in (
        '"name"',
        '"sport"',
        '"schedule_date"',
        '"repeat"',
        '"pace"',
        "partial_success",
        "garminconnect==0.3.2",
        "strength_training",
    ):
        assert expected in DOCS


def test_ai_workouts_docs_protects_schema_cardinality_and_strength_limitations():
    assert "every action has exactly one end condition" in DOCS.lower()
    assert "at most one target field per action" in DOCS.lower()
    assert "strength" in DOCS
    assert "exercise" in DOCS
    assert "category" in DOCS
    assert "pass-through" in DOCS
    assert "free-form names" in DOCS


def test_ai_workouts_docs_protects_complete_friendly_vocabularies_and_constraints():
    sports = re.search(r"Supported sports are (.+?)\.", DOCS, re.DOTALL)
    assert sports is not None
    assert set(re.findall(r"`([^`]+)`", sports.group(1))) == {
        "running",
        "cycling",
        "walking",
        "strength",
    }
    assert "`strength_training` is accepted as a compatibility alias" in DOCS

    actions = re.search(r"Actions are (.+?)\. A repeat group", DOCS, re.DOTALL)
    assert actions is not None
    assert set(re.findall(r"`([^`]+)`", actions.group(1))) == {
        "warmup",
        "cooldown",
        "work",
        "run",
        "interval",
        "recovery",
        "rest",
    }

    end_section = DOCS.split("Every action has exactly one end condition:", 1)[1].split(
        "Targets are optional", 1
    )[0]
    assert set(re.findall(r"^- `([^`]+)`:", end_section, re.MULTILINE)) == {
        "duration",
        "distance",
        "reps",
        "lap_button",
    }

    target_section = DOCS.split("Targets are optional", 1)[1].split(
        "For example", 1
    )[0]
    target_fields = set(re.findall(r'`"([^"`]+)":', target_section))
    assert target_fields == {
        "pace",
        "heart_rate_zone",
        "heart_rate",
        "power_zone",
        "power",
    }
    target_lower = target_section.lower()
    assert "pace" in target_section and re.search(r"running\s+only", target_lower)
    assert "heart-rate" in target_section and "any sport" in target_lower
    assert "power" in target_section and re.search(r"cycling\s+only", target_lower)


def test_ai_workouts_docs_names_package_seam_and_unchanged_compatibility():
    compatibility = DOCS.split("## Upstream compatibility", 1)[1]
    assert "ai_workouts" in compatibility
    assert "minimal workouts seam" in compatibility
    assert "authentication" in compatibility
    assert "default registration" in compatibility
    assert "unchanged" in compatibility


def test_ai_workouts_docs_protects_safe_create_flow_order():
    flow = DOCS.lower()
    terms = (
        "validate and normalize",
        "compile the normalized",
        "prepare_workout_for_upload",
        "taxuspt normalization",
        "validation seam",
        "upload with garmin connect",
        "optionally schedule",
    )
    positions = [flow.index(term) for term in terms]
    assert positions == sorted(positions)


def test_ai_workouts_docs_protects_all_statuses_and_retention_safety():
    for expected in (
        '"status": "success"',
        '"status": "error"',
        '"status": "partial_success"',
    ):
        assert expected in DOCS
    assert "retains the" in DOCS
    assert "never auto-deletes" in DOCS
    assert "scheduling failure" in DOCS


def test_ai_workouts_docs_marks_deferred_operations_explicitly():
    for expected in (
        "## Update (deferred)",
        "## Move (deferred)",
        "## Training context (deferred)",
    ):
        assert expected in DOCS


def test_ai_workouts_docs_describes_profile_and_unchanged_default():
    profile_section = DOCS.split("## The `ai-coach` tool profile", 1)[1].split(
        "Profile precedence", 1
    )[0]
    tools = re.findall(r"^\d+\. `([^`]+)`$", profile_section, re.MULTILINE)
    expected = {
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
    assert len(tools) == 10
    assert set(tools) == expected
    assert "full upstream tool registration" in DOCS

    precedence = DOCS.lower().split("profile precedence", 1)[1]
    assert precedence.index("explicitly configured") < precedence.index("subtracts")
    assert precedence.index("subtracts") < precedence.index("profile unset")
    for hidden in ("upload_workout", "upload_workouts"):
        assert hidden in DOCS
    assert "unrelated" in DOCS


def test_ai_workouts_docs_protects_pinned_ids_and_missing_update_api():
    pinned = DOCS.lower().split("## pinned api assumptions", 1)[1]
    assert "garminconnect==0.3.2" in pinned
    assert "no update method" in pinned
    assert "workout_id" in pinned
    assert "scheduled_workout_id" in pinned
    assert "distinct" in pinned


def test_ai_workouts_docs_protects_deferred_operation_contracts():
    update = DOCS.split("## Update (deferred)", 1)[1].split(
        "## Move (deferred)", 1
    )[0].lower()
    assert "whole-document" in update
    assert "put" in update
    assert "preserves" in update
    assert "workout id" in update
    assert "schedules" in update

    move = DOCS.split("## Move (deferred)", 1)[1].split(
        "## Training context (deferred)", 1
    )[0].lower()
    assert "scheduled_workout_id" in move
    assert "unschedule" in move
    assert "schedule" in move
    assert "same `workout_id`" in move
    assert "never" in move and "delete" in move and "template" in move
    assert "partial" in move and "failure" in move

    context = DOCS.split("## Training context (deferred)", 1)[1].split(
        "## Upstream compatibility", 1
    )[0].lower()
    assert "aggregator" in context
    assert "activities" in context
    assert "scheduled workouts" in context
    assert "readiness" in context
