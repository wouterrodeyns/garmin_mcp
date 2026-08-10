# AI Activity Analysis v1 Design

## Objective

Add one compact, read-only MCP tool that lets an AI coach inspect how one
completed Garmin activity was executed without exposing Garmin's full activity
API or second-by-second payloads:

```python
analyze_activity(activity_id: int | str)
```

This closes the coaching feedback loop without adding coaching judgment to the
server:

```text
get_training_context -> recommend -> create_workout -> athlete trains
        -> analyze_activity -> AI coach interprets the facts
```

`analyze_activity` returns a reduced activity summary plus sport-relevant laps,
zone distributions, or strength sets. It may calculate transparent unit
conversions and split comparisons, but it does not label an effort good, bad,
easy, hard, successful, or failed and it does not recommend the next session.

## Scope and product boundary

V1 supports four sport families with a generic fallback:

- running and walking: activity summary, laps, and heart-rate zones when the
  summary contains a heart-rate signal;
- cycling: activity summary, laps, heart-rate zones when heart rate exists, and
  power zones when power exists;
- strength: activity summary and exercise sets/repetitions;
- every other or unrecognized Garmin activity type: activity summary only.

The tool reads the configured, pinned `garminconnect==0.3.2` client directly. It
does not call the existing `get_activity`, `get_activity_splits`, zone, or set
MCP tools internally. Those low-level tools remain available under the broad
upstream-compatible registration, but Garmin DTOs stay behind the new
abstraction for the recommended `ai-coach` profile.

V1 deliberately excludes:

- FIT downloads, record-by-record samples, `get_activity_details`, map
  polylines, typed splits, and split summaries;
- weather, gear, course, device, and location data;
- scheduled-workout linkage, calendar-entry lookup, `wktStepIndex`
  interpretation, and comparison against prescribed workout steps;
- mutation of activity names, types, descriptions, RPE, feel, gear, or any
  other Garmin data;
- coaching recommendations, pass/fail judgments, inferred intensity labels,
  HR drift/decoupling, cardiac efficiency, fatigue classification, or workout
  compliance scores;
- strength volume/load calculations until the units and semantics of Garmin's
  exercise-set weight fields have been verified with live payloads.

The server may report Garmin-supplied training effect, training load, workout
RPE, and workout feel as facts. It must not reinterpret those values.

## Architecture

Fork-owned code lives in a new package:

```text
src/garmin_mcp/ai_activity/
    __init__.py
    providers.py
    service.py
    tools.py
```

- `providers.py` contains five small, read-only wrappers around the pinned
  client and translates exceptions into bounded internal results without
  interpreting activity metrics.
- `service.py` validates the identifier, classifies the sport, gates follow-up
  reads, normalizes the known Garmin fields, calculates only the documented
  transparent metrics, and applies the stable response contract.
- `tools.py` configures the shared proxied Garmin client, registers
  `analyze_activity`, and JSON-encodes the service result.
- `__init__.py` exposes the package's configure/register entry points and stable
  constants needed by tests.

`garmin_mcp/__init__.py` receives the only runtime integration changes: import
and configure `ai_activity`, register its tool alongside the other packages,
and add `analyze_activity` to `TOOL_PROFILES["ai-coach"]`. Existing
upstream-oriented activity, authentication, proxy, and Garmin client modules are
not rewritten.

The data flow is:

```text
pinned Garmin client reads
        -> ai_activity providers
        -> sport-gated normalization service
        -> compact factual analyze_activity result
        -> AI coach
```

Calls are sequential. A follow-up call is made only after the base activity has
identified the sport and exposed the signal needed for that provider. This
keeps behavior deterministic, preserves the existing session/proxy model, and
avoids fetching irrelevant payloads.

## Pinned client provider contracts

The installed `garminconnect==0.3.2` client exposes these verified methods:

| Provider | Pinned client method | Purpose |
|---|---|---|
| `activity` | `client.get_activity(activity_id)` | required base summary and sport |
| `splits` | `client.get_activity_splits(activity_id)` | lap summaries |
| `heart_rate_zones` | `client.get_activity_hr_in_timezones(activity_id)` | HR time-in-zone distribution |
| `power_zones` | `client.get_activity_power_in_timezones(activity_id)` | cycling power time-in-zone distribution |
| `strength` | `client.get_activity_exercise_sets(activity_id)` | strength exercises and sets |

Every method is a read through `connectapi`. The feature must call these client
methods, not reconstruct their URLs and not call `client.client.*`. Provider
functions take the configured client and normalized integer activity ID and
return an internal result object; they never return JSON strings or raw
exceptions to the MCP boundary.

Provider results distinguish a successful raw response from an exception. The
service owns all payload-shape validation and metric normalization, so there is
one authoritative set of field rules rather than duplicated provider/service
parsers.

