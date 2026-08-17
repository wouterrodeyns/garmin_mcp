# Security Defaults Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make absent configuration select the curated `ai-coach` surface, require explicit opt-in for the full upstream surface, and eliminate the repository's unsafe HTTP, credential-file, OpenCode, and DXT defaults.

**Architecture:** Keep all Garmin modules intact and change only the startup policy that filters their registration. Add a small, pure HTTP-host validator beside the existing transport parser, then pin repository configuration and documentation with offline tests. Preserve current explicit allowlist precedence and provide `upstream-full` as the sole intentional register-all selector.

**Tech Stack:** Python 3.12, FastMCP 1.28.1, pytest, stdlib `ipaddress`, JSON configuration, Markdown documentation, Git ignore rules.

---

## File map

- Modify `src/garmin_mcp/__init__.py`: profile resolution, startup diagnostics,
  and HTTP bind validation.
- Modify `tests/unit/test_tool_filter.py`: pure resolver contracts.
- Modify `tests/unit/test_server_startup.py`: real FastMCP default/full startup and
  pre-authentication failure behavior.
- Modify `tests/unit/test_transport_config.py`: loopback and dangerous-override
  transport matrix.
- Create `tests/unit/test_security_defaults.py`: repository-level OpenCode,
  secrets-ignore, Docker-ignore, and DXT-absence contracts.
- Modify `.gitignore`: exclude `/secrets/` from Git.
- Modify `.dockerignore`: tracked portable Docker exclusions for secrets,
  build context, and local artifacts.
- Modify `opencode.json`: explicitly select `ai-coach`.
- Delete `dxt/manifest.json`, `garmin-mcp.dxt`, and
  `tests/unit/test_dxt_manifest.py`, and `scripts/build_dxt.sh`: remove
  misleading upstream artifacts, the now-broken builder, and their artifact-only
  tests.
- Modify `README.md` and `docs/setup.md`: document default `ai-coach`, explicit
  `upstream-full`, refused remote HTTP, ignored secrets, and no DXT release.
- Modify `tests/unit/test_readme_docs.py`: pin those current documentation
  contracts.

### Task 1: Make tool registration fail closed

**Files:**
- Modify: `tests/unit/test_tool_filter.py`
- Modify: `tests/unit/test_server_startup.py`
- Modify: `src/garmin_mcp/__init__.py:100-181`
- Modify: `src/garmin_mcp/__init__.py:532-540`

- [ ] **Step 1: Write failing resolver tests**

Replace the old empty-profile broad-default test and add the explicit full-mode
matrix:

```python
@pytest.mark.parametrize("profile", [None, "", "   "])
def test_empty_profile_defaults_to_ai_coach(profile):
    enabled, disabled = _resolve_tool_filters(
        profile, None, " GET_WORKOUTS, analyze_activity "
    )

    assert enabled == TOOL_PROFILES["ai-coach"] - {
        "get_workouts",
        "analyze_activity",
    }
    assert disabled == set()


def test_upstream_full_profile_preserves_denylist_behavior():
    enabled, disabled = _resolve_tool_filters(
        " UPSTREAM-FULL ", None, " GET_DEVICES, get_devices "
    )

    assert enabled == set()
    assert disabled == {"get_devices"}


def test_explicit_enabled_tools_override_upstream_full_and_disabled_tools():
    enabled, disabled = _resolve_tool_filters(
        "upstream-full", " GET_DEVICES ", "get_devices"
    )

    assert enabled == {"get_devices"}
    assert disabled == set()
```

Update the unknown-profile assertion to require both valid names:

```python
def test_unknown_profile_names_are_rejected():
    with pytest.raises(ValueError, match=r"valid profile\(s\): ai-coach, upstream-full"):
        _resolve_tool_filters("unknown", None, None)
```

- [ ] **Step 2: Write failing real-startup tests**

Change `test_main_registers_tools_and_starts_stdio` so an unset profile expects
the exact curated set:

```python
assert set(run_calls[0]["tool_names"]) == garmin_mcp.TOOL_PROFILES["ai-coach"]
assert run_calls[0]["tool_count"] == 16
assert "get_devices" not in run_calls[0]["tool_names"]
```

Add an explicit compatibility test:

```python
def test_main_upstream_full_registers_broad_surface(monkeypatch, capsys):
    run_calls = []
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", " upstream-FULL ")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append({tool.name for tool in asyncio.run(self.list_tools())})

    monkeypatch.setattr(FastMCP, "run", capture_run)
    garmin_mcp.main()

    assert "get_devices" in run_calls[0]
    assert "create_workout" in run_calls[0]
    assert len(run_calls[0]) > len(garmin_mcp.TOOL_PROFILES["ai-coach"])
    assert "full upstream-compatible tool surface" in capsys.readouterr().err
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
uv run pytest -q tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
```

