# AI Workouts v1 Design

## Objective

Add a narrow, LLM-friendly workout creation and optional scheduling layer on top
of the maintained Taxuspt Garmin integration. The first release must support one
high-level call for the threshold-workout example while preserving all existing
normalization and validation protections. It must not expose raw Garmin DTOs to
the AI or change the default upstream-compatible tool surface.

## Scope

V1 adds one new write tool:

```python
create_workout(name: str, sport: str, steps: list[dict], schedule_date: str | None = None)
```

It supports running, cycling, walking, and conservative strength workouts;
executable warmup, cooldown, work/run/interval, recovery, and rest steps;
nested repeat groups; time, distance, reps, and lap-button end conditions; and
pace, named heart-rate zone, custom heart-rate range, power zone, and absolute
power targets.

V1 also adds an opt-in `ai-coach` tool profile. It does not add high-level move,
update, unschedule, delete, training-context, or recent-training aggregation
tools. Existing safe read and intentional schedule/unschedule/delete tools may
be selected by the profile as interim capabilities, but raw upload and bulk
mutation tools are excluded.

## Architecture

Fork-specific behavior lives in a new `src/garmin_mcp/ai_workouts/` package:

- `schema.py` defines the normalized friendly workout model and validation
  vocabulary without adding a runtime dependency.
- `parsing.py` parses and validates intuitive unit and target strings.
- `compiler.py` lowers the validated model into canonical Garmin workout JSON.
- `service.py` owns upload and optional scheduling orchestration.
- `tools.py` registers the single AI-facing MCP tool.
- `__init__.py` exports the package's stable internal entry points.

The implementation makes only small changes to upstream-oriented modules:

- `workouts.py` exposes a reusable preparation function that deep-copies a
  payload, then calls the existing normalization, end-condition validation, and
  target validation functions. It also exposes one reusable idempotent schedule
  operation so the new service does not duplicate Taxuspt scheduling behavior.
- `garmin_mcp/__init__.py` configures/registers the new package and resolves an
  optional named tool profile through the existing `_ToolFilter`.

No authentication, token, generic Garmin proxy, or dependency behavior changes.
The project remains pinned to `garminconnect==0.3.2`.

## Friendly Schema

The MCP call uses a compact action/repeat DSL. Every list item contains exactly
one action key or a repeat group.

```json
{
  "name": "Threshold 4x6",
  "sport": "running",
  "schedule_date": "2026-08-10",
  "steps": [
    {"warmup": {"duration": "15m"}},
    {
      "repeat": 4,
      "steps": [
        {"run": {"duration": "6m", "pace": "4:20-4:30/km"}},
        {"recovery": {"duration": "2m"}}
      ]
    },
    {"cooldown": {"duration": "10m"}}
  ]
}
```

Accepted sports are `running`, `cycling`, `walking`, and `strength`.
`strength_training` is accepted as a compatibility alias. The compiler maps
these to centralized Garmin sport ID/key pairs and uses walking ID 12, matching
the repository's working template and tests rather than its stale upload-tool
documentation.

Accepted action keys are `warmup`, `cooldown`, `work`, `run`, `interval`,
`recovery`, and `rest`. The aliases `work`, `run`, and `interval` all lower to
Garmin's interval step type. `recovery` and `rest` remain distinct step types.

Each executable action must contain exactly one end condition:

- `duration`: `"15m"`, `"90s"`, or another positive seconds/minutes/hours value.
- `distance`: `"800m"` or `"5km"`.
- `reps`: a positive integer.
- `lap_button`: the boolean value `true`.

Each action may contain at most one target:

- `pace`: a running range such as `"4:20-4:30/km"`. Walking pace is deferred
  until its Garmin target representation is verified.
- `heart_rate_zone`: `"Z1"` through `"Z5"` or the integers 1 through 5.
- `heart_rate`: a custom range such as `"150-165bpm"`.
- `power_zone`: `"Z1"` through `"Z7"` or the integers 1 through 7, for cycling.
- `power`: an absolute cycling range such as `"220-250W"`.

