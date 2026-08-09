# AI Training Context v1 Design

## Objective

Add one compact, read-only MCP tool that gives an AI coach enough factual Garmin
context to recommend an appropriate session without making many low-level tool
calls:

```python
get_training_context(days: int = 14)
```

This is a separate feature from AI workout creation. Together,
`get_training_context` is the coach's primary read tool (its "eyes") and
`create_workout` is its primary write tool (its "hands"). The new tool must
normalize Garmin-specific response shapes and reduce payload size rather than
expose more of the Garmin API.

## Scope

V1 reads a bounded set of sources from the pinned `garminconnect==0.3.2` client:

- activities in the requested retrospective period;
- the latest running activity, including one outside that period;
- scheduled workouts in a fixed seven-day forward window;
- today's daily statistics;
- today's sleep summary;
- today's HRV summary;
- today's morning training readiness;
- today's aggregate training status.

The feature adds no write operation and does not call existing MCP tools
internally. It does not redesign `create_workout`, broadly refactor Taxuspt
modules, or upgrade `garminconnect`. Lactate threshold and a custom "last hard
session" classification are deliberately omitted because the pinned integration
does not provide a sufficiently reliable, uniform source for them. The service
returns factual activity summaries so the AI coach may reason about workout
intensity itself; it does not add inferred coaching fields.

## Architecture

Fork-specific behavior lives in a new `src/garmin_mcp/ai_training/` package:

- `providers.py` contains small, read-only wrappers around the configured Garmin
  client and isolates endpoint details.
- `service.py` validates dates and bounds, normalizes provider payloads,
  aggregates training totals, applies availability and error semantics, and
  returns a JSON-serializable context object.
- `tools.py` registers `get_training_context` and encodes its result as JSON text,
  consistent with the repository's other MCP tools.
- `__init__.py` exposes only the package's configuration and registration entry
  points.

`garmin_mcp/__init__.py` receives the only runtime integration changes: configure
the new package with the same proxied Garmin client, register its tool, and add
`get_training_context` to the existing `ai-coach` allowlist. Upstream-oriented
activity, health, training, workout, authentication, and proxy modules are not
rewritten.

The data flow is:

```text
pinned Garmin client reads
        -> ai_training providers
        -> normalization and aggregation service
        -> compact get_training_context result
        -> AI coach
```

Provider calls are sequential in v1. This keeps client/session behavior simple,
avoids unverified thread-safety assumptions, and makes partial failure ordering
deterministic. At most eight bounded Garmin requests are made per tool call.

## Provider Contracts

The providers call the configured pinned client directly:

1. **Period activities** use `connectapi` with the client's
   `garmin_connect_activities` URL and `startDate`, `endDate`, `start=0`, and
   `limit=200`. This avoids the pinned SDK helper's unbounded pagination.
2. **Latest run** uses `get_activities(0, 1, "running")`. It is a separate read so
   `last_run_date` remains useful when the athlete did not run during the selected
   lookback.
3. **Scheduled workouts** use the existing Garmin GraphQL
   `workoutScheduleSummariesScalar(startDate, endDate)` query through
   `query_garmin_graphql`. This is a read-only GraphQL query even though the
   pinned client transports GraphQL queries over HTTP POST. The provider never
   calls a GraphQL mutation or Garmin schedule, unschedule, delete, upload,
   update, or PUT/DELETE operation.
4. **Daily statistics** use `get_stats(today)` for resting heart rate, seven-day
   average resting heart rate, and the most recent Body Battery value.
5. **Sleep** uses `get_sleep_data(today)`.
6. **HRV** uses `get_hrv_data(today)`.
7. **Training readiness** uses `get_morning_training_readiness(today)`.
8. **Training status** uses `get_training_status(today)` for Garmin's status,
   acute/chronic load, load focus, and running/cycling VO2 max when present.

These methods and fields are based on current Taxuspt code, fixtures, and the
pinned client. Garmin response shapes vary by device and account, so normalizers
must accept only known shapes and leave unrecognized or absent values as `null`.
They must not guess a value from an unrelated field.

