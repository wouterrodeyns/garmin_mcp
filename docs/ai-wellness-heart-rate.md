# AI wellness heart-rate evidence

## Purpose

`get_wellness_heart_rate` is an explicit, read-only request for detailed,
all-day Garmin wellness heart-rate evidence. It is intentionally separate from
the compact `get_training_context` snapshot: the coach pays the token and
interpretation cost only when this evidence is relevant. It is not embedded in
`get_training_context`, and the broad raw `get_heart_rates` and
`get_heart_rates_summary` compatibility tools remain outside the `ai-coach`
profile.
The broad raw `get_heart_rates` remains outside `ai-coach`.

This is wellness evidence, not a coaching conclusion. Garmin availability
varies by device, account, and sync state. The normalized response is not a
Garmin DTO.

## Call signature and request rules

The exact signature is:

```text
get_wellness_heart_rate(start_date, end_date=None, resolution="raw", start_time=None, end_time=None)
```

Dates use strict real-calendar `YYYY-MM-DD` values. An omitted `end_date`
means the `start_date`; the inclusive range must be ordered and contain at most
7 dates. Future dates are allowed because Garmin may legitimately return an
empty date.

`resolution` must be exactly one of `daily`, `raw`, `5m`, `15m`, `30m`, or
`60m`:

| Mode | Evidence and constraints |
| --- | --- |
| `daily` | Garmin daily summary fields only; it is sample-free and rejects a time window. Daily rejects any time window. |
| `raw` | Every validated source entry in the selected window, including a null `bpm`; one date only. |
| `5m`, `15m`, `30m`, `60m` | Fixed wall-clock bins containing returned valid samples; one or more dates. |

`start_time` and `end_time` must either both be omitted or both be strict
24-hour `HH:MM` values. The interval is same-day, start-inclusive and
end-exclusive; `start_time` must be earlier than `end_time`. Cross-midnight
windows are rejected. The same daily window applies to every requested date.
Window filtering and bins require unambiguous Garmin local-time provenance.

These are product bounds, not claimed Garmin API limits: at most 7 dates, at
most 10,000 source points per day, at most 1,000 selected raw points, at most
1,000 returned bins per request, and at most 262,144 UTF-8 output bytes. Raw
and binned requests refuse an over-bound result; they never silently truncate.
The internal-gap threshold is 300 seconds. The service makes at most seven
sequential reads, one per requested date.
Raw and binned results never truncate; the service never truncates evidence.
These are product safety limits, not claimed Garmin API limits.

## Response contract

Every outcome has the same top-level keys, in this order:

```text
status, error, period, resolution, availability, days, warnings
```

`status` is `success`, `partial_success`, or `error`. `error` is null or a
fixed `{code, message}` object. `period` has exactly
`start_date`, `end_date`, `start_time`, and `end_time`.

After provider reads are attempted, ordinary success and partial_success, and
an all-date provider/malformed/local-required total failure, retain one day
and availability boolean per requested date in date order, including failed
dates, with dated warnings. Request validation, `client_unavailable`, and
global raw/bin/output-size refusals happen before a per-date result exists and
return `availability {}`, `days []`, and `warnings []`.
The global empty envelope is availability {}, days [], warnings [].

```text
date, available, summary, time_provenance, sampling, points, gaps
```

`summary` has `resting_hr_bpm`, `min_hr_bpm`, `max_hr_bpm`, and
`seven_day_avg_resting_hr_bpm`. `time_provenance` has
`local_offset_minutes` and `local_time_available`. `sampling` has
`source_points`, `valid_bpm_points`, `null_bpm_points`, `returned_points`,
`observed_median_interval_seconds`, and
`duration_from_sample_count_valid`. `points` and `gaps` are always present.

The following examples use synthetic values only. They are parseable JSON and
contain no real user data.

### Daily summary