The required base provider is called first. A missing client or a base failure
ends the request. Optional providers are then called in this fixed order when
applicable: `splits`, `heart_rate_zones`, `power_zones`, `strength`. `strength`
is mutually exclusive with the three endurance-sport providers under the v1
sport vocabulary.

### Exact sport vocabulary

Sport classification uses only `activityTypeDTO.typeKey`, falling back to
`activityType.typeKey` for the alternate response shape already represented in
the repository. The raw Garmin key is always returned as `activity.sport`.

The v1 families are fixed and centralized in `ai_activity` constants:

```python
RUNNING_TYPE_KEYS = frozenset({
    "running",
    "trail_running",
    "treadmill_running",
})

WALKING_TYPE_KEYS = frozenset({
    "walking",
    "treadmill_walking",
})

CYCLING_TYPE_KEYS = frozenset({
    "cycling",
    "indoor_cycling",
    "road_biking",
    "mountain_biking",
    "gravel_cycling",
})

STRENGTH_TYPE_KEYS = frozenset({"strength_training"})
```

These keys are evidenced by the current repository's activity, course, and
workout integrations. V1 does not infer a family from a substring, display
name, undocumented numeric parent ID, or unknown Garmin subtype. An unlisted
key receives the generic base-only response. Adding a verified subtype later is
a small constant-and-test change rather than a schema change.

### Exact provider gating and call budget

| Family | Splits | HR zones | Power zones | Strength sets | Maximum calls |
|---|---|---|---|---|---:|
| running | yes, unless `metadataDTO.hasSplits is False` | only with a positive HR signal | never | never | 3 |
| walking | yes, unless `metadataDTO.hasSplits is False` | only with a positive HR signal | never | never | 3 |
| cycling | yes, unless `metadataDTO.hasSplits is False` | only with a positive HR signal | only with a positive power signal | never | 4 |
| strength | never | never | never | always | 2 |
| generic/unknown | never | never | never | never | 1 |

An HR signal exists when any of `summaryDTO.averageHR`, `maxHR`, or `minHR` is a
finite number greater than zero. A power signal exists when any of
`summaryDTO.averagePower`, `maxPower`, or `normalizedPower` is a finite number
greater than zero. Boolean values are never numeric signals. Missing signal
data prevents the corresponding provider call; this is normal, emits no
warning, and leaves the availability flag false.

`metadataDTO.hasSplits` suppresses the split call only when it is the literal
boolean `false`. Missing, null, true, or an unrecognized value does not suppress
the read for a recognized endurance family because older activity payloads may
omit that metadata while the split endpoint remains useful.

The service never calls a provider twice and performs no pagination. Garmin's
split endpoint returns one activity's lap collection in one response. The
output cap described below reduces model payload size; it is not an additional
Garmin request.

## Input validation

`activity_id` accepts a positive integer or an ASCII decimal string. Leading and
trailing whitespace in a string is ignored. The service rejects:

- booleans;
- zero and negative integers;
- empty strings;
- signs, decimal points, exponents, separators, or non-ASCII digits;
- floats, lists, objects, and every other type.

The accepted value is normalized once to a Python integer and that integer is
passed to every provider. Invalid input returns `invalid_activity_id` without a
Garmin call. This behavior is pinned at the service seam. The MCP JSON schema
requires the argument and declares its integer-or-string shape; a missing
argument is rejected by FastMCP before the service and therefore does not
return the service envelope.

## Stable normalized response

Every result contains exactly these top-level keys:

```text
status
error
activity
availability
splits
heart_rate_zones
power_zones
strength
derived
warnings
```

Unavailable optional sections are `null`, not an object populated with zeros.
Collections inside an available section are lists and may legitimately be
empty. A numeric zero is retained only when Garmin supplied a valid zero or a
documented aggregate over known values is exactly zero.

On every successful base read, the `activity` object contains every field shown
in the examples, including all nested `heart_rate`, `power`, `cadence`,
`elevation`, `training_effect`, `workout_feedback`, and `recovery` keys; missing
values are null. Available `splits`, zone, and strength sections likewise retain
their documented counters/collections even when empty. The `derived` object
always contains its six documented keys. This makes both top-level and nested
shapes stable without turning absence into zero.

### Successful running example

