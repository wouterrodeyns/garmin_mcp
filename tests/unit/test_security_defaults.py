"""Regression tests for secure repository and runtime defaults."""

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]


def test_opencode_uses_the_ai_coach_tool_profile():
    config = json.loads((REPO_ROOT / "opencode.json").read_text())

    assert config["mcp"]["garmin"]["environment"] == {
        "GARMIN_TOOL_PROFILE": "ai-coach"
    }


def test_local_deployment_credentials_are_gitignored():
    for secret in ("secrets/garmin_email.txt", "secrets/garmin_password.txt"):
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", secret],
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, f"{secret} is not ignored"


def test_dockerignore_is_portable_and_preserves_docker_build_inputs():
    dockerignore = REPO_ROOT / ".dockerignore"
    gitignore = REPO_ROOT / ".gitignore"
    rules = dockerignore.read_text().splitlines()

    assert dockerignore.is_file()
    assert not dockerignore.is_symlink()
    for required_rule in (
        ".git",
        ".env",
        ".venv/",
        ".uv-cache/",
        ".worktrees/",
        "/secrets/",
        "__pycache__/",
        "*.py[cod]",
        "dist/",
        "build/",
        "*.log",
        ".DS_Store",
        "playground/",
        "scratch/",
        "tests/fixtures/captured/",
    ):
        assert required_rule in rules
    for build_input in ("src", "tests", "pyproject.toml", "README.md", "pytest.ini"):
        assert build_input not in rules
    assert "/secrets/" in gitignore.read_text().splitlines()


def test_stale_dxt_artifacts_are_absent():
    assert not (REPO_ROOT / "garmin-mcp.dxt").exists()
    assert not (REPO_ROOT / "dxt" / "manifest.json").exists()
    assert not (REPO_ROOT / "scripts" / "build_dxt.sh").exists()
