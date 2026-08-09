from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
README = (ROOT / "README.md").read_text()
DOCS_PATH = ROOT / "docs/ai-workouts.md"
DOCS = DOCS_PATH.read_text() if DOCS_PATH.exists() else ""


def _normalize_heading(value: str) -> str:
    value = re.sub(r"[`*_]", "", value).lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _markdown_sections(markdown: str) -> dict[str, str]:
    headings = list(re.finditer(r"^#{1,6}\s+(.+?)\s*$", markdown, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        sections[_normalize_heading(heading.group(1))] = markdown[heading.end() : end]
    return sections


def _numbered_items(section: str) -> list[str]:
    items = re.findall(
        r"^\d+\.\s+(.+?)(?=^\d+\.\s+|\Z)", section, re.MULTILINE | re.DOTALL
    )
    return [re.sub(r"\s+", " ", item).strip().lower() for item in items]


SECTIONS = _markdown_sections(DOCS)


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
    create = SECTIONS["create one workout"]
    for expected in (
        '"name"',
        '"sport"',
        '"schedule_date"',
        '"repeat"',
        '"pace"',
        "strength_training",
    ):
        assert expected in create
    assert "partial_success" in SECTIONS["what the call does"]
    assert "garminconnect==0.3.2" in SECTIONS["pinned api assumptions"]


def test_ai_workouts_docs_protects_schema_cardinality_and_strength_limitations():
    create = SECTIONS["create one workout"]
    create_lower = create.lower()
    assert "every action has exactly one end condition" in create_lower
    assert "at most one target field per action" in create_lower
    for expected in ("strength", "exercise", "category", "pass-through", "free-form names"):
        assert expected in create_lower


def test_ai_workouts_docs_protects_complete_friendly_vocabularies_and_constraints():
    create = SECTIONS["create one workout"]
    sports = re.search(r"Supported sports are (.+?)\.", create, re.DOTALL)
    assert sports is not None
    assert set(re.findall(r"`([^`]+)`", sports.group(1))) == {
        "running",
        "cycling",
        "walking",
        "strength",
    }
    assert re.search(r"`strength_training`\s+is accepted as a compatibility alias", create)

    actions = re.search(r"Actions are (.+?)\. A repeat group", create, re.DOTALL)
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

    assert set(re.findall(r"^- `([^`]+)`:", create, re.MULTILINE)) == {
        "duration",
        "distance",
        "reps",
        "lap_button",
    }

    target_vocab = {
        "pace",
        "heart_rate_zone",
        "heart_rate",
        "power_zone",
        "power",
    }
    target_fields = set(re.findall(r'`"([^"`]+)":', create)) & target_vocab
    assert target_fields == target_vocab
    target_lower = create.lower()
    assert "pace" in create and re.search(r"running\s+only", target_lower)
    assert "heart-rate" in create and "any sport" in target_lower
    assert "power" in create and re.search(r"cycling\s+only", target_lower)


def test_ai_workouts_docs_names_package_seam_and_unchanged_compatibility():
    compatibility = SECTIONS["upstream compatibility"].lower()
    for expected in (
        "ai_workouts",
        "minimal workouts seam",
        "authentication",
        "default registration",
        "unchanged",
    ):
        assert expected in compatibility


def test_ai_workouts_docs_protects_safe_create_flow_order():
    steps = _numbered_items(SECTIONS["what the call does"])
    assert len(steps) == 5
    assert "validate" in steps[0] and "normalize" in steps[0]
    assert "compile" in steps[1]
    assert all(
        expected in steps[2]
        for expected in (
            "prepare_workout_for_upload",
            "taxuspt",
            "normalization",
            "validation",
        )
    )
    assert "upload" in steps[3]
    assert "schedule" in steps[4]


def test_ai_workouts_docs_protects_all_statuses_and_retention_safety():
    call = SECTIONS["what the call does"]
    for expected in (
        '"status": "success"',
        '"status": "error"',
        '"status": "partial_success"',
    ):
        assert expected in call
    call_lower = call.lower()
    assert "retains the" in call_lower
    assert "never auto-deletes" in call_lower
    assert "scheduling failure" in call_lower


def test_ai_workouts_docs_marks_deferred_operations_explicitly():
    assert {
        "update deferred",
        "move deferred",
        "training context deferred",
    } <= SECTIONS.keys()


def test_ai_workouts_docs_describes_profile_and_unchanged_default():
    profile = SECTIONS["the ai coach tool profile"]
    tools = re.findall(r"^\d+\. `([^`]+)`$", profile, re.MULTILINE)
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
    assert "full upstream tool registration" in profile

    precedence = profile.lower()
    assert precedence.index("explicitly configured") < precedence.index("subtracts")
    assert precedence.index("subtracts") < precedence.index("profile unset")
    for hidden in ("upload_workout", "upload_workouts"):
        assert hidden in precedence
    assert "unrelated" in precedence


def test_ai_workouts_docs_protects_pinned_ids_and_missing_update_api():
    pinned = SECTIONS["pinned api assumptions"].lower()
    for expected in (
        "garminconnect==0.3.2",
        "no update method",
        "workout_id",
        "scheduled_workout_id",
        "distinct",
    ):
        assert expected in pinned


def test_ai_workouts_docs_protects_deferred_operation_contracts():
    update = SECTIONS["update deferred"].lower()
    for expected in ("whole-document", "put", "preserves", "workout id", "schedules"):
        assert expected in update

    move = SECTIONS["move deferred"].lower()
    for expected in (
        "scheduled_workout_id",
        "unschedule",
        "schedule",
        "same `workout_id`",
        "partial",
        "failure",
    ):
        assert expected in move
    assert "never" in move and "delete" in move and "template" in move

    context = SECTIONS["training context deferred"].lower()
    for expected in ("aggregator", "activities", "scheduled workouts", "readiness"):
        assert expected in context
