# AI Activity Time Series v1 Design

## Decision

Add one fork-owned, read-only MCP tool:

```text
get_activity_timeseries(
    activity_id,
    start_seconds=0,
    duration_seconds=600,
    resolution_seconds=1,
)
```

It supplies small, paged, factual FIT-record evidence for one activity. It is
the intentional escape hatch for a question that needs cadence, power, pace,
or elevation over a short interval. It does not change the role of
`analyze_activity(activity_id)`: the latter remains the default bounded
completed-session overview. `get_activity_fit_data` remains the existing
low-level, unrestricted compatibility/debugging tool and remains outside the
AI-coach profile.

The v1 tool has one Garmin read, performs no mutations, returns at most 600
non-empty time bins, and never emits GPS. It is evidence for an AI or user to
interpret, not a coaching, comparison, compliance, or workout-prescription
engine.

## Scope and explicit exclusions

This work adds the tool, its narrow parser/service/provider seams, offline
tests, and current-facing documentation. It does not redesign
`activity_analysis.py`, `analyze_activity`, or upstream-oriented modules.

V1 does not add any of the following:

- a raw/full activity stream in one call, a cache, artifact, resource, or
  download file;
- GPX, GPS, latitude, longitude, route/polyline, maps, names, descriptions,
  weather, temperature, gear, cycling dynamics, R-R/HRV values, or raw FIT
  fields;
- interpolation, invented seconds, pause filling, resampling, smoothing, or
  inferred measurements;
- a comparison to a planned/scheduled workout, activity-analysis redesign,
  fitness/coaching inference, recommendations, or a `move_workout` operation;
- a live Garmin-account test.

## Local compatibility facts

The repository pins `garminconnect==0.3.10` and already has
`fitparse>=1.2.0`. In that pinned Garmin client,
`Garmin.ActivityDownloadFormat.ORIGINAL` downloads the original activity as a
ZIP archive; it is not a GPX or TCX endpoint. The call is exactly:

```python
client.download_activity(
    activity_id,
    dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL,
)
```

where `activity_id` is the normalized positive Python `int`. The client
accepts the ID as a string internally, but this fork passes the normalized
integer consistently with the existing activity tool test seam.

`fitparse` 1.2 converts FIT `date_time` values to naïve Python `datetime`
objects using UTC. A FIT record timestamp is therefore treated as a naïve UTC
instant, never as local device time. The public serializer writes that instant
as a canonical UTC RFC 3339 value with a `Z` suffix, for example
`2026-08-13T06:00:01.250000Z`. It does not infer a local timezone or expose a
local timestamp field.

The existing `activity_analysis._parse_fit` is deliberately not reused. It
reads position fields and serves an unrestricted tool with unrelated cycling
analysis. Reusing it would make the new privacy boundary difficult to prove.
The new parser is a small independent allowlist parser. A future shared pure
helper is allowed only if it takes no message fields itself, has no GPS-aware
callers, and has tests proving that it cannot expand the new parser's field
allowlist; v1 should otherwise keep the duplication narrow.

## Public input contract

The FastMCP adapter has this exact signature and defaults:

```python
async def get_activity_timeseries(
    activity_id: StrictInt | StrictStr,
    start_seconds: StrictInt = 0,
    duration_seconds: StrictInt = 600,
    resolution_seconds: StrictInt = 1,
) -> str:
```

`StrictInt` is required for each window argument. FastMCP must reject JSON
booleans, floats, numeric strings, arrays, and objects for
`start_seconds`, `duration_seconds`, and `resolution_seconds` before a Garmin
read. The activity ID intentionally preserves the existing AI ID convention:
it accepts a `StrictInt` or `StrictStr`, but no coercion. Thus booleans and
floats are rejected before a read for all four arguments.

The service repeats the same checks so direct service calls cannot bypass the
boundary. Its normalization rules are exact:

| Argument | Accepted and normalized form | Constraint |
| --- | --- | --- |
| `activity_id` | `type(value) is int`, or `type(value) is str` after `strip()` when it is non-empty ASCII decimal digits only; normalize to `int` | `> 0` |
| `start_seconds` | `type(value) is int` only | `>= 0` |
| `duration_seconds` | `type(value) is int` only | `1..86400` inclusive |
| `resolution_seconds` | `type(value) is int` only | `1..300` inclusive |

