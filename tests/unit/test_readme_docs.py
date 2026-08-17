from pathlib import Path
import re

from garmin_mcp import TOOL_PROFILES


ROOT = Path(__file__).parents[2]
SETUP_PATH = ROOT / "docs" / "setup.md"
FORK_URL = "https://github.com/wouterrodeyns/garmin_mcp"
UPSTREAM_URL = "https://github.com/Taxuspt/garmin_mcp"


def _setup() -> str:
    return SETUP_PATH.read_text() if SETUP_PATH.exists() else ""


def _section(markdown: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^## |\Z)",
        markdown,
        re.MULTILINE,
    )
    assert match is not None, f"missing section: {heading}"
    return match.group(1)


def _mcp_config_blocks(markdown: str) -> list[str]:
    return [
        block
        for block in re.findall(
            r"^[ \t]*```(?:json|toml)\n(.*?)^[ \t]*```$",
            markdown,
            re.MULTILINE | re.DOTALL,
        )
        if any(marker in block for marker in ('"mcpServers"', "[mcp_servers", '"mcp"'))
    ]


def test_setup_reference_has_required_sections_and_fork_sources():
    setup = _setup()
    for heading in (
        "Authentication first",
        "Claude Desktop",
        "Codex",
        "opencode",
        "Local development",
        "Runtime configuration and tool filtering",
        "Transport",
        "Docker and non-interactive deployments",
        "Garmin Connect China",
        "MFA and token recovery",
        "Tests",
        "Troubleshooting",
    ):
        assert f"## {heading}" in setup
    assert f"git+{FORK_URL}" in setup
    assert f"git clone {FORK_URL}.git" in setup
    assert UPSTREAM_URL not in setup
    assert 'uv run pytest -m "not e2e"' in setup
    assert "uv run pytest -m e2e" in setup


def test_current_runtime_docs_require_python_312_and_pinned_client():
    readme = _readme()
    setup = _setup()
    training = (ROOT / "docs" / "ai-training.md").read_text()
    workouts = (ROOT / "docs" / "ai-workouts.md").read_text()

    assert "Python 3.12+" in readme
    assert "Python 3.12+" in setup
    assert "garminconnect==0.3.10" in training
    assert "garminconnect==0.3.10" in workouts
    assert "Python 3.10+" not in readme
    assert "Python 3.10+" not in setup


def test_file_secret_guidance_is_deployment_only():
    setup = _setup()
    docker = _section(setup, "Docker and non-interactive deployments")
    claude = _section(setup, "Claude Desktop")
    assert "GARMIN_EMAIL_FILE" in docker
    assert "GARMIN_PASSWORD_FILE" in docker
    assert "not Claude Desktop configuration" in docker
    assert "GARMIN_EMAIL_FILE" not in claude
    assert "GARMIN_PASSWORD_FILE" not in claude


def test_setup_documents_fail_closed_http_and_docker_secret_defaults():
    setup = " ".join(_setup().lower().split())
    for expected in (
        "refuses non-loopback",
        "garmin_mcp_allow_unauthenticated_remote=true",
        "authenticating reverse proxy",
        "secrets/garmin_email.txt",
        "secrets/garmin_password.txt",
        "ignored by git",
        "excluded from the docker build context",
    ):
        assert expected in setup


def test_setup_transport_section_pins_fail_closed_remote_http_defaults():
    transport = " ".join(_section(_setup(), "Transport").lower().split()).replace(
        "`", ""
    )
    assert "streamable-http" in transport
    assert "sse" in transport
    assert "refuses non-loopback" in transport
    assert "garmin_mcp_allow_unauthenticated_remote=true" in transport
    assert "does not add auth" in transport
    assert "only behind an authenticating reverse proxy" in transport
    assert "0.0.0.0 requires the same explicit override" in transport


def test_setup_client_config_fences_are_credential_free():
    forbidden_patterns = (
        r"\bGARMIN_(?:EMAIL|PASSWORD)(?:_FILE)?\b",
        r"\bMFA(?:_CODE)?\b",
        r"\b(?:GARMIN_)?(?:ACCESS_)?TOKEN\b",
        r"\bYOUR_GARMIN\b",
        r"\bYOUR@EMAIL\b",
    )
    blocks = _mcp_config_blocks(_setup())
    assert blocks
    for block in blocks:
        assert not any(
            re.search(pattern, block, re.IGNORECASE)
            for pattern in forbidden_patterns
        )