Strength work steps may add `exercise` and an optional `category`. Values are
trimmed and passed through without guessing Garmin exercise identifiers. An
invalid Garmin catalog value may still be rejected by Garmin; the documentation
must make that limitation explicit.

The schema is extensible through parser/compiler registries keyed by end
condition and target name. The normalized model represents an end condition and
target independently of their input spelling. Cadence, RPE metadata, or
open-ended warmups can therefore be added as new handlers without changing the
top-level tool signature or existing fields.

## Validation and Compilation

Validation rejects:

- an unsupported sport or action;
- an empty workout or repeat group;
- an action/repeat object with unknown or conflicting structural keys;
- non-positive durations, distances, reps, or repeat counts;
- malformed or inverted pace, heart-rate, or power ranges;
- multiple targets or end conditions on one action;
- pace on unsupported sports;
- power targets outside cycling;
- strength exercise metadata on non-strength workouts;
- a malformed or impossible ISO calendar date.

Compilation uses centralized constants for Garmin DTO types, sport types, step
types, end-condition IDs/keys, and target IDs/keys. It emits:

- `ExecutableStepDTO` for actions;
- `RepeatGroupDTO` for repeats, always with `numberOfIterations`,
  `endConditionValue`, and end condition ID/key 7/`iterations`;
- segment-local step ordering beginning at 1, including ordering within repeats;
- target values at the executable-step level, never inside `targetType`;
- no-target ID/key 1/`no.target` when a friendly target is absent.

Pace is converted from minutes per kilometre to metres per second. Garmin's pace
range uses the faster speed in `targetValueOne` and slower speed in
`targetValueTwo`, so `4:20-4:30/km` becomes approximately 3.8462 and 3.7037 m/s.
Named HR and power zones use `zoneNumber`; custom HR and watt ranges use
`targetValueOne` and `targetValueTwo`. The compiler never mixes the two forms.

The compiler produces Garmin JSON but does not write it. Before upload,
`prepare_workout_for_upload()` deep-copies the result and invokes, in order:

1. `_normalize_workout_steps`
2. `_validate_end_condition_steps`
3. `_validate_target_type_steps`

This preparation gate is mandatory in the service and is independently tested.

## Write Orchestration

`create_workout` performs this sequence:

1. Validate and normalize the friendly input.
2. Compile it into Garmin JSON.
3. Prepare it through the existing Taxuspt normalization/validation gate.
4. Call `garmin_client.upload_workout`.
5. Require a returned `workoutId`.
6. If `schedule_date` is present, call the shared idempotent scheduling helper.
7. Return a concise structured result encoded as JSON text, consistent with the
   repository's existing MCP tools.

Successful upload without scheduling returns:

```json
{"status":"success","workout_id":123456789,"name":"Threshold 4x6"}
```

Successful upload and scheduling returns:

```json
{
  "status":"success",
  "workout_id":123456789,
  "name":"Threshold 4x6",
  "scheduled_date":"2026-08-10"
}
```

If validation, compilation, preparation, or upload fails, the tool returns
`status: "error"` and does not schedule. If upload succeeds but scheduling
fails, it returns `status: "partial_success"`, preserves and reports the new
workout ID, and includes `requested_date` plus a concise scheduling error. It
does not return `scheduled_date` unless Garmin confirmed the calendar operation.
The service never deletes an uploaded workout as an attempted rollback because
the two Garmin calls are not transactional and cleanup can also fail.

Scheduling retains Taxuspt's GraphQL pre-check. An already-scheduled workout/date
pair is a successful idempotent no-op and must not issue a second POST. If the
pre-check itself fails, current Taxuspt behavior fails open to the normal POST;
the new layer does not add blind retries.

## Curated MCP Profile

