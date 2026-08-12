# AI-Friendly Workout Update v1 Design

## Objective

Add one high-level MCP tool that lets an AI coach modify an existing regular
Garmin workout without generating raw Garmin DTO JSON:

```python
update_workout(
    workout_id,
    name=None,
    sport=None,
    steps=None,
)
```

The tool uses patch-style top-level inputs. It fetches the complete existing
workout, applies only the requested friendly changes, compiles any replacement
steps, passes the complete result through Taxuspt's existing workout
normalization and validation, and calls GarminConnect's true in-place update.

The outcome keeps the workout ID. Garmin calendar entries that already point
at that ID therefore remain scheduled. The tool never uploads a replacement,
deletes a workout, or mutates the calendar.

## Product boundary

This feature extends the fork's narrow workout-writing surface. It does not
expose Garmin's raw whole-document PUT or require the AI to reconstruct Garmin
DTOs. The intended workflows are:

```text
"Rename tomorrow's workout"
    -> identify its workout_id
    -> update_workout(workout_id=..., name="Easy aerobic run")

"Change it from 4 x 6 minutes to 5 x 5 minutes"
    -> identify its workout_id
    -> update_workout(workout_id=..., steps=[friendly steps])
```

`workout_id` is the underlying workout-template ID returned by `get_workouts`,
`get_workout_by_id`, or `get_scheduled_workouts`. It is not the
`scheduled_workout_id` used by `unschedule_workout`.

V1 modifies only regular numeric workouts in the four sports already supported
by the friendly compiler:

- running;
- cycling;
- walking;
- strength (`strength_training` is accepted as its Garmin alias).

UUID-based Garmin Coach/adaptive-plan workouts and unsupported sports are
rejected rather than converted approximately.

## Considered approaches

### 1. Patch-style top-level fields — selected

The server fetches the existing whole document and lets the caller provide
only a new name and/or friendly steps. This gives the AI a natural operation
while retaining Garmin's required complete-document PUT internally.

### 2. Full friendly replacement

Require `workout_id`, `name`, `sport`, and all steps on every call. This is
smaller internally, but it forces the AI to recreate unchanged content and
increases accidental-loss risk.

### 3. Step-addressed patch language

Add operations such as `replace_step`, `change_repeat_count`, and
`insert_after`. This would require stable addressing across Garmin step IDs,
repeat groups, and freshly compiled structures. It is too large and fragile
for v1.

## Verified GarminConnect contract

The pinned `garminconnect==0.3.10` client exposes:

```python
update_workout(
    workout_id: int | str,
    workout_json: dict[str, Any] | str,
) -> dict[str, Any]
```

The tagged implementation validates a positive ID, requires a complete JSON
object, forces `workoutId` in the body to the requested ID, and issues a PUT to
`/workout-service/workout/{workout_id}`. Its documented contract is that the
workout keeps its ID and existing schedules remain valid. The client does not
mutate the caller's input dictionary.

The feature must call this public client method. It must not reconstruct the
URL or call `client.client.put` directly.

## Architecture

The feature remains inside the fork-owned `ai_workouts` package:

```text
src/garmin_mcp/ai_workouts/
    schema.py       existing friendly validation
    compiler.py     existing Garmin DTO compiler
    service.py      create + new update orchestration
    tools.py        create_workout + new update_workout MCP tools
```

No new upstream-oriented module is required. `workouts.py` remains the single
source of Taxuspt normalization and Garmin-specific validation through
`prepare_workout_for_upload`.

The update data flow is:

```text
strict update request validation
        -> client.get_workout_by_id(workout_id)
        -> validate existing regular workout shape and supported sport
        -> apply name-only patch OR compile friendly replacement steps
        -> prepare_workout_for_upload
        -> client.update_workout(workout_id, complete_payload)
        -> compact structured result
```

The service performs the calls sequentially. It makes exactly one initial read
and at most one PUT. It never invokes MCP tools internally.

## AI-facing input contract

### Workout identifier

`workout_id` accepts a positive integer or an ASCII decimal string. String
whitespace is trimmed before parsing. The service rejects:

- booleans;
- zero and negative integers;
- floats, including integer-valued floats;
- empty strings;
- signs, decimal points, exponents, separators, UUIDs, and non-ASCII digits;
- lists, objects, and every other type.

The MCP annotation uses strict integer-or-string types so FastMCP cannot coerce
JSON `true` or `1.0` into workout ID `1`. The service repeats validation as a
defense-in-depth contract for direct callers.

### Patch fields