README_PATH = ROOT / "README.md"
PROFILE_TOOLS = {
    "get_training_context",
    "get_sleep_trend",
    "get_wellness_heart_rate",
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


def _readme() -> str:
    return README_PATH.read_text()


def test_readme_is_ai_coach_first_and_credits_upstream_once():
    readme = _readme()
    assert readme.startswith("# Garmin MCP for AI Coaching")
    for expected in (
        "purpose-built Garmin MCP for AI coaching and workout creation",
        "get_training_context",
        "analyze_activity",
        "create_workout",
        "docs/ai-training.md",
        "docs/ai-activity.md",
        "docs/ai-workouts.md",
        FORK_URL,
        "python-garminconnect",
    ):
        assert expected in readme
    assert f"fork of [Taxuspt's Garmin MCP]({UPSTREAM_URL})" in readme
    assert readme.count(UPSTREAM_URL) == 1


def test_readme_profile_and_filter_contract():
    profile = _section(_readme(), "AI-coach tool profile")
    profile_normalized = " ".join(profile.lower().split()).replace("`", "")
    tools = re.findall(r"^`([^`]+)`$", profile, re.MULTILINE)
    assert set(tools) == PROFILE_TOOLS
    assert PROFILE_TOOLS == TOOL_PROFILES["ai-coach"]
    assert tools.index("update_workout") == tools.index("create_workout") + 1
    assert "garmin_tool_profile=ai-coach" in profile_normalized
    assert (
        "ai-coach is the default profile when garmin_tool_profile is unset or empty"
        in profile_normalized
    )
    assert "garmin_tool_profile=upstream-full" in profile_normalized
    assert "full upstream tool registration is an explicit choice" in profile_normalized
    assert profile_normalized.index("garmin_enabled_tools") < profile_normalized.index(
        "garmin_disabled_tools"
    )
    assert profile_normalized.index("garmin_disabled_tools") < profile_normalized.index(
        "selected or default profile"
    )
    assert profile_normalized.index(
        "garmin_tool_profile=upstream-full"
    ) < profile_normalized.index("all tools exposed by the upstream-compatible server")
    assert (
        "selected profile and denylist are both ignored while the explicit allowlist is active"
        in profile_normalized
    )
    for stale in ("no profile", "broad default"):
        assert stale not in profile_normalized
    assert not re.search(
        r"[^.]*?(?:no profile|profile is unset|garmin_tool_profile is unset)"
        r"[^.]*?(?:broad|full upstream)",
        profile_normalized,
    )


def test_setup_runtime_section_pins_profile_defaults_full_opt_in_and_precedence():
    runtime = " ".join(
        _section(_setup(), "Runtime configuration and tool filtering").lower().split()
    ).replace("`", "")
    assert (
        "ai-coach is the default profile when garmin_tool_profile is unset or empty"
        in runtime
    )
    assert "garmin_tool_profile=upstream-full" in runtime
    assert "full upstream tool registration is an explicit choice" in runtime
    assert runtime.index("garmin_enabled_tools") < runtime.index(
        "garmin_disabled_tools"
    )
    assert runtime.index("garmin_disabled_tools") < runtime.index(
        "selected or default profile"
    )
    assert runtime.index("garmin_tool_profile=upstream-full") < runtime.index(
        "all tools exposed by the upstream-compatible server"
    )
    assert (
        "selected profile and denylist are both ignored while the explicit allowlist is active"
        in runtime
    )
    for stale in ("no profile", "broad default"):
        assert stale not in runtime
    assert not re.search(
        r"[^.]*?(?:no profile|profile is unset|garmin_tool_profile is unset)"
        r"[^.]*?(?:broad|full upstream)",
        runtime,
    )


def test_readme_pins_sixteen_tools_and_in_place_update_semantics():
    lower = " ".join(_readme().lower().split())
    for expected in (
        "16-tool surface",
        "update_workout",
        "in-place",
        "preserves",
        "existing schedules",
        "workout_id",
        "scheduled_workout_id",
        "read the workout before retrying",
    ):
        assert expected in lower

    setup = " ".join(_setup().lower().split())
    assert (
        "selected profile and denylist are both ignored while the explicit allowlist is active"
        in setup
    )


def test_setup_doc_describes_create_and_update_as_workout_hands():
    setup = " ".join(_setup().lower().split())
    assert "create_workout" in setup
    assert "update_workout" in setup
    assert "workout creation is the coach's hands/write operation" not in setup
    assert "workout creation and in-place update" in setup


def test_readme_quick_start_uses_fork_preauth_and_secret_free_config():
    quick_start = _section(_readme(), "Claude Desktop quick start")
    normalized = " ".join(quick_start.split())
    assert "garmin-mcp-auth" in quick_start
    assert f"git+{FORK_URL}" in quick_start
    assert '"GARMIN_TOOL_PROFILE": "ai-coach"' in quick_start
    assert (
        "do not put garmin email addresses, passwords, mfa codes, or tokens"
        in normalized.lower()
    )
    blocks = _mcp_config_blocks(_readme())
    assert len(blocks) == 1
    for pattern in (
        r"\bGARMIN_(?:EMAIL|PASSWORD)(?:_FILE)?\b",
        r"\bMFA(?:_CODE)?\b",
        r"\b(?:GARMIN_)?(?:ACCESS_)?TOKEN\b",
    ):
        assert not re.search(pattern, blocks[0], re.IGNORECASE)


def test_readme_pins_snapshot_sync_and_confirmation_semantics():
    lower = " ".join(_readme().lower().split())
    for expected in (
        "not available in this snapshot",
        "does not prove that the account or device cannot support it",
        "structured warnings",
        "actual metric dates",
        "unsynced",
        "stale",
        "confirmation",
    ):
        assert expected in lower
    assert 'schedule_date="YYYY-MM-DD"' in _readme()


def test_readme_removes_stale_dxt_raw_and_volatile_claims():
    lower = _readme().lower()
    for forbidden in (
        "mseep",
        "one-click install",
        "garmin-mcp.dxt",
        "download the latest",
        "create_walk_run_workout",
        "create_z2_walk_workout",
        "create_strength_workout",
        "schedule_week",
        "raw `upload_workout`",
        "reinstalling from local path",
        "110+",
        "~90%",
        "90% coverage",
        "140 tools",
        "all tests are currently passing",
        "100%",
    ):
        assert forbidden not in lower
    assert "fork-specific desktop extension is not published yet" in lower
    assert "desktop extension bundle" not in lower
    assert "desktop extension install" not in lower


def test_cross_document_install_sources_and_client_config_fences_are_safe():
    markdown = _readme() + "\n" + _setup()
    assert f"git+{UPSTREAM_URL}" not in markdown
    assert f"{UPSTREAM_URL}/releases" not in markdown
    for source in re.findall(r"git\+https://github\.com/[^\s\"']+", markdown):
        assert source.startswith(f"git+{FORK_URL}")
    blocks = _mcp_config_blocks(markdown)
    assert blocks
    forbidden_patterns = (
        r"\bGARMIN_(?:EMAIL|PASSWORD)(?:_FILE)?\b",
        r"\bMFA(?:_CODE)?\b",
        r"\b(?:GARMIN_)?(?:ACCESS_)?TOKEN\b",
        r"\bYOUR_GARMIN\b",
        r"\bYOUR@EMAIL\b",
    )
    for block in blocks:
        assert not any(
            re.search(pattern, block, re.IGNORECASE)
            for pattern in forbidden_patterns
        )


def test_readme_is_concise_and_links_to_tracked_detail():
    readme = _readme()
    assert 150 <= len(readme.splitlines()) <= 220
    for target in (
        "docs/ai-training.md",
        "docs/ai-activity.md",
        "docs/ai-workouts.md",
        "docs/setup.md",
    ):
        assert f"]({target})" in readme
        assert (ROOT / target).is_file()