`GARMIN_TOOL_PROFILE=ai-coach` resolves to a maintained allowlist through the
existing filter. Explicit `GARMIN_ENABLED_TOOLS` remains the strongest user
override. When no explicit allowlist is set, the profile supplies the allowlist
and `GARMIN_DISABLED_TOOLS` may subtract entries from it. Leaving the profile
unset preserves the existing allowlist/denylist behavior and the default of
registering all upstream tools.

The v1 profile includes:

- `create_workout`
- `get_activities`
- `get_activities_by_date`
- `get_activity`
- `get_workouts`
- `get_workout_by_id`
- `get_scheduled_workouts`
- `schedule_workout`
- `unschedule_workout`
- `delete_workout`

It excludes `upload_workout`, all bulk workout mutations, legacy high-level
builders, activity mutations, unrelated Garmin mutations, and all authentication
or credential-management entry points. Future releases can replace interim read
names with compact `get_recent_training`, `get_training_context`,
`get_workout_calendar`, and `get_workout` tools without changing the friendly
workout schema.

## Deferred Semantics

Update is deliberately deferred. The pinned SDK has no `update_workout` method.
Current `python-garminconnect` supports a whole-document `PUT` to
`/workout-service/workout/{workout_id}` that preserves the workout ID and its
calendar references. A future compatibility helper should prefer the library
method when available and use the same endpoint through `.client.put(...,
api=True)` on 0.3.2. It must prepare the complete replacement payload through
the same safety gate.

Move is deliberately deferred. It must identify the calendar entry by
`scheduled_workout_id`, retain the separate `workout_id`, unschedule only the
calendar entry, and schedule the same workout on the new date. Because the two
calls are non-transactional, a future implementation must report partial failure
and enough identifiers for manual recovery; it must never delete the underlying
workout template.

Training context is also deferred. Its future aggregator should depend on small
read-only provider functions and return a compact coaching snapshot rather than
expose many Garmin endpoints directly.

## Tests

Pure unit tests cover:

1. simple easy workout;
2. warmup, continuous work, and cooldown;
3. time-based repeats;
4. distance-based repeats;
5. pace conversion and Garmin bound ordering;
6. named HR zone;
7. custom HR range;
8. malformed duration;
9. malformed pace;
10. invalid repeat count;
11. complete Garmin JSON generation;
12. cycling power zone and absolute power range;
13. walking compilation;
14. feasible strength reps/exercise compilation;
15. laps, reps, incompatible targets, ambiguity, and impossible dates;
16. compiled examples passing the shared Taxuspt preparation gate.

Mocked integration tests cover create-only, create-and-schedule, returned ID,
validation before write, upload failure, missing upload ID, schedule partial
success, idempotent scheduling behavior, MCP argument/response shape, and profile
inclusion/exclusion. No normal test requires a Garmin account. Verification runs
the focused new tests followed by `uv run pytest -m "not e2e"`.

## Documentation and Upstream Compatibility

The README documents the new profile and links to focused friendly-schema
documentation. A fork-specific document describes supported fields, examples,
failure semantics, pinned API assumptions, and deferred work. Existing Taxuspt
tools remain in place and default registration remains unchanged.

The feature is implemented and reviewed on `feat/ai-workouts-v1`. The final
delivery is a draft pull request against `main`; nothing is pushed directly to
`main`.

## API Evidence

- The repository pins
  [`garminconnect==0.3.2`](https://github.com/cyberjunky/python-garminconnect/releases/tag/0.3.2),
  which supports upload, schedule, unschedule, and delete but not update.
- Current
  [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/__init__.py)
  adds whole-document workout update while preserving the workout ID.
- The maintained
  [`Taxuspt/garmin_mcp`](https://github.com/Taxuspt/garmin_mcp)
  supplies the normalization, validation, authentication, and calendar-ID
  distinctions reused here.
- The narrow-surface philosophy follows
  [`brunosantos/garmin-workouts-mcp`](https://github.com/brunosantos/garmin-workouts-mcp)
  without adopting its Garmin integration implementation.