The provider layer returns raw-but-bounded responses only to the service. Garmin
DTOs and raw response bodies never cross the MCP boundary.

## Date and Request Bounds

`days` is an integer from 1 through 90, inclusive, with a default of 14. Booleans
are rejected even though Python treats them as integers.

"Today" is the server's local calendar date. Production uses `date.today()`;
tests inject a fixed date into the service. The retrospective period is inclusive:
for `days=14` and today `2026-08-09`, it is `2026-07-27` through `2026-08-09`.

`days` controls only retrospective training history. Scheduled workouts always
use a fixed, inclusive seven-day forward window from today through today plus six
days. For the same example, that is `2026-08-09` through `2026-08-15`. This
separation is explicit in the returned `period` and `schedule_period` objects and
in the user documentation.

The activity provider requests at most 200 period activities. The service returns
at most the newest 20 reduced activities. If the provider returns exactly 200,
`training.activities_truncated` is `true`, a structured warning is included, and
period aggregates are documented as lower bounds.

## Normalized Response

The tool returns JSON text containing a stable, compact object. Optional metric
keys remain present with `null` values, so callers can distinguish unavailable
data from a numeric zero without learning Garmin DTO shapes.

```json
{
  "status": "success",
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
    "training_readiness": false,
    "recovery_time": false,
    "training_status": true,
    "training_load": true,
    "load_focus": false,
    "vo2max": true
  },
  "training": {
    "activity_count": 5,
    "sessions_by_sport": {
      "cycling": 4,
      "strength_training": 1
    },
    "total_training_minutes": 245,
    "running_distance_km": 0,
    "last_run_date": "2026-06-06",
    "days_since_last_run": 64,
    "activities_truncated": false
  },
  "recent_activities": [
    {
      "date": "2026-08-07",
      "sport": "cycling",
      "duration_minutes": 58,
      "distance_km": 27.4,
      "average_hr": 132,
      "max_hr": 158,
      "average_speed_kph": 28.3
    }
  ],
  "recovery": {
    "training_readiness": null,
    "training_readiness_level": null,
    "recovery_hours": null,
    "body_battery": 78
  },
  "sleep": {
    "date": "2026-08-09",
    "duration_hours": 7.6,
    "score": 82,
    "score_qualifier": "GOOD"
  },
  "hrv": {
    "last_night_avg_ms": 54,
    "weekly_avg_ms": 52,
    "status": "BALANCED",
    "baseline_balanced_low_ms": 46,
    "baseline_balanced_high_ms": 62
  },
  "heart_rate": {
    "resting_hr": 49,
    "resting_hr_7_day_avg": 51
  },
  "fitness": {
    "training_status": "MAINTAINING",
    "training_status_feedback": null,
    "fitness_trend": null,
    "acute_load": 250,
    "chronic_load": 220,
    "acute_chronic_ratio": 1.14,
    "acwr_status": "OPTIMAL",
    "vo2max_running": 51,
    "vo2max_cycling": null,
    "load_focus": {
      "aerobic_low": null,
      "aerobic_high": null,
      "anaerobic": null,
      "feedback": null
    }
  },
  "scheduled_workouts": [],
  "warnings": []
}
```

### Activity reduction and aggregation

The service accepts only the following activity fields when present:

- `activityId` as `activity_id`;
- the activity type's `typeKey` as `sport`;
- the local start timestamp's calendar portion as `date`;
- duration seconds converted to display minutes;
- distance metres converted to kilometres;
- average and maximum heart rate;
- average speed converted from metres per second to kilometres per hour.

Activities are sorted newest first. Unknown activity types remain factual string
keys rather than being forced into a known sport. Period duration is summed from
validated source seconds and rounded only after aggregation; per-activity display
minutes are rounded independently and are not re-summed. Distance follows the
same source-first aggregation rule. Missing duration or distance is not treated
as zero for an individual activity, while aggregate sums include only present
values. `sessions_by_sport` contains only observed sports.
`running_distance_km` is `0.0` when the period contains no running activities or
only running activities with confirmed zero distance. It is `null` when running
activities exist but all of their distance values are missing or invalid, or
when the activity provider failed. Present valid running distances are summed
even if another running activity lacks distance.

