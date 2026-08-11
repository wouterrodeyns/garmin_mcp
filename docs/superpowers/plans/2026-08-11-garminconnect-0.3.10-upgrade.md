# GarminConnect 0.3.10 Security Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the fork to `garminconnect==0.3.10`, remove the audited vulnerable lock entries, and preserve every existing MCP and AI-facing contract.

**Architecture:** Keep the existing Taxuspt and fork-owned provider layers unchanged. Update only the project/runtime contract, the five nutrition requests rejected by GarminConnect's hardened path validator, their live-test helpers, and current documentation. Prove compatibility with explicit API-surface tests, the full offline suite, a dependency audit, a package build, and a bounded read-only live smoke.

**Tech Stack:** Python 3.12+, `garminconnect==0.3.10`, FastMCP 1.x, `uv`, pytest, GitHub Actions, `pip-audit`.

---

## File map

- `pyproject.toml`: Python floor, GarminConnect pin, and standard development dependency group.
- `uv.lock`: generated, reproducible safe dependency graph.
- `.github/workflows/ci.yml`: supported Python 3.12/3.13 matrix.
- `.github/WORKFLOWS.md`: human-readable CI/runtime contract.
- `tests/unit/test_project_dependencies.py`: metadata and locked-version contract.
- `tests/unit/test_garminconnect_contract.py`: high-value installed-client API contract.
- `tests/unit/test_ci_workflows.py`: CI matrix and workflow-doc contract.
- `src/garmin_mcp/nutrition.py`: clean request paths plus separate query parameters.
- `tests/integration/test_nutrition_tools.py`: exact runtime request assertions.
- `tests/e2e/test_brand_and_micros_live.py`: safe custom-food query construction.
- `tests/e2e/test_delete_custom_food_live.py`: safe custom-food query construction.
- `tests/e2e/test_upsert_dedup_and_update_merge_live.py`: safe custom-food query construction.
- `README.md`, `docs/setup.md`, `docs/ai-training.md`, `docs/ai-workouts.md`: current runtime and pinned-client documentation.
- `tests/unit/test_readme_docs.py`, `tests/unit/test_ai_training_docs.py`, `tests/unit/test_ai_workouts_docs.py`: documentation regression contracts.
- `src/garmin_mcp/workout_builders.py`, `src/garmin_mcp/workouts.py`, `src/garmin_mcp/challenges.py`, `tests/integration/test_workout_builders_tools.py`: version-neutral compatibility comments.

### Task 1: Pin the secure runtime and installed Garmin API contract

**Files:**
- Modify: `tests/unit/test_project_dependencies.py`
- Create: `tests/unit/test_garminconnect_contract.py`
- Modify: `tests/unit/test_ci_workflows.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/WORKFLOWS.md`
- Regenerate: `uv.lock`

- [ ] **Step 1: Write the failing project and lock contract tests**

Replace `tests/unit/test_project_dependencies.py` with tests that parse both TOML files rather than matching incidental formatting:

```python
"""Project metadata and locked dependency regression tests."""

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
LOCK = tomllib.loads((ROOT / "uv.lock").read_text())


def _locked_version(name: str) -> str:
    packages = [item for item in LOCK["package"] if item["name"] == name]
    assert len(packages) == 1
    return packages[0]["version"]


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_project_pins_secure_runtime_contract() -> None:
    project = PYPROJECT["project"]
    assert project["requires-python"] == ">=3.12"
    assert "garminconnect==0.3.10" in project["dependencies"]
    assert "mcp>=1.28.1,<2" in project["dependencies"]


def test_project_uses_standard_development_dependency_group() -> None:
    assert set(PYPROJECT["dependency-groups"]["dev"]) == {
        "pytest>=9.0.2",
        "pytest-asyncio>=0.25.2",
        "pytest-mock>=3.14.0",
        "pytest-timeout>=2.3.1",
    }
    assert "dev-dependencies" not in PYPROJECT.get("tool", {}).get("uv", {})


def test_lock_contains_fixed_dependency_versions() -> None:
    assert LOCK["requires-python"] == ">=3.12"
    assert _locked_version("garminconnect") == "0.3.10"
    assert _version_tuple(_locked_version("click")) >= (8, 3, 3)
    assert _version_tuple(_locked_version("h11")) >= (0, 16, 0)
```

- [ ] **Step 2: Write the installed-client API contract test**

Create `tests/unit/test_garminconnect_contract.py`:

