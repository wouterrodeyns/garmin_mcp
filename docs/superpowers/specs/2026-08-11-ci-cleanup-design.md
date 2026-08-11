# CI Cleanup Design

## Goal

Replace the three inherited, overlapping GitHub Actions workflows with one small,
trustworthy workflow for pull requests and pushes to `main`. The workflow must be
safe to run without Garmin credentials and must fail visibly when validation
fails.

## Scope

- Consolidate `ci.yml`, `pr-validation.yml`, and `security.yml` into `ci.yml`.
- Preserve Python compatibility coverage at the supported range boundaries:
  Python 3.10 and Python 3.13.
- Install from the committed lock file with `uv sync --locked --all-extras --dev`.
- Run the complete offline suite with `pytest -m "not e2e"`.
- Validate the lock file and build the distributable package once per workflow.
- Use read-only repository permissions, bounded job timeouts, and concurrency
  cancellation for superseded runs.
- Update `.github/WORKFLOWS.md` to describe the actual workflow and local
  equivalents.
- Add a focused repository test that pins the safety-critical workflow contract.

## Workflow Shape

The workflow runs for pull requests, pushes to `main`, and manual dispatches. A
test job uses a two-version matrix. A separate validation job runs once on Python
3.13 and checks the lock file and package build. No step receives repository or
Garmin secrets, and no live E2E test is eligible to run.

The workflow does not claim to perform dependency vulnerability scanning or test
coverage because neither capability is currently configured. Those can be added
later as real, separately reviewed checks.

## Failure Semantics

Commands are not followed by `|| echo` or otherwise made non-fatal. A failed
dependency install, test, lock check, or build fails its job. The workflow does
not contain a synthetic summary that can contradict the actual job result.

## Tests and Acceptance

A unit test reads the checked-in workflow and documentation and asserts the
stable safety contract: one workflow, explicit offline marker exclusion, locked
dependency installation, supported Python boundary versions, read-only
permissions, no swallowed commands, and accurate documentation. The complete
offline test suite must pass locally before the branch is pushed.

## Non-goals

- No application-code or dependency-version changes.
- No live Garmin tests or credential setup in GitHub Actions.
- No coverage service, vulnerability scanner, release automation, or required
  branch-protection configuration.
- No unrelated cleanup of upstream project configuration.
