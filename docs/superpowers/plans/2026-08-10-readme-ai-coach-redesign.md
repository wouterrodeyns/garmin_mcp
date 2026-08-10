# AI-Coach README Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the upstream-centric README with a concise, secure AI-coach landing page, move detailed setup/deployment guidance into `docs/setup.md`, and protect both documents with offline tests.

**Architecture:** `README.md` is a 150–220-line product landing page centered on `get_training_context` (eyes) and `create_workout` (hands), with one credential-free Claude Desktop quick start. `docs/setup.md` owns detailed client, development, transport, Docker, Garmin China, MFA/recovery, testing, and troubleshooting detail. Deterministic text tests pin the fork’s branding, security boundaries, profile membership, missing-data semantics, and removal of stale content.

**Tech Stack:** Markdown, Python 3.10+, pytest, uv.

---

## File Structure

| File | Responsibility |
|---|---|
| `.gitignore` | Preserve `docs/*` ignore policy but explicitly allow the tracked setup reference. |
| `docs/setup.md` | Secure, fork-branded operational reference; not a second landing page. |
| `README.md` | Concise AI-coach-first public landing page. |
| `tests/unit/test_readme_docs.py` | Local text contract for README/setup content and security. |
| `tests/unit/test_ai_workouts_docs.py` | Existing dedicated workout-doc contract; update only obsolete README-facing wording if needed. |

No task changes runtime source, authentication, MCP registration, Docker files, DXT manifest/artifact, release configuration, or `docs/ai-training.md` / `docs/ai-workouts.md`.

### Task 1: Allow the tracked setup reference without changing documentation behavior

**Files:**

- Modify: `.gitignore`

- [ ] **Step 1: Add the one tracked-document exception**

Add the following directly after `docs/*` in `.gitignore`:

```gitignore
!docs/setup.md
```

The exact surrounding block becomes:

```gitignore
docs/*
!docs/setup.md
!docs/superpowers/
docs/superpowers/*
```

- [ ] **Step 2: Verify the exception does not unignore arbitrary docs**

Run each command separately:

```bash
git check-ignore -q docs/setup.md
git check-ignore -q docs/temporary-note.md
```

Expected: the first exits `1`; the second exits `0`. Do not create `docs/temporary-note.md`.

- [ ] **Step 3: Commit the green ignore-only change**

```bash
git add .gitignore
git commit --no-gpg-sign -m "docs: allow tracked setup reference"
```

Expected: this task has no pytest change and the `.gitignore` policy check is green.

### Task 2: Create the secure detailed setup reference and finish green

**Files:**

- Create: `docs/setup.md`
- Test: `tests/unit/test_readme_docs.py`

- [ ] **Step 1: Write and run the setup-only red test before documentation**

Create `tests/unit/test_readme_docs.py` with this complete module:

```python
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
        for block in re.findall(r"^```(?:json|toml)\n(.*?)^```$", markdown, re.MULTILINE | re.DOTALL)
        if any(marker in block for marker in ('"mcpServers"', "[mcp_servers", '"mcp"'))
    ]


def test_setup_reference_has_required_sections_and_fork_sources():
    setup = _setup()
    for heading in (
        "Authentication first", "Claude Desktop", "Codex", "opencode",
        "Local development", "Runtime configuration and tool filtering",
        "Transport", "Docker and non-interactive deployments",
        "Garmin Connect China", "MFA and token recovery", "Tests",
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
```

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/test_readme_docs.py -q
```

Expected: FAIL at `SETUP_PATH.exists()` / missing required heading.

- [ ] **Step 2: Create `docs/setup.md` using these exact headings and concrete copy**

Create a reference document with the following actual content requirements; preserve useful operational details from the prior README under the indicated heading, while changing every end-user clone and `uvx --from` source to the fork URL.

```markdown
# Garmin MCP setup reference

This reference covers [Garmin MCP for AI Coaching](../README.md) installation, client configuration, deployment, authentication, and troubleshooting. Start with the README for product orientation.

## Authentication first

Install `uv`, then authenticate in a terminal before launching an MCP client:

```bash
uvx --python 3.12 --from git+https://github.com/wouterrodeyns/garmin_mcp garmin-mcp-auth
```

The interactive command stores local Garmin tokens. Garmin email addresses, passwords, MFA codes, and tokens do not belong in an MCP client configuration.

## Claude Desktop

