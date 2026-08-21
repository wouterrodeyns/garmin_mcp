# AI training context

`get_training_context(days=14)` is a compact, read-only Garmin snapshot for an
AI coach. It is the coach's **eyes**: it reduces a bounded set of Garmin reads
to coaching-relevant facts. `create_workout` and `update_workout` are the
coach's **hands** when the athlete later asks to put a recommendation on
Garmin or change an existing workout in place. The context tool never uploads,
schedules, changes, or deletes Garmin data. It does not provide coaching advice.

Detailed multi-night sleep or all-day wellness heart-rate evidence is an
explicit follow-up, not another field embedded in `get_training_context`. Use
[`get_sleep_trend`](ai-sleep-trend.md) when a recent sleep pattern needs
evidence, and use
[`get_wellness_heart_rate`](ai-wellness-heart-rate.md) only when the question
needs its bounded raw samples, daily summary, or time bins. An empty or
unavailable current date can simply mean the watch/device has not synced to
Garmin Connect yet; it does not establish an unsupported account or device.
Sync, then retry.

Target events also remain separate from the compact context. Use
[`get_target_events`](ai-target-events.md) only for an event-aware question,
such as how a named race or target date should inform the discussion. Its
calendar facts are not a coaching conclusion, and an empty result does not
prove the athlete has no race or target.

The implementation is pinned to `garminconnect==0.3.10`. Garmin metric
availability varies by device and account, so every recovery and fitness metric
described below is optional.

## Dates and request bounds

`days` must be an integer from 1 through 90. It is only the inclusive retrospective
training lookback: the period ends on today and contains exactly
`days` local calendar dates. It does not change the separate, fixed seven-day schedule window.
Scheduled workouts always cover today through the following six days,
inclusive.

“Today” is the MCP host's local calendar date. The pinned client does not expose
a reliable athlete timezone for these calls, so run the server in the athlete's local timezone.
An internal date seam makes tests deterministic but is not an
MCP argument.

Activity history uses 200-record pages in newest-first order. The computed
period cap is the smallest 200-record multiple covering `max(200, days * 10)`,
with a hard maximum of 1,000 records. The most recent run search also pages by
200 and stops after the first page containing a running match or 1,000 records;
within that page it selects the newest timestamped running item. Only the newest
20 recent activities are returned. If the computed cap is reached, period
totals are lower bounds. If a later page fails, already retrieved pages are
kept; this mid-page failure is marked as truncated rather than discarding useful
history. Latest run is searched independently across up to 1,000 activity
records and may be older than the requested period.

| Data | Query window |
| --- | --- |
| Activities | `days` retrospective activity lookback |
| Scheduled workouts | Today through the following six days |
| Daily recovery and fitness metrics | Today |
| Sleep, HRV, and readiness | Today, then yesterday only for a legitimately empty response |

## Returned metric groups

The stable response contains:

- training totals, running history, and reduced recent activities;
- scheduled workouts for the fixed schedule window;
- sleep duration and score;
- HRV values, status, and Garmin baseline bounds;
- resting heart rate and seven-day average;
- Body Battery;
- training readiness and recovery time;
- training status, training load, load focus, and running/cycling VO2 max.

The top-level `availability` object is metric-granular. A flag is true only
when that metric group was successfully normalized. An available empty
collection is different from an unavailable provider: zero activities can be a
known value, while unsupported or missing scalar metrics remain null, not zero.
The Body Battery and training-readiness flags are independent, as are
training readiness and recovery time.

A null optional metric with no warning means the metric was not available in
this snapshot; it does not prove the account or device does not support it.
Provider failures are reported in structured warnings. Garmin metric
availability can vary by device and account, but the fixed query windows above
mean old recovery or fitness metric dates must not be used to infer today's
recovery state.

Sleep, HRV, and readiness first query today. When today's response is
legitimately empty, each may fall back once to the previous local calendar day.
For these sections, date provenance uses Garmin's `calendarDate` when supplied;
otherwise it records the requested query date (today or the fallback date).
This prevents yesterday's overnight data from being presented as today's.
A failed or non-empty malformed response does not trigger fallback.

The service never derives ACWR from acute and chronic load. Garmin-supplied
ratio and status values are returned; otherwise they stay null. Lactate threshold
is deliberately omitted in v1, as is last-hard-session
classification. Per-activity training effect and load are also omitted.

## Example response

The payload is deliberately much smaller than Garmin's source DTOs. Numeric
display values use the documented precision, while aggregates sum raw source
values before final rounding.

