# AI Wellness Heart-Rate V1 Design

## Goal

Add one bounded, read-only AI-facing tool for Garmin's all-day wellness heart
rate:

```python
get_wellness_heart_rate(
    start_date,
    end_date=None,
    resolution="raw",
    start_time=None,
    end_time=None,
)
```

The tool gives an AI coach detailed heart-rate evidence only after an explicit
decision to fetch it. It does not expand `get_training_context`, expose a raw
Garmin DTO, or mix the wellness series with FIT activity heart rate.

## Product rationale

The compact `get_training_context` tool is called at the start of coaching
interactions. Embedding hundreds of detailed samples there would make every
conversation pay the token and interpretation cost even when the evidence is
irrelevant. Detailed evidence belongs behind a separate call, following the
same pattern as `analyze_activity` and `get_activity_timeseries`.

The upstream-oriented `health_wellness` module already registers
`get_heart_rates(date)`, but `GARMIN_TOOL_PROFILE=ai-coach` intentionally does
not expose it. That broad tool serializes the complete Garmin response without
normalizing or validating its fields and supports one date per call. V1 keeps
that compatibility tool unchanged and adds a narrow fork-owned abstraction.

## Verified dependency and payload behavior

The pinned `garminconnect==0.3.10` client provides:

```python
Garmin.get_heart_rates(cdate: str) -> dict[str, Any]
Garmin.get_rhr_day(cdate: str) -> dict[str, Any]
```

`get_rhr_day` accepts one date, not a start/end range. V1 does not call it:
`get_heart_rates` already returns Garmin's daily resting, minimum, maximum, and
seven-day-average resting-heart-rate fields with the detailed samples.

The sample field is `heartRateValues`, a list whose entries are expected to be
`[timestamp_ms, bpm]`. Garmin may use `null` for a missing bpm. Useful daily
time provenance is supplied through `calendarDate`, `startTimestampGMT`,
`endTimestampGMT`, `startTimestampLocal`, and `endTimestampLocal`.

A read-only local metadata probe on 2026-08-14 inspected counts and timestamp
deltas without printing heart-rate values. Three complete days, including a
day containing a run, returned 713, 716, and 720 source points. Their median
positive interval was 120 seconds; the run day did not switch the wellness
endpoint to one-second samples. Two days contained larger timestamp gaps and
some explicit null bpm values. This evidence supports a one-day raw default,
but it does not establish uniform cadence for every device, account, or date.

## Non-negotiable interpretation guardrails

The tool description, response metadata, and documentation must state:

- wellness sample spacing can be irregular or missing;
- sample count multiplied by an assumed cadence is not duration;
- the series does not establish heart-rate-zone duration;
- the wellness endpoint is distinct from FIT activity records and must not be
  assumed to match an activity's sensor samples, smoothing, or zones;
- a gap proves only that the returned wellness series has no valid measurement
  in that observed interval; it does not prove watch removal, charging, sleep,
  illness, exercise, or another cause;
- binned means/minima/maxima describe only the samples Garmin returned in that
  bin and do not establish continuous coverage.

The service never calculates time in zone, time above a threshold,
cardiovascular drift, recovery state, stress, or coaching conclusions.

## Architecture

Keep the feature inside the existing fork-owned `ai_training` package:

```text
Garmin.get_heart_rates(date)
        ↓
ai_training provider wrapper
        ↓
strict payload validation + normalization
        ↓
daily summary / raw projection / time bins
        ↓
get_wellness_heart_rate
        ↓
AI coach
```

Suggested responsibilities:

- `ai_training/providers.py`: add a small read-only daily wellness-HR wrapper
  returning the existing `ProviderResult` contract.
- `ai_training/heart_rate.py`: validate arguments and payloads, normalize time
  provenance, project summaries, reduce bins, detect factual gaps, apply bounds,
  and aggregate per-date status.
- `ai_training/tools.py`: register the new FastMCP tool beside
  `get_training_context` using the package's existing configured client.

Do not call an existing MCP tool internally. Do not modify the broad
`health_wellness.get_heart_rates` tool. Do not add a second Garmin client.

