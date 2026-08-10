# AI activity analysis

`analyze_activity(activity_id)` is the completed-session feedback read for an
AI coach. It is deliberately factual, bounded, sport-aware, and read-only: it
summarizes one completed Garmin activity so the AI can interpret evidence in a
feedback loop. It is not another training-context aggregate and it never
uploads, edits, schedules, unschedules, or deletes Garmin data.

## Argument, source, and call budget

The only tool argument is `activity_id`: a positive integer or decimal string
(ASCII digits) representing one. Detail is not an argument. Optional detail may be
absent because it was unavailable in this snapshot, device, account, or sync
state; that does not mean the device or account is unsupported. The low-level
get_activity remains a compatibility and targeted read.
An unavailable snapshot or sync is not the same as an unsupported device or
account.

After a valid activity_id and configured client, the service makes one base
activity read. Invalid activity_id input and an unavailable client make zero
Garmin calls. Optional reads are gated by the normalized Garmin raw activity
type key and by signals in the base summary. These are the exact supported
sport families and maximum call budgets. This fixed call budget is part of the
v1 contract:

In shorthand: run/walk: splits + heart-rate zones when a heart-rate signal
exists; cycling: splits + heart-rate zones + power zones when the corresponding
signals exist; strength: exercise sets; generic: base activity summary only.
These are exactly these sport families, and no other sport-specific detail is
promised.

| Family | Garmin raw type keys | Optional reads and budget |
| --- | --- | --- |
| running | `running`, `trail_running`, `treadmill_running` | splits + heart-rate zones when a heart-rate signal exists; maximum 3 calls (base + 2) |
| walking | `walking`, `treadmill_walking` | splits + heart-rate zones when a heart-rate signal exists; maximum 3 calls (base + 2) |
| cycling | `cycling`, `indoor_cycling`, `road_biking`, `mountain_biking`, `gravel_cycling` | splits + heart-rate zones + power zones when the corresponding signals exist; maximum 4 calls (base + 3) |
| strength | `strength_training` | exercise sets; maximum 2 calls (base + 1) |
| generic | every other raw type key | generic base activity summary only; exactly 1 call |

Splits are skipped when Garmin explicitly reports `metadataDTO.hasSplits` as
`false`. A heart-rate read requires a positive finite average, maximum, or
minimum heart-rate signal. A power read additionally requires a positive finite
average, maximum, or normalized-power signal and is only gated for cycling.
Missing signals skip that optional read without a warning. There are no
optional provider calls for a missing or invalid base activity.

## Stable response envelope

Every response has the same top-level keys, in this order:

This stable top-level envelope is part of the live contract.

```text
status, error, activity, availability, splits, heart_rate_zones,
power_zones, strength, derived, warnings
```

Availability is section-level. The `availability` object has one boolean per section: `activity`, `splits`,
`heart_rate_zones`, `power_zones`, and `strength`. A known empty collection can
be available, while an unavailable optional scalar or section is `null`, not
zero. Missing optional values are null, not zero. Optional sections are always
present in the top-level envelope; unavailable optional sections are null.
Device, account, and sync state affect whether those optional sections are
available in a snapshot. An unavailable optional section is therefore not
evidence that Garmin does not support it.

`status` is `success` when the base activity is usable and optional reads are
absent or valid; `partial_success` when an attempted optional provider fails or
returns a malformed non-empty response; and `error` for invalid input,
unavailable client/base activity, not-found data, or an invalid base response.
Warnings are structured objects with `provider`, `code`, and a fixed safe
`message`. The only warning codes are `provider_unavailable`,
`invalid_provider_response`, and `splits_truncated`. Warnings never contain
raw provider payloads or exception text. These are fixed warning codes, not
free-form provider diagnostics.

The `activity` section uses normalized keys such as `id`, `name`, `description`,
`sport`, `sport_family`, `event_type`, `start_time_local`,
`duration_minutes`, `moving_duration_minutes`, `elapsed_duration_minutes`,
`distance_km`, `average_speed_kph`, `max_speed_kph`, `average_pace`, nested
`heart_rate`, `power`, `cadence`, `elevation`, `training_effect`,
`workout_feedback`, `recovery`, and `reported_lap_count`. Optional values stay
`null`; Garmin metrics are not inferred.

## Units, splits, and derived facts

Conversions use raw source values before rounding or display: seconds to minutes
at one decimal (`duration_minutes` is one decimal; duration_minutes: one decimal), meters to kilometers at two
decimals (`distance_km` is two decimals; distance_km: two decimals), meters per second to
kilometers per hour at one decimal, and elevation meters at one decimal. Pace
uses raw duration divided by raw kilometers and displays rounded whole
seconds as `M:SS/km`. Zone durations retain raw seconds and also expose
one-decimal minutes; zone percentages are bounded to 0–100 and displayed to
one decimal.