```json
{
  "status": "success",
  "error": null,
  "activity": {
    "id": 123456789,
    "name": "Progression Run",
    "description": null,
    "sport": "running",
    "sport_family": "running",
    "event_type": "training",
    "start_time_local": "2026-08-10 07:14:00",
    "duration_minutes": 58.2,
    "moving_duration_minutes": 56.9,
    "elapsed_duration_minutes": 60.1,
    "distance_km": 10.42,
    "average_speed_kph": 10.7,
    "max_speed_kph": 15.1,
    "average_pace": "5:35/km",
    "heart_rate": {
      "average_bpm": 151,
      "max_bpm": 174,
      "min_bpm": 91
    },
    "power": {
      "average_watts": null,
      "max_watts": null,
      "normalized_watts": null
    },
    "cadence": {
      "average_spm": 170,
      "max_spm": 186
    },
    "elevation": {
      "gain_meters": 44.0,
      "loss_meters": 43.0,
      "minimum_meters": 17.0,
      "maximum_meters": 35.0
    },
    "calories": 642,
    "training_effect": {
      "aerobic": 3.6,
      "anaerobic": 1.4,
      "label": "THRESHOLD",
      "load": 146
    },
    "workout_feedback": {
      "rpe": 70,
      "feel": 75
    },
    "recovery": {
      "heart_rate_bpm": 32,
      "body_battery_impact": -12
    },
    "reported_lap_count": 2
  },
  "availability": {
    "activity": true,
    "splits": true,
    "heart_rate_zones": true,
    "power_zones": false,
    "strength": false
  },
  "splits": {
    "total_count": 2,
    "returned_count": 2,
    "truncated": false,
    "items": [
      {
        "lap_number": 1,
        "start_time": "2026-08-10T05:14:00.0",
        "duration_minutes": 15.0,
        "moving_duration_minutes": 14.8,
        "elapsed_duration_minutes": 15.0,
        "distance_km": 2.61,
        "average_speed_kph": 10.4,
        "max_speed_kph": 12.2,
        "pace": "5:45/km",
        "average_hr_bpm": 136,
        "max_hr_bpm": 153,
        "average_cadence_spm": 168,
        "average_power_watts": null,
        "calories": 154,
        "elevation_gain_meters": 11.0,
        "elevation_loss_meters": 10.0,
        "intensity_type": "WARMUP"
      },
      {
        "lap_number": 2,
        "start_time": "2026-08-10T05:29:00.0",
        "duration_minutes": 43.2,
        "moving_duration_minutes": 42.1,
        "elapsed_duration_minutes": 45.1,
        "distance_km": 7.81,
        "average_speed_kph": 10.8,
        "max_speed_kph": 15.1,
        "pace": "5:32/km",
        "average_hr_bpm": 156,
        "max_hr_bpm": 174,
        "average_cadence_spm": 171,
        "average_power_watts": null,
        "calories": 488,
        "elevation_gain_meters": 33.0,
        "elevation_loss_meters": 33.0,
        "intensity_type": "ACTIVE"
      }
    ]
  },
  "heart_rate_zones": {
    "items": [
      {
        "zone": 1,
        "duration_seconds": 420,
        "duration_minutes": 7.0,
        "percentage": 12.0,
        "lower_bpm": null,
        "upper_bpm": null
      },
      {
        "zone": 2,
        "duration_seconds": 1200,
        "duration_minutes": 20.0,
        "percentage": 34.4,
        "lower_bpm": null,
        "upper_bpm": null
      },
      {
        "zone": 3,
        "duration_seconds": 1872,
        "duration_minutes": 31.2,
        "percentage": 53.6,
        "lower_bpm": null,
        "upper_bpm": null
      }
    ]
  },
  "power_zones": null,
  "strength": null,
  "derived": {
    "scope": "all_returned_splits",
    "fastest_split_number": 2,
    "fastest_pace": "5:32/km",
    "slowest_split_number": 1,
    "slowest_pace": "5:45/km",
    "pace_range_seconds_per_km": 13
  },
  "warnings": []
}
```

The values above are illustrative facts, not a server assessment that the
workout was executed well.

### Successful strength example

```json
{
  "status": "success",
  "error": null,
  "activity": {
    "id": 22334455,
    "name": "Full Body",
    "description": null,
    "sport": "strength_training",
    "sport_family": "strength",
    "event_type": "training",
    "start_time_local": "2026-08-09 18:00:00",
    "duration_minutes": 42.5,
    "moving_duration_minutes": null,
    "elapsed_duration_minutes": 48.0,
    "distance_km": null,
    "average_speed_kph": null,
    "max_speed_kph": null,
    "average_pace": null,
    "heart_rate": {"average_bpm": 121, "max_bpm": 158, "min_bpm": 78},
    "power": {"average_watts": null, "max_watts": null, "normalized_watts": null},
    "cadence": {"average_spm": null, "max_spm": null},
    "elevation": {"gain_meters": null, "loss_meters": null, "minimum_meters": null, "maximum_meters": null},
    "calories": 311,
    "training_effect": {"aerobic": 1.8, "anaerobic": 1.1, "label": null, "load": 34},
    "workout_feedback": {"rpe": 60, "feel": 75},
    "recovery": {"heart_rate_bpm": null, "body_battery_impact": -6},
    "reported_lap_count": null
  },
  "availability": {
    "activity": true,
    "splits": false,
    "heart_rate_zones": false,
    "power_zones": false,
    "strength": true
  },
  "splits": null,
  "heart_rate_zones": null,
  "power_zones": null,
  "strength": {
    "exercise_count": 1,
    "set_count": 3,
    "repetition_count": 24,
    "items": [
      {
        "name": "Bench Press",
        "set_count": 3,
        "repetition_count": 24,
        "sets": [
          {"set_number": 1, "repetitions": 10},
          {"set_number": 2, "repetitions": 8},
          {"set_number": 3, "repetitions": 6}
        ]
      }
    ]
  },
  "derived": {
    "scope": null,
    "fastest_split_number": null,
    "fastest_pace": null,
    "slowest_split_number": null,
    "slowest_pace": null,
    "pace_range_seconds_per_km": null
  },
  "warnings": []
}
```