## MCP argument contract

```python
async def get_wellness_heart_rate(
    start_date: str,
    end_date: str | None = None,
    resolution: Literal["daily", "raw", "5m", "15m", "30m", "60m"] = "raw",
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
```

### Dates

- Dates use strict `YYYY-MM-DD` syntax and real calendar validation.
- When `end_date` is omitted, it equals `start_date`.
- `start_date` must be on or before `end_date`.
- The inclusive range may contain at most seven dates.
- Future dates are not rejected; Garmin may legitimately return no data.

### Resolution

- `daily`: daily Garmin summary fields only; no samples or bins.
- `raw`: every validated source entry in the selected window, including entries
  whose bpm is null. Raw mode requires one date.
- `5m`, `15m`, `30m`, `60m`: fixed wall-clock bins using Garmin-local time when
  an unambiguous daily offset is available.
- The resolution string must match one of the six literals exactly.

### Optional daily time window

- `start_time` and `end_time` must be supplied together or both omitted.
- Values use strict 24-hour `HH:MM` syntax.
- The interval is start-inclusive and end-exclusive.
- `start_time` must be earlier than `end_time`; cross-midnight windows are not
  supported in V1.
- The same daily wall-clock window applies to every requested date.
- Omitting both selects the complete Garmin calendar day.
- `daily` resolution rejects a time window because its summary fields describe
  Garmin's complete calendar day.
- Window filtering requires unambiguous Garmin local-time provenance. If local
  time cannot be established, the affected date is unavailable rather than
  silently applying the window in UTC.

## Bounds

Constants are exported from the feature module and pinned by tests:

```text
MAX_DAYS = 7
MAX_SOURCE_POINTS_PER_DAY = 10_000
MAX_RAW_POINTS = 1_000
MAX_RETURNED_BINS = 1_000
MAX_SERIALIZED_BYTES = 262_144
GAP_THRESHOLD_SECONDS = 300
```

Rules:

- Reject invalid arguments before any Garmin call.
- Reject a binned request before any Garmin call when its theoretical number
  of daily wall-clock bins exceeds 1,000.
- Refuse a provider payload containing more than 10,000 source entries before
  iterating those entries.
- Raw mode never truncates. If the selected window contains more than 1,000
  validated source entries, return `raw_response_too_large` and instruct the
  caller to narrow the time window or choose a binned mode.
- Binned mode never silently truncates.
- Before returning success, serialize the normalized envelope compactly and
  require it to be at most 262,144 UTF-8 bytes. If it exceeds the cap, return a
  fixed `response_too_large` error recommending a narrower window or coarser
  resolution.

These are product safety limits, not claimed Garmin API limits.

## Stable response envelope

All outcomes return the same top-level keys:

```json
{
  "status": "success",
  "error": null,
  "period": {
    "start_date": "2026-08-10",
    "end_date": "2026-08-10",
    "start_time": null,
    "end_time": null
  },
  "resolution": "raw",
  "availability": {
    "2026-08-10": true
  },
  "days": [],
  "warnings": []
}
```

`status` is one of `success`, `partial_success`, or `error`. `error` is either
null or a fixed structured object:

```json
{
  "code": "invalid_date_range",
  "message": "start_date must be on or before end_date."
}
```

Warnings are structured and sanitized:

```json
{
  "provider": "wellness_heart_rate",
  "date": "2026-08-11",
  "code": "provider_unavailable",
  "message": "Wellness heart-rate data is unavailable for this date."
}
```

No exception text, request IDs, URLs, headers, tokens, profile IDs, or discarded
raw payload content crosses the MCP boundary.

## Per-day object

Every requested date receives one entry in date order:

```json
{
  "date": "2026-08-10",
  "available": true,
  "summary": {
    "resting_hr_bpm": 45,
    "min_hr_bpm": 41,
    "max_hr_bpm": 166,
    "seven_day_avg_resting_hr_bpm": 46
  },
  "time_provenance": {
    "local_offset_minutes": 120,
    "local_time_available": true
  },
  "sampling": {
    "source_points": 713,
    "valid_bpm_points": 711,
    "null_bpm_points": 2,
    "returned_points": 713,
    "observed_median_interval_seconds": 120,
    "duration_from_sample_count_valid": false
  },
  "points": [],
  "gaps": []
}
```