```python
"""Compatibility contract for the pinned GarminConnect client."""

from importlib.metadata import version
from inspect import Parameter, signature

from garminconnect import Garmin


REQUIRED_METHODS = {
    "connectapi",
    "delete_workout",
    "download_activity",
    "get_activities",
    "get_activities_by_date",
    "get_activity",
    "get_activity_exercise_sets",
    "get_activity_hr_in_timezones",
    "get_activity_power_in_timezones",
    "get_activity_splits",
    "get_hrv_data",
    "get_sleep_data",
    "get_training_readiness",
    "get_user_summary",
    "get_workouts",
    "login",
    "query_garmin_graphql",
    "schedule_workout",
    "unschedule_workout",
    "upload_workout",
}


def test_installed_garminconnect_version_is_pinned() -> None:
    assert version("garminconnect") == "0.3.10"


def test_high_value_garmin_methods_remain_available() -> None:
    missing = sorted(name for name in REQUIRED_METHODS if not callable(getattr(Garmin, name, None)))
    assert missing == []


def test_connectapi_accepts_separate_request_parameters() -> None:
    parameters = signature(Garmin.connectapi).parameters.values()
    assert any(parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters)
```

- [ ] **Step 3: Update CI tests first**

Change the expected matrix and documentation text in `tests/unit/test_ci_workflows.py`:

```python
assert 'python-version: ["3.12", "3.13"]' in workflow
...
assert "Python 3.12 and 3.13" in docs
```

- [ ] **Step 4: Run the new tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv run pytest -q \
  tests/unit/test_project_dependencies.py \
  tests/unit/test_garminconnect_contract.py \
  tests/unit/test_ci_workflows.py
```

Expected: failures report Python `>=3.10`, GarminConnect `0.3.2`, old `click`/`h11`, deprecated dev dependencies, and the Python 3.10 CI matrix.

- [ ] **Step 5: Update project metadata**

Change `pyproject.toml` to:

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "python-dotenv==1.2.2",
    "garminconnect==0.3.10",
    "requests==2.33.0",
    "mcp>=1.28.1,<2",
    "fitparse>=1.2.0",
]

[dependency-groups]
dev = [
    "pytest>=9.0.2",
    "pytest-asyncio>=0.25.2",
    "pytest-mock>=3.14.0",
    "pytest-timeout>=2.3.1",
]
```

Keep the existing MCP 2.x compatibility comment immediately above its dependency.

- [ ] **Step 6: Update CI and its current documentation**

In `.github/workflows/ci.yml`, use:

```yaml
python-version: ["3.12", "3.13"]
```

In `.github/WORKFLOWS.md`, state that offline tests run on Python 3.12 and 3.13, the supported lower bound and current upper CI target.

- [ ] **Step 7: Regenerate and install the lock**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv lock --upgrade
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv sync --locked --all-extras --dev
```

Expected: `uv.lock` records `requires-python = ">=3.12"`, GarminConnect 0.3.10, Click at least 8.3.3, and h11 at least 0.16.0.

- [ ] **Step 8: Run the focused tests and verify GREEN**

Run the Step 4 command again. Expected: all tests pass.

- [ ] **Step 9: Commit Task 1**

```bash
git add pyproject.toml uv.lock .github/workflows/ci.yml .github/WORKFLOWS.md \
  tests/unit/test_project_dependencies.py tests/unit/test_garminconnect_contract.py \
  tests/unit/test_ci_workflows.py
git -c commit.gpgSign=false commit -m "chore: upgrade garminconnect to 0.3.10"
```

### Task 2: Adapt hardened nutrition request paths

**Files:**
- Modify: `tests/integration/test_nutrition_tools.py`
- Modify: `src/garmin_mcp/nutrition.py`
- Modify: `tests/e2e/test_brand_and_micros_live.py`
- Modify: `tests/e2e/test_delete_custom_food_live.py`
- Modify: `tests/e2e/test_upsert_dedup_and_update_merge_live.py`

- [ ] **Step 1: Replace URL-fragment assertions with exact endpoint/params assertions**

Import `call` in `tests/integration/test_nutrition_tools.py`:

```python
from unittest.mock import Mock, call
```

Pin the general catalog call:

```python
mock_garmin_client.connectapi.assert_called_once_with(
    "/nutrition-service/food/search",
    params={"searchExpression": "Cheerios", "start": 0, "limit": 20},
)
```

Pin custom-food calls with the existing include-content behavior:

```python
mock_garmin_client.connectapi.assert_called_once_with(
    "/nutrition-service/customFood",
    params={
        "searchExpression": "cookie",
        "start": 0,
        "limit": 10,
        "includeContent": "true",
    },
)
```

Add equivalent exact assertions to the update-preservation and existing-food upsert tests. Add a creation-with-empty-response test whose call list proves the second lookup also uses the clean custom-food endpoint:

```python
assert mock_garmin_client.connectapi.call_args_list[:2] == [
    call(
        "/nutrition-service/customFood",
        params={
            "searchExpression": "New Food",
            "start": 0,
            "limit": 10,
            "includeContent": "true",
        },
    ),
    call(
        "/nutrition-service/customFood",
        params={
            "searchExpression": "New Food",
            "start": 0,
            "limit": 10,
            "includeContent": "true",
        },
    ),
]
```

The test supplies three `connectapi` responses: initial empty search, lookup containing the created IDs, and meal metadata. Both `client.put` calls return empty dictionaries.

- [ ] **Step 2: Run the focused nutrition tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv run pytest -q \
  tests/integration/test_nutrition_tools.py
```

