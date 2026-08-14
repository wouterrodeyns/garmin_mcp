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
`fitparse>=1.2.0` for the existing low-level activity-analysis tool. This v1
tool adds and pins the separate dependency `fitdecode==0.11.0` in both
`pyproject.toml` and `uv.lock`; it does not replace or loosen the existing
`fitparse` dependency. In that pinned Garmin client,
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

The v1 parser uses `fitdecode.FitReader`, the dependency's public streaming
reader API. It yields header, definition, data, and CRC frames as they are
decoded; it does not require an all-message cache. Each tool call creates and
closes a fresh reader, so local message definitions and developer-field state
are per-reader/per-FIT-file state rather than global state retained by the
service. The reader is constructed exactly with
`check_crc=fitdecode.CrcCheck.RAISE`,
`error_handling=fitdecode.ErrorHandling.RAISE`, and
`keep_raw_chunks=False`. CRC or malformed-FIT failures are therefore fatal and
raw frame chunks are never retained.

`fitdecode` 0.11's default data processor converts usable FIT `date_time`
values to timezone-aware UTC Python `datetime` objects. This tool treats the
underlying FIT `raw_value`, not that rendered datetime, as the timestamp
authority for sorting, elapsed-time arithmetic, window selection, and binning.
The rendered UTC datetime is a required cross-check and is used only to
serialize an accepted timestamp. The public serializer writes canonical UTC
RFC 3339 with a `Z` suffix, for example `2026-08-13T06:00:01.000000Z`; it does
not expose a local timestamp field.

The existing `activity_analysis._parse_fit` is deliberately not reused. It
reads position fields and serves an unrestricted tool with unrelated cycling
analysis. Reusing it would make the new privacy boundary difficult to prove.
The new parser is a small independent allowlist parser. `fitdecode` must
consume every field's bytes in a data frame to keep FIT decoder state correct,
but v1 selects, copies, retains, and serializes only its explicit measurement
allowlist. It does not retain raw frames/messages or unselected values. A
future shared pure helper is allowed only if it takes no message fields itself,
has no GPS-aware callers, and has tests proving that it cannot expand the new
parser's field allowlist; v1 should otherwise keep the duplication narrow.

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
| `activity_id` | `type(value) is int`, or `type(value) is str` after `strip()` when it is non-empty ASCII decimal digits only; normalize to `int` | `1..9007199254740991` inclusive |
| `start_seconds` | `type(value) is int` only | `0..4026531838` inclusive |
| `duration_seconds` | `type(value) is int` only | `1..86400` inclusive |
| `resolution_seconds` | `type(value) is int` only | `1..300` inclusive |

No leading sign, decimal point, exponent, non-ASCII numeral, Boolean, float,
or other scalar form is accepted. `activity_id` strings may contain surrounding
ASCII or Unicode whitespace only because `strip()` is applied before the
ASCII-decimal check; the accepted remaining characters are still ASCII `0-9`.
The normalized ID is not allowed to be zero or exceed
`MAX_ACTIVITY_ID = 9007199254740991`, the largest JSON-safe integer. The
normalized start is capped at
`MAX_FIT_ELAPSED_SECONDS = 0xEFFFFFFE = 4026531838`. This and the JSON-safe ID
cap are v1 service safety bounds, not Garmin activity-ID or activity-duration
limits.

The request is also invalid unless:

```text
ceil(duration_seconds / resolution_seconds) <= 600
```

Arguments are rejected rather than clamped. The service performs zero Garmin
calls for every invalid argument or unavailable client. It performs no envelope
end arithmetic until both the bounded start and duration have passed their
checks; their maximum possible sum is `4026531838 + 86400 = 4026618238`, well
within the JSON-safe integer range, so `actual_end_seconds` cannot become an
unbounded Python integer. The computed end may exceed
`MAX_FIT_ELAPSED_SECONDS`; this is valid as a half-open request bound, while
the cursor rule below guarantees every emitted next input remains within that
v1 bound.

Validation stops at the first failure in this order: `activity_id`,
`start_seconds`, `duration_seconds`, `resolution_seconds`, then the point
limit. This fixes the error returned for a request with more than one bad
field. The error envelope retains only values already normalized before that
failure: an invalid activity ID yields `activity_id: null` and a wholly null
window; an invalid start retains the bounded ID; an invalid duration retains
the ID and bounded requested start; an invalid resolution also retains the
safely computed end; and a point-limit error retains all normalized window
values. No later validation or Garmin read occurs after the first failure.