Daily summary values come only from Garmin's `restingHeartRate`, `minHeartRate`,
`maxHeartRate`, and `lastSevenDaysAvgRestingHeartRate` fields. Missing values are
null, never zero, and are not reconstructed from samples.

`points` and `gaps` are always present. In `daily` mode they are empty and
`returned_points` is zero. Daily mode validates the exact sample-list container
and its length bound but does not inspect individual sample entries that it
will not return. Its `valid_bpm_points`, `null_bpm_points`, and
`observed_median_interval_seconds` are null.

Availability is mode-aware:

- `daily` is available when at least one Garmin summary scalar is valid;
- `raw` is available when at least one selected source entry is valid, even if
  its bpm is null, or when at least one summary scalar is valid;
- a binned day is available when at least one valid bpm contributes to a bin or
  at least one summary scalar is valid.

A legitimate null/empty day with no usable content remains `available: false`
without inventing a provider failure.

## Timestamp normalization

Each validated source timestamp is epoch milliseconds. The service always
produces exact UTC ISO 8601 with `Z`.

For local time, parse Garmin's local/GMT daily bounds and calculate the UTC
offset they establish. If the start and end bounds establish the same offset,
emit local ISO 8601 timestamps with that numeric offset, for example:

```text
2026-08-10T19:02:00+02:00
```

If bounds are missing, malformed, or imply an offset transition during the
day, do not guess. Set local timestamps to null, retain UTC timestamps, set
`local_time_available: false`, and emit one `local_time_unavailable` warning
for that date. In unwindowed `raw` and `daily` modes, this warning alone does
not make the result partial. Binned modes and explicit time windows require
local wall-clock boundaries, so the affected date is unavailable instead.

## Raw points

Raw mode returns:

```json
{
  "time_local": "2026-08-10T19:02:00+02:00",
  "time_utc": "2026-08-10T17:02:00Z",
  "bpm": 138
}
```

An explicit Garmin null bpm is retained as `"bpm": null`. Timestamps must be
finite integers within Python's supported datetime range. Entries with invalid
shape or invalid timestamp/bpm types make that provider date an
`invalid_provider_response`; they are not partially copied.

Valid bpm values are finite integers from 1 through 300. Booleans, strings,
floats, zero, negative values, and values above 300 are invalid provider data.

## Binned points

Binned modes return only bins containing at least one valid bpm sample:

```json
{
  "start_time_local": "2026-08-10T19:00:00+02:00",
  "end_time_local": "2026-08-10T19:15:00+02:00",
  "start_time_utc": "2026-08-10T17:00:00Z",
  "end_time_utc": "2026-08-10T17:15:00Z",
  "min_bpm": 126,
  "mean_bpm": 139.4,
  "max_bpm": 151,
  "sample_count": 7
}
```

- Group by Garmin-local wall-clock boundaries.
- Sum raw bpm values first, divide by count, then round the final mean to one
  decimal using Python's normal `round` behavior.
- Min and max are exact observed sample extrema.
- Null bpm samples do not contribute to statistics.
- `sample_count` is the number of valid samples in the bin, not minutes or
  coverage.
- Do not emit a `coverage` field. Calculating coverage would require assuming
  an expected cadence that Garmin does not guarantee in this contract.

## Gap reporting

`gaps` is a compact list of internal observed intervals containing no valid bpm
measurement for at least 300 seconds:

```json
{
  "start_time_local": "2026-08-10T15:00:00+02:00",
  "end_time_local": "2026-08-10T15:12:00+02:00",
  "start_time_utc": "2026-08-10T13:00:00Z",
  "end_time_utc": "2026-08-10T13:12:00Z",
  "elapsed_minutes": 12.0
}
```

