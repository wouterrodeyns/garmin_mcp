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
- today's sleep summary, with one previous-day fallback;
- today's HRV summary, with one previous-day fallback;
- today's morning training readiness, with one previous-day fallback;
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
deterministic. Each source has an explicit request bound. Sleep, HRV, and
readiness may each make one additional previous-day request only when today's
response is legitimately empty. The worst successful/partial context is 19
sequential reads: five period-activity pages, the schedule query, five latest-run
pages, daily stats, two each for sleep/HRV/readiness, and training status. A
normal 14-day call with a first-page run match and no overnight fallbacks uses
eight reads. When both core providers fail, the service stops after the schedule
query instead of performing optional reads whose result cannot make the context
usable.

## Provider Contracts

The providers call the configured pinned client directly:

1. **Period activities** call `client.connectapi(...)` with the client's
   `garmin_connect_activities` URL and `startDate`, `endDate`, `start`, `limit`,
   and explicit `sortOrder="desc"`. Pages contain at most 200 records and stop at
   a calculated total cap. The pinned
   `get_activities` helper is bounded but does not accept a date range; the only
   date-filtered helper, `get_activities_by_date`, pages in hard-coded batches of
   20 until it exhausts the period. Direct paging therefore preserves the date
   filter while keeping total work bounded and ordering explicit.
2. **Scheduled workouts** use the existing Garmin GraphQL
   `workoutScheduleSummariesScalar(startDate, endDate)` query through
   `query_garmin_graphql`. This is a read-only GraphQL query even though the
   pinned client transports GraphQL queries over HTTP POST. The provider never
   calls a GraphQL mutation or Garmin schedule, unschedule, delete, upload,
   update, or PUT/DELETE operation.
3. **Latest run** pages unfiltered activities newest-first in 200-record pages,
   stopping immediately at the first local match from the shared running type-
   key set and stopping after at most 1,000 records. It does not use
   `activityType="running"`, because the pinned SDK only forwards that filter and
   cannot prove that Garmin includes running subtypes. The separate bounded read
   keeps `last_run_date` useful when no run appears in the retrospective period.
4. **Daily statistics** use `get_stats(today)` for resting heart rate, seven-day
   average resting heart rate, and the most recent Body Battery value.
5. **Sleep** uses `get_sleep_data(today)`, then the previous date only when
   today's response is legitimately empty.
6. **HRV** uses `get_hrv_data(today)` with the same one-day fallback.
7. **Training readiness** uses `get_morning_training_readiness(today)` with the
   same one-day fallback.
8. **Training status** uses `get_training_status(today)` for Garmin's status,
   acute/chronic load, load focus, and running/cycling VO2 max when present.

The service executes providers in this numbered order. It evaluates the two core
providers first and stops immediately with `context_unavailable` when both fail.
Otherwise it continues through the optional providers. Each fallback completes
inside its provider before the service advances to the next provider.

These methods and fields are based on current Taxuspt code, fixtures, and the
pinned client. Garmin response shapes vary by device and account, so normalizers
must accept only known shapes and leave unrecognized or absent values as `null`.
They must not guess a value from an unrelated field.

The provider layer returns raw-but-bounded responses only to the service. Garmin
DTOs and raw response bodies never cross the MCP boundary.

Activity normalizers accept the two collection roots used by the pinned client:
a top-level list or an object containing an `activityList` list. `None` is an
empty collection. Any other non-empty root, or a non-list `activityList`, is an
`invalid_provider_response`. This applies to both period paging and the bounded
latest-run search and is pinned by provider tests.

The pinned SDK documents `sortOrder="asc"` but otherwise relies on Garmin's
newest-first default; it does not document the explicit `"desc"` value. V1 sends
`sortOrder="desc"` to make intent explicit, then sorts validated results locally
by `startTimeLocal` as the correctness guarantee. It does not add an unverified
`sortBy` parameter. If Garmin rejects the explicit descending value, normal
provider-failure semantics apply rather than silently trusting response order.

