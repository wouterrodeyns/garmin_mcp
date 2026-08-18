# AI sleep trend evidence

`get_sleep_trend(days=7)` is an explicit, read-only evidence read for an AI
coach. It answers questions such as “was poor sleep a one-off or a pattern?”
by returning bounded nightly facts and request-level averages. It is
deliberately separate from `get_training_context`: the context tool remains a
compact current snapshot. Its sleep/HRV/readiness reads query today, then
yesterday only when today's response is legitimately empty; failed or
malformed responses do not trigger that fallback. This tool fetches detailed
multi-night evidence on demand.

## Call and date rules

The public signature is exactly:

```text
get_sleep_trend(days=7)
```

`days` must be an integer from 1 through 30; booleans and numeric strings are
not accepted. At the MCP boundary, StrictInt validation raises MCP ToolError
for a bool, string, float, or null before the service or Garmin is called. An
exact integer such as 0 or 31 reaches the service and returns the
stable invalid_days envelope. The service uses a fixed inclusive period that ends today, where
“today” is the MCP host's local calendar date. A request for seven nights
ending 2026-08-17 therefore covers 2026-08-11 through 2026-08-17.

Dates are read oldest to newest with one sequential Garmin client call per
requested date. The tool layer adds no pagination, retry, previous-day
fallback, parallel burst, or hidden replacement date. The pinned Garmin client
may retry transient network or 5xx failures and currently defaults to three
retries. Physical HTTP attempts can therefore exceed the requested night
count: the maximum 30-night request means 30 client method calls, not a
guarantee of only 30 HTTP attempts. Authentication errors, rate limits, and
other 4xx responses fail fast. If today's sleep is not synchronized yet,
today's sleep may be unavailable until the watch synchronizes. The date stays
in the requested period either way.

## Recommended workflow

The three primary coaching roles are context eyes, completed-session feedback,
and workout hands. Sleep trend and wellness heart-rate are deliberate
evidence reads that support those roles:

```text
get_training_context  -> compact current snapshot
get_sleep_trend       -> explicit recent multi-night sleep evidence
create_workout        -> a write only after the user confirms a proposed workout
```

`get_training_context` does not imply a multi-night sleep pattern. Call
`get_sleep_trend` when the user explicitly needs recent sleep history, then
explain which Garmin facts are available and which dates or metrics are
missing. Sleep evidence alone does not establish causation, readiness,
recovery, or a training recommendation.

## Response contract

Every response has the stable top-level keys, in this order:
`status`, `error`, `period`, `availability`, `summary`, `nights`, and
`warnings`. `nights` and `availability` are chronological and contain one
entry for every requested date. Missing dates remain visible; they are never
shifted or replaced. Missing numeric data is null, never zero.

This example shows two available nights and an unsynchronized current night.
The values are illustrative normalized Garmin facts, not an inference about a
person or a correlation between metrics.