State the macOS path `~/Library/Application Support/Claude/claude_desktop_config.json` and Windows path `%APPDATA%\Claude\claude_desktop_config.json`. Include exactly one credential-free JSON block with this server entry:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": ["--python", "3.12", "--from", "git+https://github.com/wouterrodeyns/garmin_mcp", "garmin-mcp"],
      "env": {"GARMIN_TOOL_PROFILE": "ai-coach"}
    }
  }
}
```

Then state that the local checkout alternative is `uv --directory /absolute/path/to/garmin_mcp run garmin-mcp`.

## Codex

After token pre-authentication, include this credential-free TOML entry, then state that a local checkout can use `uv run garmin-mcp` instead:

```toml
[mcp_servers.garmin]
command = "uvx"
args = ["--python", "3.12", "--from", "git+https://github.com/wouterrodeyns/garmin_mcp", "garmin-mcp"]

[mcp_servers.garmin.env]
GARMIN_TOOL_PROFILE = "ai-coach"
```

## opencode

State that the tracked `opencode.json` supports development from a clone. Include this credential-free global configuration and retain only the public `https://opencode.ai/config.json` schema URL:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "garmin": {
      "command": ["uvx", "--python", "3.12", "--from", "git+https://github.com/wouterrodeyns/garmin_mcp", "garmin-mcp"],
      "environment": {"GARMIN_TOOL_PROFILE": "ai-coach"}
    }
  }
}
```

## Local development

```bash
git clone https://github.com/wouterrodeyns/garmin_mcp.git
cd garmin_mcp
uv sync
uv run garmin-mcp-auth
uv run garmin-mcp
```

State Python 3.10+ support and that hosted install examples use Python 3.12. Include the existing MCP Inspector command if it remains accurate.

## Runtime configuration and tool filtering

Document `GARMIN_TOOL_PROFILE=ai-coach`, `GARMIN_ENABLED_TOOLS`, and `GARMIN_DISABLED_TOOLS` in this order: explicit allowlist wins; denylist subtracts from the selected set; otherwise profile selection applies; when the profile is unset the broad upstream-compatible registration remains. Link to `ai-training.md` and `ai-workouts.md`.

## Transport

State that `stdio` is the local-client default. List `GARMIN_MCP_TRANSPORT` (`stdio`, `streamable-http`, or `sse`), `GARMIN_MCP_HOST` (default `127.0.0.1`), and `GARMIN_MCP_PORT` (default `8000`). Include `GARMIN_MCP_TRANSPORT=streamable-http garmin-mcp`, the `/mcp` client path, and `GET /healthz`. State that `0.0.0.0` requires an authenticating reverse proxy because the server has no HTTP authentication.

## Docker and non-interactive deployments

Migrate useful Compose, direct Docker, persistent-token-volume, and file-secret details. `GARMIN_EMAIL_FILE` and `GARMIN_PASSWORD_FILE` may appear only here. State verbatim that these are for non-interactive deployments, require appropriate secret management, and are not Claude Desktop configuration. Prefer persisted tokens after interactive authentication where practical.

## Garmin Connect China

Document `GARMIN_IS_CN=true`, `garmin-mcp-auth --is-cn`, and a credential-free client configuration using the fork URL.

## MFA and token recovery

Explain that desktop MCP servers are non-interactive. Direct users to run `garmin-mcp-auth` in a terminal for MFA, verification, re-authentication, or a custom token location; never show a literal MFA code. Tell users to restart the MCP client after recovery.

## Tests

```bash
uv run pytest -m "not e2e"
uv run pytest -m e2e
```

State live E2E requires a real Garmin account and is separate. Do not state any passing-test count or percentage.

## Troubleshooting

Keep concise guidance for a missing `uvx` PATH, first-download latency, expired tokens, Claude logs, and client restart. Direct desktop users back to `garmin-mcp-auth`, never credentials in client config.
```

Do not include Taxuspt URLs in this document. Docker secrets are allowed only in the Docker section, never in a Claude, Codex, or opencode configuration fence.