Expected: exact call assertions fail because the implementation still embeds query strings in paths.

- [ ] **Step 3: Convert all five runtime searches to separate params**

In `src/garmin_mcp/nutrition.py`, remove `quote` from imports. Use this form for the catalog search:

```python
url = "/nutrition-service/food/search"
params = {
    "searchExpression": query,
    "start": start,
    "limit": limit,
}
data = garmin_client.connectapi(url, params=params)
```

Use this form for every custom-food search, preserving each existing `start` and `limit`:

```python
url = "/nutrition-service/customFood"
params = {
    "searchExpression": food_name,
    "start": 0,
    "limit": 10,
    "includeContent": "true",
}
data = garmin_client.connectapi(url, params=params)
```

The five runtime call sites are catalog search, custom-food listing, update merge lookup, upsert initial lookup, and upsert post-create lookup.

- [ ] **Step 4: Convert the five live-test helper requests**

In the three named E2E files, replace every `?searchExpression=...` path with:

```python
client.connectapi(
    "/nutrition-service/customFood",
    params={
        "searchExpression": name,
        "start": 0,
        "limit": 20,
        "includeContent": "true",
    },
)
```

Preserve each helper's existing variable name and limit (`10` or `20`) and remove now-unused `urllib.parse.quote` imports.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run the Step 2 command again. Expected: all nutrition integration tests pass.

Then run:

```bash
rg -n '\?searchExpression|quote\(' src/garmin_mcp/nutrition.py tests/e2e
```

Expected: no matches.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/garmin_mcp/nutrition.py tests/integration/test_nutrition_tools.py \
  tests/e2e/test_brand_and_micros_live.py tests/e2e/test_delete_custom_food_live.py \
  tests/e2e/test_upsert_dedup_and_update_merge_live.py
git -c commit.gpgSign=false commit -m "fix(nutrition): separate query parameters from paths"
```

### Task 3: Update the current runtime documentation

**Files:**
- Modify: `tests/unit/test_readme_docs.py`
- Modify: `tests/unit/test_ai_training_docs.py`
- Modify: `tests/unit/test_ai_workouts_docs.py`
- Modify: `README.md`
- Modify: `docs/setup.md`
- Modify: `docs/ai-training.md`
- Modify: `docs/ai-workouts.md`
- Modify: `src/garmin_mcp/workout_builders.py`
- Modify: `src/garmin_mcp/workouts.py`
- Modify: `src/garmin_mcp/challenges.py`
- Modify: `tests/integration/test_workout_builders_tools.py`

- [ ] **Step 1: Change current-document assertions first**

In `tests/unit/test_ai_training_docs.py`, require `garminconnect==0.3.10` instead of `0.3.2`.

In both pinned-workout assertions in `tests/unit/test_ai_workouts_docs.py`, require:

```python
"garminconnect==0.3.10"
```

Add this test to `tests/unit/test_readme_docs.py`:

```python
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
```

- [ ] **Step 2: Run current-document tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv run pytest -q \
  tests/unit/test_readme_docs.py \
  tests/unit/test_ai_training_docs.py \
  tests/unit/test_ai_workouts_docs.py
```

Expected: failures identify the stale Python 3.10 and GarminConnect 0.3.2 claims.

- [ ] **Step 3: Update current user documentation**

Make these exact contract changes:

- `README.md`: “The project supports Python 3.12+.”
- `docs/setup.md`: “The project supports Python 3.12+.”
- `docs/ai-training.md`: implementation pinned to `garminconnect==0.3.10`; retain the existing bounded snapshot and coarse warning semantics.
- `docs/ai-workouts.md`: pinned API section targets `garminconnect==0.3.10`, links to the 0.3.10 PyPI/source tags, and records the new high-level whole-document `update_workout` method while keeping the fork tool deferred.