Weight is intentionally absent even if Garmin includes a `weight` field.

## Exact base-activity mapping

The base response must be a non-empty object whose `activityId` is a positive
integer-equivalent value equal to the requested ID. Missing, malformed, or
mismatched IDs make the base response invalid. The normalizer reads only the
following known paths:

| Garmin path | Normalized field |
|---|---|
| `activityId` | `activity.id` |
| `activityName` | `activity.name` |
| `description` | `activity.description` |
| `activityTypeDTO.typeKey`, fallback `activityType.typeKey` | `activity.sport` and classification |
| `eventTypeDTO.typeKey`, fallback `eventType.typeKey` | `activity.event_type` |
| `summaryDTO.startTimeLocal` | `activity.start_time_local` |
| `summaryDTO.duration` | `activity.duration_minutes` |
| `summaryDTO.movingDuration` | `activity.moving_duration_minutes` |
| `summaryDTO.elapsedDuration` | `activity.elapsed_duration_minutes` |
| `summaryDTO.distance` | `activity.distance_km` |
| `summaryDTO.averageSpeed`, `.maxSpeed` | `activity.average_speed_kph`, `.max_speed_kph` |
| `summaryDTO.averageHR`, `.maxHR`, `.minHR` | `activity.heart_rate` fields |
| `summaryDTO.averagePower`, `.maxPower`, `.normalizedPower` | `activity.power` fields |
| `summaryDTO.averageRunCadence`, `.maxRunCadence` | `activity.cadence` fields |
| `summaryDTO.elevationGain`, `.elevationLoss`, `.minElevation`, `.maxElevation` | `activity.elevation` fields |
| `summaryDTO.calories` | `activity.calories` |
| `summaryDTO.trainingEffect`, `.anaerobicTrainingEffect`, `.trainingEffectLabel`, `.activityTrainingLoad` | `activity.training_effect` |
| `summaryDTO.directWorkoutRpe`, `.directWorkoutFeel` | `activity.workout_feedback` |
| `summaryDTO.recoveryHeartRate`, `.differenceBodyBattery` | `activity.recovery` |
| `metadataDTO.lapCount` | `activity.reported_lap_count` |
| `metadataDTO.hasSplits` | split-call suppression only |

The service does not fall back from these summary fields to similarly named
top-level fields. A missing optional base metric remains null. Strings are
trimmed; empty strings become null. Numeric values must be finite and not
boolean. Durations, distances, speeds, cadence, heart rate, power, calories,
loads, and elevations use their physical validity constraints: durations,
distances, speed, calories, and load cannot be negative; heart rate, cadence,
and power must be positive when present; elevation and Body Battery impact may
be negative where Garmin semantics allow it.

`activity.average_pace` is calculated only for the running and walking families
and only when normalized duration and distance source values are both positive.
It is not calculated from rounded display values. Generic and cycling
activities leave it null even if distance and duration exist.

## Split normalization, limit, and derived metrics

The accepted split root is a non-empty object containing a `lapDTOs` list.
`{"lapDTOs": []}` is a valid available empty split collection. `None` or `{}`
means no split data in this snapshot: availability remains false and no warning
is emitted. Any other non-empty root is `invalid_provider_response`.

Each list entry must be an object. A non-object entry is dropped, usable entries
are retained, and exactly one `invalid_provider_response` warning is emitted for
the provider. An object is usable only when at least one normalized field in the
table below is valid; an empty or entirely unrecognized object is invalid and
is not returned. The normalized split fields are:

| Garmin lap field | Normalized split field |
|---|---|
| `lapIndex` | `lap_number` |
| `startTimeGMT` | `start_time` |
| `duration` | `duration_minutes` |
| `movingDuration` | `moving_duration_minutes` |
| `elapsedDuration` | `elapsed_duration_minutes` |
| `distance` | `distance_km` |
| `averageSpeed`, `maxSpeed` | `average_speed_kph`, `max_speed_kph` |
| `duration` + `distance` for run/walk only | `pace` |
| `averageHR`, `maxHR` | `average_hr_bpm`, `max_hr_bpm` |
| `averageRunCadence` | `average_cadence_spm` |
| `averagePower` | `average_power_watts` |
| `calories` | `calories` |
| `elevationGain`, `elevationLoss` | elevation fields |
| `intensityType` | `intensity_type` |

