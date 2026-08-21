# AI-friendly workouts

`create_workout` and `update_workout` are the small, user-facing workout-hands
seam for an AI coach. Create accepts a readable workout description in one
call, validates it, uploads it to Garmin, and optionally puts it on the
calendar. Update applies a friendly patch to an existing regular workout in
place. Callers do not need to produce raw Garmin workout DTOs.

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
retry or explain what happened. Do not rerun `create_workout` after this
response because it could duplicate the template. Retry only `schedule_workout`
with the returned `workout_id` and `requested_date`.
Partial results use `requested_date` to avoid claiming that Garmin scheduled
the workout when the calendar operation failed.

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

ai-coach is the default profile when `GARMIN_TOOL_PROFILE` is unset or empty.
Set `GARMIN_TOOL_PROFILE=ai-coach` explicitly when documenting that intent. The
profile exposes exactly these 17 tools:

1. `get_training_context`
2. `get_target_events`
3. `get_sleep_trend`
4. `get_wellness_heart_rate`
5. `analyze_activity`
6. `get_activity_timeseries`
7. `create_workout`
8. `update_workout`
9. `get_activities`
10. `get_activities_by_date`
11. `get_activity`
12. `get_workouts`
13. `get_workout_by_id`
14. `get_scheduled_workouts`
15. `schedule_workout`
16. `unschedule_workout`
17. `delete_workout`

Profile precedence is explicit:

1. A non-empty `GARMIN_ENABLED_TOOLS` allowlist wins; the selected profile and
   denylist are both ignored while the explicit allowlist is active.
2. Without an explicit allowlist, `GARMIN_DISABLED_TOOLS` subtracts tools from
   the selected or default profile.
3. Otherwise, the selected profile controls registration. Full upstream tool
   registration is an explicit choice: complete upstream-compatible registration
   requires explicitly setting `GARMIN_TOOL_PROFILE=upstream-full`.
4. When `GARMIN_TOOL_PROFILE` is unset or empty, `ai-coach` applies by default.

The `ai-coach` profile intentionally hides raw `upload_workout`, bulk
`upload_workouts`, and unrelated health, nutrition, device, and management
tools. `analyze_activity` remains the first/default activity overview;
`get_activity_timeseries` is a narrow follow-up evidence read, documented in
the [activity time-series guide](ai-activity-timeseries.md), and does not
mutate workouts.

## Pinned API assumptions

This seam targets `garminconnect==0.3.10`. That upstream client provides
`upload_workout`, `schedule_workout`, `unschedule_workout`, and
`delete_workout`. It also provides a whole-document `update_workout` method,
and this fork exposes the AI-facing update tool. A calendar schedule entry ID
is distinct from the workout ID: unscheduling needs the
`scheduled_workout_id`, while deletion needs the `workout_id`.

The primary references are the [python-garminconnect 0.3.10 package on
PyPI](https://pypi.org/project/garminconnect/0.3.10/) and its [upstream source on
GitHub](https://github.com/cyberjunky/python-garminconnect/tree/0.3.10).

## Update workout

`update_workout` uses patch-style top-level fields. Supply `workout_id` and a
new `name` to rename an existing workout, or supply friendly replacement
`steps` (and optionally `sport`) using the same schema as `create_workout`.
The ID must be a positive integer or an ASCII decimal string; booleans, floats,
UUIDs, and other ID shapes are invalid. The operation has no `schedule_date`
argument.
The approved replacement example changes 4 x 6 minutes to 5 x 5 minutes:

```json
{
  "workout_id": 123456789,
  "name": "Threshold 5x5",
  "steps": [
    {"warmup": {"duration": "15m"}},
    {
      "repeat": 5,
      "steps": [
        {"run": {"duration": "5m", "pace": "4:20-4:30/km"}},
        {"recovery": {"duration": "2m"}}
      ]
    },
    {"cooldown": {"duration": "10m"}}
  ]
}
```

`workout_id` is the numeric reusable workout-template ID returned by
`get_workouts`, `get_workout_by_id`, or `get_scheduled_workouts`.
`scheduled_workout_id` is the calendar-entry ID used only by
`unschedule_workout`; the two IDs are distinct. An in-place update keeps the
same underlying `workout_id` (the workout ID) and preserves existing schedules.
No calendar call is made, and it does not upload a replacement, move,
unschedule, or delete.

When `steps` is supplied, `sport` may be `running`, `cycling`, `walking`, or
`strength` (`strength_training` is accepted as an alias); if omitted, the
current supported sport is retained. `sport` is valid only with `steps`, and
steps use the friendly units, targets, actions, and repeat limits documented
for creation. UUID-based Garmin Coach/adaptive-plan workouts and unsupported sports
are outside v1 and are rejected. Move semantics remain deferred.

The server fetches the complete workout, applies the patch, validates the
whole document, and uses GarminConnect's public whole-document `PUT` under the
hood. It never automatically retries. If the result says
`update_may_have_applied` or is `partial_success`, call
`get_workout_by_id` to read the current state before retrying; do not blindly
repeat the mutation. The fixed ambiguous-write guidance is: “read the workout before retrying.”
A success response reports the effective name and sport and the matching
workout ID returned by Garmin; `schedules_preserved` follows from retaining
that ID and is not a separate calendar confirmation.

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
covers current context, and `create_workout` plus `update_workout` are the
coach's hands/write operations after confirmation.

## Upstream compatibility

The new `ai_workouts` package is a minimal workouts seam. Existing
authentication and unrelated upstream tools remain available through the
explicit `GARMIN_TOOL_PROFILE=upstream-full` profile; adopting the feature is
additive.