## Window, sampling, and pagination semantics

The parser first reads all valid timestamped record messages, sorts them by
`(raw_timestamp_seconds, original_encounter_index)`, and chooses the earliest
raw timestamp as `T0`. A record's elapsed time is the exact non-negative
integer `raw_timestamp_seconds - T0`; it is not rounded before selection or
binning. All FIT timestamps accepted by this contract are whole seconds.

The requested window is half-open:

```text
[start_seconds, start_seconds + duration_seconds)
```

The lower bound is inclusive and the upper bound is exclusive. A record at
exactly `start_seconds` belongs to this response; one at exactly the computed
end belongs to the next page. This rule applies equally to irregular
whole-second elapsed times. The response calls the computed exclusive end
`actual_end_seconds`; it is `start_seconds + duration_seconds`, not a rounded or
source-clipped activity end. The term *bounded end* means the validated
request bound. Keeping it un-clipped gives a caller a stable continuation
cursor even through an empty pause.

Only non-empty bins are returned. For a selected record, the zero-based bin is
`floor((elapsed_seconds - start_seconds) / resolution_seconds)`. Its anchor is
`start_seconds + bin * resolution_seconds`. Empty bins are omitted, rather
than represented by fabricated null samples. Each returned point therefore has
one or more source records and `sample_count` proves how many. Normatively,
`series.timestamp[i]` is the canonical UTC serialization of the FIT epoch plus
`T0 + series.elapsed_seconds[i]` seconds, where that elapsed value is the bin
anchor. The anchor timestamp is metadata for the bin, not a claim that a device
sampled exactly at that instant. This preserves visible pauses and gaps without
interpolation.

The output is paged by using a later request with
`start_seconds=window.next_start_seconds` and the desired new duration and
resolution. `next_start_seconds` is present only when at least one globally
valid timestamped record has elapsed time `>= actual_end_seconds`; its value is
exactly `actual_end_seconds`. Because such a record has
`raw_timestamp_seconds - T0 <= MAX_FIT_ELAPSED_SECONDS`, every emitted cursor
is at most `MAX_FIT_ELAPSED_SECONDS` and is therefore a valid subsequent
`start_seconds` input. A page boundary is consequently continuous:

- a record at elapsed second `599` is in `[0, 600)`;
- one at elapsed second `600` is in `[600, 1200)`;
- neither is repeated nor skipped, regardless of duplicate timestamps,
  uneven recording intervals, empty bins, or a different resolution on the
  next request.

No cursor is emitted after the last valid timestamped record. An activity that
has valid timestamped records but no records in a requested window is a
factual `success` with zero source records and zero returned points; it does
not invent a point or turn an out-of-range page into an error.

## Stable response envelope

Every call that passes FastMCP schema validation, and every direct call to the
service, has these top-level keys in this order:

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

A malformed declared adapter argument is a FastMCP `ToolError` before the
service or Garmin client is called, so it is not a JSON envelope. Direct
service calls instead return the stable input-error envelope. A pinned-FastMCP
integration test verifies that undeclared extra adapter arguments are ignored.
They are outside this tool contract and are never delegated to or used by the
service; v1 does not promise rejection of extras.

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

The parser identifies FIT records and standard fields numerically, never by a
message or field name. It considers a frame only when
`frame.frame_type == fitdecode.FIT_FRAME_DATA` **and**
`frame.global_mesg_num == 20` (the FIT `record` global message number). It
never gates on `frame.name`, `frame.mesg_type.name`, or any other display name.
For a candidate record it iterates `frame.fields` exactly; it does not call
generic `get_value(...)`, `get_raw_value(...)`, `get_field(...)`, name lookup,
or `all_field_defs`.

A direct standard candidate is accepted only when all of the following are
true: `field_data.field_def is not None`,
`field_data.field_def.is_dev is False`, `field_data.is_expanded is False`, and
`field_data.parent_field is None`; then its field definition's `def_num`,
`base_type.identifier`, and `size` must exactly match this table. Names are not
part of the match.