At least one mutable field must be supplied:

- `name`: optional non-empty string, trimmed before use;
- `steps`: optional non-empty list using the exact existing friendly workout
  schema;
- `sport`: optional friendly sport string, permitted only when `steps` is also
  supplied.

Supplying only `sport`, or supplying `sport` with only a name change, is
rejected. Changing a sport while retaining old sport-specific Garmin steps is
unsafe.

When `steps` is present and `sport` is omitted, the current supported sport is
inherited. When `name` is omitted, the current non-empty workout name is
inherited. The service does not accept `schedule_date`; scheduling is a
separate concern.

The caller-owned `steps` list and every fetched provider object remain
unmodified.

## Existing-workout validation

The service calls `client.get_workout_by_id(normalized_id)` before any write.
The response must be a normal built-in dictionary containing:

- a `workoutId` that normalizes to the requested ID;
- a non-empty `workoutName`;
- a built-in `sportType` dictionary with a supported canonical sport key;
- a non-empty built-in `workoutSegments` list.

Malformed, absent, mismatched, or unsupported responses produce a sanitized
pre-write error. No PUT occurs.

The supported raw sport-key mapping is centralized:

```text
running            -> running
cycling            -> cycling
walking            -> walking
strength_training  -> strength
```

V1 does not infer a sport from numeric IDs, substrings, segment content, or
display names.

## Patch construction

### Rename-only update

For `name` without `steps`, the service deep-copies the complete fetched
workout and changes only `workoutName`. This follows the pinned client's own
whole-document rename example and preserves existing Garmin fields and step
IDs.

The copied document still runs through `prepare_workout_for_upload` before the
PUT. Existing target and end-condition protections therefore remain active.

### Replacement-step update

When `steps` is supplied, the service:

1. chooses the supplied or inherited name;
2. chooses the supplied or inherited friendly sport;
3. calls the existing `validate_workout` with no schedule date;
4. calls the existing `compile_workout`;
5. passes the compiled document through `prepare_workout_for_upload`.

This is a deliberate full replacement of the workout's step structure. Old
step IDs, estimates, created/updated timestamps, and provider-computed fields
are not copied into the new structure because they may be stale or
server-owned. A valid existing string `description` may be retained as
compatible user-authored metadata. No other top-level metadata is preserved
without verified semantics.

The pinned client injects the requested `workoutId` into the final body.

## Garmin normalization and safety

Every update payload passes through `prepare_workout_for_upload` immediately
before the client update. The feature does not bypass or duplicate Taxuspt's
protections for:

- malformed repeat groups;
- target fields nested in the wrong DTO location;
- named HR zones versus custom HR ranges;
- target ID/key mismatches;
- end-condition ID/key mismatches;
- pace bound ordering;
- cycling power-zone versus absolute-watt shapes;
- recursive Garmin DTO structure.

Replacement steps inherit all friendly-schema safety limits, including one
repeat level, at most 50 repeat iterations, 24-hour end conditions, and
500-kilometre distance conditions.

## Response contract

### Success

Success requires a built-in dictionary response with a `workoutId` that
normalizes to the requested ID:

```json
{
  "status": "success",
  "workout_id": 123456789,
  "name": "Threshold 5x5",
  "sport": "running",
  "schedules_preserved": true
}
```

The result uses the effective submitted name and sport. It does not copy
arbitrary Garmin response fields.

### Pre-write errors

Invalid input, a missing client, a failed existing-workout read, or an invalid
existing-workout response returns:

```json
{
  "status": "error",
  "workout_id": 123456789,
  "message": "Could not retrieve a valid existing workout from Garmin."
}
```

Validation errors may use precise messages derived from caller-provided data.
Provider failures use fixed messages and never include exception text, tokens,
headers, URLs, request IDs, or raw Garmin payloads. These paths guarantee that
the PUT was not called.

### Ambiguous write outcomes

The service never automatically retries a PUT. A connection failure can occur
after Garmin applied the write, and blind mutation retries obscure the actual
state.

If `client.update_workout` raises, the service returns `status: "error"` with
the requested ID, a fixed message, and:

```json
{
  "update_may_have_applied": true
}
```

The message directs the caller to read the workout before retrying.

If the client call returns but its response is not a built-in dictionary, has
no usable workout ID, or reports a different ID, the service returns:

```json
{
  "status": "partial_success",
  "workout_id": 123456789,
  "name": "Threshold 5x5",
  "sport": "running",
  "schedules_preserved": true,
  "message": "Garmin returned an unexpected update response; read the workout before retrying."
}
```