```json
{
  "status": "partial_success",
  "error": null,
  "period": {
    "days": 3,
    "start_date": "2026-08-15",
    "end_date": "2026-08-17"
  },
  "availability": {
    "2026-08-15": true,
    "2026-08-16": true,
    "2026-08-17": false
  },
  "summary": {
    "nights_requested": 3,
    "nights_available": 2,
    "averages": {
      "duration_hours": {"value": 7.4, "nights": 2},
      "score": {"value": 81.0, "nights": 2},
      "resting_hr_bpm": {"value": 45.0, "nights": 2},
      "overnight_hrv_ms": {"value": 92.0, "nights": 2},
      "spo2_percent": {"value": 96.0, "nights": 2}
    }
  },
  "nights": [
    {
      "date": "2026-08-15",
      "available": true,
      "duration_hours": 7.2,
      "nap_minutes": 0.0,
      "score": 80,
      "score_qualifier": "GOOD",
      "stages": {
        "deep_minutes": 88.0,
        "light_minutes": 251.0,
        "rem_minutes": 105.0,
        "awake_minutes": 22.0
      },
      "resting_hr_bpm": 45,
      "overnight_hrv_ms": 91,
      "average_sleep_stress": 15,
      "awake_count": 3,
      "restless_moments_count": 10,
      "spo2": {"average_percent": 96, "lowest_percent": 94},
      "sleep_times": {
        "bedtime_local": "2026-08-14T23:30:00",
        "bedtime_utc": "2026-08-14T21:30:00Z",
        "bedtime_utc_offset_minutes": 120,
        "wake_time_local": "2026-08-15T06:42:00",
        "wake_time_utc": "2026-08-15T04:42:00Z",
        "wake_time_utc_offset_minutes": 120
      }
    },
    {
      "date": "2026-08-16",
      "available": true,
      "duration_hours": 7.6,
      "nap_minutes": 10.0,
      "score": 82,
      "score_qualifier": "GOOD",
      "stages": {
        "deep_minutes": 92.0,
        "light_minutes": 260.0,
        "rem_minutes": 110.0,
        "awake_minutes": 24.0
      },
      "resting_hr_bpm": 45,
      "overnight_hrv_ms": 93,
      "average_sleep_stress": 13,
      "awake_count": 2,
      "restless_moments_count": 8,
      "spo2": {"average_percent": 96, "lowest_percent": 95},
      "sleep_times": {
        "bedtime_local": "2026-08-15T23:15:00",
        "bedtime_utc": "2026-08-15T21:15:00Z",
        "bedtime_utc_offset_minutes": 120,
        "wake_time_local": "2026-08-16T06:51:00",
        "wake_time_utc": "2026-08-16T04:51:00Z",
        "wake_time_utc_offset_minutes": 120
      }
    },
    {
      "date": "2026-08-17",
      "available": false,
      "duration_hours": null,
      "nap_minutes": null,
      "score": null,
      "score_qualifier": null,
      "stages": {
        "deep_minutes": null,
        "light_minutes": null,
        "rem_minutes": null,
        "awake_minutes": null
      },
      "resting_hr_bpm": null,
      "overnight_hrv_ms": null,
      "average_sleep_stress": null,
      "awake_count": null,
      "restless_moments_count": null,
      "spo2": {"average_percent": null, "lowest_percent": null},
      "sleep_times": {
        "bedtime_local": null,
        "bedtime_utc": null,
        "bedtime_utc_offset_minutes": null,
        "wake_time_local": null,
        "wake_time_utc": null,
        "wake_time_utc_offset_minutes": null
      }
    }
  ],
  "warnings": [
    {
      "provider": "sleep",
      "date": "2026-08-17",
      "code": "sleep_data_unavailable",
      "message": "Sleep data is unavailable for this date."
    }
  ]
}
```

## Metrics and units

Only supported normalized metrics cross the Garmin boundary. Unknown Garmin
fields are ignored and raw DTOs are never returned.

| Night field | Source meaning and display unit |
| --- | --- |
| `duration_hours` | Total sleep seconds converted to hours, one decimal. |
| `nap_minutes` | Nap seconds converted to minutes, one decimal. |
| `score`, `score_qualifier` | Garmin overall score and trimmed qualifier text. |
| `stages.deep_minutes`, `light_minutes`, `rem_minutes`, `awake_minutes` | Stage seconds converted to minutes, one decimal. |
| `resting_hr_bpm` | Resting heart rate in beats per minute. |
| `overnight_hrv_ms` | Overnight HRV in milliseconds. |
| `average_sleep_stress` | Garmin nightly average sleep-stress value. |
| `awake_count`, `restless_moments_count` | Integer event counts. |
| `spo2.average_percent`, `lowest_percent` | Average and lowest nightly SpO2 percentage. |
| `sleep_times.bedtime_local`, `wake_time_local` | Sleep onset and wake as naive local wall-clock ISO-8601 text, no offset suffix. |
| `sleep_times.bedtime_utc`, `wake_time_utc` | The same two boundaries as unambiguous UTC instants, `Z`-suffixed. |
| `sleep_times.bedtime_utc_offset_minutes`, `wake_time_utc_offset_minutes` | Whole-minute UTC offset derived per boundary. |

Every listed field is optional. An unavailable supported field is `null`; it
does not make an otherwise usable night invalid. A night is available when at
least one supported normalized metric is present. The implementation does not
return sleep-stage percentages, sleep debt, consistency, slopes, variance,
readiness, or recovery scores.

## Sleep boundary times and timezone frames

`sleep_times` reports sleep onset and wake, each in an explicitly named frame.
Garmin sends `dailySleepDTO.sleepStartTimestampGMT` / `sleepEndTimestampGMT`
and, on observed accounts, `sleepStartTimestampLocal` / `sleepEndTimestampLocal`
as epoch milliseconds. The `Local` variants are pre-shifted by the local UTC
offset, so reading them in UTC yields the wall clock the watch displayed.