| Copied fact / output source | `def_num` | Base-type identifier | Definition size |
| --- | ---: | ---: | ---: |
| timestamp | 253 | `0x86` | 4 |
| heart rate | 3 | `0x02` | 1 |
| speed | 6 | `0x84` | 2 |
| cadence | 4 | `0x02` | 1 |
| power | 7 | `0x84` | 2 |
| altitude | 2 | `0x84` | 2 |
| grade | 9 | `0x83` | 2 |

The only permitted non-direct timestamp candidate is fitdecode's own
compressed-timestamp field. It is accepted only when
`frame.time_offset is not None`, `field_data.field_def is None`,
`field_data.field is fitdecode.profile.FIELD_TYPE_TIMESTAMP` (the canonical
profile timestamp identity), and `field_data.parent_field is None`. This is
the decoder-generated timestamp special case, not a general expanded-field
path. Every other expanded/component field is excluded, including enhanced
speed `def_num 73`, enhanced altitude `def_num 78`, and component-derived
speed/altitude. All developer fields are excluded even if their definition
number, profile/display name, or value resembles an allowed standard field.

Exactly one valid timestamp candidate is required; zero or more than one makes
the whole record malformed. For each optional metric, zero candidates or more
than one candidate yields `null` for that metric in the otherwise timestamped
record. With exactly one optional candidate, the parser copies only the
normalized finite numeric measurement needed for reduction; it does not retain
the `FieldData`, its definition, or its raw value. The timestamp alone uses
the candidate's exact integer `raw_value`, under the raw-timestamp contract
below.

An accepted timestamp raw value has `type(raw_value) is int` and is in the
inclusive range `0x10000000..0xFFFFFFFE`. This rejects booleans, the uint32
invalid sentinel `0xFFFFFFFF`, and values below fitdecode's
`FIT_DATETIME_MIN = 0x10000000`, which represent device-power-on elapsed time
rather than absolute time. FIT raw seconds are measured from the UTC FIT epoch
`1989-12-31T00:00:00Z`; the accepted raw range therefore represents
`1998-07-03T21:24:16Z` through `2126-02-06T06:28:14Z`, inclusive. The matching
fitdecode value must be an aware UTC `datetime` equal to the FIT-epoch instant
plus that exact raw-second count. The parser uses the raw integer for sorting,
`T0`, elapsed seconds, window selection, and binning; it uses the cross-checked
UTC datetime only for canonical `Z` serialization. Thus every accepted source
timestamp and elapsed value is an integer number of seconds. Since the earliest
possible `T0` is `0x10000000` and the latest accepted raw timestamp is
`0xFFFFFFFE`, no valid activity elapsed value can exceed
`0xEFFFFFFE = MAX_FIT_ELAPSED_SECONDS`.

It never selects, copies, retains, or serializes `position_lat`,
`position_long`, route data, developer fields, or any unlisted field. GPS is
excluded both by the numeric parser allowlist and the response serializer
allowlist. Latitude, longitude, coordinates, polyline, and derived location
data must never appear, even as `null` keys.

For each field, a usable value is a non-Boolean Python `int` or `float` that
is finite and in the stated inclusive physical-safety range. An invalid,
non-finite, or out-of-range individual metric becomes `null` for that record;
the timestamped record itself remains usable.

| Output metric | FIT field identity | Valid normalized range | Reduction and output rounding |
| --- | --- | --- | --- |
| `heart_rate_bpm` | `heart_rate` | `1..300` | mean/min/max over valid values. Mean is 0.1 bpm; extrema are whole bpm. |
| `speed_mps` | `speed` | `0..100` m/s | mean over all valid values, including recorded zero, at 0.001 m/s. |
| `pace_seconds_per_km` | derived from `speed` only | positive speed from the preceding range | mean pace is `1000 / mean(positive_speeds)`; fastest is `1000 / max(positive_speeds)`; slowest is `1000 / min(positive_speeds)`, each whole seconds/km. Zero speeds are excluded from pace. A zero-only bin has speed `0.000` and all pace values `null`. |
| `cadence_rpm` | `cadence` | `0..300` rpm | mean at 0.1 rpm. |
| `power_w` | `power` | `0..3000` W | mean at 0.1 W. |
| `altitude_m` | `altitude` | `-1000..10000` m | mean at 0.1 m. |
| `grade_pct` | `grade` | `-100..100` % | mean at 0.1 percentage point. |

