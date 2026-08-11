from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
WORKFLOW_DOCS = ROOT / ".github" / "WORKFLOWS.md"


def test_ci_is_the_only_workflow() -> None:
    assert sorted(path.name for path in WORKFLOWS.glob("*.yml")) == ["ci.yml"]


def test_ci_pins_the_offline_safety_contract() -> None:
    workflow = CI.read_text()

    assert 'python-version: ["3.10", "3.13"]' in workflow
    assert workflow.count("uv sync --locked --all-extras --dev") == 2
    assert 'uv run pytest -m "not e2e"' in workflow
    assert "uv lock --check" in workflow
    assert "uv build" in workflow
    assert "contents: read" in workflow
    assert "timeout-minutes:" in workflow
    assert "||" not in workflow
    assert "coverage" not in workflow.lower()
    assert "vulnerabil" not in workflow.lower()


def test_workflow_documentation_matches_ci() -> None:
    docs = WORKFLOW_DOCS.read_text()

    assert "one GitHub Actions workflow" in docs
    assert 'uv run pytest -m "not e2e"' in docs
    assert "Python 3.10 and 3.13" in docs
    assert "Garmin credentials" in docs
    assert "vulnerability scanner" in docs
