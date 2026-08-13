# Activity time-series evidence

`get_activity_timeseries` is a narrow, read-only follow-up for factual evidence
from one completed activity. It downloads and parses the original FIT file for
the requested window, then returns bounded time bins. It is not a replacement
for `analyze_activity`: use the overview first and ask for this read only when
the AI needs concrete short-interval evidence.

## Choosing the tool

Use `analyze_activity(activity_id)` first. That is the default completed-session
overview and feedback read. Use `get_activity_timeseries` only for concrete
short interval evidence that the overview does not contain, such as checking a
short sequence of heart-rate, speed, pace, cadence, power, altitude, or grade
bins. The time-series read makes no coaching recommendation, comparison, or
workout mutation.

The workflow is literal: analyze_activity(activity_id) first, then use
get_activity_timeseries only for concrete short interval evidence.

## Arguments and paging

activity_id positive integer or ASCII decimal string from 1 through
9007199254740991 is accepted. activity_id strings are strip()ped first; after trimming, a nonempty ASCII decimal string is validated
and range checked from 1 through 9007199254740991. Leading/trailing whitespace
around ASCII digits is accepted. Internal whitespace is rejected, signs are
rejected, exponents are rejected, and Unicode digits are rejected. An integer
value must be positive and within the same range.
The window arguments are exact integers (not booleans, floats, or numeric
strings).
FastMCP rejects booleans and floats before the service runs; numeric strings for
window arguments are rejected. Optional integer arguments have these
defaults:

Bounds contract: start_seconds exact integer from 0 through 4026531838;
duration_seconds exact integer from 1 through 86400; resolution_seconds exact
integer from 1 through 300.

- `start_seconds=0`
- `duration_seconds=600`
- `resolution_seconds=1`

The requested interval is half-open: `[start_seconds,
start_seconds+duration_seconds)`. A bin is anchored at its elapsed-second
start. `ceil(duration_seconds / resolution_seconds) <= 600` must hold, so a
request for 600 non-empty bins is the largest one at one-second resolution.
The service does not manufacture empty bins to reach that count.

When more source records remain after the returned window, `window` contains an
integer `next_start_seconds`. Continue from that cursor without changing the
other arguments:

1. Call get_activity_timeseries(activity_id=123456, start_seconds=0, duration_seconds=600, resolution_seconds=1).
2. If window.next_start_seconds is present, call the same tool with that integer as start_seconds.
3. Stop when next_start_seconds is absent. Do not create missing seconds, carry values forward, or assume a one-Hz source stream.

## Returned evidence

Every response is a stable envelope. `status` is `success` when the bounded
read completed, `partial_success` when useful bins remain after malformed FIT
records were discarded, and `error` for a rejected request, unavailable
client/download, unsafe archive, or parse failure. Errors use fixed provider,
code, and message fields; an unexpected internal failure uses the fixed generic
message `Activity time series is temporarily unavailable.` and exposes no raw
exception details; internal_error is the error code for that fixed response.

partial_success is a status, never a warning code. When selected records
exist and malformed activity-global records were discarded, `warnings` contains
the exact object `{"provider":"fit","code":"malformed_records_discarded","message":"Malformed FIT record messages were discarded.","count":N}`.
Its fields are provider: fit, code: malformed_records_discarded, message:
Malformed FIT record messages were discarded., and count: N. This is the
malformed warning for that partial result.
Empty selected window returns success and suppresses the warning.

The one primary response example below is intentionally small. All series
arrays have the same length as `sampling.returned_points`. `source_records`
counts usable source records considered, while `returned_points` counts the
non-empty bins returned. `sampling.observed_median_interval_seconds` and
`irregular` describe the observed source timing; they do not promise a 1Hz
source.

```json
{
  "status": "success",
  "error": null,
  "activity_id": 123456,
  "window": {
    "requested_start_seconds": 0,
    "actual_end_seconds": 600,
    "resolution_seconds": 1,
    "next_start_seconds": 600
  },
  "sampling": {
    "source_records": 4,
    "returned_points": 2,
    "observed_median_interval_seconds": 1.0,
    "irregular": false
  },
  "availability": {
    "heart_rate_bpm": true,
    "speed_mps": true,
    "pace_seconds_per_km": true,
    "cadence_rpm": true,
    "power_w": true,
    "altitude_m": true,
    "grade_pct": true
  },
  "series": {
    "elapsed_seconds": [0, 1],
    "timestamp": ["2026-08-13T06:30:00.000000Z", "2026-08-13T06:30:01.000000Z"],
    "sample_count": [2, 2],
    "heart_rate_bpm": {
      "average": [142.5, 143.0],
      "minimum": [140, 141],
      "maximum": [145, 145]
    },
    "speed_mps": {
      "average": [3.125, 3.2]
    },
    "pace_seconds_per_km": {
      "average": [320, 312],
      "fastest": [315, 308],
      "slowest": [325, 316]
    },
    "cadence_rpm": {
      "average": [84.5, 85.0]
    },
    "power_w": {
      "average": [210.0, 212.0]
    },
    "altitude_m": {
      "average": [42.1, 42.2]
    },
    "grade_pct": {
      "average": [0.4, null]
    }
  },
  "warnings": []
}
```

Timestamps are canonical UTC Z bin anchors, not exact device sample claims.
Sparse bins and gaps remain sparse: there is no fill and no interpolation, and
the source is not exactly 1Hz. Units are elapsed seconds; heart rate in bpm;
speed in m/s to 3 decimals; cadence in rpm; power in W; altitude in m; and
grade in %. A missing value is `null` (missing is null); recorded zero remains 0.

Rounding contract: heart-rate average to one decimal bpm; heart-rate minimum
and maximum to whole integer bpm; pace average, fastest, and slowest in
seconds/km to whole integers; and other means (cadence, power, altitude, and
grade) to one decimal.

`availability` is returned-window only, not device or account capability; it
describes evidence only in that window. A field can be unavailable in this
snapshot even when the device or account supports it.

## Privacy and safety

Each valid call makes one original FIT download per valid call; there is no
caching or repeated download within the service. The response never returns GPS,
location, coordinates, a polyline, raw FIT bytes, developer/raw fields, or
activity names/descriptions. Fixed errors and warnings never echo exception
text, credentials, tokens, URLs, headers, or raw provider payloads.

The parser enforces these limits before exposing evidence: archive/member
25MB, entries 16, a cd/read chunk 65536 bytes, auxiliary 65536 bytes,
frames 200000, records 100000, definition fields 128, and
returned points 600. Strict classic ZIP/CRC/chained fatal. Other malformed or
unsafe inputs remain fixed `error` responses. The parser is pinned to fitdecode
0.11 (`fitdecode==0.11`) for this read. The existing fitparse
analyze path unchanged.

## Limits and exclusions

This is a read-only factual evidence tool and not a replacement for
analyze_activity. There is no coaching
recommendation, no comparison, no interpolation, no GPS output, and no workout
mutation.
It does not infer missing seconds, carry values forward, claim an exact 1Hz
device stream, or judge compliance, quality, or pass/fail. Use
`analyze_activity` for the bounded overview and let the AI and user decide how
to interpret these measurements.