Round only after aggregating normalized values. Every mean and the positive-speed
mean used for pace is `math.fsum(values) / len(values)` over the sorted,
per-bin values. Decimal rounding is round-half-up; whole pace/extrema are JSON
integers and all other populated numeric outputs are JSON numbers at the
stated precision. The primary value is always the average. Minimum/maximum and
fastest/slowest preserve within-bin extrema, so a coarser resolution retains
relevant peaks. A one-second bin can still contain multiple records: its
primary values are averages and its `sample_count` is greater than one.

Records are sorted before reduction. For equal timestamps the original
archive encounter index breaks the tie, making output deterministic for a
given archive/message order while retaining every duplicated record in the
bin. It does not claim equal results when the archive's message order changes.
No metric is carried forward from a previous record or bin.

## FIT download and parser safety boundary

The single source read is deliberately narrow. `ai_activity.providers` owns
only the bounded `download_original_fit(client, activity_id)` seam. After all
service validation succeeds, it makes exactly one call to the pinned
`download_activity(..., dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)`
method. It calls no activity summary, detail, map, raw request, mutation, or
second download method. Invalid input and an unavailable client make zero
Garmin calls; every valid configured invocation makes exactly the one download.
V1 has no cache, so a separate invocation makes one new permitted download.

The provider accepts only a non-empty `bytes`, `bytearray`, or contiguous
one-byte `memoryview` response. It measures the response before parsing or
copying it and rejects an original download larger than **25,000,000 bytes**
(25 MB). It never calls `bytes()` on arbitrary provider objects. Provider
exceptions and payload values are converted to fixed safe outcomes; raw
exceptions, URLs, headers, token values, request IDs, and response bodies are
never returned or logged in the tool result.

These are the normative parser/resource constants; all values are inclusive
unless their corresponding `+1` abort point is stated:

| Constant | Value | Bound |
| --- | --- | --- |
| `MAX_ORIGINAL_DOWNLOAD_BYTES` | 25,000,000 | Downloaded ZIP archive bytes. |
| `ZIP_EOCD_TAIL_BYTES` | 65,557 | Maximum trailing bytes searched for classic EOCD. |
| `MAX_ARCHIVE_ENTRIES` | 16 | Central-directory entries. |
| `MAX_CENTRAL_DIRECTORY_BYTES` | 65,536 | Declared central-directory size. |
| `MAX_AUXILIARY_ENTRY_BYTES` | 65,536 | Declared uncompressed size of each never-opened non-FIT entry. |
| `MAX_FIT_MEMBER_BYTES` | 25,000,000 | Declared and streamed decompressed selected FIT member bytes. |
| `FIT_STREAM_READ_CHUNK_BYTES` | 65,536 | Maximum underlying stream read. |
| `MAX_FIT_FRAMES` | 200,000 | Header, definition, data, and CRC frames combined. |
| `MAX_RECORD_MESSAGES` | 100,000 | FIT `record` data messages. |
| `MAX_FIELDS_PER_DEFINITION` | 128 | Standard plus developer fields in one definition. |

`timeseries.py` owns archive preflight, stream extraction, decoder limits, and
minimal-fact reduction. It accepts the provider's already bounded archive byte
string only. Because the pinned client's ORIGINAL response is evidenced to be
a ZIP archive, it accepts a classic ZIP archive and has no gzip or raw-FIT
fallback. It must complete the following preflight **before** constructing a
`zipfile.ZipFile`:

1. Inspect only the final `min(len(archive), 65557)` bytes for a classic
   single-disk EOCD. Require one EOCD whose comment-length field ends exactly
   at archive EOF. Reject a missing/ambiguous EOCD, all ZIP64 sentinels,
   ZIP64 locator/record signatures, and ZIP64 extra fields.
2. Require EOCD disk number and central-directory start disk to be zero, and
   require equal per-disk/total entry counts. Reject multi-disk archives.
   Require `MAX_ARCHIVE_ENTRIES = 16` or fewer entries and
   `MAX_CENTRAL_DIRECTORY_BYTES = 65536` or fewer central-directory bytes.