Do not rewrite historical specs or implementation plans; they describe the repository at their creation time.

- [ ] **Step 4: Make current source comments version-neutral**

Replace claims tied to `0.3.2` with behavior-based wording:

```python
# Modern garminconnect versions expose the raw client as .client.
```

For workout upload/scheduling comments, describe whether the high-level method returns a parsed dictionary or delegates to `client.post/delete` without naming an obsolete version. In the challenge comment, state only that Garmin rejects zero for that endpoint. Update the workout-builder regression-test docstring to describe the `.client` compatibility contract.

- [ ] **Step 5: Run the documentation tests and verify GREEN**

Run the Step 2 command again. Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add README.md docs/setup.md docs/ai-training.md docs/ai-workouts.md \
  src/garmin_mcp/workout_builders.py src/garmin_mcp/workouts.py \
  src/garmin_mcp/challenges.py tests/integration/test_workout_builders_tools.py \
  tests/unit/test_readme_docs.py tests/unit/test_ai_training_docs.py \
  tests/unit/test_ai_workouts_docs.py
git -c commit.gpgSign=false commit -m "docs: update GarminConnect runtime contract"
```

### Task 4: Verify, audit, build, and perform the bounded live read

**Files:**
- No committed file changes expected.

- [ ] **Step 1: Run all focused upgrade tests**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv run pytest -q \
  tests/unit/test_project_dependencies.py \
  tests/unit/test_garminconnect_contract.py \
  tests/unit/test_ci_workflows.py \
  tests/integration/test_nutrition_tools.py \
  tests/unit/test_readme_docs.py \
  tests/unit/test_ai_training_docs.py \
  tests/unit/test_ai_workouts_docs.py
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete offline suite**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv run pytest -m "not e2e" -q
```

Expected: all selected tests pass and only E2E tests are deselected.

- [ ] **Step 3: Verify the lock and package**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv lock --check
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv build --out-dir /private/tmp/garmin-mcp-upgrade-dist
```

Expected: the lock is current and both source distribution and wheel build successfully.

- [ ] **Step 4: Audit the locked runtime dependency set**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uv export --locked --no-dev \
  --no-emit-project --format requirements-txt --no-hashes \
  --output-file /private/tmp/garmin-mcp-upgrade-requirements.txt
UV_CACHE_DIR=/private/tmp/garmin-mcp-upgrade-uv-cache uvx --from pip-audit pip-audit \
  -r /private/tmp/garmin-mcp-upgrade-requirements.txt
```

Expected: `pip-audit` reports no known vulnerabilities.

- [ ] **Step 5: Run a bounded read-only live smoke when local tokens exist**

Create an uncommitted temporary script at `/private/tmp/garmin_mcp_upgrade_smoke.py` containing:

```python
from datetime import date
import json
from pathlib import Path

from garminconnect import Garmin
from garmin_mcp.token_utils import get_token_path


token_path = Path(get_token_path())
if not token_path.exists():
    print(json.dumps({"status": "skipped", "reason": "tokens_absent"}))
    raise SystemExit(0)

client = Garmin()
client.login(str(token_path))
today = date.today().isoformat()


def probe(read, *, count: bool = False) -> dict[str, object]:
    try:
        value = read()
    except Exception:
        return {"type": "unavailable"}
    result: dict[str, object] = {"type": type(value).__name__}
    if count and isinstance(value, list):
        result["count"] = len(value)
    return result


checks = {
    "activities": probe(lambda: client.get_activities(0, 1), count=True),
    "daily_stats": probe(lambda: client.get_user_summary(today)),
    "workouts": probe(lambda: client.get_workouts(0, 1), count=True),
    "schedule": probe(
        lambda: client.query_garmin_graphql(
            {
                "query": (
                    'query{workoutScheduleSummariesScalar('
                    f'startDate:"{today}", endDate:"{today}")}}'
                )
            }
        )
    ),
}

print(
    json.dumps(
        {
            "status": "success",
            "checks": checks,
        }
    )
)
```

Run it only from the authenticated local environment. Expected: either a sanitized `tokens_absent` skip or a success object containing only container types and bounded counts. The script performs no Garmin write.

- [ ] **Step 6: Check the final diff and worktree**

```bash
git diff --check main...HEAD
git status --short
```

Expected: no whitespace errors and a clean worktree.

- [ ] **Step 7: Finish the branch**

Use `superpowers:finishing-a-development-branch`, open a ready-for-review pull request against `main`, and verify the GitHub Actions jobs complete successfully.