The split response keeps source order and reports `total_count`,
`returned_count`, `truncated`, and `items`. At most 100 source laps are
returned. If the source has more than 100 laps, `truncated` is true,
`splits_truncated` is emitted, and every derived comparison is `null` (including
`scope`, fastest/slowest split and pace, and `pace_range_seconds_per_km`).
Derived comparisons are null when truncation occurs.
Without truncation, running and walking derived pace extrema are mechanical
facts over valid returned laps, with source-order tie breaking. They describe
the recorded splits, not coaching quality or compliance, and are not a
recommendation, pass/fail judgment, or proof of workout execution.

Strength results expose exercise and set counts and repetitions when known.
Strength weight, resistance, and volume are intentionally not returned until
their units are verified.

## Example

This is a compact shape example using exact current key names. Illustrative
values are copied from normalized source fields after conversion; no metrics
are inferred. Optional sections are null when unavailable in the snapshot, and
nested optional metric fields may also be null. This example uses null for the
stable envelope keys.

```json
{
  "status": "success",
  "error": null,
  "activity": {
    "id": 123,
    "name": "Private morning run",
    "description": "steady session",
    "sport": "running",
    "sport_family": "running",
    "event_type": "training",
    "start_time_local": "2026-08-07 07:30:00",
    "duration_minutes": 30.0,
    "moving_duration_minutes": 28.3,
    "elapsed_duration_minutes": 31.7,
    "distance_km": 5.0,
    "average_speed_kph": 9.9,
    "max_speed_kph": 15.3,
    "average_pace": "6:00/km",
    "heart_rate": {"average_bpm": 145, "max_bpm": 170, "min_bpm": 91},
    "power": {"average_watts": null, "max_watts": null, "normalized_watts": null},
    "cadence": {"average_spm": 176, "max_spm": 190},
    "elevation": {"gain_meters": 42.5, "loss_meters": 20.0, "minimum_meters": null, "maximum_meters": null},
    "calories": 450,
    "training_effect": {"aerobic": 3.4, "anaerobic": 1.2, "label": "PRODUCTIVE", "load": 71},
    "workout_feedback": {"rpe": 7, "feel": 75},
    "recovery": {"heart_rate_bpm": 32, "body_battery_impact": -8},
    "reported_lap_count": 5
  },
  "availability": {"activity": true, "splits": false, "heart_rate_zones": false, "power_zones": false, "strength": false},
  "splits": null,
  "heart_rate_zones": null,
  "power_zones": null,
  "strength": null,
  "derived": {"scope": null, "fastest_split_number": null, "fastest_pace": null, "slowest_split_number": null, "slowest_pace": null, "pace_range_seconds_per_km": null},
  "warnings": []
}
```

The example does not imply that an absent optional response was requested and
rejected; it means that optional detail was unavailable in this snapshot. A
real response may populate those sections when Garmin returns the applicable
signal and detail.

## Read-only and bounded by design

This read-only guarantee is intentional. Provider seams call only the pinned
Garmin reads for the base activity, splits, heart-rate zones, power zones, and
exercise sets. The service never performs writes or raw requests. Fixed error
and warning objects never include exception text, raw provider responses,
tokens, credentials, URLs, headers, or request IDs; discarded malformed
payloads are not echoed. Successful responses return bounded user-authored
names, descriptions, and exercise names verbatim-ish after trimming and
bounding; those fields may contain arbitrary text. A name is bounded to 200
characters, a description is bounded to 500, and other text fields are bounded
to 100.

Garmin raw activity type keys are retained in `sport`, while
`create_workout.sport` uses the distinct normalized vocabulary `running`,
`cycling`, `walking`, or `strength`; for example, `trail_running` can be
translated to `running` only when the AI and user intentionally choose the next
workout. This is the create_workout normalized sport vocabulary: running,
cycling, walking, or strength.

The intended feedback loop is: identify the completed activity → analyze it →
the AI interprets the evidence → the user confirms → create the next workout.
`analyze_activity` supplies the feedback read; `get_training_context` remains
the coach's eyes for current context, while `create_workout` is the coach's
hands/write operation.

## Explicit v1 exclusions

V1 does not expose FIT files, second-by-second records, details, maps, weather,
and gear; planned or scheduled workout linkage, step comparison, or
`wktStepIndex`; coaching judgment, compliance, pass/fail, or recommendations;
heart-rate drift or decoupling; strength weight or volume until units are
verified; swimming and other sport-specific detail; or thresholds, lactate
threshold, and FTP.
