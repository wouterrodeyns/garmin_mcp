# GitHub Actions

This repository uses one GitHub Actions workflow: `.github/workflows/ci.yml`.
It runs for every pull request, every push to `main`, and manual invocations from
the Actions tab.

## Checks

The workflow has two jobs:

- **Offline tests** runs the complete credential-free test suite on
  Python 3.12 and 3.13, the supported lower bound and current upper CI target.
- **Lock file and package** verifies that `uv.lock` matches `pyproject.toml` and
  builds the source distribution and wheel on Python 3.13.

Dependencies are installed from the committed lock file. Commands fail their job
directly; failures are not replaced with informational success messages.

## Garmin credentials and E2E tests

CI does not receive Garmin credentials. Live tests are marked `e2e` and are
explicitly excluded with:

```bash
uv run pytest -m "not e2e"
```

Run live tests manually only from an authenticated local environment:

```bash
uv run pytest -m e2e
```

## Local equivalents

Install the locked development environment and run the same checks locally:

```bash
uv sync --locked --all-extras --dev
uv lock --check
uv run pytest -m "not e2e"
uv build
```

## Deliberately not configured

The workflow does not currently use a dependency vulnerability scanner or a
coverage-reporting service. CI does not claim to provide either check until a
real tool is configured and reviewed.