3. Walk every central-directory entry inside the declared directory range.
   Require valid central-header lengths and ranges, start disk zero, no
   encryption flags, and compression method `ZIP_STORED` or `ZIP_DEFLATED`
   only. Validate each referenced local header, name/extra range, compressed
   data range, and offset lies before the central directory. Reject unsafe
   paths (absolute, traversal, or backslash paths), symlinks, and any ZIP64
   extra field. A non-FIT auxiliary entry is permitted only when it is an
   ordinary file/directory with declared uncompressed size at most 65536;
   auxiliary entries are never opened.
4. Require exactly one non-directory `.fit` entry, case-insensitively. Its
   declared uncompressed size must be at most 25,000,000 bytes. Construct
   `ZipFile` only after these checks and cross-check its selected `ZipInfo`
   values (name, compression, flags, sizes, and local-header offset) against
   the preflight values before opening it.

The ZIP archive itself was already capped at 25,000,000 bytes by the provider.
Archive parse errors with no valid classic structure are `invalid_fit_payload`;
every preflight/cross-check limit or safety violation is `unsafe_fit_archive`.
This two-stage validation prevents archive surprises without speculative
format heuristics.

The selected `ZipFile.open()` handle is never passed through `zf.read()` and
the member is never extracted into one bytes object. A counting
`LimitedReader` wraps that handle and is passed directly to `fitdecode`. It
limits every underlying read to 65536 bytes, counts decompressed bytes, and
raises the safe member-limit outcome on byte 25,000,001. The parser therefore
does not allocate the declared or actual full FIT member before applying the
cap.

The stream uses exactly:

```python
fitdecode.FitReader(
    limited_reader,
    check_crc=fitdecode.CrcCheck.RAISE,
    error_handling=fitdecode.ErrorHandling.RAISE,
    keep_raw_chunks=False,
)
```

Count every yielded header, definition, data, and CRC frame before filtering.
At frame 200,001 (`MAX_FIT_FRAMES = 200000`), return the fatal frame-limit
outcome. A valid decoded FIT stream contains exactly one `FIT_FRAME_HEADER`.
Count those frames separately: a second header is immediately the fatal
`chained_fit_unsupported` outcome. It discards all accumulated minimal facts
and never combines consecutive FIT streams. For every definition frame, check
`len(field_defs) + len(dev_field_defs)` and return the fatal definition-field
outcome above `MAX_FIELDS_PER_DEFINITION = 128`. For record data messages,
count every message before window filtering; at record 100,001
(`MAX_RECORD_MESSAGES = 100000`), return the fatal record-limit outcome. None
of these outcomes may silently truncate a stream.

Malformed records are the only non-fatal FIT-message condition. A `record`
message is discarded and counted as malformed when its numeric extraction has
zero or multiple timestamp candidates, its timestamp `raw_value` is not the
exact accepted integer/range, or its fitdecode timestamp value fails the aware
UTC epoch cross-check defined above. Missing, duplicate, malformed, or
out-of-range optional metric candidates do **not** make the record malformed;
they produce null metrics as described above. An exception while normalizing
one optional allowlisted measurement is handled the same way: that metric is
null while the timestamped record remains usable. Out-of-order and duplicate
valid timestamps are valid, sorted records. Other fitdecode/file failures are
fatal.

The decoder necessarily consumes all field bytes in a data message to advance
its FIT state. The parser nevertheless applies only the numeric standard-field
rules above, copies only normalized allowed metric values and a raw timestamp
into a minimal record fact, and drops the yielded frame/message immediately.
It neither selects nor retains GPS, developer fields, component fields, or any
other unlisted value. The service retains at most 100,000 minimal allowlisted
record facts for sorting; it retains no decoded frame/message, raw chunk,
archive member, or raw payload. The parser returns only those facts, the
global-valid-record continuation fact, and the activity-global malformed-record
count to the service.

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

