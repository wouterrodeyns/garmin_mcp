# Cycling Power Target Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every workout write path encodes absolute cycling watt ranges
as Garmin target ID `2` / `power.zone`, while rejecting the legacy target ID
`6` / `power.between` representation before upload.

**Architecture:** Keep the friendly schema unchanged. Update its compiler to
emit the verified Garmin DTO, then strengthen the existing shared Taxuspt
normalization/validation boundary so friendly, raw, batch, scheduling,
secondary-target, and nested-repeat writes all receive the same protection.
Update the existing low-level guidance rather than adding another abstraction.

**Tech Stack:** Python 3.10+, pytest, FastMCP, uv.

---

## Task 1: Compile friendly watt ranges to the canonical Garmin target

**Files:**

- Modify: `tests/unit/ai_workouts/test_compiler.py`
- Modify: `src/garmin_mcp/ai_workouts/compiler.py`

- [ ] Change the existing cycling power regression so that both named zones
  and absolute watts use target ID `2` / `power.zone`, while asserting their
  payload shapes remain unambiguous:

```python
assert zone_step["targetType"] == {
    "workoutTargetTypeId": 2,
    "workoutTargetTypeKey": "power.zone",
}
assert zone_step["zoneNumber"] == 4
assert "targetValueOne" not in zone_step

assert watts_step["targetType"] == {
    "workoutTargetTypeId": 2,
    "workoutTargetTypeKey": "power.zone",
}
assert watts_step["targetValueOne"] == 220.0
assert watts_step["targetValueTwo"] == 250.0
assert "zoneNumber" not in watts_step
```

- [ ] Run the single compiler test and confirm RED because the watt step still
  emits ID `6` / `power.between`:

```bash
uv run pytest tests/unit/ai_workouts/test_compiler.py::test_compile_cycling_power_zone_and_watts_use_distinct_canonical_ids -q
```

- [ ] Change `_power_target()` to use `_bounds_target(target, 2,
  "power.zone")`.
- [ ] Re-run the compiler test and the complete compiler module; confirm GREEN:

```bash
uv run pytest tests/unit/ai_workouts/test_compiler.py -q
```

- [ ] Commit:

```bash
git add src/garmin_mcp/ai_workouts/compiler.py tests/unit/ai_workouts/test_compiler.py
git commit -m "fix(ai-workouts): compile watt ranges as power targets"
```

## Task 2: Protect every workout write path at shared validation

**Files:**

- Modify: `tests/integration/test_workouts_tools.py`
- Modify: `src/garmin_mcp/workouts.py`

- [ ] Replace tests that endorse ID `6` / `power.between` with regressions that
  prove:

  - ID `2` / `power.zone` accepts either zone `1..7` or complete watt bounds;
  - the legacy `power.between` key is rejected with the migration guidance for
    missing, ID `6`, and unknown numeric IDs;
  - ID `6` / `pace.zone` remains valid;
  - custom bounds are checked in primary, secondary, and nested repeat steps;
  - invalid custom values include missing or one-sided bounds, booleans,
    strings, infinity, NaN, negatives, and reversed bounds;
  - invalid zones include booleans, non-integral numbers, and values outside
    `1..7`;
  - mixing a zone number and watt bounds is rejected.

- [ ] Run only the new/reworked power tests and confirm RED on the old mapping
  and missing shape checks:

```bash
uv run pytest tests/integration/test_workouts_tools.py -q -k "power_target or power_between or power_zone"
```

- [ ] Narrow the known mapping and add an explicit legacy-key rejection:

```python
KNOWN_TARGET_TYPE_IDS[6] = frozenset(["pace.zone"])

REJECTED_TARGET_TYPE_KEYS = {
    "power.between": (
        "use workoutTargetTypeId 2 / 'power.zone' with step-level "
        "targetValueOne/targetValueTwo and no zoneNumber for absolute watts"
    ),
}
```

- [ ] Add a helper that resolves a missing target key only when a known ID has
  exactly one canonical key. Add a power-shape validator that checks the
  primary and secondary field layouts after nested target fields have been
  normalized.
- [ ] Reject `power.between` before numeric ID/key-pair validation so every
  legacy form gets the same actionable error.
- [ ] Keep unknown target IDs permissive unless they use the explicitly unsafe
  legacy key.
- [ ] Re-run the focused power tests, then the entire low-level workout
  integration module; confirm GREEN:

```bash
uv run pytest tests/integration/test_workouts_tools.py -q
```

- [ ] Commit:

```bash
git add src/garmin_mcp/workouts.py tests/integration/test_workouts_tools.py
git commit -m "fix(workouts): validate cycling power target shapes"
```

## Task 3: Correct all AI- and user-facing target guidance

**Files:**

- Modify: `tests/unit/test_ai_workouts_docs.py`
- Modify: `src/garmin_mcp/workouts.py`
- Modify: `src/garmin_mcp/workout_templates.py`
- Modify: `README.md`
- Modify if necessary: `docs/ai-workouts.md`

- [ ] Add documentation regressions that pin ID `2` / `power.zone` for both
  power forms, ID `6` / `pace.zone` only, and explicit rejection of
  `power.between`. Assert no live guidance recommends the legacy mapping.
- [ ] Run the documentation tests and confirm RED against the current guidance:

```bash
uv run pytest tests/unit/test_ai_workouts_docs.py -q
```

- [ ] Update low-level tool docstrings, reference tables, README examples, and
  the AI-workout guide only where they mention native target DTOs. Preserve the
  friendly input syntax `"power": "220-250W"`.
- [ ] Re-run documentation, compiler, AI-workout integration, and low-level
  workout tests; confirm GREEN:

```bash
uv run pytest \
  tests/unit/ai_workouts/test_compiler.py \
  tests/integration/test_ai_workouts_tools.py \
  tests/integration/test_workouts_tools.py \
  tests/unit/test_ai_workouts_docs.py -q
```

- [ ] Commit:

```bash
git add README.md docs/ai-workouts.md src/garmin_mcp/workouts.py \
  src/garmin_mcp/workout_templates.py tests/unit/test_ai_workouts_docs.py
git commit -m "docs(workouts): correct cycling power target guidance"
```

## Task 4: Verify and deliver

- [ ] Confirm no obsolete recommendation remains:

```bash
rg -n "power\.between|workoutTargetTypeId 6" README.md docs src tests
```

  Remaining `power.between` occurrences must be only the rejection constant,
  migration guidance, and negative tests.

- [ ] Run the full offline test suite:

```bash
uv run pytest -m "not e2e" -q
```

- [ ] Build the package and verify repository hygiene:

```bash
uv build
git diff --check main...HEAD
git status --short
```

- [ ] Push `fix/cycling-power-targets` and open a ready-for-review (not draft)
  pull request against `main`.
- [ ] Confirm GitHub Actions passes and report the exact test/build evidence in
  the PR and handoff.