The service preserves Garmin's source order and returns at most
`MAX_RETURNED_SPLITS = 100` normalized entries. One hundred is high enough for
ordinary endurance workouts and low enough to prevent unusually lap-heavy
activities from dominating model context. The endpoint itself is not paged, so
`total_count` is the source-list length and `returned_count` is the output-list
length after invalid entries are removed and the cap is applied.

When more than 100 source laps exist:

- the first 100 source-order laps are considered for normalization;
- `splits.truncated` is true;
- one `splits_truncated` warning is emitted;
- status remains `success` unless a provider also failed or was malformed;
- every derived split-comparison field remains null and `derived.scope` is
  `null`, because the returned subset cannot establish whole-activity extrema.

When the split result is not truncated, pace comparisons use every returned
split with a valid positive duration and distance. They apply only to the
running and walking families. Fastest means the lowest seconds per kilometre;
slowest means the highest. Ties choose the first item in source order. The
reported split number is `lap_number` when it is a valid positive integer,
otherwise its one-based returned position.

The exact pace formula is:

```text
raw_seconds_per_km = duration_seconds / (distance_meters / 1000)
display_seconds_per_km = int(round(raw_seconds_per_km))
display = total_minutes + ":" + zero-padded seconds + "/km"
```

Python's `round` behavior is the v1 rounding mode. `pace_range_seconds_per_km`
is `int(round(max(raw_pace) - min(raw_pace)))`, calculated from raw values, not
the formatted pace strings. A single valid split has a range of `0` and is both
fastest and slowest. `derived.scope` is `all_returned_splits` only when at least
one valid comparison exists and the response is not truncated.

This is a transparent split calculation, not HR drift, decoupling, effort
classification, or prescription compliance.

## Zone normalization

HR and power-zone providers accept either a top-level list or an object whose
`zones` value is a list, matching the pinned low-level integration and current
fixtures. An explicit empty list or `{"zones": []}` is an available empty
collection. `None` or `{}` means no data in this snapshot and does not warn.
Every other non-empty root is invalid.

Each zone entry must be an object. V1 extracts these exact fields:

| Garmin field | HR output | Power output |
|---|---|---|
| `zone` | `zone` | `zone` |
| `timeInZone` | `duration_seconds` and converted `duration_minutes` | same |
| `percentageInZone` | `percentage` | `percentage` |
| `zoneLowBoundary` | `lower_bpm` | `lower_watts` |
| `zoneHighBoundary` | `upper_bpm` | `upper_watts` |

The service does not invent a zone number, percentage, or boundary from list
position or other fields. Zone number must be a positive integer; time must be
a finite non-negative number of seconds; percentage must be finite and from 0
through 100; boundaries must be finite non-negative numbers. Missing fields
remain null. An object is retained when it has at least one recognized valid
value. Invalid entries are dropped while usable entries are retained, and the
provider emits one `invalid_provider_response` warning.

Duration minutes are seconds divided by 60 and rounded to one decimal. The
Garmin-supplied percentage is rounded to one decimal; percentages are never
recomputed or forced to sum to 100. Source order is preserved. V1 does not
assign labels such as recovery, aerobic, threshold, or VO2 max to zone numbers.

## Strength normalization

The accepted strength root is a non-empty object containing an `exercises`
list, matching the current repository fixture for
`get_activity_exercise_sets`. `{"exercises": []}` is a valid available empty
collection. `None` or `{}` means no exercise-set data in this snapshot and does
not warn. Other non-empty roots are invalid.

Each exercise is an object with optional `exerciseName` and a required `sets`
list. Each set is an object. V1 returns only:

- trimmed `exerciseName` as `name`;
- positive integer `setNumber` as `set_number`;
- non-negative integer `reps` as `repetitions`;
- per-exercise and whole-activity set/repetition counts.

Boolean values are invalid integers. A set object is retained if it contains a
valid set number or repetitions. An exercise is retained when it has a name or
at least one retained set. Invalid entries are dropped, usable entries remain,
and exactly one provider-level `invalid_provider_response` warning is emitted.

`set_count` counts retained set objects, including a retained set whose reps
are missing. `repetition_count` sums raw valid reps and is null when no retained
set contains a valid repetition value. A known set collection whose valid reps
sum to zero reports `0`, not null. Activity totals sum the per-set raw integer
reps once; they are not reconstructed from rounded or display values.

V1 deliberately ignores weight, resistance, unit, exercise category, duration,
and volume fields. It must not calculate kilograms, pounds, tonnage, or volume
until a separately reviewed live-payload verification establishes Garmin's
weight units and missing-data semantics.

## Numeric conversion and missing-data rules

All display conversions operate on validated raw Garmin values:

- seconds to minutes: divide by 60 and round to one decimal;
- metres to kilometres: divide by 1,000 and round to two decimals;
- metres/second to kilometres/hour: multiply by 3.6 and round to one decimal;
- pace: the whole-second formula above;
- zone percentage: round Garmin's value to one decimal;
- elevations: round to one decimal;
- other Garmin-supplied numeric facts retain their numeric value after finite
  validation; integer-equivalent identifiers/counts are emitted as integers.

Python's built-in `round(value, places)` is the v1 rounding mode. Calculations
use raw source units first. For example, pace for 1,000 metres in 259.6 seconds
is formatted from 259.6 and becomes `4:20/km`; it is not calculated from a
rounded `4.3` display minute value.

Missing is never converted to zero. Empty strings, booleans in numeric fields,
NaN, positive/negative infinity, and physically invalid values are missing. A
missing optional field within an otherwise recognized object does not warn.
Provider warnings describe failed or malformed sources, not ordinary Garmin
metric absence.

## Availability, warnings, and status

`availability` has exactly five flags:

| Provider | Availability key | True condition |
|---|---|---|
| `activity` | `activity` | valid base object for the requested ID |
| `splits` | `splits` | valid empty `lapDTOs` list, a fully valid non-empty list, or at least one retained item from a partially malformed list |
| `heart_rate_zones` | `heart_rate_zones` | valid empty zone list, a fully valid non-empty list, or at least one retained item |
| `power_zones` | `power_zones` | valid empty zone list, a fully valid non-empty list, or at least one retained item |
| `strength` | `strength` | valid empty exercise list, a fully valid non-empty list, or at least one retained item |

A provider skipped by sport/signal gating is false with a null section and no
warning. `None`/`{}` from an optional provider is also false with no warning: it
means the metric was not available in this snapshot, not that the account or
device can never provide it. An explicitly recognized empty collection is true
with an empty section. A non-empty collection in which every entry is invalid
is unavailable, emits `invalid_provider_response`, and causes
`partial_success`; it is not treated as a valid empty collection.

Warnings are structured and sanitized:

```json
{
  "provider": "heart_rate_zones",
  "code": "provider_unavailable",
  "message": "Heart-rate zone data is unavailable."
}
```

V1 uses exactly three warning codes:

- `provider_unavailable`: an attempted optional provider raised;
- `invalid_provider_response`: a non-empty provider response or one or more
  collection entries did not match the accepted shape;
- `splits_truncated`: more than 100 source laps were intentionally omitted from
  the MCP result.

Messages are fixed by provider/code so tests and clients do not depend on
exception text:

| Provider/code | Message |
|---|---|
| `splits/provider_unavailable` | `Activity splits are unavailable.` |
| `splits/invalid_provider_response` | `Activity splits response had an unexpected shape.` |
| `splits/splits_truncated` | `Activity splits were limited to 100 laps; split comparisons are unavailable.` |
| `heart_rate_zones/provider_unavailable` | `Heart-rate zone data is unavailable.` |
| `heart_rate_zones/invalid_provider_response` | `Heart-rate zone response had an unexpected shape.` |
| `power_zones/provider_unavailable` | `Power-zone data is unavailable.` |
| `power_zones/invalid_provider_response` | `Power-zone response had an unexpected shape.` |
| `strength/provider_unavailable` | `Strength exercise-set data is unavailable.` |
| `strength/invalid_provider_response` | `Strength exercise-set response had an unexpected shape.` |

Warnings never contain exception text, raw Garmin payloads, URLs, headers,
tokens, email addresses, passwords, MFA data, or request identifiers. Multiple
invalid entries in one response produce one warning, not one per item. A
provider can contribute at most one failure/malformed warning plus the
independent split truncation warning.

Status and errors follow this exact table:

| Condition | Status | Error | Optional reads |
|---|---|---|---|
| invalid `activity_id` | `error` | `invalid_activity_id` | none |
| configured client is `None` | `error` | `client_unavailable` | none |
| base provider raises | `error` | `activity_unavailable` | none |
| base provider returns `None` or `{}` | `error` | `activity_not_found` | none |
| base provider returns another invalid/mismatched shape | `error` | `invalid_activity_response` | none |
| base valid; all attempted optional providers valid or legitimately empty; no malformed data | `success` | `null` | complete |
| base valid; at least one attempted optional provider raises or is malformed | `partial_success` | `null` | continue all other applicable providers |
| base valid; only `splits_truncated` warning occurs | `success` | `null` | complete |
| optional providers are skipped or return legitimate absence | `success` | `null` | complete |

The pinned client does not preserve sufficiently reliable status/cause
information on every read to distinguish not-found, authentication, timeout,
rate-limit, and server failures from exceptions alone without parsing strings.
V1 does not parse exception messages. An empty base response is the only
`activity_not_found` signal; a raised base read is conservatively
`activity_unavailable`. Finer transport classification is deferred until the
client/proxy exposes structured causes/status.

The `error` object is always either null or:

```json
{
  "code": "activity_unavailable",
  "message": "Activity data is unavailable. Check the activity ID, re-run garmin-mcp-auth if the session expired, or retry later."
}
```

