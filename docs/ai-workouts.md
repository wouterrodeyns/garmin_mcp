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
`rest`. A repeat group is `{ "repeat": 4, "steps": [...] }`. One repeat level
is supported: its `steps` must be actions, not repeat groups. Repeat counts are
integers from 1 through 50; nested repeat groups are not supported.

Every action has exactly one end condition:

- `duration`: a positive value such as `"30m"`, `"90s"`, or `"1h"`.
- `distance`: metres or kilometres, such as `"5km"`.
- `reps`: a positive integer, useful for strength steps.
- `lap_button`: `true` to let the athlete press the lap button to finish.

Units are field-specific: `m` means minutes only for `duration` (for example,
`"15m"`), and `m` means metres only for `distance` (for example, `"800m"`).
Do not use distance notation as a duration. V1 safety limits are one repeat
level, at most 50 repeat iterations, duration of at most 24h, distance of at
most 500km, and a custom heart-rate range whose low value is at least 30 bpm.

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

To create a workout without scheduling, omit `schedule_date` or pass `null`.
An empty string is invalid; scheduled dates must use canonical `YYYY-MM-DD`.

## Native Garmin cycling power targets

Callers of `create_workout` should keep using the friendly `power_zone` and
`power` fields above; the compiler handles Garmin's native representation.
Both forms use `workoutTargetTypeId` `2` with key `power.zone`. A named FTP
zone uses `zoneNumber` from 1 through 7, while an absolute watt range uses
step-level `targetValueOne` and `targetValueTwo` with no `zoneNumber`.

ID `6` is Garmin's `pace.zone` speed target. The obsolete `power.between` key
is rejected before upload because pairing watts with ID `6` makes Garmin
interpret them as speed and display distance-per-time units instead of watts.

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
retry or explain what happened. Partial results use `requested_date` to avoid
claiming that Garmin scheduled the workout when the calendar operation failed.

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
  "requested_date": "2026-09-01",
  "scheduling_error": "calendar rejected"
}
```

## The `ai-coach` tool profile

Set `GARMIN_TOOL_PROFILE=ai-coach` to expose exactly these 12 tools:

1. `get_training_context`
2. `analyze_activity`
3. `create_workout`
4. `get_activities`
5. `get_activities_by_date`
6. `get_activity`
7. `get_workouts`
8. `get_workout_by_id`
9. `get_scheduled_workouts`
10. `schedule_workout`
11. `unschedule_workout`
12. `delete_workout`

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

## Training context

`get_training_context` now combines a bounded set of activities, scheduled
workouts, and available recovery signals without exposing every upstream
endpoint or returning large raw payloads. It is the coach's eyes/current
context and is strictly read-only. [Activity analysis](ai-activity.md) is the
separate completed-session feedback read; [AI training context](ai-training.md)
covers current context, and `create_workout` is the coach's hands/write
operation after confirmation.

## Upstream compatibility

The new `ai_workouts` package is a minimal workouts seam. Existing
authentication and default registration remain unchanged, as do unrelated
upstream tools; adopting the feature is additive unless
`GARMIN_TOOL_PROFILE` is set.
