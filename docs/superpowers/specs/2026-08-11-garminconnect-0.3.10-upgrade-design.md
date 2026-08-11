# GarminConnect 0.3.10 Security Upgrade Design

## Goal

Upgrade the fork from `garminconnect==0.3.2` to `garminconnect==0.3.10`
without changing its MCP surface or AI-facing response contracts. The upgrade
must remove the currently audited vulnerable dependency versions, preserve the
Taxuspt backend architecture, and prove compatibility offline before any
bounded live read.

## Why now

The current locked environment reports three known vulnerabilities:

- `garminconnect 0.3.2`, fixed in `0.3.5`;
- `click 8.1.8`, fixed in `8.3.3`;
- `h11 0.14.0`, fixed in `0.16.0`.

GarminConnect `0.3.10`, released on 2026-08-11, includes the earlier token-file
permission fix plus broader authentication, token-path, request-path, domain,
logging, session, pagination, and identifier hardening. It requires Python
3.12 or newer.

## Considered approaches

### 1. Upgrade directly to 0.3.10 — selected

Pin the latest researched client, raise the Python floor to 3.12, adapt the
small incompatible raw-path surface, and refresh the lock. This removes the
known Garmin vulnerability and avoids immediately scheduling another client
upgrade.

### 2. Stop at 0.3.5

This would fix the published token permission vulnerability but omit the newer
authentication, request-validation, and data-hygiene hardening. It has the same
Python 3.12 floor and therefore offers little compatibility benefit.

### 3. Override only vulnerable transitive packages

Refreshing `click` and `h11` alone would leave the vulnerable Garmin client in
place. This does not meet the security goal.

## Dependency and runtime contract

- Set `requires-python = ">=3.12"`.
- Pin `garminconnect==0.3.10`.
- Refresh `uv.lock` so it resolves at least `click 8.3.3` and `h11 0.16.0`.
- Restrict lock upgrades to GarminConnect and the packages needed to remove the
  audited findings (`click`, `h11`, and `httpcore`); retain unrelated locked
  versions, including MCP, Pydantic, pytest, Starlette, and Uvicorn.
- Do not add `click` or `h11` as artificial direct runtime dependencies. Their
  secure versions belong in the lock through the existing dependency graph.
- Move the deprecated `[tool.uv].dev-dependencies` declaration to the standard
  `[dependency-groups].dev` table without changing the test dependency set.
- Keep MCP on the existing `>=1.28.1,<2` compatibility range.
- Do not install or adopt GarminConnect's experimental `typed` extra.

The CI compatibility matrix becomes Python 3.12 and 3.13. README and setup
examples already use 3.12; claims that the project supports Python 3.10 are
updated.

## Garmin API compatibility findings

Static signature comparison against the installed `0.3.10` wheel found all 94
Garmin methods called by this repository still present. The only signature
annotation change is `get_training_readiness`, from a dictionary annotation to
`list[dict]`; the fork's training-context normalizer already supports the list
shape and preserves its existing missing-data semantics.

The full offline suite also passes when forced to import `0.3.10`, but one
behavioral incompatibility is hidden by mocked clients: the hardened client now
rejects `?`, `#`, and query fragments embedded in API path strings. Five
nutrition search flows currently append query parameters to the path. Those
calls must pass a clean endpoint plus a separate `params` dictionary. The five
live nutrition test helpers that directly exercise the same raw endpoints must
use the same safe calling convention.

No MCP tool names, AI profile membership, provider return schemas, warning
codes, workout compiler behavior, or authentication entrypoints change in this
PR.

## Compatibility implementation

The nutrition changes are mechanical and limited to existing read/search
requests:

```python
url = "/nutrition-service/food/search"
params = {
    "searchExpression": query,
    "start": start,
    "limit": limit,
}
data = garmin_client.connectapi(url, params=params)
```

Custom-food searches use the same pattern with
`url = "/nutrition-service/customFood"` and preserve their existing
`"includeContent": "true"` parameter. Catalog searches do not add that
custom-food-only parameter.

Values are passed unquoted to `params`; the HTTP client owns URL encoding. No
query text is logged or returned beyond the existing normalized tool result.

Version-specific comments that describe `0.3.2` response behavior are replaced
with current or version-neutral explanations where the behavior remains
relevant. The training-context failure vocabulary remains deliberately coarse:
the fork does not introduce unstable parsing of exception messages merely
because the dependency changed.

## Tests

Tests are added or updated before production/configuration changes to pin:

- Python `>=3.12`, GarminConnect `0.3.10`, MCP v1, and standard dependency
  groups in `pyproject.toml`;
- the CI matrix at Python 3.12 and 3.13;
- locked `garminconnect`, `click`, and `h11` versions at their safe minimums;
- the high-value Garmin APIs used by authentication, training context,
  activity analysis, and workout creation;
- clean nutrition endpoint paths with exact separate parameter dictionaries,
  including the opt-in live nutrition helpers;
- README, setup, workflow, training-context, and workout documentation matching
  the new runtime/client contract.

Normal verification is:

```text
focused dependency/CI/nutrition/docs tests
→ complete offline suite
→ uv lock --check
→ package build
→ pip-audit of the installed environment
→ git diff --check
```

The upgrade must leave no known vulnerabilities in the audited installed
environment. A scanner is not added to GitHub Actions in this PR; the existing
small, free CI workflow continues to verify the committed lock and package.

## Bounded live-read smoke test

After all offline checks pass, a live smoke test may run only when the normal
local Garmin token directory is already configured. It uses the upgraded
client and performs a small fixed set of reads covering token login, one recent
activity page, daily stats, workouts, and the scheduled-workout GraphQL seam.

The smoke test:

- performs no uploads, schedules, updates, deletes, or other writes;
- does not print names, activity data, tokens, headers, or raw responses;
- reports only success/failure, returned container types, and bounded counts;
- treats device-specific missing health data as non-fatal;
- is not part of normal tests or CI.

If tokens are absent, the live test is skipped and reported as such rather than
triggering an interactive login.

## Upstream compatibility

The fork keeps using raw GarminConnect provider results and its own bounded
normalizers. Changes outside dependency metadata, tests, and documentation are
limited to the query-path adaptation required by `0.3.10`. Authentication and
generic Garmin modules are not redesigned.

## Non-goals

- No `update_workout` or `move_workout` tool.
- No MCP 2.x migration.
- No typed GarminConnect response layer.
- No new AI-facing tools or profile changes.
- No permanent vulnerability-scanner or coverage service in CI.
- No unrelated upstream refactor.