Error messages are fixed, actionable strings:

| Error code | Message |
|---|---|
| `invalid_activity_id` | `activity_id must be a positive integer or decimal string.` |
| `client_unavailable` | `Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.` |
| `activity_not_found` | `No activity data was found for the requested activity ID.` |
| `invalid_activity_response` | `Activity data had an unexpected shape.` |
| `activity_unavailable` | `Activity data is unavailable. Check the activity ID, re-run garmin-mcp-auth if the session expired, or retry later.` |

They do not echo the input or exception. Error results preserve the complete top-level envelope with
`activity: null`, every availability flag false, every detail section null, a
fully null `derived` object, and no raw exception warning. Invalid optional
providers do not erase a valid base or other detail sections.

## Read-only and security guarantees

This feature is read-only by construction:

- providers may call only the five methods listed in the provider table;
- it never obtains or calls `client.client.post`, `put`, `delete`, or raw
  request methods;
- it never calls upload, schedule, unschedule, update, delete, edit, import,
  request-reload, gear-link, or credential-management functions;
- tool arguments contain only an activity ID; credentials and token paths are
  not MCP arguments;
- provider exceptions and responses are normalized before reaching JSON;
- activity description is returned because it is user-authored activity data,
  but it is trimmed and bounded to 500 characters; activity name is bounded to
  200 characters, exercise names to 120 characters, and all other returned
  strings to 100 characters. Longer strings are truncated without appending raw
  data and produce no extra Garmin call.

The test harness uses a recording client that raises immediately on unexpected
attribute access and explicitly defines common write methods (`upload_workout`,
`schedule_workout`, `unschedule_workout`, `delete_workout`, activity setters,
`client.post`, `client.put`, and `client.delete`) to fail the test if invoked.

## MCP and profile integration

The MCP signature is exactly:

```python
async def analyze_activity(activity_id: int | str) -> str:
```

The tool description states that it is read-only, factual, bounded, and
sport-aware; that optional Garmin detail may be null/unavailable; and that the
AI must interpret the evidence rather than treating the response as coaching
advice. The MCP tool exposes no cap, sport override, provider selector, date, or
internal test seam.

`GARMIN_TOOL_PROFILE=ai-coach` changes atomically from 11 to exactly 12 tools:

```text
get_training_context
analyze_activity
create_workout
get_activities
get_activities_by_date
get_activity
get_workouts
get_workout_by_id
get_scheduled_workouts
schedule_workout
unschedule_workout
delete_workout
```

No existing profile tool is removed. The low-level `get_activity` remains for
compatibility and targeted inspection, while `analyze_activity` becomes the
preferred completed-session read. Profile allowlist membership and tool
registration must land in the same commit so startup's exact-registration
check cannot fail between changes. Explicit allowlist/denylist precedence and
the broad profile-unset default remain unchanged.

## Documentation

Add `docs/ai-activity.md` covering:

- the feedback-loop role of `analyze_activity`;
- the exact sport families and provider gating;
- the stable response, availability, warnings, and missing-data meaning;
- unit conversions, split cap, and the fact that derived values are mechanical;
- excluded raw/activity-detail data and non-goals;
- the difference between Garmin raw activity type keys and
  `create_workout.sport`'s normalized vocabulary;
- the read-only guarantee and device/account/sync variability;
- a workflow in which the AI first identifies a completed activity using a
  bounded activity read, calls `analyze_activity(activity_id)`, explains its
  interpretation, and only creates another workout after confirmation.

Update the README, `docs/setup.md`, `docs/ai-training.md`, and
`docs/ai-workouts.md` where they claim exactly 11 tools or describe only two
high-level tools. The README should keep `get_training_context` as the coach's
eyes and `create_workout` as its hands, and introduce `analyze_activity` as the
completed-session feedback tool rather than redefining it as a third mutation
or another training-context aggregate. Every published 12-tool list must match
`TOOL_PROFILES["ai-coach"]` exactly.

Historical design specifications and implementation plans remain historical
records and are not rewritten merely because the live profile grew.

## Test strategy and acceptance criteria

Normal tests use mocks/fixtures and require no live Garmin account. Add unit
tests under `tests/unit/ai_activity/`, MCP/integration tests using the existing
FastMCP test style, startup/profile tests, read-only tests, and documentation
contract tests.

At minimum, tests must pin all of the following:

1. integer and whitespace-trimmed decimal-string activity IDs normalize to the
   same positive integer;
2. bool, zero, negative, float, signed string, decimal string, exponent, empty,
   Unicode-digit, list, and object IDs fail before a provider call;
3. missing configured client returns the stable `client_unavailable` envelope;
4. empty base activity returns `activity_not_found`;
5. raised base provider returns sanitized `activity_unavailable` and makes no
   optional calls;
6. malformed and mismatched-ID base responses return
   `invalid_activity_response`;