Expected: failures show that empty profiles currently register broadly,
`upstream-full` is unknown, and unset startup exposes `get_devices`.

- [ ] **Step 4: Implement the minimal profile policy**

Add constants beside `TOOL_PROFILES`:

```python
DEFAULT_TOOL_PROFILE = "ai-coach"
UPSTREAM_FULL_PROFILE = "upstream-full"
```

Implement the resolver without duplicating the full tool set:

```python
def _normalized_profile_name(value):
    if not value or not value.strip():
        return DEFAULT_TOOL_PROFILE
    return value.strip().lower()


def _resolve_tool_filters(profile_value, enabled_value, disabled_value):
    explicit_enabled = _parse_tool_set(enabled_value)
    if explicit_enabled:
        return explicit_enabled, set()

    disabled = _parse_tool_set(disabled_value)
    profile_name = _normalized_profile_name(profile_value)
    if profile_name == UPSTREAM_FULL_PROFILE:
        return set(), disabled
    if profile_name not in TOOL_PROFILES:
        valid_profiles = ", ".join(
            sorted((*TOOL_PROFILES, UPSTREAM_FULL_PROFILE))
        )
        raise ValueError(
            f"Unknown GARMIN_TOOL_PROFILE {profile_value!r}; "
            f"valid profile(s): {valid_profiles}"
        )
    return TOOL_PROFILES[profile_name] - disabled, set()
```

In `_resolve_tool_filters_from_environment`, use `_normalized_profile_name` and
make the default profile an active allowlist:

```python
profile_name = _normalized_profile_name(profile_value)
allowlist_active = bool(parsed_enabled) or profile_name in TOOL_PROFILES
```

Keep `configured_names` based on the selected maintained profile. In `main()`,
emit this diagnostic when the explicit profile normalizes to `upstream-full`:

```python
elif _normalized_profile_name(os.getenv("GARMIN_TOOL_PROFILE")) == UPSTREAM_FULL_PROFILE:
    print("Tool filter: full upstream-compatible tool surface active.", file=sys.stderr)
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
uv run pytest -q tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
```

Expected: all tests pass, including existing zero-tool and typo diagnostics.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/garmin_mcp/__init__.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
git commit -m "fix(server): default to curated tool profile"
```

### Task 2: Refuse unauthenticated remote HTTP by default

**Files:**
- Modify: `tests/unit/test_transport_config.py`
- Modify: `tests/unit/test_server_startup.py`
- Modify: `src/garmin_mcp/__init__.py:1-30`
- Modify: `src/garmin_mcp/__init__.py:226-240`

- [ ] **Step 1: Write the loopback and override test matrix**

Add to `tests/unit/test_transport_config.py`:

```python
@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.0.0.42", "::1", "localhost", "LOCALHOST."],
)
@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_http_accepts_loopback_hosts(transport, host):
    with patch.dict(
        os.environ,
        {"GARMIN_MCP_TRANSPORT": transport, "GARMIN_MCP_HOST": host},
        clear=False,
    ):
        os.environ.pop("GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE", None)
        assert _parse_transport_config()[:2] == (transport, host)


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "192.168.1.5", "8.8.8.8", "garmin.internal"],
)
def test_http_rejects_non_loopback_without_override(host):
    with patch.dict(
        os.environ,
        {"GARMIN_MCP_TRANSPORT": "streamable-http", "GARMIN_MCP_HOST": host},
        clear=False,
    ):
        os.environ.pop("GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE", None)
        with pytest.raises(ValueError, match="does not provide HTTP authentication"):
            _parse_transport_config()


@pytest.mark.parametrize("value", ["true", "1", "YES", " yes "])
def test_explicit_dangerous_override_allows_remote_http(value):
    with patch.dict(
        os.environ,
        {
            "GARMIN_MCP_TRANSPORT": "streamable-http",
            "GARMIN_MCP_HOST": "0.0.0.0",
            "GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE": value,
        },
    ):
        assert _parse_transport_config()[:2] == ("streamable-http", "0.0.0.0")


def test_stdio_does_not_validate_unused_host():
    with patch.dict(
        os.environ,
        {"GARMIN_MCP_TRANSPORT": "stdio", "GARMIN_MCP_HOST": "0.0.0.0"},
    ):
        assert _parse_transport_config()[:2] == ("stdio", "0.0.0.0")