Build gaps from adjacent valid bpm measurements after window filtering. Do not
invent leading or trailing gaps from the requested window boundaries, because
today's future portion and partial syncs are not evidence of missing wear.
Round elapsed minutes to one decimal. Gap entries describe the elapsed interval
between valid measurements; they do not assert the cause or continuous device
state.

Raw null entries remain visible even when an isolated null is too short to
appear in `gaps`.

## Status and missing-data semantics

Provider calls are sequential and date-ordered, with at most seven reads.

| Situation | Status | Behavior |
|---|---|---|
| All requested dates return valid data | `success` | Return normalized days |
| Some dates fail or are malformed and at least one date is valid | `partial_success` | Keep valid dates and add one fixed warning per failed date |
| Every attempted provider date fails or is malformed | `error` | `wellness_heart_rate_unavailable` |
| Garmin legitimately returns no samples/summary for a date | Does not itself change status | Date remains unavailable with null summary and no fabricated zero |
| Local time cannot be established in unwindowed `raw` or `daily` mode | Does not itself change status | Return UTC/null local times or the daily summary, plus one warning |
| Local time cannot be established for bins or an explicit window | `partial_success` when another date remains useful; otherwise `error` | Mark the affected date unavailable instead of binning/filtering in UTC |
| Invalid arguments or projected bounds | `error` | Zero Garmin calls |
| Raw or serialized response exceeds a cap | `error` | No partial/truncated series returned |

Warnings do not automatically imply `partial_success`; only a failed or
malformed requested date does. A local-time warning with usable UTC data remains
`success`.

## Error and warning vocabulary

V1 uses fixed codes only:

Errors:

- `invalid_start_date`
- `invalid_end_date`
- `invalid_date_range`
- `date_range_too_large`
- `invalid_resolution`
- `raw_requires_single_date`
- `invalid_time_window`
- `request_too_large`
- `client_unavailable`
- `wellness_heart_rate_unavailable`
- `raw_response_too_large`
- `response_too_large`

Warnings:

- `provider_unavailable`
- `invalid_provider_response`
- `local_time_unavailable`

The pinned client does not reliably preserve enough structured status
information to distinguish rate limits, timeouts, and server failures without
parsing exception strings. V1 therefore uses `provider_unavailable`, matching
the established `ai_training` policy.

## Read-only guarantee

The entire path may call only `client.get_heart_rates(date)`. It must never call:

- `get_rhr_day`;
- an activity endpoint;
- a raw request method such as `connectapi`, `post`, `put`, or `delete`;
- any workout, schedule, upload, update, unschedule, or delete method;
- any credential-management function.

Tests use an allowlist recording client whose forbidden methods record the
attempt before raising, so a forbidden call cannot be swallowed unnoticed.

## Security and malformed payloads

- Accept only exact built-in JSON container types at untrusted response
  boundaries; reject dict/list subclasses before invoking their protocols.
- Validate roots, daily scalar fields, and source-list type/length before
  normalization. For raw and binned modes, validate every selected sample
  shape, timestamp, and bpm before projection. Daily mode deliberately does not
  inspect unused sample entries.
- Do not catch exceptions raised by trusted local reducers or serializers as if
  they were provider failures. Provider invocation is the only broad external
  exception boundary.
- Do not echo provider payloads or exception strings.
- Never write heart-rate data to disk, logs, caches, or repository fixtures.
- Tests use synthetic values only. The metadata probe described above is not
  committed as user data.

## AI-coach profile

Add only `get_wellness_heart_rate` to `TOOL_PROFILES["ai-coach"]`, producing an
exact 15-tool profile. Keep the broad upstream `get_heart_rates` and
`get_heart_rates_summary` tools outside the profile. Preserve explicit
allowlist-over-profile and denylist-subtraction precedence.

## Documentation

Create `docs/ai-wellness-heart-rate.md` and update the current README/setup and
AI guides where the exact profile count/list or coaching data flow is stated.

Documentation must cover:

- explicit-fetch philosophy;
- argument modes and bounds;
- raw, daily, and binned examples;
- local/UTC time provenance;
- null samples and factual gaps;
- partial date availability;
- the interpretation guardrails verbatim in substance;
- distinction from `get_activity_timeseries` and activity zones;
- read-only behavior;
- device/account/sync variability.

Add documentation-pinning tests that compare the literal 15-tool list to
`TOOL_PROFILES` and reject stale 14-tool claims in current documentation. Do not
modify historical specs or plans.

## Testing

Normal tests make no live Garmin requests. Required coverage includes:

### Arguments and bounds

- omitted end date;
- strict date validation and ordering;
- exact seven-day boundary and eight-day rejection;
- all six resolution literals;
- raw multi-date rejection;
- valid and malformed time windows;
- cross-midnight rejection;
- projected bin cap before provider access;
- exact raw/source/serialized boundaries.

### Payload normalization

- complete daily payload;
- legitimate empty/null sample collection;
- null bpm preservation;
- malformed root, daily summary, sample list, sample tuple, timestamp, and bpm;
- exact built-in container enforcement;
- finite/range checks;
- Garmin-provided summary values remain source facts and missing values remain
  null;
- timestamp ordering and deterministic sorting without mutating input.

### Time and reduction

- verified GMT/local offset conversion;
- unavailable local provenance with UTC retention;
- offset-transition detection;
- window filtering boundaries;
- raw projection;
- every bin resolution;
- sum-before-round means;
- min/max/sample count;
- no coverage field;
- gap threshold below, at, and above 300 seconds;
- no leading/trailing invented gaps;
- non-uniform interval metadata and explicit duration-inference prohibition.

### Status and safety

- complete success;
- one date unavailable while later dates continue;
- malformed date response while later dates continue;
- all providers unavailable;
- legitimate all-empty range;
- local-time warning does not force partial status;
- sanitized warnings and errors with secret sentinels absent from serialized
  output;
- provider exception isolation versus local-helper exception propagation;
- read-only allowlist and actively invoked mutation/raw-request traps.

### MCP and documentation

- exact FastMCP argument schema/defaults;
- compact JSON return delegation;
- tool metadata pins all interpretation guardrails;
- package configure/register seam remains lazy;
- exact 15-tool profile registration;
- profile/filter precedence remains unchanged;
- all current documentation examples match the service schema.

After focused tests, run:

```bash
pytest -m "not e2e"
uv lock --check
uv build
git diff --check
```

No live Garmin account is required for acceptance.

## Files

Expected implementation scope:

- `src/garmin_mcp/ai_training/providers.py`
- `src/garmin_mcp/ai_training/heart_rate.py` (new)
- `src/garmin_mcp/ai_training/tools.py`
- `src/garmin_mcp/ai_training/__init__.py`
- `src/garmin_mcp/__init__.py`
- focused unit/integration tests under `tests/unit/ai_training/` and
  `tests/integration/`
- current documentation and documentation-pinning tests

Keep changes to upstream-oriented modules at zero for this feature.

## Deferred

- Cross-midnight wall-clock windows.
- More than seven dates per call.
- Pagination of raw samples; V1 asks the caller to narrow the window or bin.
- Time-in-zone, threshold duration, drift, sleep, stress, or recovery inference.
- Merging wellness and activity FIT series.
- Caching or persistence.
- Separate `get_rhr_day` exposure.

## Acceptance criteria

- Claude can explicitly fetch one exact Garmin wellness-HR day or a compact
  summary/binned view across up to seven dates.
- Raw and binned results are bounded and never silently truncated.
- Output contains readable local timestamps when Garmin provides unambiguous
  provenance and exact UTC timestamps otherwise.
- Missing samples and internal observed gaps are visible without assigning a
  cause.
- The response and tool description explicitly forbid invalid duration, zone,
  coverage, sensor-equivalence, and coaching inferences.
- Per-date failures degrade to a useful partial result when possible.
- The path is strictly read-only and never exposes the Garmin DTO.
- The `ai-coach` profile contains exactly 15 deliberate tools.
- Focused tests, the full offline suite, lock verification, package build, and
  diff checks pass.