No leading sign, decimal point, exponent, non-ASCII numeral, Boolean, float,
or other scalar form is accepted. `activity_id` strings may contain surrounding
ASCII or Unicode whitespace only because `strip()` is applied before the
ASCII-decimal check; the accepted remaining characters are still ASCII `0-9`.
The normalized ID is not allowed to be zero.

The request is also invalid unless:

```text
ceil(duration_seconds / resolution_seconds) <= 600
```

Arguments are rejected rather than clamped. The service performs zero Garmin
calls for every invalid argument or unavailable client.

Validation stops at the first failure in this order: `activity_id`,
`start_seconds`, `duration_seconds`, `resolution_seconds`, then the point
limit. This fixes the error returned for a request with more than one bad
field. The error envelope retains only values already normalized before that
failure: an invalid activity ID yields `activity_id: null` and a wholly null
window; an invalid start retains the ID; an invalid duration retains the ID and
requested start; an invalid resolution also retains the computed end; and a
point-limit error retains all normalized window values. No later validation or
Garmin read occurs after the first failure.

## Window, sampling, and pagination semantics

The parser first reads all valid timestamped record messages, sorts them by
`(timestamp, original_encounter_index)`, and chooses the earliest valid
timestamp as `T0`. A record's exact elapsed time is
`(timestamp - T0).total_seconds()`; it is not rounded before selection or
binning. This makes the first valid record elapsed second `0`, even when its
timestamp has a microsecond component.

The requested window is half-open:

```text
[start_seconds, start_seconds + duration_seconds)
```

The lower bound is inclusive and the upper bound is exclusive. A record at
exactly `start_seconds` belongs to this response; one at exactly the computed
end belongs to the next page. This rule applies equally to irregular and
fractional elapsed times. The response calls the computed exclusive end
`actual_end_seconds`; it is `start_seconds + duration_seconds`, not a rounded or
source-clipped activity end. The term *bounded end* means the validated
request bound. Keeping it un-clipped gives a caller a stable continuation
cursor even through an empty pause.

Only non-empty bins are returned. For a selected record, the zero-based bin is
`floor((elapsed_seconds - start_seconds) / resolution_seconds)`. Its anchor is
`start_seconds + bin * resolution_seconds`. Empty bins are omitted, rather
than represented by fabricated null samples. Each returned point therefore has
one or more source records and `sample_count` proves how many. The anchor time
is metadata for the bin, not a claim that a device sampled exactly at that
instant. This preserves visible pauses and gaps without interpolation.

The output is paged by using a later request with
`start_seconds=window.next_start_seconds` and the desired new duration and
resolution. `next_start_seconds` is present only when at least one globally
valid timestamped record has elapsed time `>= actual_end_seconds`; its value is
exactly `actual_end_seconds`. A page boundary is consequently continuous:

- a record at `599.999999` is in `[0, 600)`;
- one at `600.000000` is in `[600, 1200)`;
- neither is repeated nor skipped, regardless of duplicate timestamps,
  uneven recording intervals, empty bins, or a different resolution on the
  next request.

No cursor is emitted after the last valid timestamped record. An activity that
has valid timestamped records but no records in a requested window is a
factual `success` with zero source records and zero returned points; it does
not invent a point or turn an out-of-range page into an error.

## Stable response envelope

Every result has these top-level keys in this order:

```text
status, error, activity_id, window, sampling, availability, series, warnings
```

`activity_id` is the normalized integer after its own validation, otherwise
`null`. `window` always contains normalized values where they were available:

```text
requested_start_seconds, actual_end_seconds, resolution_seconds
```

Each unavailable or not-yet-computable value is `null`. `next_start_seconds`
is omitted entirely unless a later valid record exists, as specified above.
The default request therefore reports `requested_start_seconds: 0`,
`actual_end_seconds: 600`, and `resolution_seconds: 1`.

`sampling` is window-scoped, not a device capability statement:

| Field | Meaning |
| --- | --- |
| `source_records` | Number of valid timestamped FIT `record` messages in the requested half-open window, before bin reduction. Duplicate timestamps count separately. |
| `returned_points` | Number of non-empty output bins. It is at most both `source_records` and 600. |
| `observed_median_interval_seconds` | Median of positive deltas between successive distinct, sorted source timestamps in this window, rounded to three decimals; `null` if fewer than two distinct timestamps occur. |
| `irregular` | `true` only when the window has at least two positive timestamp deltas and at least two distinct positive delta values. It is `false` for zero or one positive interval, including a duplicate-only timestamp set. |

The source interval fields describe observed source records, not a claim of 1
Hz sampling. `resolution_seconds=1` is a one-second bin width; it does not
mean the device recorded exactly once per second.

`availability` has exactly these Boolean, returned-window-scoped keys:

```text
heart_rate_bpm, speed_mps, pace_seconds_per_km,
cadence_rpm, power_w, altitude_m, grade_pct
```

A key is `true` if at least one selected valid record contributes a valid raw
observation for that metric. Pace is true only if at least one selected speed
is strictly positive. It does not claim an account, device, or activity type
can always provide that metric. A false metric has an all-`null` array (or, for
an empty window, an empty array); it is never represented as zero.

`series` has exactly the following aligned arrays:

```text
elapsed_seconds
timestamp
sample_count
heart_rate_bpm.average
heart_rate_bpm.minimum
heart_rate_bpm.maximum
speed_mps.average
pace_seconds_per_km.average
pace_seconds_per_km.fastest
pace_seconds_per_km.slowest
cadence_rpm.average
power_w.average
altitude_m.average
grade_pct.average
```

All listed arrays have exactly `sampling.returned_points` elements and the
same index describes the same bin. The JSON nesting used to realize that
field list is shown in the examples below. No other per-record, FIT, provider,
or request/response fields may be serialized.

## Allowed measurements and deterministic reduction

The parser may read only these FIT `record` fields:

```text
timestamp
heart_rate
speed
cadence
power
altitude
grade
```

It never reads `position_lat`, `position_long`, enhanced position aliases,
route data, developer fields, or any unlisted field. GPS is excluded both by
the parser allowlist and by the response serializer allowlist. Latitude,
longitude, coordinates, polyline, and derived location data must never appear,
even as `null` keys.

For each field, a usable value is a non-Boolean Python `int` or `float` that
is finite and in the stated inclusive physical-safety range. An invalid,
non-finite, or out-of-range individual metric becomes `null` for that record;
the timestamped record itself remains usable.

| Output metric | FIT field | Valid raw range | Reduction and output rounding |
| --- | --- | --- | --- |
| `heart_rate_bpm` | `heart_rate` | `1..300` | mean/min/max over valid values. Mean is 0.1 bpm; extrema are whole bpm. |
| `speed_mps` | `speed` | `0..100` m/s | mean over all valid values, including recorded zero, at 0.001 m/s. |
| `pace_seconds_per_km` | derived from `speed` only | positive speed from the preceding range | mean pace is `1000 / mean(positive_speeds)`; fastest is `1000 / max(positive_speeds)`; slowest is `1000 / min(positive_speeds)`, each whole seconds/km. Zero speeds are excluded from pace. A zero-only bin has speed `0.000` and all pace values `null`. |
| `cadence_rpm` | `cadence` | `0..300` rpm | mean at 0.1 rpm. |
| `power_w` | `power` | `0..3000` W | mean at 0.1 W. |
| `altitude_m` | `altitude` | `-1000..10000` m | mean at 0.1 m. |
| `grade_pct` | `grade` | `-100..100` % | mean at 0.1 percentage point. |

Round only after aggregating raw values. Decimal rounding is round-half-up;
whole pace/extrema are JSON integers and all other populated numeric outputs
are JSON numbers at the stated precision. The primary value is always the
average. Minimum/maximum and fastest/slowest preserve within-bin extrema, so a
coarser resolution retains relevant peaks. A one-second bin can still contain
multiple records: its primary values are averages and its `sample_count` is
greater than one.

Records are sorted before reduction. For equal timestamps the original
`fitparse` encounter index breaks the tie, making output independent of
source-message order while retaining every duplicated record in the bin. No
metric is carried forward from a previous record or bin.

## FIT download and parser safety boundary

