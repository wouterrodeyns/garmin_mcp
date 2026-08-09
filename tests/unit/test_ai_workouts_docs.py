from pathlib import Path


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


def test_ai_workouts_docs_covers_threshold_schema_and_partial_success():
    for expected in (
        '"name"',
        '"sport"',
        '"schedule_date"',
        '"repeat"',
        '"pace"',
        "partial_success",
        "garminconnect==0.3.2",
    ):
        assert expected in DOCS


def test_ai_workouts_docs_marks_deferred_operations_explicitly():
    for expected in (
        "## Update (deferred)",
        "## Move (deferred)",
        "## Training context (deferred)",
    ):
        assert expected in DOCS


def test_ai_workouts_docs_describes_profile_and_unchanged_default():
    assert "full upstream tool registration" in DOCS
    assert "create_workout" in DOCS
    assert "get_activities" in DOCS
    assert "get_activities_by_date" in DOCS
    assert "get_activity" in DOCS
    assert "get_workouts" in DOCS
    assert "get_workout_by_id" in DOCS
    assert "get_scheduled_workouts" in DOCS
    assert "schedule_workout" in DOCS
    assert "unschedule_workout" in DOCS
    assert "delete_workout" in DOCS
    for hidden in ("upload_workout", "upload_workouts"):
        assert hidden in DOCS
