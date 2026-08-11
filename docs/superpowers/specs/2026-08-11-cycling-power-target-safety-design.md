# Cycling Power Target Safety Design

## Problem

Garmin treats `workoutTargetTypeId` as authoritative. The current compiler and
shared workout normalizer encode an absolute cycling watt range as target ID
`6` with key `power.between`. Live Garmin Connect, FIT, and device validation in
Taxuspt issue #245 and PR #194 shows that ID `6` is a pace/speed target. A bound
such as `240` is therefore interpreted as 240 m/s and can appear on a watch as
864 km/h.

The friendly `create_workout` path currently compiles this unsafe shape and the
required Taxuspt normalization layer accepts it. Low-level upload and scheduling
paths can accept it as well.

## Decision

Apply full-path safety rather than protecting only the friendly compiler.

- Absolute cycling watts use target ID `2`, key `power.zone`, complete
  step-level `targetValueOne` and `targetValueTwo` bounds, and no `zoneNumber`.
- Named FTP zones keep target ID `2`, key `power.zone`, one `zoneNumber` from 1
  through 7, and no custom bounds.
- Target ID `6` maps only to `pace.zone` and remains available for legitimate
  pace/speed guidance.
- The obsolete `power.between` key is rejected before a Garmin write, even when
  its numeric ID is missing or misleading. The error explains the safe ID `2`
  migration.

This intentionally makes legacy unsafe payloads fail instead of silently
creating a speed target.

## Architecture and data flow

The high-level path remains:

```text
friendly workout schema
→ ai_workouts compiler
→ Taxuspt prepare_workout_for_upload normalization and validation
→ Garmin upload
→ optional scheduling
```

`ai_workouts/compiler.py` emits the safe canonical Garmin DTO. The shared
validation in `workouts.py` remains the final protection for friendly, raw,
batch, inline-scheduling, primary-target, secondary-target, and repeat-group
paths. No Garmin client, authentication, tool-profile, or package changes are
required.

## Validation contract

For ID `2` / `power.zone`, the shared validator accepts exactly one form:

1. a named zone: integer `zoneNumber` from 1 through 7; or
2. a custom watt range: two finite, numeric, non-negative bounds whose low
   value does not exceed the high value.

It rejects missing values, incomplete ranges, booleans, numeric strings,
non-finite values, negative values, reversed bounds, and a payload that mixes a
zone number with custom bounds. The same rules apply to secondary target fields
and nested executable steps. Unknown Garmin target IDs remain permissive so the
partial mapping does not block unrelated valid targets.

## Compatibility

The fork will adapt the verified behavior of Taxuspt PR #194 without waiting
for it to merge. Changes to upstream-oriented `workouts.py` stay narrowly
limited to the target mapping, power validation, and user-facing guidance so a
future upstream sync remains straightforward.

Existing friendly workout syntax does not change:

```json
{"work": {"duration": "10m", "power": "220-250W"}}
```

Only the compiled Garmin representation changes. Named power zones and pace
targets retain their existing public behavior.

## Tests

Test-first regressions must cover:

- friendly absolute watts compile to ID `2` / `power.zone` with ordered bounds;
- named zones and custom watts remain distinct, unambiguous forms;
- legacy `power.between` is rejected before upload;
- custom watt validation covers primary, secondary, and nested repeat targets;
- valid ID `6` / `pace.zone` remains accepted;
- tool documentation no longer recommends the unsafe mapping;
- all existing AI-workout and Taxuspt workout tests remain green.

Normal verification includes focused tests, the complete offline suite, package
build, `git diff --check`, and the repository CI matrix. No live Garmin account
is required for this PR because the device/FIT behavior is already established
by the upstream live validation.

## Non-goals

- No dependency upgrade or security-audit changes.
- No workout update/move implementation.
- No automatic migration of stored workouts already uploaded with the unsafe
  target.
- No automatic retries or timeout changes for Garmin writes.
- No new MCP tools or changes to the `ai-coach` profile.