- [ ] **Step 3: Run the Task 1 tests to verify green**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/test_readme_docs.py -q
```

Expected: PASS. Task 2 is complete only when its own tests are green.

- [ ] **Step 4: Commit the setup reference**

```bash
git add docs/setup.md tests/unit/test_readme_docs.py
git commit --no-gpg-sign -m "docs: add secure setup reference"
```

Expected: only `docs/setup.md` changes in this commit.

### Task 3: Add the README/cross-document contract, rewrite the README, and finish green

**Files:**

- Modify: `README.md`
- Modify: `tests/unit/test_readme_docs.py`
- Modify only if needed: `tests/unit/test_ai_workouts_docs.py`

- [ ] **Step 1: Add README and cross-document tests after setup is green**

Append the following to `tests/unit/test_readme_docs.py`:

```python
README_PATH = ROOT / "README.md"
PROFILE_TOOLS = {
    "get_training_context",
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
CLIENT_SECRET_PATTERNS = (
    r"\bGARMIN_(?:EMAIL|PASSWORD)(?:_FILE)?\b",
    r"\bMFA(?:_CODE)?\b",
    r"\b(?:GARMIN_)?(?:ACCESS_)?TOKEN\b",
    r"\bYOUR_GARMIN\b",
    r"\bYOUR@EMAIL\b",
)


def _readme() -> str:
    return README_PATH.read_text()


def _fenced_blocks(markdown: str) -> list[str]:
    return re.findall(r"^```[^\n]*\n(.*?)^```$", markdown, re.MULTILINE | re.DOTALL)


def _mcp_config_blocks(markdown: str) -> list[str]:
    return [
        block
        for block in _fenced_blocks(markdown)
        if any(marker in block for marker in ('"mcpServers"', "[mcp_servers", '"mcp"'))
    ]


def test_readme_is_ai_coach_first_and_credits_upstream_once():
    readme = _readme()
    assert readme.startswith("# Garmin MCP for AI Coaching")
    for expected in (
        "purpose-built Garmin MCP for AI coaching and workout creation",
        "get_training_context",
        "create_workout",
        "docs/ai-training.md",
        "docs/ai-workouts.md",
        FORK_URL,
        "python-garminconnect",
    ):
        assert expected in readme
    assert f"fork of [Taxuspt's Garmin MCP]({UPSTREAM_URL})" in readme
    assert readme.count(UPSTREAM_URL) == 1


def test_readme_profile_and_filter_contract():
    profile = _section(_readme(), "AI-coach tool profile")
    assert set(re.findall(r"^`([^`]+)`$", profile, re.MULTILINE)) == PROFILE_TOOLS
    lower = _readme().lower()
    assert "garmin_tool_profile=ai-coach" in lower
    assert lower.index("garmin_enabled_tools") < lower.index("garmin_disabled_tools")
    assert lower.index("garmin_disabled_tools") < lower.index("profile is unset")
    assert "broad upstream-compatible registration remains available" in lower


def test_readme_quick_start_uses_fork_preauth_and_secret_free_config():
    quick_start = _section(_readme(), "Claude Desktop quick start")
    assert "garmin-mcp-auth" in quick_start
    assert f"git+{FORK_URL}" in quick_start
    assert '"GARMIN_TOOL_PROFILE": "ai-coach"' in quick_start
    assert "do not put Garmin email addresses, passwords, MFA codes, or tokens" in quick_start
    blocks = _mcp_config_blocks(_readme())
    assert len(blocks) == 1
    assert not any(
        re.search(pattern, blocks[0], re.IGNORECASE)
        for pattern in CLIENT_SECRET_PATTERNS
    )


def test_readme_pins_snapshot_sync_and_confirmation_semantics():
    lower = _readme().lower()
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


def test_cross_document_install_sources_and_client_config_fences_are_safe():
    markdown = _readme() + "\n" + _setup()
    assert f"git+{UPSTREAM_URL}" not in markdown
    assert f"{UPSTREAM_URL}/releases" not in markdown
    for source in re.findall(r"git\+https://github\.com/[^\s\"']+", markdown):
        assert source.startswith(f"git+{FORK_URL}")
    blocks = _mcp_config_blocks(markdown)
    assert blocks
    for block in blocks:
        assert not any(
            re.search(pattern, block, re.IGNORECASE)
            for pattern in CLIENT_SECRET_PATTERNS
        )


def test_readme_is_concise_and_links_to_tracked_detail():
    readme = _readme()
    assert 150 <= len(readme.splitlines()) <= 220
    for target in ("docs/ai-training.md", "docs/ai-workouts.md", "docs/setup.md"):
        assert f"]({target})" in readme
        assert (ROOT / target).is_file()
```

- [ ] **Step 2: Run the expanded contract to confirm red**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/test_readme_docs.py -q
```

Expected: setup tests stay PASS; new README/cross-document tests FAIL against the old README.

- [ ] **Step 3: Replace `README.md` with this concrete ordered content**

Write 150–220 physical lines with exactly these headings and contents:

```markdown
# Garmin MCP for AI Coaching

Purpose-built Garmin MCP for AI coaching and workout creation. This project is a fork of [Taxuspt's Garmin MCP](https://github.com/Taxuspt/garmin_mcp), keeps its maintained Garmin backend intentionally upstream-compatible, and is installed from [wouterrodeyns/garmin_mcp](https://github.com/wouterrodeyns/garmin_mcp). It uses the unofficial [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) client; Garmin data and metric availability vary by account, device, subscription, and sync state.

## Designed AI-coach workflow

Include this table:
| Tool | Purpose |
| --- | --- |
| [`get_training_context(days=14)`](docs/ai-training.md) | Compact, read-only factual context before coaching decisions. |
| [`create_workout(...)`](docs/ai-workouts.md) | Validate a readable schema, upload it, and optionally schedule one intentional workout write. |

Include exactly this workflow:
```text
User: Review my last 30 days and recommend today's run.
AI:   get_training_context(days=30) -> factual context -> conservative advice.

User: Put that workout on Garmin for tomorrow.
AI:   explain the proposed workout, request confirmation, then
      create_workout(..., schedule_date="YYYY-MM-DD") -> upload + schedule.
```

State: A `null` recovery or fitness metric means it was not available in this snapshot. It does not prove that the account or device cannot support it. Use structured warnings and actual metric dates; do not treat stale or unsynced Garmin data as current.

## Claude Desktop quick start

Number four steps: install uv; run `uvx --python 3.12 --from git+https://github.com/wouterrodeyns/garmin_mcp garmin-mcp-auth`; add this JSON; restart Claude Desktop:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": ["--python", "3.12", "--from", "git+https://github.com/wouterrodeyns/garmin_mcp", "garmin-mcp"],
      "env": {"GARMIN_TOOL_PROFILE": "ai-coach"}
    }
  }
}
```

State verbatim: Do not put Garmin email addresses, passwords, MFA codes, or tokens in Claude Desktop configuration. State that `garmin-mcp-auth` stores local tokens and link to `docs/setup.md`.

## AI-coach tool profile

Put each exact tool in a text fence on a separate backtick-quoted line:
`get_training_context`
`create_workout`
`get_activities`
`get_activities_by_date`
`get_activity`
`get_workouts`
`get_workout_by_id`
`get_scheduled_workouts`
`schedule_workout`
`unschedule_workout`
`delete_workout`

State reads are read-only and workout operations are deliberate writes. State `GARMIN_ENABLED_TOOLS` has precedence, `GARMIN_DISABLED_TOOLS` subtracts from the selected set, and when the explicit allowlist is absent and the profile is unset the broad upstream-compatible registration remains available.

## Documentation and development

Link `docs/ai-training.md`, `docs/ai-workouts.md`, and `docs/setup.md`. State Python 3.10+. Include:
```bash
git clone https://github.com/wouterrodeyns/garmin_mcp.git
cd garmin_mcp
uv sync
uv run pytest -m "not e2e"
```
State real-account E2E is separate and documented in setup.

## Compatibility, contributing, and license

State that fork-specific AI abstractions live in separate packages wrapping Taxuspt’s backend for practical future sync. Link fork issues, upstream context, and `LICENSE`. State: A fork-specific Desktop Extension is not published yet; use the token-based `uvx` quick start above.
```

