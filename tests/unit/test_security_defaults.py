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


def test_dockerignore_reuses_gitignore_and_excludes_secrets():
    dockerignore = REPO_ROOT / ".dockerignore"
    gitignore = REPO_ROOT / ".gitignore"

    assert dockerignore.is_symlink()
    assert dockerignore.resolve() == gitignore.resolve()
    assert "/secrets/" in gitignore.read_text().splitlines()


def test_stale_dxt_artifacts_are_absent():
    assert not (REPO_ROOT / "garmin-mcp.dxt").exists()
    assert not (REPO_ROOT / "dxt" / "manifest.json").exists()
