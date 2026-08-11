# CI Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace three inherited, overlapping workflows with one accurate, credential-free CI workflow.

**Architecture:** A single GitHub Actions workflow owns offline testing and package validation. A small text-contract unit test pins the safety-critical configuration without adding a YAML dependency.

**Tech Stack:** GitHub Actions, `uv`, Python 3.10/3.13, pytest, stdlib `pathlib`.

---

### Task 1: Pin and implement the consolidated workflow

**Files:**
- Create: `tests/unit/test_ci_workflows.py`
- Modify: `.github/workflows/ci.yml`
- Delete: `.github/workflows/pr-validation.yml`
- Delete: `.github/workflows/security.yml`
- Modify: `.github/WORKFLOWS.md`

- [ ] **Step 1: Write the failing workflow-contract tests**

```python
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
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run pytest tests/unit/test_ci_workflows.py -q
```

Expected: failures because three workflows exist and the current CI lacks the new locked/offline/build contract.

- [ ] **Step 3: Replace `ci.yml` with the consolidated workflow**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    name: Offline tests (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    timeout-minutes: 15
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.13"]
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8.3.2
        with:
          python-version: ${{ matrix.python-version }}
          enable-cache: true
      - run: uv sync --locked --all-extras --dev
      - run: uv run pytest -m "not e2e"

  package:
    name: Lock file and package
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8.3.2
        with:
          python-version: "3.13"
          enable-cache: true
      - run: uv lock --check
      - run: uv sync --locked --all-extras --dev
      - run: uv build
```

Delete `pr-validation.yml` and `security.yml`. Rewrite `WORKFLOWS.md` to document the one workflow, its triggers, the two jobs, the explicit E2E exclusion, local commands, and the fact that vulnerability scanning is not currently configured.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
uv run pytest tests/unit/test_ci_workflows.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit the implementation**

```bash
git add .github tests/unit/test_ci_workflows.py
git commit -m "ci: consolidate offline validation"
```

### Task 2: Verify the branch and prepare the pull request

**Files:**
- Verify: all files changed from `main`

- [ ] **Step 1: Run formatting and scope checks**

```bash
git diff --check main...HEAD
git diff --stat main...HEAD
```

Expected: no whitespace errors; changes limited to the design, CI workflow/docs, and workflow-contract test.

- [ ] **Step 2: Run the complete offline suite**

```bash
uv run pytest -m "not e2e" -q
```

Expected: all selected tests pass and 20 E2E tests are deselected.

- [ ] **Step 3: Verify package creation**

```bash
uv build
```

Expected: source distribution and wheel build successfully.

- [ ] **Step 4: Push and open a ready-for-review PR**

```bash
git push -u origin chore/ci-cleanup
gh pr create --base main --head chore/ci-cleanup --title "ci: consolidate offline validation" --body-file /tmp/ci-cleanup-pr.md
```

The PR body must summarize consolidation, explicit E2E exclusion, locked installs, package validation, and the verification results. Do not pass `--draft`.