Malformed-record status, warning, and count are activity-global because a
timestamp-invalid record cannot be assigned to a requested window. Thus any
selected window with usable records is `partial_success` when any malformed
record was discarded anywhere in the decoded activity. Sampling and
availability remain strictly window-scoped. The special empty-window rule takes
precedence: if the activity has at least one globally valid timestamped record
but the selected window has none, return `success` with empty arrays even when
malformed records were found elsewhere in the file. This prevents an empty page
from claiming a sample or pretending to be a failed activity.

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
| `input` | `invalid_activity_id` | `activity_id must be a positive integer or ASCII decimal string from 1 through 9007199254740991.` | Invalid ID type, text, zero, or JSON-safe range. |
| `input` | `invalid_start_seconds` | `start_seconds must be an integer from 0 through 4026531838.` | Invalid start type or `MAX_FIT_ELAPSED_SECONDS` v1 safety range. |
| `input` | `invalid_duration_seconds` | `duration_seconds must be an integer from 1 through 86400.` | Invalid duration type or range. |
| `input` | `invalid_resolution_seconds` | `resolution_seconds must be an integer from 1 through 300.` | Invalid resolution type or range. |
| `input` | `point_limit_exceeded` | `ceil(duration_seconds / resolution_seconds) must not exceed 600.` | Valid scalar values exceed the bin limit. |
| `client` | `client_unavailable` | `Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.` | No configured client. |
| `garmin` | `download_failed` | `Original FIT download is unavailable. Retry later or re-authenticate.` | The permitted download raised. |
| `garmin` | `invalid_download_payload` | `Original FIT download returned an invalid payload.` | Empty or unsupported return type. |
| `garmin` | `fit_download_too_large` | `Original FIT download exceeds the 25 MB limit.` | Downloaded bytes exceed 25,000,000. |
| `fit` | `invalid_fit_payload` | `Original FIT data is invalid or unavailable.` | Not a valid ZIP or no ordinary `.fit` member. |
| `fit` | `unsafe_fit_archive` | `Original FIT archive violates safety limits.` | ZIP64, non-classic/multi-disk structure, EOCD/central/local range failure, archive entry/directory/compression/encryption/path violation, ambiguous FIT member, or member safety limit. |
| `fit` | `fit_member_too_large` | `Original FIT member exceeds the 25 MB limit.` | Streaming `LimitedReader` reaches byte 25,000,001. |
| `fit` | `fit_parse_failed` | `Original FIT data could not be parsed.` | Strict `fitdecode` construction, CRC, or iteration failed. |
| `fit` | `chained_fit_unsupported` | `Chained FIT files are not supported.` | A second `FIT_FRAME_HEADER` was yielded; accumulated facts are discarded. |
| `fit` | `frame_limit_exceeded` | `Original FIT data exceeds the 200000-frame limit.` | More than 200,000 header/definition/data/CRC frames. |
| `fit` | `definition_field_limit_exceeded` | `Original FIT data exceeds the 128-field definition limit.` | A definition has more than 128 standard plus developer field definitions. |
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
  timeseries.py           ZIP preflight, bounded fitdecode stream, allowlist facts, sort, bin, reduce
  timeseries_service.py   strict validation, one provider call, stable envelope
  tools.py                FastMCP adapter and registration