```json
{
  "status": "success",
  "error": null,
  "period": {
    "days": 14,
    "start_date": "2026-07-27",
    "end_date": "2026-08-09"
  },
  "schedule_period": {
    "start_date": "2026-08-09",
    "end_date": "2026-08-15"
  },
  "availability": {
    "activities": true,
    "last_run": true,
    "scheduled_workouts": true,
    "sleep": true,
    "hrv": true,
    "resting_heart_rate": true,
    "body_battery": true,
    "training_readiness": true,
    "recovery_time": true,
    "training_status": true,
    "training_load": true,
    "load_focus": true,
    "vo2max": true
  },
  "training": {
    "activity_count": 5,
    "running_sessions": 0,
    "sessions_by_sport": {"cycling": 4, "walking": 1},
    "total_training_minutes": 245.0,
    "running_distance_km": 0.0,
    "last_run_date": "2026-06-06",
    "days_since_last_run": 64,
    "activities_truncated": false
  },
  "recent_activities": [
    {
      "date": "2026-08-07",
      "sport": "cycling",
      "duration_minutes": 58.0,
      "distance_km": 27.4,
      "average_hr": 132
    }
  ],
  "recovery": {
    "readiness_date": "2026-08-09",
    "training_readiness": 72,
    "training_readiness_level": "HIGH",
    "recovery_hours": 4.0,
    "body_battery": 78,
    "body_battery_date": "2026-08-09"
  },
  "sleep": {
    "date": "2026-08-09",
    "duration_hours": 7.6,
    "score": 82,
    "score_qualifier": "GOOD"
  },
  "hrv": {
    "date": "2026-08-09",
    "last_night_avg_ms": 54,
    "weekly_avg_ms": 52,
    "status": "BALANCED",
    "baseline_balanced_low_ms": 46,
    "baseline_balanced_upper_ms": 62
  },
  "heart_rate": {
    "date": "2026-08-09",
    "resting_hr": 49,
    "resting_hr_7_day_avg": 50
  },
  "fitness": {
    "training_status": "MAINTAINING",
    "training_status_feedback": null,
    "fitness_trend": null,
    "acute_load": 247,
    "chronic_load": 193,
    "acute_chronic_ratio": 1.14,
    "acwr_status": "OPTIMAL",
    "vo2max_running": 51,
    "vo2max_cycling": null,
    "load_focus": {
      "aerobic_low": 320,
      "aerobic_high": 180,
      "anaerobic": 70,
      "feedback": null
    }
  },
  "scheduled_workouts": [
    {
      "date": "2026-08-10",
      "scheduled_workout_id": 987654321,
      "workout_id": 123456789,
      "name": "Easy Run",
      "sport": "running",
      "completed": false
    }
  ],
  "warnings": []
}
```

The `scheduled_workout_id` identifies the calendar entry and is distinct from
the reusable `workout_id`. This matters for future move semantics.

## Activities and workout sports

`recent_activities[].sport` and `sessions_by_sport` use raw Garmin activity type keys.
Values may include `trail_running`, `treadmill_running`, or device-specific
keys the context service has not enumerated. By contrast, `create_workout.sport`
accepts the narrower normalized vocabulary: running, cycling, walking, or strength.
The coach must translate a Garmin activity such as `trail_running` to
`running` when creating an appropriate workout.

## Status, errors, and warnings

Period activities and scheduled workouts are the two core providers:

- `success` means neither a core nor optional provider failed. An informational
  truncation warning may still be present.
- `partial_success` means one core provider failed, or an optional provider had
  an isolated exception or invalid response, while useful core context remains.
- `error` is used for `invalid_days`, `client_unavailable`, or
  `context_unavailable`. The last case means both core providers failed; the
  service stops after those two reads and includes both failures as warnings.

Malformed scheduled-workout entries are unavailable rather than being reduced
to a phantom `completed: false` item. A valid empty scheduled-workout collection
remains available.

Warnings alone do not imply `partial_success`. V1 has exactly three warning codes:
`provider_unavailable`, `invalid_provider_response`, and
`activities_truncated`. The pinned client erases structured HTTP status/cause
information on most reads, so timeout, rate-limit, server, and expired-session
classification is deliberately deferred. A `context_unavailable` message
therefore suggests re-running `garmin-mcp-auth` if the session may have expired.
Warnings never include raw Garmin responses, tokens, or credentials.

## AI-coach profile and workflow

Set `GARMIN_TOOL_PROFILE=ai-coach` to expose exactly 17 tools. The three
primary coaching roles are context eyes (`get_training_context`),
completed-session feedback (`analyze_activity`, with the narrow
`get_activity_timeseries` follow-up for concrete short-interval evidence), and
workout hands (`create_workout` plus in-place `update_workout`). Deliberate
sleep-trend (`get_sleep_trend`) and all-day wellness-heart-rate
(`get_wellness_heart_rate`) reads provide evidence for those roles.
`get_target_events` is a separate target-eyes read for event-aware planning.
The full profile also preserves compatibility for focused reads and calendar
operations:

The compact snapshot does not imply a multi-night sleep pattern. The workflow
is `get_training_context` for the current snapshot, then an explicit
`get_sleep_trend(days=7)` call when the user asks whether recent sleep is a
one-off or a pattern. Sleep evidence alone does not establish causation,
readiness, recovery, or a training recommendation; only create a workout after
the user confirms the proposed session. See the [sleep trend guide](ai-sleep-trend.md)
for its fixed period, visible missing dates, metrics, and denominators.

```text
User: "I haven't run for two months and I'm targeting a half marathon.
Review my Garmin data and recommend how I should restart."

Claude: get_training_context(days=30)
        -> get_target_events(days=180) when the race date or target matters
        -> reviews training, recovery, and available target-event facts
        -> recommends a conservative return-to-running session

After a completed session, `analyze_activity(activity_id)` is the bounded,
read-only feedback read for the AI to interpret. It is not another context
aggregate; see the [activity analysis guide](ai-activity.md). If that overview
leaves a concrete short interval to inspect, use the narrow, read-only
[`get_activity_timeseries`](ai-activity-timeseries.md) follow-up; it is not a
replacement for `analyze_activity`.

User: "Put that workout on Garmin for tomorrow."

Claude: create_workout(..., schedule_date="2026-08-10")

User: "Change that workout to five five-minute intervals."

Claude: update_workout(workout_id=123456789, name="Threshold 5x5", steps=[...])
        -> preserves the workout ID and existing schedule entries
```

The remaining profile tools preserve compatibility for focused activity and
workout reads and explicit calendar operations. `get_training_context` itself
remains strictly read-only. `create_workout` and `update_workout` are the
coach's hands/write operations after the user confirms the proposed workout or
change. For update ambiguity, read with `get_workout_by_id` before retrying.
