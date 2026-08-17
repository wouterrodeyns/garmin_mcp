# AI sleep trend v1

## Purpose

`get_training_context` provides a compact current coaching snapshot, including
the latest available sleep duration and score. It intentionally does not fetch
or return a multi-night sleep history. An AI coach sometimes needs that history
to distinguish one poor night from a sustained pattern.

Add one explicit, read-only MCP tool:

```python
get_sleep_trend(days: int = 7)
```

The tool returns a bounded, normalized series of recent nightly sleep summaries
plus transparent request-level averages. Detailed sleep evidence therefore
costs an intentional tool call instead of making every training-context call
larger and more expensive.

This design takes inspiration from Taxuspt upstream PR #256 without copying its
90-night, silent-skip behavior.

## Product boundaries

This feature:

- belongs to the curated `ai_training` package;
- reads the pinned Garmin client directly;
- makes one sequential `get_sleep_data(date)` call per requested date;
- does not invoke another MCP tool internally;
- does not expose raw Garmin sleep DTOs;
- does not add or invoke any Garmin mutation;
- does not alter workout creation, activity analysis, wellness heart-rate, or
  training-context input contracts;
- does not infer sleep debt, readiness, recovery, causation, or coaching
  conclusions;
- does not calculate sleep-stage percentages; and
- does not return sleep start/end timestamps in v1.

Sleep timestamps are deliberately deferred. The pinned `garminconnect` client
documents that some China/UTC+8 accounts have returned local sleep timestamps
with the timezone offset applied twice. A trend of nightly totals does not need
that ambiguity.

## Architecture

```text
Pinned Garmin client: get_sleep_data(date)
        |
        | one sequential read per requested night
        v
ai_training provider seam
        |
        v
strict single-night normalizer
        |
        v
bounded trend aggregation service
        |
        v
get_sleep_trend
        |
        v
AI coach
```

Add `src/garmin_mcp/ai_training/sleep.py`. It owns:

- exact input validation;
- immutable normalized single-night facts;
- supported-field validation and conversion;
- stable empty-night construction;
- request-level aggregation;
- status, error, availability, and warning construction; and
- the internal deterministic `today` seam.

The existing `ai_training.providers.get_sleep(client, date)` remains the only
Garmin access point. If a provider-result wrapper is introduced, it must remain
inside `ai_training.providers` and preserve the one-read contract.

The existing training-context snapshot should reuse the new strict single-night
normalizer through a small adapter. Its public response remains unchanged:

```json
{
  "sleep": {
    "date": "2026-08-17",
    "duration_hours": 7.2,
    "score": 78,
    "score_qualifier": "FAIR"
  }
}
```

This avoids maintaining two interpretations of Garmin's sleep fields while
keeping the new trend service isolated from the larger training-context
aggregator.

## Input contract

The public MCP signature is exactly:

```python
get_sleep_trend(days: int = 7)
```

Rules:

- `days` must be an exact built-in integer, not a Boolean or coerced string;
- minimum: `1`;
- default: `7`;
- maximum: `30`;
- the fixed inclusive period ends on the MCP host's current local calendar
  date; and
- the period never shifts to replace a missing current or historical night.

The service has a keyword-only internal seam:

```python
get_sleep_trend_service(client, days=7, *, today: date | None = None)
```

The MCP tool never exposes `today`. When omitted, the service resolves the host
local calendar date once. An injected value must be an exact built-in `date`,
not a `datetime` or subclass; misuse is an internal `TypeError` rather than a
public validation error.

Dates are queried from oldest to newest. A seven-night request ending
`2026-08-17` reads `2026-08-11` through `2026-08-17` exactly once each.

## Supported Garmin field mapping

Only these verified fields cross the abstraction boundary:

| Garmin path | Public field | Conversion |
|---|---|---|
| `dailySleepDTO.calendarDate` | `date` provenance | Exact ISO date; if present it must equal the requested date |
| `dailySleepDTO.sleepTimeSeconds` | `duration_hours` | Seconds / 3600, one decimal |
| `dailySleepDTO.napTimeSeconds` | `nap_minutes` | Seconds / 60, one decimal |
| `dailySleepDTO.sleepScores.overall.value` | `score` | Numeric value |
| `dailySleepDTO.sleepScores.overall.qualifierKey` | `score_qualifier` | Trimmed bounded text |
| `dailySleepDTO.deepSleepSeconds` | `stages.deep_minutes` | Seconds / 60, one decimal |
| `dailySleepDTO.lightSleepSeconds` | `stages.light_minutes` | Seconds / 60, one decimal |
| `dailySleepDTO.remSleepSeconds` | `stages.rem_minutes` | Seconds / 60, one decimal |
| `dailySleepDTO.awakeSleepSeconds` | `stages.awake_minutes` | Seconds / 60, one decimal |
| `dailySleepDTO.restingHeartRate` or top-level `restingHeartRate` | `resting_hr_bpm` | Numeric value; accept either compatible Garmin shape |
| `dailySleepDTO.avgSleepStress` | `average_sleep_stress` | Numeric value |
| `dailySleepDTO.awakeCount` | `awake_count` | Integer count |
| `dailySleepDTO.restlessMomentsCount` | `restless_moments_count` | Integer count |
| top-level `avgOvernightHrv` | `overnight_hrv_ms` | Numeric value |
| `wellnessSpO2SleepSummaryDTO.calendarDate` | secondary date provenance | If present it must equal the requested date |
| `wellnessSpO2SleepSummaryDTO.averageSpo2` or `.averageSPO2` | `spo2.average_percent` | Numeric value; accept either compatible Garmin casing |
| `wellnessSpO2SleepSummaryDTO.lowestSpo2` or `.lowestSPO2` | `spo2.lowest_percent` | Numeric value; accept either compatible Garmin casing |

Unknown Garmin fields are ignored and never echoed.

Garmin currently returns different compatible response shapes across accounts.
For the same requested night, Forerunner 265 data was observed with resting heart
rate at the response root and sleep SpO2 under the all-caps `SPO2` keys, while
the original contract fixtures use the nested/lowercase-`o` variants. The
normalizer accepts both shapes without adding another Garmin request. If two
variants are simultaneously non-null, their values must agree; conflicting or
malformed variants make the complete date `invalid_provider_response`.

Missing supported fields become `null`; they do not make an otherwise usable
night invalid. If a supported field is present with a malformed type or unsafe
value, the complete date is classified as `invalid_provider_response` rather
than selectively trusting a partly malformed DTO.

All inspected containers must be exact built-in JSON containers before their
methods, length, iteration, equality, or truthiness are used. Strings are
bounded to 64 characters after requiring a bounded raw length. Numeric values
must be exact built-in integers or floats, never Booleans, and must be finite.
V1 product-safety ranges are:

- duration and stage seconds: `0..86400`;
- score, sleep stress, and SpO2 percentage: `0..100`;
- resting heart rate: `1..300` bpm;
- overnight HRV: `1..1000` ms; and
- counts: integer `0..10000`.

These are v1 safety limits, not claimed Garmin server limits.

## Stable response envelope

Every response uses this top-level order:

```text
status, error, period, availability, summary, nights, warnings
```

Example with an unsynced current night:

```json
{
  "status": "partial_success",
  "error": null,
  "period": {
    "days": 7,
    "start_date": "2026-08-11",
    "end_date": "2026-08-17"
  },
  "availability": {
    "2026-08-11": true,
    "2026-08-12": true,
    "2026-08-13": true,
    "2026-08-14": true,
    "2026-08-15": true,
    "2026-08-16": true,
    "2026-08-17": false
  },
  "summary": {
    "nights_requested": 7,
    "nights_available": 6,
    "averages": {
      "duration_hours": {"value": 7.2, "nights": 6},
      "score": {"value": 78.5, "nights": 6},
      "resting_hr_bpm": {"value": 45.2, "nights": 5},
      "overnight_hrv_ms": {"value": 91.4, "nights": 5},
      "spo2_percent": {"value": 96.1, "nights": 4}
    }
  },
  "nights": [
    {
      "date": "2026-08-11",
      "available": true,
      "duration_hours": 7.4,
      "nap_minutes": 0.0,
      "score": 82,
      "score_qualifier": "GOOD",
      "stages": {
        "deep_minutes": 88.0,
        "light_minutes": 251.0,
        "rem_minutes": 105.0,
        "awake_minutes": 22.0
      },
      "resting_hr_bpm": 44,
      "overnight_hrv_ms": 94,
      "average_sleep_stress": 14,
      "awake_count": 3,
      "restless_moments_count": 12,
      "spo2": {
        "average_percent": 96,
        "lowest_percent": 93
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
      "spo2": {
        "average_percent": null,
        "lowest_percent": null
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

The abbreviated example omits the other five available nightly records only
for readability. Production returns exactly one stable night object per
requested date.

Night objects and `availability` entries are chronological. Every nightly key
is always present. Missing numeric data is `null`, never zero. A night is
available when at least one supported normalized metric is present.

## Aggregate semantics

The service calculates averages only for:

- `duration_hours`;
- `score`;
- `resting_hr_bpm`;
- `overnight_hrv_ms`; and
- nightly average SpO2.

Every average is represented as `{value, nights}`. `nights` is the number of
available source values for that specific metric, not `nights_available` and
not `nights_requested`. With no source values, the stable result is
`{"value": null, "nights": 0}`.

The service retains raw validated source units internally, sums those raw
values first, divides by the per-metric count, converts units where necessary,
and rounds the final average to one decimal. It never averages already-rounded
nightly display values.

No slope, variance, consistency score, stage percentage, sleep debt, readiness,
or interpretation is derived.

## Missing data and status semantics

Missing sleep data is normal, especially before the watch has synchronized.
The service never shifts the date window to hide a gap.

Status is determined as follows:

| Condition | Status | Error |
|---|---|---|
| Invalid `days` | `error` | `invalid_days` |
| Client is absent | `error` | `client_unavailable` |
| All requested nights unavailable, failed, or invalid | `error` | `sleep_trend_unavailable` |
| At least one night available and at least one unavailable, failed, or invalid | `partial_success` | `null` |
| Every requested night available | `success` | `null` |

The fixed public errors are:

| Code | Message |
|---|---|
| `invalid_days` | `days must be an integer from 1 through 30.` |
| `client_unavailable` | `Garmin client is unavailable.` |
| `sleep_trend_unavailable` | `Sleep trend is unavailable for the requested period.` |

Per-date warnings are:

| Code | Message |
|---|---|
| `sleep_data_unavailable` | `Sleep data is unavailable for this date.` |
| `provider_unavailable` | `Sleep data could not be retrieved for this date.` |
| `invalid_provider_response` | `Sleep data returned an invalid response for this date.` |

Warnings have exactly `provider`, `date`, `code`, and `message`; `provider` is
always `sleep`. Raw responses, exception text, URLs, tokens, headers, request
IDs, and credentials never appear in errors or warnings.

A legitimately empty DTO produces `sleep_data_unavailable`. A supported field
with an unsafe type/value or a mismatched Garmin calendar date produces
`invalid_provider_response`. Expected pinned Garmin authentication, connection,
and rate-limit exceptions produce `provider_unavailable` for that date. The
service continues with later dates.

Exception handling is narrow:

- only expected external Garmin exceptions are normalized at the provider-call
  boundary;
- `AssertionError`, internal normalizer defects, and local aggregation defects
  propagate visibly during development and testing; and
- no broad exception handler surrounds trusted service logic.

## Read-only and request-budget guarantees

The path may access only `client.get_sleep_data(date)` through the existing
provider seam. It must never access raw `connectapi`, `garth`, `session`, HTTP
verbs, workout mutations, scheduling mutations, or credential operations.

The service performs exactly one sequential read for each requested date after
successful input/client validation. Therefore:

- default request: 7 reads;
- maximum request: 30 reads;
- no pagination;
- no retries;
- no previous-day fallback;
- no hidden replacement dates; and
- no parallel request burst.

## MCP and profile integration

`ai_training.tools` registers the async FastMCP adapter and delegates to the
service. The adapter returns compact JSON text and exposes only `days: int = 7`.

Add `get_sleep_trend` to `TOOL_PROFILES["ai-coach"]` in the same commit as tool
registration. The profile then contains exactly 16 tools. Default unfiltered
mode and explicit allowlist/denylist precedence remain unchanged.

The description must tell the AI:

- the tool is read-only and detailed evidence is fetched explicitly;
- the period is fixed, recent, inclusive, and ends today;
- today may be unavailable until watch synchronization;
- missing dates remain visible and are not replaced;
- each date costs one Garmin read, with a 30-night maximum;
- averages state their actual per-metric denominator;
- availability varies by device/account/sync state; and
- the result does not establish causation, readiness, recovery, or a training
  recommendation by itself.

## Testing

Normal tests require no Garmin account. Add unit and mocked FastMCP integration
coverage for at least:

1. default seven-night period and chronological call order;
2. maximum 30-night period and exactly 30 reads;
3. exact `days` validation, including Boolean, string, zero, negative, and 31;
4. invalid requests and missing client make zero Garmin reads;
5. deterministic exact-date `today` seam and rejected internal misuse;
6. complete normalization of every supported field;
7. every optional supported field missing and represented as `null`;
8. empty current night retained as a visible gap without shifting the period;
9. mismatched Garmin calendar dates;
10. malformed nested containers and supported scalars;
11. non-finite, out-of-range, and oversized values;
12. exact built-in container enforcement using hostile subclasses whose
    protocols raise if invoked;
13. mixed complete, empty, failed, and malformed nights;
14. all-night unavailability;
15. provider exception sanitization and later-night continuation;
16. internal normalizer and aggregation defects remain visible;
17. per-metric aggregate denominators;
18. raw-first sum and final one-decimal rounding using values where
    round-before-sum would differ;
19. stable top-level and nightly key order;
20. fixed warning/error vocabulary and absence of private sentinels;
21. real FastMCP omitted/default and explicit `days` calls;
22. compact JSON return shape;
23. read-only client allowlist plus actively invoked traps for mutation and raw
    HTTP access;
24. exact 16-tool `ai-coach` profile registration;
25. existing `get_training_context` sleep output remains unchanged while using
    the shared normalizer;
26. documentation-pinning tests; and
27. the complete offline suite with `uv run pytest -m "not e2e"`.

## Documentation

Add `docs/ai-sleep-trend.md` and update the README/profile table plus
`docs/ai-training.md`. Document:

- when to call `get_sleep_trend` after `get_training_context`;
- exact metrics and optionality;
- fixed recent-date behavior;
- current-day sync gaps;
- request cost and maximum;
- aggregate denominator semantics;
- status, warnings, and missing-data behavior;
- absence of timestamps and the Garmin China timestamp caveat;
- read-only guarantees; and
- interpretation guardrails.

Example workflow:

```text
User: My sleep has felt poor this week. Is it a one-off or a pattern?

Claude:
  -> get_training_context(days=14)
  -> get_sleep_trend(days=7)
  -> distinguishes available Garmin facts from missing nights
  -> discusses the observed pattern without inventing readiness or causation
```

## Upstream compatibility

Custom behavior stays in `ai_training`. The provider continues to use the
pinned Garmin client's public `get_sleep_data(date)` method. Changes to
upstream-oriented `health_wellness.py`, authentication, generic Garmin setup,
and transport code are out of scope.

The existing training-context adapter may import the shared normalizer, but its
public response and provider schedule must remain unchanged.

## Deferred

V1 deliberately defers:

- exact historical start/end-date arguments;
- windows ending on a caller-selected historical date;
- more than 30 nights;
- parallel provider calls;
- retries or rate-limit backoff;
- sleep start/end timestamps;
- raw sleep-stage time series;
- stage percentages;
- trend slopes, variance, sleep consistency, sleep debt, or readiness scores;
- coaching recommendations generated by the server; and
- any Garmin write capability.

These can be reconsidered only with a separate evidence-backed design.