Each frame is projected only from its own source, and a missing frame is never
reconstructed from the other:

- `*_local` is populated only from a `Local` timestamp. Absent it, the value is
  `null`; a UTC instant is never relabelled as local.
- `*_utc` is populated only from a `GMT` timestamp.
- `*_utc_offset_minutes` requires both frames for that boundary and is `null`
  otherwise. No timezone name or region is ever inferred.

Offsets are derived per boundary, not per night, so a night spanning a
daylight-saving transition correctly reports different bedtime and wake offsets.
Values are truncated to whole seconds; sub-second precision is not returned.
Each present start/end pair must form a positive interval no longer than 24
hours. A boundary outside the year 2000 through 2100 epoch window, an invalid
interval, or a local frame outside the real-world whole-minute UTC offset range
of -14:00 through +14:00 makes that date `invalid_provider_response`.

## Averages and denominators

The `summary.averages` object contains only `duration_hours`, `score`,
`resting_hr_bpm`, `overnight_hrv_ms`, and nightly average `spo2_percent`.
Each average is `{ "value": ..., "nights": ... }`. The `nights` value is the
per-metric denominator: the number of available source values for that metric,
not the number of requested or generally available nights. If no source value
exists, the result is `{ "value": null, "nights": 0 }`.

The service sums validated actual source values first, converts units where
needed, and rounds the final average to one decimal. It does not average
already-rounded display values. No causal or coaching conclusion is derived
from these aggregates.

## Status, errors, and warnings

`success` means every requested date is available. `partial_success` means at
least one date is available and at least one is unavailable, failed, or
invalid. `error` means the request is invalid, the Garmin client is
unavailable, or no requested night is available.

| Situation | `status` | Error code |
| --- | --- | --- |
| MCP `StrictInt` rejects a bool, string, float, or null | `ToolError` before the service | no envelope |
| Integer `days` is outside 1 through 30 (for example 0 or 31) | `error` | `invalid_days` |
| No Garmin client is configured | `error` | `client_unavailable` |
| No requested night is available | `error` | `sleep_trend_unavailable` |

Fixed expected provider failures are converted to fixed, sanitized
per-date warning codes/messages. Warnings have exactly `provider`, `date`,
`code`, and `message`. Their fixed codes are:

- `sleep_data_unavailable`: the DTO was legitimately empty or absent;
- `provider_unavailable`: an expected Garmin authentication, connection, or
  rate-limit failure occurred; and
- `invalid_provider_response`: a supported field or calendar date was
  malformed or unsafe.

Raw responses and provider exception details are not copied into these fixed
errors or warnings. Unexpected internal/programming exceptions propagate
intentionally for diagnosis; the public contract does not promise that those
unexpected exceptions are sanitized.

## Read-only and Garmin caveats

The path performs authenticated reads through `client.get_sleep_data(date)` via
the existing provider seam. It performs no workout or schedule mutations and
no credential-management operations. This path does not directly access raw
connectapi, garth, session, or HTTP verbs, and it does not invoke another
MCP tool.

Garmin metric availability varies by device, account, and sync state. A missing
metric or night is not evidence that a device or account
cannot support it. Sleep boundary times are reported per frame rather than as a
single resolved instant because some Garmin China/UTC+8 responses have
documented local timestamp ambiguity. This path therefore never infers a
timezone: it reports the `Local` wall clock and the `GMT` instant only from
their own source fields, and rejects a night whose two frames disagree by
anything other than a sane whole-minute offset. Nightly totals do not depend on
any timestamp interpretation. This guide does not replace
historical Garmin records or claim a causal relationship between sleep and
training outcomes.

## Garmin response compatibility

The sleep normalizer accepts the verified compatible Garmin field shapes for
nightly resting heart rate: nested `dailySleepDTO.restingHeartRate` or root
`restingHeartRate`. It also accepts the sleep-summary casing variants
`averageSpo2` / `averageSPO2` and `lowestSpo2` / `lowestSPO2`. When duplicate
variants are present, they must agree; a conflicting or malformed supported
variant makes that date `invalid_provider_response`. This compatibility remains
within the existing one `get_sleep_data(date)` request per date; it does not add
another Garmin endpoint or request.