The single source read is deliberately narrow. `ai_activity.providers` adds a
bounded `download_original_fit(client, activity_id)` seam. It calls only the
pinned `download_activity(..., dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)`
method, exactly once after validation. It calls no activity summary, detail,
map, raw request, mutation, or second download method. V1 has no cache, so a
separate tool invocation makes one new permitted download.

The provider accepts only a non-empty `bytes`, `bytearray`, or contiguous
one-byte `memoryview` response. It measures the response before parsing or
copying it and rejects an original download larger than **25,000,000 bytes**
(25 MB). It never calls `bytes()` on arbitrary provider objects. Provider
exceptions and payload values are converted to fixed safe outcomes; raw
exceptions, URLs, headers, token values, request IDs, and response bodies are
never returned or logged in the tool result.

The pure `timeseries.py` parser accepts that bounded byte string only. Because
the pinned client's ORIGINAL response is evidenced to be a ZIP archive, it
accepts a ZIP archive and does not guess gzip or raw-FIT fallback formats. It
must safely require exactly one non-directory `.fit` member, reject encrypted
members, reject a declared uncompressed member larger than 25,000,000 bytes,
and after extraction verify that the actual member length is also at most
25,000,000 bytes. The ZIP itself was already capped by the provider. Any ZIP
format error, member ambiguity, unsupported member, or size violation is a
safe error, never a fallback parse. This prevents decompression/archive
surprises without adding speculative gzip heuristics.

Only the extracted bounded FIT member is passed to
`fitparse.FitFile(io.BytesIO(...))`. Iteration counts every FIT `record`
message before window filtering. At message 100,001 the parser stops and
returns the fatal record-limit outcome; it must not silently truncate.

Malformed records are the only non-fatal FIT-message condition. A `record`
message is discarded and counted as malformed when its timestamp cannot be
obtained without an exception, is not a naïve `datetime`, cannot participate in
safe arithmetic/UTC serialization, or yields a negative elapsed time after
sorting (the last condition is defensive and should not occur). Missing or
invalid optional measurement fields do **not** make the record malformed; they
produce null metrics as described above. An exception while obtaining an
optional allowlisted measurement is handled the same way as an invalid optional
value: that metric is null, while the timestamped record remains usable.
Out-of-order and duplicate valid timestamps are valid, sorted records. Other
fitparse/file failures are fatal.

The parser returns only small typed facts to the service: sorted allowlisted
records, the global-valid-record continuation fact, and the malformed-record
count. It never returns a raw `FitFile`, `DataMessage`, archive member, or raw
payload to a serializer.

## Status, errors, and warnings

The tool uses only `success`, `partial_success`, and `error`.

- `success` means validation, download, archive handling, and parsing were
  usable. It includes a valid activity whose requested window has no source
  records.
- `partial_success` means there is at least one usable timestamped source
  record in the requested window and one or more malformed FIT record messages
  were discarded while parsing the activity. The result remains factual and
  bounded; its single aggregate warning reports the discard count.
- `error` means invalid input, unavailable client/download, invalid or unsafe
  FIT input, parse failure, record safety breach, or no usable timestamped
  record message anywhere in the activity. Errors have empty series arrays,
  all availability flags false, and no partially truncated data.

The special empty-window rule takes precedence over the partial rule: if the
activity has at least one globally valid timestamped record but the selected
window has none, return `success` with empty arrays even when malformed records
were found elsewhere in the file. This prevents an empty page from claiming a
sample or pretending to be a failed activity.

`error` is either `null` or this fixed object:

```json
{"provider": "fit", "code": "invalid_fit_payload", "message": "Original FIT data is invalid or unavailable."}
```

`warnings` is always an array. A warning has `provider`, `code`, `message`,
and `count`; no warning may contain provider data or exception text. The only
v1 warning is:

```json
{"provider": "fit", "code": "malformed_records_discarded", "message": "Malformed FIT record messages were discarded.", "count": 1}
```

The fixed error vocabulary is:

| Provider | Code | Exact message | Condition |
| --- | --- | --- | --- |
| `input` | `invalid_activity_id` | `activity_id must be a positive integer or ASCII decimal string.` | Invalid ID type, text, or range. |
| `input` | `invalid_start_seconds` | `start_seconds must be an integer greater than or equal to 0.` | Invalid start type or range. |
| `input` | `invalid_duration_seconds` | `duration_seconds must be an integer from 1 through 86400.` | Invalid duration type or range. |
| `input` | `invalid_resolution_seconds` | `resolution_seconds must be an integer from 1 through 300.` | Invalid resolution type or range. |
| `input` | `point_limit_exceeded` | `ceil(duration_seconds / resolution_seconds) must not exceed 600.` | Valid scalar values exceed the bin limit. |
| `client` | `client_unavailable` | `Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.` | No configured client. |
| `garmin` | `download_failed` | `Original FIT download is unavailable. Retry later or re-authenticate.` | The permitted download raised. |
| `garmin` | `invalid_download_payload` | `Original FIT download returned an invalid payload.` | Empty or unsupported return type. |
| `garmin` | `fit_download_too_large` | `Original FIT download exceeds the 25 MB limit.` | Downloaded bytes exceed 25,000,000. |
| `fit` | `invalid_fit_payload` | `Original FIT data is invalid or unavailable.` | Not a valid ZIP or no ordinary `.fit` member. |
| `fit` | `unsafe_fit_archive` | `Original FIT archive violates safety limits.` | More than one FIT member, encrypted member, or declared/actual extracted FIT member over 25,000,000 bytes. |
| `fit` | `fit_parse_failed` | `Original FIT data could not be parsed.` | `fitparse` construction or iteration failed. |
| `fit` | `record_limit_exceeded` | `Original FIT data exceeds the 100000-record limit.` | More than 100,000 FIT `record` messages. |
| `fit` | `no_timestamped_records` | `Original FIT data contains no usable timestamped record messages.` | Parsing completed but no globally valid timestamped record remained. |

Every error object uses only this table's literal provider, code, and message.
No raw exception is inserted in a response, warning, test failure assertion,
or JSON example.

## Architecture and integration

The implementation remains fork-owned under `src/garmin_mcp/ai_activity`:

```text
ai_activity/
  providers.py            bounded original-FIT download seam
  timeseries.py           pure archive validation, allowlist FIT parse, sort, bin, reduce
  timeseries_service.py   strict validation, one provider call, stable envelope
  tools.py                FastMCP adapter and registration
```

`timeseries.py` has no Garmin client, environment lookup, logging of payloads,
or FastMCP dependency. It accepts bytes and plain request values and returns
plain typed facts/outcomes. `timeseries_service.py` owns argument
normalization, empty/error envelope creation, provider orchestration, status,
and serialization-ready result selection. `tools.py` owns only strict adapter
types, concise factual/privacy documentation, delegation, and stable
`json.dumps(..., indent=2)` output. Package `__init__.py` exports the new
service and retains the existing lazy `configure`/`register_tools` pattern.

The root startup path continues to configure and register `ai_activity` once;
no second client global is created. `register_tools` adds
`get_activity_timeseries` beside `analyze_activity`.

Add the tool to `TOOL_PROFILES["ai-coach"]` atomically. The exact profile
changes from 13 to 14 tools:

```text
get_training_context
analyze_activity
get_activity_timeseries
create_workout
update_workout
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

The existing profile precedence remains unchanged: explicit
`GARMIN_ENABLED_TOOLS` wins; otherwise the named profile is selected and
`GARMIN_DISABLED_TOOLS` subtracts from it; no profile continues to register the
broad upstream-compatible surface. `get_activity_fit_data` is not in the
14-tool set. No `move_workout` is included.

## Current-facing documentation

Add `docs/ai-activity-timeseries.md` and link it from the README, setup,
training, workout, and activity-analysis guides where high-level coaching
tools/profile counts are described. Update every current list that says 13
tools to the exact 14-tool profile above. Historical specifications and plans
remain historical records and are not rewritten.

The new guide must make the tool choice unambiguous:

- Claude uses `analyze_activity(activity_id)` first for the normal bounded
  completed-session overview.
- Claude calls `get_activity_timeseries` only for a concrete, short-interval
  evidence question that the overview cannot answer, such as a cadence/power
  change during a specified section.
- Claude pages by passing the previous `window.next_start_seconds` as the next
  `start_seconds`; it must stop when that key is absent and must not assume a
  one-Hz stream or fill empty bins.
- The guide states the default 10-minute/one-second window, the 600-bin limit,
  all units and missing-vs-zero behavior, the read-only one-download budget,
  ZIP/FIT safety limits, and the absolute GPS exclusion.

The tool description and guide must not advertise raw/full FIT data, GPS,
coaching judgment, or more than one Garmin download. They should say that
availability is scoped to the returned window rather than account/device
capability.

## Offline acceptance coverage

All tests are offline. Fake FIT message objects and a recording Garmin client
are sufficient; tests must not authenticate, call a live account, or depend on
network data.

The test suite must cover at least the following observable contracts:

1. FastMCP schema/signature/defaults and actual call-time strictness: booleans,
   floats, strings for window arguments, arrays, and objects are rejected
   before any provider/client read; a trimmed ASCII decimal activity ID is
   accepted and every invalid service direct-call shape is rejected too.
2. The exact default one-second window and a coarse resolution; multiple
   source records in one one-second bin; output bin cap and aligned-array
   lengths for every metric array.
3. Half-open start/end boundaries, pagination cursor presence/absence, no
   duplicate or skipped records across pages, fractional/irregular timestamps,
   pauses/empty bins, observed median interval, and irregular flag semantics.
4. Stable sorting of out-of-order messages and deterministic duplicate
   timestamp aggregation; no interpolation or carry-forward values.
5. Heart-rate average/minimum/maximum, speed average, pace average/fastest/
   slowest, zero-only speed bins, missing fields, null arrays, and the exact
   rounding rules.
6. Finite/adversarial metric values, including Boolean, NaN, infinity, and
   out-of-range values; they become null without making an otherwise valid
   timestamped record malformed.
7. Malformed record-message discard/partial-success behavior, aggregate safe
   warning, globally no usable timestamp error, and a valid activity with an
   empty requested window returning factual `success` and zero points.
8. Provider call budget: exactly one
   `download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)`
   after valid input, no caching, and a recording client that raises on every
   mutation, raw request, or non-download read.
9. Empty, wrong-type, oversized, malformed, encrypted, multi-member, and
   decompression-size-unsafe archive payloads; raw bytes are capped before
   `fitparse`; more than 100,000 record messages is a fatal error with no
   truncation.
10. Exception/payload sanitization: nested serialized result scans find no
    secret, URL, header, request ID, raw exception text, raw FIT message, or
    raw payload value.
11. GPS privacy: fixtures containing latitude/longitude (and any other
    unlisted fields) prove the parser never asks for them, and a recursive
    serialized-output scan finds no GPS/coordinate/polyline keys or values.
12. Root configuration, registration beside `analyze_activity`, exact
    14-member profile/startup filtering, retained exclusion of
    `get_activity_fit_data`, and documentation assertions for the pinned 0.3.10
    ORIGINAL ZIP behavior, limits, paging, and tool-selection guidance.

## Response examples

The following are parseable contract examples. They show shape and semantics,
not a claim that a particular device supplies every metric.

### Successful populated page

```json
{
  "status": "success",
  "error": null,
  "activity_id": 123456,
  "window": {
    "requested_start_seconds": 0,
    "actual_end_seconds": 600,
    "resolution_seconds": 5,
    "next_start_seconds": 600
  },
  "sampling": {
    "source_records": 5,
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
    "elapsed_seconds": [0, 5],
    "timestamp": ["2026-08-13T06:00:00.000000Z", "2026-08-13T06:00:05.000000Z"],
    "sample_count": [3, 2],
    "heart_rate_bpm": {"average": [141.7, 146.0], "minimum": [140, 145], "maximum": [143, 147]},
    "speed_mps": {"average": [3.125, 3.5]},
    "pace_seconds_per_km": {"average": [320, 286], "fastest": [313, 278], "slowest": [333, 294]},
    "cadence_rpm": {"average": [174.3, 176.0]},
    "power_w": {"average": [221.7, 240.0]},
    "altitude_m": {"average": [23.4, 24.1]},
    "grade_pct": {"average": [1.2, 2.0]}
  },
  "warnings": []
}
```

### Valid activity, empty requested window

```json
{
  "status": "success",
  "error": null,
  "activity_id": 123456,
  "window": {
    "requested_start_seconds": 1200,
    "actual_end_seconds": 1800,
    "resolution_seconds": 1
  },
  "sampling": {
    "source_records": 0,
    "returned_points": 0,
    "observed_median_interval_seconds": null,
    "irregular": false
  },
  "availability": {
    "heart_rate_bpm": false,
    "speed_mps": false,
    "pace_seconds_per_km": false,
    "cadence_rpm": false,
    "power_w": false,
    "altitude_m": false,
    "grade_pct": false
  },
  "series": {
    "elapsed_seconds": [],
    "timestamp": [],
    "sample_count": [],
    "heart_rate_bpm": {"average": [], "minimum": [], "maximum": []},
    "speed_mps": {"average": []},
    "pace_seconds_per_km": {"average": [], "fastest": [], "slowest": []},
    "cadence_rpm": {"average": []},
    "power_w": {"average": []},
    "altitude_m": {"average": []},
    "grade_pct": {"average": []}
  },
  "warnings": []
}
```

### Partial success after a malformed record is discarded

```json
{
  "status": "partial_success",
  "error": null,
  "activity_id": 123456,
  "window": {
    "requested_start_seconds": 0,
    "actual_end_seconds": 600,
    "resolution_seconds": 1
  },
  "sampling": {
    "source_records": 1,
    "returned_points": 1,
    "observed_median_interval_seconds": null,
    "irregular": false
  },
  "availability": {
    "heart_rate_bpm": false,
    "speed_mps": true,
    "pace_seconds_per_km": false,
    "cadence_rpm": false,
    "power_w": false,
    "altitude_m": false,
    "grade_pct": false
  },
  "series": {
    "elapsed_seconds": [0],
    "timestamp": ["2026-08-13T06:00:00.000000Z"],
    "sample_count": [1],
    "heart_rate_bpm": {"average": [null], "minimum": [null], "maximum": [null]},
    "speed_mps": {"average": [0.0]},
    "pace_seconds_per_km": {"average": [null], "fastest": [null], "slowest": [null]},
    "cadence_rpm": {"average": [null]},
    "power_w": {"average": [null]},
    "altitude_m": {"average": [null]},
    "grade_pct": {"average": [null]}
  },
  "warnings": [
    {
      "provider": "fit",
      "code": "malformed_records_discarded",
      "message": "Malformed FIT record messages were discarded.",
      "count": 1
    }
  ]
}
```

### Safe error

```json
{
  "status": "error",
  "error": {
    "provider": "input",
    "code": "point_limit_exceeded",
    "message": "ceil(duration_seconds / resolution_seconds) must not exceed 600."
  },
  "activity_id": 123456,
  "window": {
    "requested_start_seconds": 0,
    "actual_end_seconds": 1200,
    "resolution_seconds": 1
  },
  "sampling": {
    "source_records": 0,
    "returned_points": 0,
    "observed_median_interval_seconds": null,
    "irregular": false
  },
  "availability": {
    "heart_rate_bpm": false,
    "speed_mps": false,
    "pace_seconds_per_km": false,
    "cadence_rpm": false,
    "power_w": false,
    "altitude_m": false,
    "grade_pct": false
  },
  "series": {
    "elapsed_seconds": [],
    "timestamp": [],
    "sample_count": [],
    "heart_rate_bpm": {"average": [], "minimum": [], "maximum": []},
    "speed_mps": {"average": []},
    "pace_seconds_per_km": {"average": [], "fastest": [], "slowest": []},
    "cadence_rpm": {"average": []},
    "power_w": {"average": []},
    "altitude_m": {"average": []},
    "grade_pct": {"average": []}
  },
  "warnings": []
}
```

## Completion criteria

Before implementation is considered ready, review the code, tests, and docs
against this specification for contradictory limits, profile counts, runtime
names, and privacy claims. Scan changed files for unfinished-work markers and
incomplete-language; parse every JSON example; recursively scan serialized
fixtures for forbidden GPS/location/raw-data keys and secrets; run the full
offline suite; and run `git diff --check`. The implementation change must stay
within the fork-owned seams plus minimal root registration/profile and current
documentation updates described here.