Do not include an endpoint catalog, security badge, raw Garmin DTO or `upload_workout` tutorial, legacy builders, DXT download/build steps, Docker setup, fixed broad-tool/test count, coverage percentage, or a personal local path.

- [ ] **Step 4: Preserve existing AI-workout guide tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/test_ai_workouts_docs.py -q
```

Expected: PASS. Only if the old README wording test fails, make this minimal replacement in `tests/unit/test_ai_workouts_docs.py`:

```python
def test_readme_guarantees_unset_profile_keeps_full_default_registration():
    readme = README.lower()
    assert "garmin_tool_profile" in readme
    assert "profile is unset" in readme
    assert "broad upstream-compatible registration remains available" in readme
```

Do not change any test that parses `docs/ai-workouts.md`.

- [ ] **Step 5: Run all docs contracts and check README length**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest \
  tests/unit/test_readme_docs.py tests/unit/test_ai_workouts_docs.py -q
awk 'END { print NR }' README.md
rg -n -i '110\+|~90%|90% coverage|140 tools|all tests are currently passing|100%|one-click install|garmin-mcp\.dxt|create_walk_run_workout|create_z2_walk_workout|create_strength_workout|schedule_week|raw `upload_workout`|reinstalling from local path|git\+https://github\.com/Taxuspt/garmin_mcp' README.md
```

Expected: tests pass; line count is 150–220; `rg` prints no matches.