```

`timeseries.py` has no Garmin client, environment lookup, logging of payloads,
or FastMCP dependency. It owns ZIP/stream/decoder safety and accepts bounded
archive bytes plus plain request values, returning plain minimal facts/outcomes.
`providers.py` owns only the one Garmin call, response type/25 MB archive-byte
cap, and provider failure sanitization. `timeseries_service.py` owns bounded
argument normalization, empty/error envelope creation, provider orchestration,
activity-global warning status, and serialization-ready result selection.
`tools.py` owns only strict adapter types, concise factual/privacy
documentation, delegation, and stable `json.dumps(..., indent=2)` output.
Package `__init__.py` exports the new service and retains the existing lazy
`configure`/`register_tools` pattern.

The implementation pins `fitdecode==0.11.0` in `pyproject.toml` and `uv.lock`
for this streaming parser. Existing `fitparse>=1.2.0` remains declared and is
used unchanged by the existing `activity_analysis.py` tool; it is not imported
by `timeseries.py`.

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
   with a `ToolError` before any provider/client read; a trimmed ASCII decimal
   activity ID is accepted; malformed direct service-call shapes instead return
   stable error envelopes. Exercise the 9007199254740991 activity-ID cap, the
   `MAX_FIT_ELAPSED_SECONDS = 4026531838` start cap, validation precedence,
   safe end arithmetic, and the pinned FastMCP behavior that ignores
   undeclared extra arguments (outside contract and never delegated/used).
2. The exact default one-second window and a coarse resolution; multiple
   source records in one one-second bin; output bin cap and aligned-array
   lengths for every metric array.
3. Half-open start/end boundaries, pagination cursor presence/absence, no
   duplicate or skipped records across pages, irregular whole-second
   timestamps, pauses/empty bins, observed median interval, and irregular-flag
   semantics. Prove an emitted cursor at the v1 elapsed maximum remains a valid
   next `start_seconds`, while an actual end beyond that maximum emits no cursor
   unless a later valid raw elapsed record makes it provably safe.
4. Stable sorting of out-of-order messages and deterministic duplicate
   timestamp aggregation for a given archive order; no interpolation,
   carry-forward values, or claim that archive reordering preserves reductions.
5. Heart-rate average/minimum/maximum, speed average, pace average/fastest/
   slowest, zero-only speed bins, missing fields, null arrays, and the exact
   rounding rules.
6. Finite/adversarial metric values, including Boolean, NaN, infinity, and
   out-of-range values; they become null without making an otherwise valid
   timestamped record malformed.
7. Malformed record-message discard/partial-success behavior, activity-global
   aggregate warning/count versus window-scoped sampling/availability, globally
   no usable timestamp error, and a valid activity with an empty requested
   window returning factual `success` and zero points.
8. Provider call budget: exactly one
   `download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)`
   after valid input, no caching, and a recording client that raises on every
   mutation, raw request, or non-download read.
9. Empty, wrong-type, oversized, malformed, raw/gzip fallback, ZIP64,
   multi-disk, EOCD/central/local-range-invalid, encrypted, unsupported
   compression, unsafe-path/symlink, too-many-entry, too-large-central-
   directory, multi-FIT, oversized declared FIT-member, and streamed
   25,000,001-byte-member payloads. Verify preflight occurs before `ZipFile`,
   non-FIT safe entries are not opened, and the selected member is streamed
   through a 65536-byte `LimitedReader` to strict `fitdecode`, never `zf.read`.
10. Strict `fitdecode==0.11.0` configuration: public streaming `FitReader`,
    `CrcCheck.RAISE`, `ErrorHandling.RAISE`, `keep_raw_chunks=False`, the
    raw-second/aware-UTC cross-check, fresh per-reader developer state, and no
    retained decoded frames/messages. Exercise numeric `FIT_FRAME_DATA` plus
    global message `20` gating (not a name); every listed standard
    definition-number/base-type/size tuple; wrong base/size rejection; and
    the direct-field/developer-field collision rule. Test developer fields
    with the same IDs, expanded component fields, enhanced speed `73`, and
    enhanced altitude `78` are excluded; test the sole exact compressed-
    timestamp special case and zero/multiple timestamp or optional-candidate
    policies. Exercise raw timestamp lower/upper/integer/sentinel boundaries.
    Test high non-record frame streams above 200,000, a record stream above
    100,000, standard-plus-developer definition fields above 128, and a
    second `FIT_FRAME_HEADER` chained stream; each is the specified fatal
    no-truncation outcome.
11. Exception/payload sanitization: nested serialized result scans find no
    secret, URL, header, request ID, raw exception text, raw FIT message, or
    raw payload value.
12. GPS privacy: fixtures containing latitude/longitude (and any other
    unlisted fields) prove the parser consumes frame bytes but neither selects
    nor retains those values. Include developer fields named `speed` and
    `altitude` that carry coordinate sentinels, proving they cannot cross the
    numeric direct-field boundary. A recursive serialized-output scan finds no
    GPS/coordinate/polyline keys or values.
13. Root configuration, registration beside `analyze_activity`, exact
    14-member profile/startup filtering, retained exclusion of
    `get_activity_fit_data`, `fitdecode==0.11.0` pin/lock while preserving the
    existing `fitparse` tool dependency, and documentation assertions for the
    pinned 0.3.10 ORIGINAL ZIP behavior, limits, paging, and tool-selection
    guidance.

## Response examples

The following are parseable contract examples. They show shape and semantics,
not a claim that a particular device supplies every metric.

### Successful populated page

This example's five source records can occur at elapsed seconds 0, 1, 2, 5,
and 6: its positive source deltas are 1, 1, 3, and 1, so `irregular` is
correctly `true` despite a 1.0-second median.

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
    "irregular": true
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