This reflects that the HTTP update call returned but its confirmation was not
trustworthy. The response does not echo malformed provider content.

## Read and write guarantees

The complete update path is permitted to call only:

```text
get_workout_by_id
update_workout
```

It must never call:

```text
upload_workout
schedule_workout
unschedule_workout
delete_workout
client.post
client.delete
client.put
```

The final `client.put` entry means direct raw-client access; the public
`client.update_workout` method remains the one intended write.

Tests use a recording allowlist client plus actively invoked forbidden-call
traps. They prove that validation and read failures cause zero writes, and that
all successful and ambiguous write paths make exactly one in-place update.

## MCP and profile integration

`ai_workouts.tools.register_tools` registers `update_workout` beside
`create_workout`. Both tools share the configured proxied Garmin client and the
existing friendly step documentation.

`GARMIN_TOOL_PROFILE=ai-coach` adds `update_workout` atomically with tool
registration. The exact profile grows from 12 to 13 tools. Default broad
registration and explicit allowlist/denylist precedence remain unchanged.

The MCP metadata documents:

- patch-style semantics;
- supported sports and friendly units;
- `workout_id` versus `scheduled_workout_id`;
- whole-document PUT behavior hidden by the service;
- schedule preservation;
- the need to read after an ambiguous write result.

## Test strategy

Normal tests use mocks and fixtures and require no Garmin account. Production
changes are written only after the corresponding new test has failed for the
expected reason.

Coverage includes:

1. strict accepted integer and ASCII-decimal-string IDs;
2. rejection of booleans, floats, UUIDs, zero, negative, malformed, and
   non-ASCII IDs before provider access;
3. rejection of an empty patch and `sport` without `steps`;
4. rename-only preservation of the fetched whole document;
5. replacement steps inheriting the existing name and sport;
6. simultaneous name, sport, and step replacement;
7. repeat, pace, named/custom HR, and cycling-power compilation through
   `prepare_workout_for_upload`;
8. retention only of the documented compatible description for replacement
   steps;
9. removal of stale estimates, timestamps, provider fields, and old step IDs;
10. unsupported existing sports and malformed/mismatched fetched responses;
11. read exceptions mapped to fixed pre-write errors;
12. update exceptions mapped to fixed ambiguous-write errors;
13. malformed, missing-ID, and mismatched-ID update responses mapped to
    `partial_success`;
14. no mutation of caller or provider inputs;
15. exact read/write call budgets and forbidden operation traps;
16. FastMCP omitted/explicit argument shapes and strict ID behavior;
17. concise MCP JSON return shapes;
18. exact 13-tool `ai-coach` profile registration;
19. startup configure/register wiring;
20. documentation examples and no stale claims that update remains deferred.

Verification runs focused AI-workout, startup/profile, and documentation tests,
then:

```bash
uv run pytest -m "not e2e"
```

The branch also runs `git diff --check` and builds the wheel to prove the
updated package is included.

## Documentation

Update `README.md` and `docs/ai-workouts.md` to explain:

- the 13-tool AI-coach profile;
- patch-style rename and step-replacement examples;
- the friendly schema is shared with `create_workout`;
- update preserves the workout ID and existing schedules;
- update does not move, unschedule, duplicate, or delete a workout;
- the distinction between workout and calendar-entry IDs;
- ambiguous write results must be verified with `get_workout_by_id` before a
  retry;
- Garmin Coach/adaptive and unsupported-sport updates remain outside v1.

The prior "Update (deferred)" section is replaced with the implemented
contract. Move-workout remains deliberately deferred.

## Upstream compatibility

The implementation stays in the existing fork-owned `ai_workouts` package and
uses only public methods from the pinned client plus Taxuspt's
`prepare_workout_for_upload`. Authentication, generic Garmin modules, raw
workout tools, and scheduling helpers are not refactored.

The upstream PR that exposes a raw update tool is not cherry-picked. This fork
adopts only the verified in-place API seam while preserving its narrow,
LLM-friendly surface.

## Non-goals

- No raw Garmin DTO argument.
- No schedule date argument.
- No move, schedule, unschedule, upload, replacement-create, or delete flow.
- No UUID/adaptive Garmin Coach workout updates.
- No swimming or other new friendly workout sport.
- No step-addressed patch language.
- No conversion of arbitrary existing Garmin steps back into the friendly DSL.
- No automatic retry after an ambiguous write outcome.
- No live Garmin write in normal tests or CI.
- No redesign of `create_workout` or its existing response contract.