The latest-running read supplies `last_run_date` and `days_since_last_run`.
Malformed or future dates are rejected as unavailable rather than producing a
negative elapsed-day value.

### Recovery and fitness normalization

Daily statistics independently populate resting-heart-rate and Body Battery
fields. Their availability is granular: one can be available while the other is
not, even though both came from one request.

Sleep uses `dailySleepDTO.sleepTimeSeconds` and
`sleepScores.overall.value`/qualifier when present. HRV uses
`hrvSummary.lastNightAvg`, `weeklyAvg`, `status`, and the balanced baseline's
lower/upper bounds when present.

Training-readiness responses have multiple known shapes in the pinned client and
fixtures. The normalizer checks the known score and level aliases, preferring a
wake-up entry when a list is returned. Recovery time is accepted only when a
known numeric recovery-time field is present and is converted using the existing
Taxuspt convention to hours. `training_readiness` and `recovery_time` have
separate availability flags.

Training status selects the primary training device when Garmin identifies one,
otherwise the first usable device entry. It extracts only Garmin-supplied status,
feedback/trend, acute load, chronic load, ratio/status, load-focus values, and
running/cycling VO2 max. `training_status`, `training_load`, `load_focus`, and
`vo2max` have separate availability flags. No status, load, fitness, readiness,
or recovery value is calculated by this feature.

Scheduled workouts are reduced to identifiers supplied by Garmin, date, name,
and sport/type when present. The service does not create identifiers or fetch
workout details per calendar entry.

## Availability, Warnings, and Failure Semantics

`availability` is metric-granular, not merely provider-granular. A flag is `true`
only when at least one value for that metric group was successfully normalized.
An empty but successfully fetched collection is available: for example,
`activities: true` with `activity_count: 0`, or `scheduled_workouts: true` with an
empty list. A successful provider response that legitimately lacks an optional
device/account metric leaves its availability flag `false` and its fields
`null`; this is normal and does not create a warning by itself.

Warnings are structured objects, never arbitrary raw exception strings:

```json
{
  "provider": "training_readiness",
  "code": "provider_timeout",
  "message": "Training readiness is temporarily unavailable."
}
```

V1 uses a small stable warning-code vocabulary:

- `provider_timeout`
- `provider_rate_limited`
- `provider_server_error`
- `provider_unavailable`
- `invalid_provider_response`
- `activities_truncated`

Messages are concise and sanitized. They never include tokens, credentials,
request headers, raw response bodies, URLs with query data, or an exception's
unbounded representation. Provider names use stable internal names from the
eight contracts above: `activities`, `last_run`, `scheduled_workouts`,
`daily_stats`, `sleep`, `hrv`, `training_readiness`, and `training_status`.

Status semantics are:

- `success`: validation passed and every attempted provider call completed,
  even if Garmin legitimately omitted optional metrics or returned empty lists;
- `partial_success`: one or more isolated providers timed out, were rate-limited,
  returned a server error, were otherwise unavailable, or returned an
  unrecognized payload, while at least one useful context provider succeeded;
- `error`: request validation failed, authentication/session is invalid, the
  configured client is globally unusable, or no useful context could be
  produced after attempting the bounded reads.

Only authentication/session failures and global-client failures short-circuit
the provider sequence as fatal. An isolated timeout, rate limit, server failure,
or malformed response is captured as a structured warning and collection
continues. If useful context remains, the result is `partial_success`. If every
useful provider fails, the result is `error` with sanitized provider warnings;
this is total context failure, not an isolated failure promoted to fatal.

Provider exception classification uses explicit known exception/status types
available through the pinned client where possible, with a conservative generic
fallback to `provider_unavailable`. It never depends on embedding raw exception
text in the MCP response.

Invalid `days` returns a concise structured `error` without making any Garmin
call. An empty activity period is a normal successful result, not an error.
Error results retain the normal `status`, period objects, granular
`availability`, and structured `warnings` shape where those values can be
constructed safely. They add a stable top-level `error` object rather than a raw
exception:

