# AI Activity Zone Payload Fix Implementation Plan

> **For agentic workers:** Execute each task test-first and verify the complete
> offline suite before opening a ready-for-review pull request.

**Goal:** Preserve Garmin zone numbers and durations returned under the pinned
client's real aliases, while preventing unsupported AI interpretations.

**Architecture:** Extend the existing shared zone normalizer in
`ai_activity/service.py`. Keep provider reads, the stable response envelope, and
all upstream-oriented modules unchanged. Update only the high-level tool
metadata and activity-analysis guide to clarify evidence limits.

**Tech stack:** Python 3.10+, pytest, FastMCP, uv.

## Task 1: Pin the real Garmin zone payload

**Files:**

- Modify: `tests/unit/ai_activity/test_service.py`
- Modify: `src/garmin_mcp/ai_activity/service.py`

1. Add a five-zone regression using `zoneNumber`, `secsInZone`, and
   `zoneLowBoundary`, including zero-second zones.
2. Run the test and confirm it fails because zone numbers and durations are
   currently null.
3. Add alias-aware normalization that preserves zeros and does not invent
   percentage or upper bounds.
4. Run the focused service tests and confirm they pass.

## Task 2: Pin the AI interpretation boundary

**Files:**

- Modify: `tests/integration/test_ai_activity_tools.py`
- Modify: `tests/unit/test_ai_activity_docs.py`
- Modify: `src/garmin_mcp/ai_activity/tools.py`
- Modify: `docs/ai-activity.md`

1. Add FastMCP metadata and documentation assertions for authoritative returned
   zone durations, no lap-average time-in-zone estimates, and no drift or
   decoupling claims from split averages.
2. Run those tests and confirm the new assertions fail.
3. Update the tool docstring and guide with the bounded interpretation rules
   and supported raw aliases.
4. Re-run the focused tests and confirm they pass.

## Task 3: Verify and deliver

1. Run the focused activity-analysis service, MCP, and documentation tests.
2. Run `uv run pytest -m "not e2e" -q`.
3. Run `uv build` and inspect the working-tree diff.
4. Commit the implementation, push the feature branch, and open a non-draft PR
   against `main`.
5. Confirm the GitHub Actions checks pass.