## Date and Request Bounds

`days` is an integer from 1 through 90, inclusive, with a default of 14. Booleans
are rejected even though Python treats them as integers.

The internal service contract is
`get_training_context_service(days: int = 14, today: date | None = None)`. The MCP
tool passes only `days`; it never exposes `today`. Production resolves a missing
`today` with the MCP host's local `date.today()`, while tests inject a fixed date.
The pinned client does not expose a reliable athlete-timezone value for these
calls, so deployments should run the MCP host in the athlete's local timezone.
Garmin-returned calendar dates remain authoritative in the response. The
retrospective period is inclusive: for `days=14` and today `2026-08-09`, it is
`2026-07-27` through `2026-08-09`.

`days` controls only retrospective training history. Scheduled workouts always
use a fixed, inclusive seven-day forward window from today through today plus six
days. For the same example, that is `2026-08-09` through `2026-08-15`. This
separation is explicit in the returned `period` and `schedule_period` objects and
in the user documentation.

The period-activity cap is
`min(1000, 200 * ceil(max(200, days * 10) / 200))`: the next 200-record page
boundary at or above the proportional budget, with a hard ceiling of 1,000. It
is 200 for a 14-day request, 400 for a 30-day request, and 1,000 for a 90-day
request. The service returns at
most the newest 20 reduced activities. If retrieval reaches the calculated cap,
`training.activities_truncated` is `true`, an `activities_truncated` warning is
included, and period aggregates are lower bounds. Long lookbacks therefore
receive a proportionally larger but still bounded budget.

If a later period-activity page fails after one or more valid pages, the service
keeps the validated earlier pages, sets `activities: true` and
`activities_truncated: true`, emits exactly one `provider_unavailable` warning,
and treats the provider as an isolated failure for status purposes. If the first
page fails, `activities` is unavailable and no period activities are retained.
Cap exhaustion instead emits one `activities_truncated` warning and is
informational rather than a provider failure.

The latest-run search is also bounded at 1,000 newest activities, fetched in up
to five 200-record pages. If it finds a matching activity, that date is
authoritative and no later page is requested. If it reaches 1,000 without a
match, `last_run` is unavailable and one `activities_truncated` warning explains
that the bounded search was inconclusive. This warning is informational and does
not by itself cause `partial_success`. A shorter successful response with no
match means no known run and leaves `last_run_date`/`days_since_last_run` as
`null` without a warning. A page exception before a match is an isolated
`provider_unavailable` failure; already-inspected pages need not be returned
because they contain no matching run.

For sleep, HRV, and readiness, a legitimately empty response means `None`, an
empty object/list, or a known response root with no metric values. That condition
causes exactly one retry for `today - 1 day`. A non-empty unknown shape is instead
`invalid_provider_response` and is not retried. The output date is Garmin's
calendar date when supplied, otherwise the date passed to the successful getter.
This searches at most today and the previous day; it does not claim to find the
latest value across a longer history.

## Normalized Response