```json
{
  "status": "error",
  "error": {
    "code": "invalid_days",
    "message": "days must be an integer from 1 through 90"
  },
  "warnings": []
}
```

Error codes are limited to `invalid_days`, `authentication_required`,
`client_unavailable`, and `context_unavailable` in v1.

## MCP and Profile Integration

The MCP signature is exactly:

```python
get_training_context(days: int = 14) -> str
```

The tool docstring states the 1-90 range, inclusive retrospective semantics,
fixed seven-day schedule window, read-only guarantee, and device/account
availability caveat. The MCP layer delegates once to the service and JSON-encodes
the returned object; it does not normalize Garmin data itself.

The `ai-coach` profile adds `get_training_context` and otherwise preserves its
existing entries:

- `get_training_context`
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

The default tool surface and explicit `GARMIN_ENABLED_TOOLS`/
`GARMIN_DISABLED_TOOLS` precedence remain unchanged. Profile startup tests verify
that the declared profile and actually registered tool names stay synchronized.

## Read-Only Guarantee

Every provider takes a client dependency and invokes only the eight documented
read paths. Tests use a strict client double whose read methods are allowed and
whose mutation methods fail immediately if called. The full service and MCP path
must complete without invoking upload, scheduling, unscheduling, deletion,
update, PUT, DELETE, or GraphQL mutation behavior. The scheduled-workout read is
explicitly allowed through `query_garmin_graphql`; its pinned implementation uses
HTTP POST as a query transport but performs no Garmin mutation.

This guarantee is structural as well as documented: `ai_training` does not
import `ai_workouts.service`, workout mutation helpers, or existing MCP tool
registration functions.

## Tests

Normal tests use fixtures and mocks only; no Garmin account is required.

Provider and service tests cover:

1. complete context across every supported provider;
2. an athlete with no runs inside the retrospective period;
3. latest run outside the period and days-since-last-run calculation;
4. an empty activity period;
5. activity field reduction, sorting, aggregation, and the 20-item output bound;
6. the 200-activity truncation flag, warning, and lower-bound semantics;
7. scheduled workouts in exactly today through today plus six days;
8. sleep normalization;
9. HRV and baseline normalization;
10. resting heart rate and seven-day average normalization;
11. independent Body Battery availability from the same daily-stats response;
12. readiness and recovery normalization across known response shapes;
13. training status, load, load focus, and VO2 max normalization;
14. a legitimately missing optional metric without a warning;
15. one provider timeout/rate-limit/server failure while others succeed,
    producing `partial_success` and a sanitized structured warning;
16. authentication/session or global-client failure short-circuiting to `error`;
17. all providers unavailable, producing total `error` without leaking details;
18. invalid values and types for `days`, with no provider calls;
19. accepted boundary values `days=1` and `days=90`;
20. MCP argument defaults and compact JSON return shape;
21. `ai-coach` profile declaration and actual registration;
22. the end-to-end service/tool path performing no write operation.

Focused tests are followed by the full offline suite:

```bash
uv run pytest -m "not e2e"
```

Existing tests must remain green.

## Documentation

Add `docs/ai-training.md` and update the README/profile documentation. The docs
explain:

- that the tool is a compact read-only coaching snapshot;
- the currently supported metric groups and optional fields;
- that device/account support determines Garmin metric availability;
- that `days` applies only to the inclusive retrospective training window;
- that scheduled workouts always cover today through the following six days;
- the activity request/output bounds and truncation behavior;
- the `success`, `partial_success`, and `error` meanings;
- structured warnings and granular availability;
- an example output and the two-step coach workflow using
  `get_training_context` followed by `create_workout`.

## Deliberately Deferred

V1 does not add lactate threshold, last-hard-session detection, coaching advice,
training-plan generation, longitudinal sleep/HRV/readiness queries, activity
detail calls, per-workout detail calls, write operations, or concurrent provider
requests. These can be considered separately only after their Garmin behavior,
cost, and coaching value are verified.