```json
{
  "status": "success",
  "error": null,
  "period": {"start_date": "2026-08-10", "end_date": "2026-08-10", "start_time": null, "end_time": null},
  "resolution": "daily",
  "availability": {"2026-08-10": true},
  "days": [
    {
      "date": "2026-08-10",
      "available": true,
      "summary": {"resting_hr_bpm": 45, "min_hr_bpm": 41, "max_hr_bpm": 166, "seven_day_avg_resting_hr_bpm": 46},
      "time_provenance": {"local_offset_minutes": 120, "local_time_available": true},
      "sampling": {"source_points": 713, "valid_bpm_points": null, "null_bpm_points": null, "returned_points": 0, "observed_median_interval_seconds": null, "duration_from_sample_count_valid": false},
      "points": [],
      "gaps": []
    }
  ],
  "warnings": []
}
```

### Raw points

```json
{
  "status": "success",
  "error": null,
  "period": {"start_date": "2026-08-10", "end_date": "2026-08-10", "start_time": null, "end_time": null},
  "resolution": "raw",
  "availability": {"2026-08-10": true},
  "days": [
    {
      "date": "2026-08-10",
      "available": true,
      "summary": {"resting_hr_bpm": 45, "min_hr_bpm": 41, "max_hr_bpm": 166, "seven_day_avg_resting_hr_bpm": 46},
      "time_provenance": {"local_offset_minutes": 120, "local_time_available": true},
      "sampling": {"source_points": 3, "valid_bpm_points": 2, "null_bpm_points": 1, "returned_points": 3, "observed_median_interval_seconds": 120.0, "duration_from_sample_count_valid": false},
      "points": [
        {"time_local": "2026-08-10T19:00:00+02:00", "time_utc": "2026-08-10T17:00:00Z", "bpm": 138},
        {"time_local": "2026-08-10T19:02:00+02:00", "time_utc": "2026-08-10T17:02:00Z", "bpm": null},
        {"time_local": "2026-08-10T19:04:00+02:00", "time_utc": "2026-08-10T17:04:00Z", "bpm": 142}
      ],
      "gaps": []
    }
  ],
  "warnings": []
}
```

Raw `bpm: null` is retained. Raw timestamps always have exact UTC `Z` form;
the local form is included only when its daily offset is unambiguous.

### Binned points

```json
{
  "status": "success",
  "error": null,
  "period": {"start_date": "2026-08-10", "end_date": "2026-08-10", "start_time": null, "end_time": null},
  "resolution": "5m",
  "availability": {"2026-08-10": true},
  "days": [
    {
      "date": "2026-08-10",
      "available": true,
      "summary": {"resting_hr_bpm": 45, "min_hr_bpm": 41, "max_hr_bpm": 166, "seven_day_avg_resting_hr_bpm": 46},
      "time_provenance": {"local_offset_minutes": 120, "local_time_available": true},
      "sampling": {"source_points": 4, "valid_bpm_points": 4, "null_bpm_points": 0, "returned_points": 2, "observed_median_interval_seconds": 120.0, "duration_from_sample_count_valid": false},
      "points": [
        {"start_time_local": "2026-08-10T19:00:00+02:00", "end_time_local": "2026-08-10T19:05:00+02:00", "start_time_utc": "2026-08-10T17:00:00Z", "end_time_utc": "2026-08-10T17:05:00Z", "min_bpm": 126, "mean_bpm": 139.4, "max_bpm": 151, "sample_count": 3},
        {"start_time_local": "2026-08-10T19:15:00+02:00", "end_time_local": "2026-08-10T19:20:00+02:00", "start_time_utc": "2026-08-10T17:15:00Z", "end_time_utc": "2026-08-10T17:20:00Z", "min_bpm": 133, "mean_bpm": 136.0, "max_bpm": 139, "sample_count": 1}
      ],
      "gaps": [{"start_time_local": "2026-08-10T19:05:00+02:00", "end_time_local": "2026-08-10T19:15:00+02:00", "start_time_utc": "2026-08-10T17:05:00Z", "end_time_utc": "2026-08-10T17:15:00Z", "elapsed_minutes": 10.0}]
    }
  ],
  "warnings": []
}
```