The tool returns JSON text containing a stable, compact object. Optional metric
keys remain present with `null` values, so callers can distinguish unavailable
data from a numeric zero without learning Garmin DTO shapes.

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
    "load_focus": false,
    "vo2max": true
  },
  "training": {
    "activity_count": 5,
    "running_sessions": 0,
    "sessions_by_sport": {
      "cycling": 4,
      "strength_training": 1
    },
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
      "average_hr": 132,
      "max_hr": 158,
      "average_speed_kph": 28.3
    }
  ],
  "recovery": {
    "readiness_date": "2026-08-08",
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
    "date": "2026-08-08",
    "last_night_avg_ms": 54,
    "weekly_avg_ms": 52,
    "status": "BALANCED",
    "baseline_balanced_low_ms": 46,
    "baseline_balanced_upper_ms": 62
  },
  "heart_rate": {
    "date": "2026-08-09",
    "resting_hr": 49,
    "resting_hr_7_day_avg": 51
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
      "aerobic_low": null,
      "aerobic_high": null,
      "anaerobic": null,
      "feedback": null
    }
  },
  "scheduled_workouts": [
    {
      "date": "2026-08-10",
      "scheduled_workout_id": 987654321,
      "workout_id": 123456789,
      "name": "Easy Run 40",
      "sport": "running",
      "completed": false
    }
  ],
  "warnings": []
}
```

### Activity reduction and aggregation

The service accepts only the following activity fields when present:

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

The running vocabulary is defined once as
`{"running", "trail_running", "treadmill_running"}`. These are the running type
keys evidenced by the current repository. The same set controls
`running_sessions`, `running_distance_km`, `last_run_date`, and
`days_since_last_run`. The last-run provider fetches unfiltered activities and
matches locally, so it does not assume Garmin's parent `running` filter includes
subtypes. Same-day `days_since_last_run` is `0`.

The latest-running read supplies `last_run_date` and `days_since_last_run`.
Malformed or future dates are rejected as unavailable rather than producing a
negative elapsed-day value.

Activity transformation precision is fixed:

- per-activity and aggregate duration: seconds divided by 60, rounded to one
  decimal place;
- per-activity and aggregate distance: metres divided by 1,000, rounded to two
  decimal places;
- average speed: metres per second multiplied by 3.6, rounded to one decimal
  place;
- sleep duration: seconds divided by 3,600, rounded to one decimal place;
- recovery time: minutes divided by 60, rounded to one decimal place.

Python's numeric `round(value, places)` behavior is the v1 rounding mode. All
aggregates sum validated raw Garmin units before conversion and final rounding.
For example, three activities of 1,838 seconds each must total 91.9 minutes after
summing 5,514 raw seconds. Rounding each activity first to 30.6 and summing would
incorrectly produce 91.8 minutes.

`recent_activities[].sport` deliberately exposes Garmin activity type keys such
as `trail_running`. This is a different vocabulary from `create_workout.sport`,
which accepts the narrower normalized values `running`, `cycling`, `walking`,
and `strength`. An AI coach must translate an observed Garmin subtype to the
appropriate normalized workout sport when creating a workout.

### Exact field-path mapping

The following table is the v1 extraction contract. A non-empty payload that does
not match its documented roots is invalid; the service does not search arbitrary
nested keys.

| Provider | Garmin input path | Normalized output |
|---|---|---|
| activities | `activityType.typeKey` | `recent_activities[].sport`, `sessions_by_sport`, running classification |
| activities | `startTimeLocal` | `recent_activities[].date` |
| activities | `duration` | `recent_activities[].duration_minutes`, `training.total_training_minutes` |
| activities | `distance` | `recent_activities[].distance_km`, `training.running_distance_km` |
| activities | `averageHR`, `maxHR` | `recent_activities[].average_hr`, `.max_hr` |
| activities | `averageSpeed` | `recent_activities[].average_speed_kph` |
| scheduled_workouts | `data.workoutScheduleSummariesScalar[]` | source collection |
| scheduled_workouts | `scheduledWorkoutId`, `workoutId`, `workoutUuid` | corresponding identifiers when present |
| scheduled_workouts | `scheduleDate`, `workoutName`, `workoutType`, `associatedActivityId` | `date`, `name`, `sport`, `activity_id`/completion |
| daily_stats | `calendarDate` | `heart_rate.date`, `recovery.body_battery_date` |
| daily_stats | `restingHeartRate`, `lastSevenDaysAvgRestingHeartRate` | `heart_rate.resting_hr`, `.resting_hr_7_day_avg` |
| daily_stats | `bodyBatteryMostRecentValue` | `recovery.body_battery` |
| sleep | `dailySleepDTO.calendarDate` | `sleep.date` |
| sleep | `dailySleepDTO.sleepTimeSeconds` | `sleep.duration_hours` |
| sleep | `dailySleepDTO.sleepScores.overall.value` | `sleep.score` |
| sleep | `dailySleepDTO.sleepScores.overall.qualifierKey` | `sleep.score_qualifier` |
| hrv | `hrvSummary.calendarDate` | `hrv.date` |
| hrv | `hrvSummary.lastNightAvg`, `.weeklyAvg`, `.status` | corresponding HRV fields |
| hrv | `hrvSummary.baseline.balancedLow`, `.balancedUpper` | `baseline_balanced_low_ms`, `baseline_balanced_upper_ms` |
| training_readiness | `calendarDate`, else successful request date | `recovery.readiness_date` |
| training_readiness | `readinessScore`, fallback `score`, fallback `trainingReadinessLevel` | `recovery.training_readiness` |
| training_readiness | `readinessLevel`, fallback `level`, fallback `trainingReadinessLevelKey` | `recovery.training_readiness_level` |
| training_readiness | `recoveryTime` in minutes | `recovery.recovery_hours` |
| training_status | `mostRecentTrainingStatus.latestTrainingStatusData[device]` | status device source |
| training_status | device `calendarDate`, `trainingStatus`, `trainingStatusFeedbackPhrase`, `fitnessTrend` | corresponding fitness fields |
| training_status | device `acuteTrainingLoadDTO.dailyTrainingLoadAcute`, `.dailyTrainingLoadChronic`, `.dailyAcuteChronicWorkloadRatio`, `.acwrStatus` | corresponding load fields |
| training_status | `mostRecentTrainingLoadBalance.metricsTrainingLoadBalanceDTOMap[device]` | load-focus device source |
| training_status | load-focus `monthlyLoadAerobicLow`, `monthlyLoadAerobicHigh`, `monthlyLoadAnaerobic`, `trainingBalanceFeedbackPhrase` | `fitness.load_focus` fields |
| training_status | `mostRecentVO2Max.generic.vo2MaxValue` | `fitness.vo2max_running` |
| training_status | `mostRecentVO2Max.cycling.vo2MaxValue` | `fitness.vo2max_cycling` |

Every collection response of `None` is normalized safely to an empty collection
only where emptiness is a valid response. In particular,
`{"data":{"workoutScheduleSummariesScalar":null}}` is an empty schedule.
GraphQL `errors`, a non-object top-level response, or a missing/non-object
GraphQL `data` container is provider failure, not an empty schedule.

### Recovery and fitness normalization

Daily statistics independently populate resting-heart-rate and Body Battery
fields. Their availability is granular: one can be available while the other is
not, even though both came from one request. `heart_rate.date` and
`body_battery_date` retain the daily-stats calendar date independently from the
readiness fallback date.

Sleep, HRV, and readiness include the actual source date selected by the
today/previous-day policy. Sleep uses the nested `dailySleepDTO.sleepScores`
object and its `qualifierKey`; HRV deliberately names Garmin's upper bound
`baseline_balanced_upper_ms` rather than changing it to `high`.

The pinned `get_morning_training_readiness` wrapper returns either a selected
dictionary or `None`; it selects a wake-up entry itself when the underlying
response is a list. The normalizer supports both verified dictionary field pairs:
`readinessScore`/`readinessLevel` and `score`/`level`, plus the existing
`trainingReadinessLevel`/`trainingReadinessLevelKey` compatibility pair. Recovery
time is divided by 60 only when a finite numeric `recoveryTime` value is present.
`training_readiness` and `recovery_time` have separate availability flags.

Training status selects the primary training device when Garmin identifies one,
otherwise the first usable device entry. Load focus performs the same selection
independently in its separate device map. The service extracts only Garmin-
supplied status, feedback/trend, acute load, chronic load, ratio/status,
load-focus values, and running/cycling VO2 max. It never derives ACWR from acute
and chronic load: when Garmin omits `dailyAcuteChronicWorkloadRatio` or
`acwrStatus`, the corresponding output remains `null`, even when both loads are
present. `training_status`, `training_load`, `load_focus`, and `vo2max` have
separate availability flags. No status, load, fitness, readiness, or recovery
value is calculated by this feature.

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

The provider-to-availability mapping is fixed:

| Provider | Availability keys controlled | `true` condition |
|---|---|---|
| `activities` | `activities` | valid collection response, including empty |
| `last_run` | `last_run` | valid bounded search with a matching running activity |
| `scheduled_workouts` | `scheduled_workouts` | valid GraphQL collection, including empty |
| `daily_stats` | `resting_heart_rate` | at least one recognized resting-HR value |
| `daily_stats` | `body_battery` | recognized current Body Battery value |
| `sleep` | `sleep` | at least one recognized sleep value after fallback |
| `hrv` | `hrv` | at least one recognized HRV value after fallback |
| `training_readiness` | `training_readiness` | recognized score or level after fallback |
| `training_readiness` | `recovery_time` | recognized finite `recoveryTime` after fallback |
| `training_status` | `training_status` | recognized status, feedback, or fitness trend |
| `training_status` | `training_load` | at least one Garmin-supplied load, ratio, or ACWR-status value |
| `training_status` | `load_focus` | at least one recognized load-focus value |
| `training_status` | `vo2max` | running or cycling VO2 max present |

The 13 flags are intentionally retained as a scannable capability summary for
the AI coach. They also distinguish an empty successful collection from a failed
provider and separate metrics that share one provider, notably Body Battery and
training readiness.

Warnings are structured objects, never arbitrary raw exception strings:

```json
{
  "provider": "training_readiness",
  "code": "provider_unavailable",
  "message": "Training readiness is unavailable."
}
```

V1 uses exactly three warning codes:

- `provider_unavailable`
- `invalid_provider_response`
- `activities_truncated`

A capped period read reports, for example:

```json
{
  "provider": "activities",
  "code": "activities_truncated",
  "message": "Activity history reached the 200-record limit; period totals are lower bounds."
}
```

The message interpolates the computed cap: 200 in the default example, 400 for
30 days, and 1,000 for 90 days. The same code with provider `last_run` reports an
inconclusive capped latest-run search and does not claim period totals are lower
bounds.

The pinned client's normal API reads collapse 401, 429, 5xx, and timeout failures
into exception surfaces that do not retain reliable structured status/cause data.
V1 therefore does not parse exception message strings and does not pretend to
distinguish timeout, rate limit, or server errors. Finer codes are deferred until
the client or `_GarminProxy` preserves a structured cause/status.

Messages are concise and sanitized. They never include tokens, credentials,
request headers, raw response bodies, URLs with query data, or an exception's
unbounded representation. Provider names use stable internal names from the
eight contracts above: `activities`, `last_run`, `scheduled_workouts`,
`daily_stats`, `sleep`, `hrv`, `training_readiness`, and `training_status`.

The two core providers are `activities` and `scheduled_workouts`. A context is
usable when at least one core provider returns a valid collection, including an
empty collection. Last-run and health/fitness providers enrich that core but do
not independently make a context usable. This is the complete status decision
table:

| Condition | Status | Error | Continue? |
|---|---|---|---|
| `days` invalid | `error` | `invalid_days` | no Garmin calls |
| configured client missing/globally unusable before reads | `error` | `client_unavailable` | no |
| at least one core provider succeeds; no provider failures | `success` | `null` | complete |
| at least one core provider succeeds; one or more isolated provider failures | `partial_success` | `null` | complete remaining reads |
| both core providers fail | `error` | `context_unavailable` | stop immediately after the second core result |
| only legitimate optional-data absence occurs | `success` | `null` | complete |
| only `activities_truncated` warning occurs | `success` | `null` | complete |

An isolated failure means an exception, JSON-decode failure, or non-empty invalid
shape from any provider after the fatal conditions above have been excluded. A
warning alone does not imply `partial_success`: `activities_truncated` is an
informational completeness warning for either period activities or an
inconclusive capped last-run search, and legitimate missing optional data emits
no warning.

Runtime authentication failure cannot be identified reliably on pinned
`garminconnect==0.3.2`. Read-path `connectapi` wraps inner authentication, 429,
5xx, and timeout failures into `GarminConnectConnectionError` without structured
status/cause data. The unreachable `authentication_required` result is therefore
not part of v1. A dead session normally causes both core providers to fail and
returns `context_unavailable`; its sanitized error message says to re-run
`garmin-mcp-auth` if the session expired, otherwise retry later. The service does
not parse exception strings or attempt a rate-limit short-circuit. Stopping after
both core failures bounds repeated calls during a likely outage or rate limit.

`get_stats` separately raises `GarminConnectAuthenticationError` for
`privacyProtected: true` and `GarminConnectConnectionError` for an empty daily
summary. The provider catches both. Because period activities or the schedule has
already established a usable core before optional providers run, either daily-
stats exception is isolated as `provider_unavailable`.

The scheduled-workout provider has its own exception boundary because
`query_garmin_graphql` bypasses normal `connectapi` translation. Raw request
exceptions and Garmin connection exceptions become `provider_unavailable`.
JSON-decoding exceptions, GraphQL `errors`, non-object responses, or invalid
`data`/collection shapes become `invalid_provider_response`. Tests raise the
actual production exception classes rather than generic mock exceptions.

All other provider exceptions conservatively become `provider_unavailable`.
Non-empty unknown payloads become `invalid_provider_response`. Neither path
includes raw exception text in the MCP result.

Invalid `days` returns a concise structured `error` without making any Garmin
call. An empty activity period is a normal successful result, not an error.
Every result, including early errors, contains the same top-level envelope:
`status`, `error`, `period`, `schedule_period`, `availability`, `training`,
`recent_activities`, `recovery`, `sleep`, `hrv`, `heart_rate`, `fitness`,
`scheduled_workouts`, and `warnings`. Pre-Garmin values are always populated.
Unavailable scalar data is `null`, collections are empty, and every availability
flag begins `false`. For invalid `days`, `period.days` and `period.start_date` are
`null`; its `end_date` and both schedule dates still use injected/resolved today.
The stable error object never contains a raw exception:

```json
{
  "status": "error",
  "period": {
    "days": null,
    "start_date": null,
    "end_date": "2026-08-09"
  },
  "schedule_period": {
    "start_date": "2026-08-09",
    "end_date": "2026-08-15"
  },
  "availability": {
    "activities": false,
    "last_run": false,
    "scheduled_workouts": false,
    "sleep": false,
    "hrv": false,
    "resting_heart_rate": false,
    "body_battery": false,
    "training_readiness": false,
    "recovery_time": false,
    "training_status": false,
    "training_load": false,
    "load_focus": false,
    "vo2max": false
  },
  "error": {
    "code": "invalid_days",
    "message": "days must be an integer from 1 through 90"
  },
  "training": {
    "activity_count": null,
    "running_sessions": null,
    "sessions_by_sport": {},
    "total_training_minutes": null,
    "running_distance_km": null,
    "last_run_date": null,
    "days_since_last_run": null,
    "activities_truncated": false
  },
  "recent_activities": [],
  "recovery": {
    "readiness_date": null,
    "training_readiness": null,
    "training_readiness_level": null,
    "recovery_hours": null,
    "body_battery": null,
    "body_battery_date": null
  },
  "sleep": {
    "date": null,
    "duration_hours": null,
    "score": null,
    "score_qualifier": null
  },
  "hrv": {
    "date": null,
    "last_night_avg_ms": null,
    "weekly_avg_ms": null,
    "status": null,
    "baseline_balanced_low_ms": null,
    "baseline_balanced_upper_ms": null
  },
  "heart_rate": {
    "date": null,
    "resting_hr": null,
    "resting_hr_7_day_avg": null
  },
  "fitness": {
    "training_status": null,
    "training_status_feedback": null,
    "fitness_trend": null,
    "acute_load": null,
    "chronic_load": null,
    "acute_chronic_ratio": null,
    "acwr_status": null,
    "vo2max_running": null,
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

Error codes are limited to `invalid_days`, `client_unavailable`, and
`context_unavailable` in v1. The `context_unavailable` message is:
`Core Garmin context is unavailable. Re-run garmin-mcp-auth if your session
expired; otherwise retry later.` The same error result retains one sanitized
structured warning for each failed core provider so the caller can see that both
`activities` and `scheduled_workouts` were unavailable without receiving raw
exception details.

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
The profile allowlist addition and tool registration land in the same
implementation commit so the exact-equality startup invariant is never broken.

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
4. the shared running vocabulary applied to normal, trail, and treadmill runs;
5. same-day last run producing `days_since_last_run: 0`;
6. 200-record latest-run paging stopping on the first match, plus a bounded full
   search producing an informational inconclusive warning;
7. an empty activity period;
8. explicit `sortOrder="desc"`, absence of unverified `sortBy`, 200-record
   paging, calculated caps, and newest-first output independent of response
   order;
9. list, `activityList`, `None`, and invalid activity response roots for both
   period and last-run providers;
10. activity field reduction, raw-first aggregation, precision, and the 20-item
   output bound;
11. calculated-cap truncation plus mid-paging failure retention, warning, and
    lower-bound semantics;
12. scheduled workouts in exactly today through today plus six days;
13. GraphQL request exceptions, JSON decoding, GraphQL `errors`, invalid shapes,
    and `None` collection normalization using production exception types;
14. sleep, HRV, and readiness today values plus previous-day empty fallback and
    actual date provenance;
15. non-empty invalid overnight payloads not triggering fallback;
16. exact sleep, HRV, readiness, load-focus, and VO2 field paths;
17. readiness alias pairs and recovery minutes-to-hours conversion only when
    present;
18. resting heart rate and Body Battery independently dated and available from
    daily stats;
19. daily-stats privacy/auth and empty-summary failures remaining isolated;
20. Garmin-supplied ACWR retained and absent ACWR never derived from loads;
21. a legitimately missing optional metric without a warning;
22. each provider-to-availability-key mapping;
23. fixed execution order with both core providers first and immediate stop when
    both fail;
24. the complete status decision table, including both core-provider
    combinations and warnings that do not imply `partial_success`;
25. read-path authentication collapsing to core `context_unavailable`, plus
    missing/global client failures;
26. both core providers unavailable, producing total `error`, stopping optional
    calls, and not leaking exception details;
27. invalid values and types for `days`, with no provider calls and a stable
    response envelope;
28. accepted boundary values `days=1` and `days=90`;
29. the internal injected-today service seam and MCP argument shape;
30. compact MCP JSON return shape and Garmin/workout sport-vocabulary docs;
31. `ai-coach` profile declaration exactly matching actual registration;
32. the end-to-end service/tool path performing no write operation;
33. documentation-pinning assertions for bounds, fixed schedule window,
    read-only behavior, warning codes, fallback dates, and the two-tool workflow.

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
- the raw Garmin activity-type vocabulary and normalized workout-sport
  translation;
- an example output and the two-step coach workflow using
  `get_training_context` followed by `create_workout`.

The nested `error` object and structured warning list are the forward-looking
contract for new high-level AI tools. The existing `create_workout` response is
not changed in this PR; harmonizing already-published tool responses is separate
compatibility work.

## Deliberately Deferred

V1 does not add lactate threshold, last-hard-session detection, coaching advice,
training-plan generation, longitudinal sleep/HRV/readiness queries, activity
detail calls, per-workout detail calls, write operations, or concurrent provider
requests. It also omits per-activity training effect/load because their presence
in the bounded activity-list response has not been verified; adding detail calls
would violate the v1 request budget. Fine-grained timeout/rate-limit/server
warning codes remain deferred until the client/proxy preserves structured status
or exception causes. These can be considered separately only after their Garmin
behavior, cost, and coaching value are verified.
