# AI-friendly workouts

`create_workout` is the small, user-facing seam for an AI coach. It accepts a
readable workout description in one call, validates it, uploads it to Garmin,
and optionally puts it on the calendar. Callers do not need to produce raw
Garmin workout DTOs.

## Create one workout

Pass `name`, `sport`, `steps`, and (optionally) `schedule_date` to
`create_workout`. This threshold example uses the friendly schema:

```json
{
  "name": "Threshold 4x6",
  "sport": "running",
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
  ],
  "schedule_date": "2026-09-01"
}
```

Supported sports are `running`, `cycling`, `walking`, and `strength`.
`strength_training` is accepted as a compatibility alias and normalized to
`strength`.
Actions are `warmup`, `cooldown`, `work`, `run`, `interval`, `recovery`, and
`rest`. A repeat group is `{ "repeat": 4, "steps": [...] }`; nested repeat
groups are allowed.

Every action has exactly one end condition:

- `duration`: a positive value such as `"30m"`, `"90s"`, or `"1h"`.
- `distance`: metres or kilometres, such as `"5km"`.
- `reps`: a positive integer, useful for strength steps.
- `lap_button`: `true` to let the athlete press the lap button to finish.

Targets are optional and deliberately constrained by sport:

There is at most one target field per action; do not combine pace,
heart-rate, and power targets on the same action.

- Running supports a pace range such as `"pace": "4:20-4:30/km"` (running
  only).
- Any sport can use a heart-rate zone (`"heart_rate_zone": "Z3"`) or a
  custom range (`"heart_rate": "130-150bpm"`).
- Cycling supports a power zone (`"power_zone": "Z4"`) or watt range
  (`"power": "220-260W"`) (cycling only).

For example, an easy walk can use
`{"recovery": {"duration": "45m", "heart_rate_zone": "Z2" }}` when
`sport` is `walking`, while a bike interval can use
`{ "work": { "duration": "8m", "power": "220-260W" } }`.

Strength `exercise` and `category` fields are pass-through metadata. Garmin
only retains an `exercise` value when it matches one of Garmin's exercise
keys; this seam does not translate free-form names. A supplied `category` is
also sent as-is and must be a category Garmin accepts.

## What the call does

The service follows this sequence:

1. Validate and normalize the friendly schema.
2. Compile the normalized definition to Garmin-shaped data.
3. Run `prepare_workout_for_upload` for the Taxuspt normalization and
   validation seam.
4. Upload with Garmin Connect.
5. If `schedule_date` is present, optionally schedule the uploaded workout.

Creation is intentionally non-transactional. A scheduling failure retains the
uploaded workout and never auto-deletes it; the response is
`partial_success` with the workout ID and scheduling error so an AI coach can
retry or explain what happened.

Typical concise responses are:

```json
{"status": "success", "workout_id": 101, "name": "Easy Run"}
```

```json
{"status": "success", "workout_id": 102, "name": "Threshold 4x6", "scheduled_date": "2026-09-01"}
```

```json
{"status": "error", "name": "Bad Run", "message": "invalid pace: expected M:SS-M:SS/km"}
```

```json
{
  "status": "partial_success",
  "workout_id": 103,
  "name": "Calendar Retry",
  "scheduled_date": "2026-09-01",
  "scheduling_error": "calendar rejected"
}
```

## The `ai-coach` tool profile

Set `GARMIN_TOOL_PROFILE=ai-coach` to expose exactly these 10 tools:

1. `create_workout`
2. `get_activities`
3. `get_activities_by_date`
4. `get_activity`
5. `get_workouts`
6. `get_workout_by_id`
7. `get_scheduled_workouts`
8. `schedule_workout`
9. `unschedule_workout`
10. `delete_workout`

Profile precedence is explicit: an explicitly configured
`GARMIN_ENABLED_TOOLS` allowlist overrides the profile; otherwise a profile
starts with its exact list and subtracts `GARMIN_DISABLED_TOOLS`. With the
profile unset, the default remains full upstream tool registration. The
`ai-coach` profile intentionally hides raw `upload_workout`, bulk
`upload_workouts`, and unrelated health, nutrition, device, and management
tools.

## Pinned API assumptions

This seam targets `garminconnect==0.3.2`. That upstream client provides
`upload_workout`, `schedule_workout`, `unschedule_workout`, and
`delete_workout`; it has no update method. A calendar schedule entry ID is
distinct from the workout ID: unscheduling needs the
`scheduled_workout_id`, while deletion needs the `workout_id`.

The primary references are the [python-garminconnect 0.3.2 package on
PyPI](https://pypi.org/project/garminconnect/0.3.2/) and its [upstream source on
GitHub](https://github.com/cyberjunky/python-garminconnect/tree/0.3.2).

## Update (deferred)

True update support is intentionally deferred. The desired operation is a
current-upstream whole-document `PUT` that preserves the existing workout ID
and its schedules, with a compatibility path for the pinned 0.3.2 client.
Until that seam exists, create a new workout rather than pretending that an
upload is an in-place update.

## Move (deferred)

Moving a scheduled workout must use its `scheduled_workout_id`: unschedule the
calendar entry, then schedule the same `workout_id` on the new date. Never
delete the workout template while moving it. Unschedule-then-schedule is not
transactional, so a second-call failure needs a partial-failure response and
manual recovery guidance.

## Training context (deferred)

A compact training-context aggregator is future work. It should combine the
small set of activities, scheduled workouts, and readiness signals an AI coach
needs without exposing every upstream endpoint or returning large raw payloads.

## Upstream compatibility

The new `ai_workouts` package is a minimal workouts seam. Existing
authentication and default registration remain unchanged, as do unrelated
upstream tools; adopting the feature is additive unless
`GARMIN_TOOL_PROFILE` is set.