Binned `min_bpm`, `mean_bpm`, `max_bpm`, and `sample_count` describe only
valid samples Garmin returned in that bin. There is no `coverage` field and
no claim of continuous coverage. No coverage is reported.

### Partial success and a failed date

```json
{
  "status": "partial_success",
  "error": null,
  "period": {"start_date": "2026-08-10", "end_date": "2026-08-11", "start_time": null, "end_time": null},
  "resolution": "daily",
  "availability": {"2026-08-10": true, "2026-08-11": false},
  "days": [
    {
      "date": "2026-08-10",
      "available": true,
      "summary": {"resting_hr_bpm": 45, "min_hr_bpm": 41, "max_hr_bpm": 166, "seven_day_avg_resting_hr_bpm": 46},
      "time_provenance": {"local_offset_minutes": 120, "local_time_available": true},
      "sampling": {"source_points": 1, "valid_bpm_points": null, "null_bpm_points": null, "returned_points": 0, "observed_median_interval_seconds": null, "duration_from_sample_count_valid": false},
      "points": [],
      "gaps": []
    },
    {
      "date": "2026-08-11",
      "available": false,
      "summary": {"resting_hr_bpm": null, "min_hr_bpm": null, "max_hr_bpm": null, "seven_day_avg_resting_hr_bpm": null},
      "time_provenance": {"local_offset_minutes": null, "local_time_available": false},
      "sampling": {"source_points": 0, "valid_bpm_points": null, "null_bpm_points": null, "returned_points": 0, "observed_median_interval_seconds": null, "duration_from_sample_count_valid": false},
      "points": [],
      "gaps": []
    }
  ],
  "warnings": [{"provider": "wellness_heart_rate", "date": "2026-08-11", "code": "provider_unavailable", "message": "Wellness heart-rate data is unavailable for this date."}]
}
```

Failed dates keep the stable empty day. A legitimate empty date is not itself
a failure: it stays unavailable without fabricated zeros or a provider warning.

### Global refusal

Validation and global size refusals have the same top-level shape but no
per-date entries:

```json
{
  "status": "error",
  "error": {"code": "invalid_date_range", "message": "start_date must be on or before end_date."},
  "period": {"start_date": "2026-08-11", "end_date": "2026-08-10", "start_time": null, "end_time": null},
  "resolution": "raw",
  "availability": {},
  "days": [],
  "warnings": []
}
```

## Interpretation guardrails

Daily summary facts are Garmin-only: `resting_hr_bpm`, `min_hr_bpm`,
`max_hr_bpm`, and `seven_day_avg_resting_hr_bpm` come from Garmin summary
fields. Missing values are null, never zero. Daily mode is sample-free, even
though the source sample-list container and its 10,000-point bound are checked.

Wellness sampling can be irregular or missing; missing sampling is evidence of
an incomplete series, not a duration. `sample_count * assumed cadence` is
never a duration, and `sample_count` never establishes time in
zone. Raw null bpm values stay visible. Bins contain only returned samples;
they do not establish continuous coverage. A gap is only an internal interval
between adjacent valid measurements of at least 300 seconds. Gaps have no
leading/trailing entries and no cause. They do not prove watch removal,
charging, sleep, illness, exercise, or another cause.

This endpoint is distinct from FIT activity series and completed-activity FIT
evidence and their sensor
samples, smoothing, and zones. Do not merge the sources or infer activity
heart-rate zones from wellness samples. The tool alone cannot establish time
in zone, cardiovascular drift, recovery, stress, or coaching conclusions.

## Time provenance