- [ ] **Step 6: Commit the green README implementation**

```bash
git add README.md tests/unit/test_readme_docs.py tests/unit/test_ai_workouts_docs.py
git commit --no-gpg-sign -m "docs: focus README on AI coaching"
```

Expected: stage the existing test file only if Step 4 changed it.

### Task 4: Full offline documentation verification

**Files:**

- Verify: `.gitignore`
- Verify: `README.md`
- Verify: `docs/setup.md`
- Verify: `tests/unit/test_readme_docs.py`
- Verify: `tests/unit/test_ai_workouts_docs.py`

- [ ] **Step 1: Run all documentation tests**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest \
  tests/unit/test_readme_docs.py tests/unit/test_ai_workouts_docs.py -q
```

Expected: PASS without network access, Garmin account, DXT build, or MCP process.

- [ ] **Step 2: Run the complete normal offline suite**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest -m "not e2e"
```

Expected: PASS. Do not run live E2E tests in this documentation-only PR.

- [ ] **Step 3: Inspect exact change scope**

```bash
git diff --check main...HEAD
git diff --name-only main...HEAD
git status --short
```

Expected: no whitespace error; only `.gitignore`, `README.md`, `docs/setup.md`, documentation tests, and tracked planning/spec files differ. No `src/`, `dxt/`, Docker, auth, or MCP registration file differs.

- [ ] **Step 4: Commit any final test-only correction**

```bash
git add tests/unit/test_readme_docs.py
git commit --no-gpg-sign -m "test(docs): guard fork setup contract"
```

Expected: execute only if Task 4 changed a test; otherwise skip rather than create an empty commit.

### Task 5: Two-stage review, push, and draft PR

**Files:**

- Review: `.gitignore`, `README.md`, `docs/setup.md`, `tests/unit/test_readme_docs.py`, `tests/unit/test_ai_workouts_docs.py`

- [ ] **Step 1: Conduct a specification review**

Review against `docs/superpowers/specs/2026-08-10-readme-ai-coach-redesign.md` and record concrete evidence for every acceptance item: 150–220-line AI-coach-first landing page; fork-only copyable URLs; explicit upstream attribution only; credential-free client fences; no DXT promotion or manifest change; exact eleven tools with correct precedence/default semantics; snapshot/sync/confirmation guidance; setup heading/security requirements; and documentation-only scope. Fix every real finding.

- [ ] **Step 2: Conduct an independent test-quality/security review**

Review `tests/unit/test_readme_docs.py` independently. Confirm it checks MCP configuration fences rather than globally banning allowed Docker file-secret guidance, exact profile membership, fork URLs in copyable sources, narrow stale claims, deterministic paths, and no network/live Garmin requirement.

- [ ] **Step 3: Re-run final evidence after review fixes**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest \
  tests/unit/test_readme_docs.py tests/unit/test_ai_workouts_docs.py -q
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest -m "not e2e"
git diff --check main...HEAD
git status --short
```

Expected: all pass and status is clean after committing review fixes.

- [ ] **Step 4: Push and open a draft PR against `main`**

```bash
git push -u origin docs/readme-ai-coach
gh pr create --draft --base main --head docs/readme-ai-coach \
  --title "docs: redesign README for AI coaching" \
  --body-file - <<'EOF'
## Summary
- redesign the README as a concise AI-coach landing page
- add secure, fork-branded detailed setup and deployment reference
- pin branding, profile, missing-data, and configuration security with offline tests

## Verification
- `uv run pytest tests/unit/test_readme_docs.py tests/unit/test_ai_workouts_docs.py -q`
- `uv run pytest -m "not e2e"`

## Scope
Documentation and documentation tests only. No runtime, authentication, Docker, DXT, or MCP registration changes.
EOF
```

Expected: a draft PR targeting `main`. Do not merge, publish DXT, or change a release.

## Final Plan Self-Review

- [ ] **Spec coverage:** Tasks 1–5 map every approved scope, migration, security, branding, missing-data, test, verification, review, and PR requirement to a concrete action.
- [ ] **Placeholder scan:** Run `rg -n -i 't[o]d[o]|tb[d]|implement[[:space:]]later|fill[[:space:]]in|appropriate[[:space:]]error[[:space:]]handling|similar[[:space:]]to[[:space:]]task' docs/superpowers/plans/2026-08-10-readme-ai-coach-redesign.md`; expect no matches.
- [ ] **Consistency check:** Verify the fork/upstream URLs, all eleven profile tools, headings, commands, and branch name are identical throughout; no task changes runtime/DXT files.
