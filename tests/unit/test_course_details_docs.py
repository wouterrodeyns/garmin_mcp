"""Documentation contract tests for the opt-in course-details read."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
GUIDE_PATH = ROOT / "docs" / "course-details.md"
README_PATH = ROOT / "README.md"
SETUP_PATH = ROOT / "docs" / "setup.md"

TOP_LEVEL_KEYS = ["status", "error", "course", "warnings"]
COURSE_KEYS = [
    "course_id",
    "name",
    "activity",
    "distance_m",
    "elevation_gain_m",
    "elevation_loss_m",
]
ERROR_CODES = {
    "invalid_course_id",
    "client_unavailable",
    "course_unavailable",
    "course_not_found",
    "invalid_course_response",
}
WARNING_CODES = {
    "course_name_unavailable",
    "activity_type_unavailable",
    "invalid_course_metric",
}
ACTIVITY_MAPPINGS = {
    "1 running",
    "2 cycling",
    "3 hiking",
    "4 gravel_cycling",
    "5 mountain_biking",
    "6 trail_running",
    "9 walking",
    "10 road_biking",
}


def _guide() -> str:
    assert GUIDE_PATH.is_file(), "missing course-details guide"
    return GUIDE_PATH.read_text()


def _section(markdown: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^## |\Z)",
        markdown,
        re.MULTILINE,
    )
    assert match is not None, f"missing section: {heading}"
    return match.group(1)


def test_course_details_guide_exists_and_names_signature() -> None:
    guide = _guide()
    normalized = " ".join(guide.lower().split())

    for phrase in (
        "get_course_details(course_id)",
        "get /course-service/course/{id}",
        "read-only",
        "exactly one",
        "explicit read",
        "question about a known",
        "outside the default ai-coach profile",
    ):
        assert phrase in normalized


def test_guide_documents_exact_schema_and_all_fixed_codes() -> None:
    guide = _guide()
    blocks = re.findall(r"^```json\s*\n(.*?)^```\s*$", guide, re.MULTILINE | re.DOTALL)
    assert blocks, "the guide needs parseable JSON examples"

    examples = [json.loads(block) for block in blocks]
    assert examples
    for example in examples:
        assert list(example) == TOP_LEVEL_KEYS
        assert example["status"] in {"success", "partial_success", "error"}
        assert isinstance(example["warnings"], list)
        if example["course"] is not None:
            assert list(example["course"]) == COURSE_KEYS

    for code in ERROR_CODES | WARNING_CODES:
        assert f"`{code}`" in guide

    assert "course_name_unavailable" in guide
    assert "activity_type_unavailable" in guide
    assert "invalid_course_metric" in guide


def test_guide_documents_input_bounds_and_activity_mapping() -> None:
    normalized = " ".join(_guide().lower().split())

    for phrase in (
        "positive integer",
        "ascii decimal string",
        "64 characters",
        "9007199254740991",
        "finite non-negative",
        "within the ieee-754 binary64 finite range",
        "1.7976931348623157e+308",
        "256 characters",
        "partial_success",
        "warnings",
    ):
        assert phrase in normalized

    for mapping in ACTIVITY_MAPPINGS:
        assert mapping in normalized


def test_guide_documents_geometry_and_privacy_exclusions() -> None:
    normalized = " ".join(_guide().lower().split())

    for phrase in (
        "coursepoints",
        "geopoints",
        "courselines",
        "ignored rather than parsed",
        "coordinates",
        "owner",
        "profile",
        "group",
        "urls",
        "notes",
        "raw payload",
        "exception text",
        "gpx",
        "export",
        "does not make a garmin write",
    ):
        assert phrase in normalized


def test_guide_links_are_opt_in_without_changing_ai_coach_profile() -> None:
    readme = _section(README_PATH.read_text(), "Documentation and development")
    setup = _section(SETUP_PATH.read_text(), "Runtime configuration and tool filtering")

    assert "docs/course-details.md" in readme
    assert "course-details.md" in setup
    assert "garmin_tool_profile=upstream-full" in setup.lower()
    assert "garmin_enabled_tools=get_course_details" in setup.lower()

    readme_profile = _section(README_PATH.read_text(), "AI-coach tool profile")
    assert "exactly 17 tools" in readme_profile.lower()
    assert "get_course_details" not in readme_profile

    setup_profile = re.search(
        r"The `ai-coach` profile exposes exactly 17 tools:\s*\n\n(.*?)\n\nOther runtime variables",
        setup,
        re.DOTALL,
    )
    assert setup_profile is not None
    assert "get_course_details" not in setup_profile.group(1)