UTC is present for every returned timestamped raw/bin/gap fact as an exact `Z`
timestamp. Daily mode is sample-free: points and gaps are empty, so daily
responses have no timestamps. When Garmin's daily GMT/local bounds establish
one unambiguous numeric offset, local ISO 8601 timestamps are also returned
(for example `2026-08-10T19:02:00+02:00`).
If local provenance is missing, malformed, or contains an offset transition,
an unwindowed raw response may return UTC with local timestamps null and one
`local_time_unavailable` warning. Daily remains sample-free. Binned and
explicit-window requests cannot use an unknown local wall clock: they return
an unavailable empty day rather than UTC-only bins.
Unwindowed raw may return UTC with local null. Bins and explicit windows return
an unavailable empty day, not UTC-only bins.

## Statuses, warnings, and missing dates

Dates are fetched sequentially. Per-date failures continue sequentially to
later dates.
All usable requested dates produce `success`; a failed or malformed date plus
another usable date produces `partial_success`; if every attempted date fails,
the result is `error` with fixed code `wellness_heart_rate_unavailable`.
Invalid arguments, projected bin bounds, raw over-limit responses, and output
over-limit responses are fixed errors and return no truncated series.

The fixed warning codes are `provider_unavailable`,
`invalid_provider_response`, and `local_time_unavailable`. Fixed errors include
`invalid_start_date`, `invalid_end_date`, `invalid_date_range`,
`date_range_too_large`, `invalid_resolution`, `raw_requires_single_date`,
`invalid_time_window`, `request_too_large`, `client_unavailable`,
`wellness_heart_rate_unavailable`, `raw_response_too_large`, and
`response_too_large`. Warning and error messages are sanitized and never echo
exception text, raw payloads, URLs, headers, tokens, credentials, or IDs.

An empty or unavailable current date can simply mean the watch/device has not
synced to Garmin Connect yet. It does **not** establish an unsupported
account/device. Sync Garmin Connect, then retry. Sync then retry if the date
remains empty. It does not establish unsupported account/device. Device/API
limits are not claimed by this guide.

## Read-only and security boundary

The entire path makes only `client.get_heart_rates(date)`, with at most seven
sequential reads. It does not call `get_rhr_day`, an activity endpoint,
`connectapi`, raw POST/PUT/DELETE requests, workout or schedule methods, or
credential-management functions. It never writes heart-rate data to disk,
logs, caches, or fixtures. Input and provider payloads are validated before
normalization; only the bounded normalized envelope crosses the MCP boundary.
It does not call `connectapi`.

## Choosing the tool

| Tool | Use |
| --- | --- |
| `get_training_context` | Compact automatic context at the start of coaching. |
| `get_wellness_heart_rate` | Explicit all-day wellness heart-rate evidence, with daily/raw/binned resolution. |
| `analyze_activity` | Facts from a completed Garmin activity/FIT record (completed activity evidence). |
| `get_activity_timeseries` | Narrow completed-activity/FIT evidence for a concrete interval. |
| `create_workout` / `update_workout` | Writes only after the user confirms the proposed workout or change; only after user confirmation. |

`get_wellness_heart_rate` is explicit all-day evidence, not automatic context.
`analyze_activity` and `get_activity_timeseries` provide completed activity/FIT evidence.
Use the smallest evidence read that answers the question: context first,
wellness only when detailed all-day heart rate is explicitly needed, activity
analysis for a completed session, and workout writes only after confirmation.

## AI-coach profile

The exact `ai-coach` profile has 15 names:

```text
`get_training_context`
`get_wellness_heart_rate`
`analyze_activity`
`get_activity_timeseries`
`create_workout`
`update_workout`
`get_activities`
`get_activities_by_date`
`get_activity`
`get_workouts`
`get_workout_by_id`
`get_scheduled_workouts`
`schedule_workout`
`unschedule_workout`
`delete_workout`
```

The broad upstream `get_heart_rates` and `get_heart_rates_summary` tools stay
outside this profile. Explicit `GARMIN_ENABLED_TOOLS` still takes precedence,
and `GARMIN_DISABLED_TOOLS` subtracts from a selected profile.