7. complete running normalization, including summary, laps, HR zones, pace,
   fastest/slowest split, and call order;
8. trail and treadmill running use the running family;
9. walking and treadmill walking use the walking family;
10. all five enumerated cycling type keys use the cycling family;
11. cycling with HR and power signals makes exactly four total calls and
    normalizes both zone groups;
12. cycling without HR/power signals skips only the corresponding zone calls;
13. strength makes only the base and exercise-set calls and normalizes set and
    repetition counts without returning weight;
14. an unknown sport returns a base-only success in one call;
15. literal `hasSplits: false` suppresses splits while missing/null metadata
    does not;
16. missing HR and power signals suppress their providers without warnings;
17. every base field path and fallback type/event path in the mapping table;
18. finite/physical numeric validation, null-not-zero behavior, and string
    bounds;
19. duration, distance, speed, elevation, and raw-first pace rounding;
20. valid empty split, zone, and exercise collections are available and empty;
21. `None`/`{}` optional responses are unavailable without warnings;
22. a non-empty wrong root is `invalid_provider_response` and causes
    `partial_success`;
23. mixed valid/invalid collection items retain valid facts, emit one warning,
    and cause `partial_success`;
24. one optional provider exception is sanitized, later applicable providers
    still run, and the result is `partial_success`;
25. multiple optional provider failures produce ordered provider warnings with
    no raw exception text;
26. zone percentages are not derived, renormalized, or forced to total 100;
27. power/HR zone boundaries retain their explicit units and do not gain
    intensity labels;
28. 100 or fewer splits are returned without truncation;
29. 101 splits return the first 100, one `splits_truncated` warning, success
    status, and null derived extrema;
30. fastest/slowest calculations use raw pace, source-order tie-breaking, and a
    one-split zero range;
31. cycling and generic activities never receive run/walk pace-derived extrema;
32. strength reps distinguish missing from known zero and totals count each set
    once;
33. output contains no strength weight or calculated volume even when fixture
    inputs include weight fields;
34. maximum Garmin call budgets are 3 for run/walk, 4 for cycling, 2 for
    strength, and 1 for generic;
35. provider order is base, splits, HR zones, power zones, strength as
    applicable;
36. the read-only recording client proves no write/raw-request method is called
    for every sport family and for partial failures;
37. MCP schema exposes only required `activity_id` and accepts integer/string
    values;
38. MCP return JSON has the exact stable top-level envelope;
39. `TOOL_PROFILES["ai-coach"]` exactly matches the 12 registered tools;
40. profile registration and allowlist integration occur together and startup
    reports no unknown configured tool;
41. README and live docs consistently say 12 tools, list the same members, link
    `docs/ai-activity.md`, and do not leave a current-facing “exactly 11” claim;
42. docs state read-only behavior, provider gating, null semantics, split cap,
    mechanical derivations, workout-sport translation, and all v1 non-goals;
43. existing `get_training_context`, `create_workout`, legacy activity tools,
    authentication, filtering, and offline tests remain unbroken.

Tests must use hard-coded expected values rather than reproducing production
formulas in the assertion. Fixture identifiers, descriptions, and exception
messages include secret-like strings so serialization tests can prove they are
absent from error/warning output.

Verification commands are:

```bash
uv run pytest tests/unit/ai_activity tests/integration/test_ai_activity_tools.py tests/unit/test_ai_activity_docs.py tests/unit/test_server_startup.py tests/unit/test_tool_filter.py
uv run pytest -m "not e2e"
```

The focused paths may be adjusted to the repository's final test-file naming,
but the full offline command is mandatory. Live Garmin E2E tests are not part of
normal verification.

## Upstream compatibility and deliberate divergence

This feature adds a fork-owned package and minimal import/configure/register
lines. It reuses the pinned client's maintained authentication, session,
request, and endpoint methods and preserves the low-level Taxuspt tools. It does
not duplicate Garmin login logic or move normalization into upstream-oriented
modules.

The intentional fork divergence is the narrow, LLM-friendly analysis layer and
its inclusion in the curated profile. The broad default remains compatible with
upstream registration. Future upstream changes can be merged without resolving
large rewrites in `activity_management.py` or `activity_analysis.py`.

## Deferred extensions

The following require separate evidence and review rather than being silently
added to v1:

- scheduled-workout and nested-repeat execution comparison;
- second-by-second FIT analysis, HR drift, decoupling, best efforts, or power
  curves;
- live-verified strength weight units and volume;
- swimming, rowing, hiking, multisport, or other family-specific analysis;
- gear and weather context;
- configurable split limits or user-selectable provider expansion;
- athlete-level lactate threshold, FTP, race predictions, or a separate
  performance/threshold context tool;
- transport-specific error classification after structured exception status
  and causes are preserved.

These omissions keep v1 to one reliable question: “What factual Garmin summary
and sport-relevant breakdown are available for this completed activity?”