```

Add to `tests/unit/test_server_startup.py`:

```python
def test_main_rejects_remote_http_before_authentication(monkeypatch, capsys):
    authentication = Mock()
    monkeypatch.setenv("GARMIN_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("GARMIN_MCP_HOST", "0.0.0.0")
    monkeypatch.delenv("GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", authentication)

    with pytest.raises(SystemExit) as error:
        garmin_mcp.main()

    assert error.value.code == 1
    assert "does not provide HTTP authentication" in capsys.readouterr().err
    authentication.assert_not_called()
```

- [ ] **Step 2: Run transport tests and verify RED**

Run:

```bash
uv run pytest -q tests/unit/test_transport_config.py tests/unit/test_server_startup.py
```

Expected: non-loopback HTTP cases are accepted rather than rejected.

- [ ] **Step 3: Implement exact loopback validation**

Import `ipaddress` and add:

```python
def _is_loopback_http_host(host):
    normalized = host.strip()
    if normalized.lower() in {"localhost", "localhost."}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
```

In `_parse_transport_config`, strip the host and guard only HTTP transports:

```python
http_host = os.getenv("GARMIN_MCP_HOST", "127.0.0.1").strip()
allow_remote = os.getenv(
    "GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE", ""
).strip().lower() in ("true", "1", "yes")
if transport != "stdio" and not _is_loopback_http_host(http_host) and not allow_remote:
    raise ValueError(
        "Refusing non-loopback HTTP bind: this server does not provide HTTP "
        "authentication. Use an authenticating reverse proxy, or explicitly "
        "acknowledge the risk with GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE=true."
    )
```

Document the fourth transport variable in the `main()` comment.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
uv run pytest -q tests/unit/test_transport_config.py tests/unit/test_server_startup.py
```

Expected: all transport and startup tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/garmin_mcp/__init__.py tests/unit/test_transport_config.py tests/unit/test_server_startup.py
git commit -m "fix(server): refuse unauthenticated remote HTTP"
```

### Task 3: Secure repository configuration and remove stale DXT artifacts

**Files:**
- Create: `tests/unit/test_security_defaults.py`
- Modify: `.gitignore`
- Modify: `.dockerignore`
- Modify: `opencode.json`
- Delete: `dxt/manifest.json`
- Delete: `garmin-mcp.dxt`
- Delete: `tests/unit/test_dxt_manifest.py`
- Delete: `scripts/build_dxt.sh`

- [ ] **Step 1: Write repository-policy tests before changing configuration**

Create `tests/unit/test_security_defaults.py`:

```python
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_tracked_opencode_config_explicitly_selects_ai_coach():
    config = json.loads((ROOT / "opencode.json").read_text())
    assert config["mcp"]["garmin"]["environment"] == {
        "GARMIN_TOOL_PROFILE": "ai-coach"
    }


def test_documented_secret_files_are_ignored_by_git():
    for relative_path in (
        "secrets/garmin_email.txt",
        "secrets/garmin_password.txt",
    ):
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", relative_path],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 0, relative_path


def test_dockerignore_is_portable_and_preserves_docker_build_inputs():
    dockerignore = ROOT / ".dockerignore"
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
    assert "/secrets/" in (ROOT / ".gitignore").read_text().splitlines()


def test_stale_desktop_extension_artifacts_are_not_distributed():
    assert not (ROOT / "garmin-mcp.dxt").exists()
    assert not (ROOT / "dxt" / "manifest.json").exists()
    assert not (ROOT / "scripts" / "build_dxt.sh").exists()
```

- [ ] **Step 2: Run repository tests and verify RED**

Run:

```bash
uv run pytest -q tests/unit/test_security_defaults.py
```

Expected: the OpenCode and Git-ignore tests pass from the preceding task, while
the portable Docker-ignore and obsolete-builder tests fail.

- [ ] **Step 3: Apply the minimal repository changes**

Add this exact root-anchored rule to `.gitignore`:

```gitignore
# Local deployment credentials
/secrets/
```

Add this to the tracked Garmin OpenCode entry:

```json
"environment": {
  "GARMIN_TOOL_PROFILE": "ai-coach"
},
```

Replace the `.dockerignore` symlink with a tracked regular file containing
explicit exclusions for `.git`, local environments, `/secrets/`, Python
caches/build artifacts/logs, scratch directories, and captured fixtures. Keep
`src/`, `tests/`, `pyproject.toml`, `README.md`, and `pytest.ini` available to
the Dockerfile. Delete `dxt/manifest.json`, `garmin-mcp.dxt`,
`tests/unit/test_dxt_manifest.py`, and `scripts/build_dxt.sh` using patch-based
file deletion. Do not change Docker runtime behavior or create replacement
credential files.

- [ ] **Step 4: Run repository tests and verify GREEN**

Run:

```bash
uv run pytest -q tests/unit/test_security_defaults.py
```

Expected: four tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add .gitignore .dockerignore opencode.json tests/unit/test_security_defaults.py
git add -u dxt/manifest.json garmin-mcp.dxt tests/unit/test_dxt_manifest.py scripts/build_dxt.sh
git commit -m "chore(security): remove unsafe repository defaults"
```

### Task 4: Update and pin current security documentation

**Files:**
- Modify: `tests/unit/test_readme_docs.py`
- Modify: `README.md`
- Modify: `docs/setup.md`

- [ ] **Step 1: Change documentation tests to the new contract**

Update `test_readme_profile_and_filter_contract` to require:

```python
assert "ai-coach is the default" in lower
assert "garmin_tool_profile=upstream-full" in lower
assert lower.index("garmin_enabled_tools") < lower.index("garmin_disabled_tools")
assert lower.index("garmin_disabled_tools") < lower.index("upstream-full")
assert "broad upstream-compatible registration remains available" not in lower
```

Add:

```python
def test_setup_pins_remote_http_and_secret_directory_security():
    setup = " ".join(_setup().lower().split())
    for expected in (
        "refuses non-loopback",
        "garmin_mcp_allow_unauthenticated_remote=true",
        "authenticating reverse proxy",
        "secrets/garmin_email.txt",
        "secrets/garmin_password.txt",
        "ignored by git",
    ):
        assert expected in setup


def test_current_docs_do_not_advertise_a_desktop_extension():
    markdown = (_readme() + "\n" + _setup()).lower()
    assert "fork-specific desktop extension is not published" in markdown
    assert "install the dxt" not in markdown
    assert "garmin-mcp.dxt" not in markdown
```

- [ ] **Step 2: Run documentation tests and verify RED**

Run:

```bash
uv run pytest -q tests/unit/test_readme_docs.py
```

Expected: failures identify the stale broad-default and remote-HTTP language.

- [ ] **Step 3: Update README profile language**

Replace the AI-coach introduction with:

```markdown
The server defaults to the deliberate 16-tool `ai-coach` surface when
`GARMIN_TOOL_PROFILE` is unset. Set it explicitly in client configuration to
document intent. Advanced users who intentionally need every maintained
Taxuspt-compatible tool must opt in with
`GARMIN_TOOL_PROFILE=upstream-full`.
```

Update the precedence list so explicit allowlist wins, denylist subtracts from
the selected/default profile, and the default is `ai-coach`. Keep the existing
sixteen-name list unchanged.

- [ ] **Step 4: Update setup and transport guidance**

In `docs/setup.md`, replace broad-default language with the same explicit
`upstream-full` escape hatch. Extend the transport variable list with:

```markdown
- `GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE`: dangerous explicit acknowledgement
  required before an HTTP transport may bind to a non-loopback host.
```

State that non-loopback HTTP is refused by default, the server still supplies no
HTTP authentication, and the override is acceptable only behind an
authenticating reverse proxy. In the Docker section, state that the demonstrated
`secrets/` directory is ignored by Git and Docker build context. State that no
fork-specific DXT package is distributed.

- [ ] **Step 5: Run documentation tests and verify GREEN**

Run:

```bash
uv run pytest -q tests/unit/test_readme_docs.py tests/unit/test_security_defaults.py
```

Expected: all documentation and repository-policy tests pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add README.md docs/setup.md tests/unit/test_readme_docs.py
git commit -m "docs(security): explain fail-closed server defaults"
```

### Task 5: Verify the complete branch and prepare the PR

**Files:**
- Verify all files changed since `main`

- [ ] **Step 1: Run all focused security suites**

Run:

```bash
uv run pytest -q \
  tests/unit/test_tool_filter.py \
  tests/unit/test_server_startup.py \
  tests/unit/test_transport_config.py \
  tests/unit/test_security_defaults.py \
  tests/unit/test_readme_docs.py
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete offline suite**

Run:

```bash
uv run pytest -m "not e2e" -q
```

Expected: all selected tests pass and only live E2E tests are deselected.

- [ ] **Step 3: Run structural verification**

Run:

```bash
git diff --check main...HEAD
git status --short
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Expected: no whitespace errors, a clean worktree, only approved files changed,
and the design/implementation commits are visible.

- [ ] **Step 4: Review the final diff against the design**

Confirm explicitly:

- unset configuration registers exactly sixteen `ai-coach` tools;
- `upstream-full` retains the complete maintained surface;
- explicit allowlist and denylist precedence are unchanged;
- remote HTTP fails before Garmin authentication unless explicitly overridden;
- `/secrets/` is ignored;
- stale DXT artifacts are absent;
- no individual Garmin tool or authentication implementation changed.

- [ ] **Step 5: Push and open a ready-for-review PR**

```bash
git push -u origin security/defaults-hardening
gh pr create \
  --base main \
  --head security/defaults-hardening \
  --title "Harden MCP security defaults" \
  --body-file /private/tmp/garmin-mcp-security-defaults-pr.md
```

The PR body will summarize the intentional default-profile compatibility
change, remote-HTTP guard, secrets protection, DXT removal, and fresh test
evidence. Do not use `--draft`.
