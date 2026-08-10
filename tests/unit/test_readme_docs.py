from pathlib import Path
import re


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
            r"^```(?:json|toml)\n(.*?)^```$", markdown, re.MULTILINE | re.DOTALL
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


def test_file_secret_guidance_is_deployment_only():
    setup = _setup()
    docker = _section(setup, "Docker and non-interactive deployments")
    claude = _section(setup, "Claude Desktop")
    assert "GARMIN_EMAIL_FILE" in docker
    assert "GARMIN_PASSWORD_FILE" in docker
    assert "not Claude Desktop configuration" in docker
    assert "GARMIN_EMAIL_FILE" not in claude
    assert "GARMIN_PASSWORD_FILE" not in claude


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
