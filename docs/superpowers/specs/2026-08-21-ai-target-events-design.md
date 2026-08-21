# AI target events v1

## Purpose

The curated AI coach can inspect recent training, current recovery, detailed
sleep and wellness evidence, completed activities, and the next seven days of
scheduled workouts. It cannot currently discover the event an athlete is
preparing for. Without that target, an otherwise well-informed recommendation
can miss the required progression, taper, or event-specific preparation.

Add one explicit, read-only MCP tool:

```python
get_target_events(days: int = 180)
```

The tool returns a bounded, normalized list of Garmin calendar events beginning
on the MCP host's current local date. It provides factual target context for an
AI coach without interpreting the event, changing the compact
`get_training_context` contract, or adding calendar latency to every coaching
request.

This design adapts the calendar discovery demonstrated by Taxuspt upstream PR
#258. The fork owns a stricter service boundary, stable response envelope,
request budget, privacy limits, and partial-failure semantics.

## Product boundaries

This feature:

- is an explicit evidence read, separate from `get_training_context`;
- reads only Garmin calendar entries whose exact `itemType` is `event`;
- makes one sequential calendar request per intersecting calendar month;
- exposes normalized coaching facts, not raw calendar payloads;
- does not create, update, delete, subscribe to, or otherwise mutate events;
- does not expose event URLs, UUIDs, provider request data, or GPX data;
- does not infer race priority, training phase, taper dates, readiness, or a
  coaching recommendation;
- returns at most 100 events, preserving the chronologically nearest events;
- does not link an event to a Garmin course or training plan;
- does not add events to the default training-context response; and
- adds no dependency.

Event titles and locations are untrusted user/provider-authored labels. The
tool returns them only as bounded JSON string values. They are never treated as
instructions and never appear in server-generated errors or warnings.

## Architecture

```text
Pinned Garmin client: get_scheduled_workouts(year, month)
        |
        | one sequential read per intersecting month
        v
ai_events provider seam
        |
        v
strict event normalizer
        |
        v
bounded period service
        |
        v
get_target_events(days=180)
        |
        v
AI coach
```

Add an isolated package:

```text
src/garmin_mcp/ai_events/
    __init__.py
    providers.py
    service.py
    tools.py
```

Responsibilities:

- `providers.py` owns the only Garmin calendar call and converts each month
  into a provider result without leaking exception text.
- `service.py` owns input validation, period/month calculation, strict
  normalization, clipping, deduplication, sorting, status, errors, availability,
  and warnings.
- `tools.py` owns client configuration, FastMCP registration, the public
  docstring, and JSON serialization.
- `__init__.py` exposes only `configure` and `register_tools`.

The package does not invoke another MCP tool. Existing upstream-oriented
calendar and workout modules remain unchanged except for top-level import,
configuration, registration, and profile wiring in `garmin_mcp.__init__`.

## Public input contract

The public signature is exactly:

```python
get_target_events(days: StrictInt = 180) -> str
```

Rules:

- `days` must be an exact integer accepted by Pydantic `StrictInt`; Booleans,
  strings, and floats are rejected before the service;
- minimum: `1`;
- default: `180`;
- maximum: `366`;
- the period begins on the MCP host's current local calendar date;
- the inclusive end is `start_date + days - 1`; and
- the service resolves the host date once per request.

The deterministic internal seam is:

```python
get_target_events_service(client, days=180, *, today: date | None = None)
```

The MCP tool never exposes `today`. An injected `today` must be an exact
built-in `date`, not a `datetime` or subclass. Invalid internal injection raises
`TypeError`; it is not represented as a public input error.

At most 13 distinct calendar months can intersect a valid request. Months are
read in chronological order. There are no retries at this layer; the pinned
Garmin client may perform its own transport retries.

## Provider contract

`providers.py` defines an immutable result containing:

- the requested `YYYY-MM` month key;
- `data`: an immutable sequence of raw calendar entries when readable;
- `failed`: whether the Garmin call raised; and
- `invalid`: whether a non-empty response violated the expected month shape.

The provider calls:

```python
client.get_scheduled_workouts(year, month)
```

with a one-indexed month, matching the pinned `garminconnect` public method. It
accepts a documented empty response as an available empty month. A non-empty
mapping must contain `calendarItems` as a list or explicit `null`; `null` means
an available empty month. Other non-empty roots or non-list `calendarItems` are
invalid.

Provider exceptions are caught at this boundary. Results never include the
exception object, exception text, URL, headers, request identifiers, tokens, or
raw response fragments.

## Supported event mapping

Only entries with exact string `itemType == "event"` are candidates. Other
calendar items, including workouts, weigh-ins, goals, and adaptive workouts,
are ignored without warnings.

| Garmin path | Public field | Rule |
|---|---|---|
| `title` | `title` | Required non-empty string; trim and cap at 256 code points |
| `date` | `date` | Required exact ISO calendar date; valid dates outside the requested period are clipped without warning |
| derived | `days_until` | Integer difference between event date and period start |
| `isRace` | `is_race` | Exact Boolean, otherwise `null` |
| `primaryEvent` | `primary_event` | Exact Boolean, otherwise `null` |
| `completionTarget.value` | `distance_km` | Used only when `unitType == "distance"`; finite non-negative meters / 1000, rounded to three decimals |
| `eventTimeLocal.startTimeHhMm` | `start_time_local` | Valid exact `HH:MM`, otherwise `null` |
| `eventTimeLocal.timeZoneId` | `time_zone` | Trimmed string capped at 128 code points, otherwise `null` |
| `location` | `location` | Trimmed non-empty string capped at 256 code points, otherwise `null` |

`bool` is never accepted as a number. Numeric values must be built-in finite
`int` or `float` values and may not be subclasses. An invalid optional field is
projected as `null` and marks that source month malformed. Invalid required
fields drop the event and mark the month malformed. One malformed month produces
at most one warning, regardless of its number of invalid fields or entries.

The implementation may inspect `shareableEventUuid` solely as an internal
deduplication key when it is a bounded non-empty string. It is never returned.
When no usable UUID exists, the fallback key is the normalized tuple of date,
title, local start time, distance, and location. First occurrence wins.

Events are clipped to the exact requested period after validation and sorted by
`date`, then case-folded `title`, then original `title`. The output does not
claim Garmin priority from ordering; `primary_event` remains the only provider
priority fact.

## Response contract

Every service result has exactly these top-level keys:

```json
{
  "status": "success",
  "error": null,
  "period": {
    "days": 180,
    "start_date": "2026-08-21",
    "end_date": "2027-02-16"
  },
  "availability": {
    "events": true
  },
  "events_truncated": false,
  "events": [
    {
      "title": "Spring Half Marathon",
      "date": "2026-10-18",
      "days_until": 58,
      "is_race": true,
      "primary_event": true,
      "distance_km": 21.097,
      "start_time_local": "09:00",
      "time_zone": "Europe/Brussels",
      "location": "Brussels"
    }
  ],
  "warnings": []
}
```

There is no redundant `count`; consumers can use `len(events)`. A valid empty
calendar returns an empty event list with availability true. After validating,
deduplicating, and sorting all candidates, the service returns the first 100.
`events_truncated` is true when additional valid events were omitted.

Public errors use only fixed codes and messages:

| Code | Meaning |
|---|---|
| `invalid_days` | `days` is outside 1 through 366 at the service boundary |
| `client_unavailable` | no configured Garmin client is available |
| `target_events_unavailable` | every requested month failed or was structurally invalid |

Month warnings have exactly:

```json
{
  "provider": "calendar_events",
  "month": "2026-10",
  "code": "provider_unavailable",
  "message": "Target-event calendar data is unavailable for this month."
}
```

The other month warning code is `invalid_provider_response`, with the fixed
message `Target-event calendar data returned an invalid response for this
month.` The month is service-derived, not copied from provider data.

Truncation adds one warning without a `month`:

```json
{
  "provider": "calendar_events",
  "code": "events_truncated",
  "message": "Additional target events were omitted after the 100-event output limit."
}
```

Truncation is informational and does not by itself change `success` to
`partial_success`. `events_truncated` is false on every error response.

Status and availability rules:

| Situation | Status | `availability.events` | Events |
|---|---|---:|---|
| all months readable and all candidate events valid | `success` | `true` | normalized events, possibly empty |
| at least one month readable and at least one month failed, invalid, or contained malformed event candidates | `partial_success` | `true` | all usable normalized events |
| every month failed or was structurally invalid | `error` | `false` | empty |
| invalid `days` or missing client | `error` | `false` | empty |

A structurally readable month with only malformed event candidates is still a
readable calendar month. It therefore keeps availability true but produces
`partial_success`, an empty event list if nothing else is valid, and one
`invalid_provider_response` warning for that month.

Warnings are ordered chronologically by month. Provider failures do not stop
later reads. A truncation warning, when present, follows all month warnings.
This preserves useful target context while making gaps explicit.

## Tool registration and profile

`garmin_mcp.__init__` will:

- import `ai_events` next to the other curated AI packages;
- configure it with the existing `_GarminProxy` client;
- register its tools through the existing `_ToolFilter`; and
- add `get_target_events` to `TOOL_PROFILES["ai-coach"]` immediately after
  `get_training_context`.

The default curated profile therefore grows from 16 to exactly 17 tools. The
explicit `upstream-full` profile also registers the tool because it registers
the complete server surface. Existing allowlist/denylist precedence remains
unchanged.

## Security and privacy

- This is a read-only path and exposes no credential-management operation.
- The public response is assembled from a fixed allowlist of fields.
- Raw Garmin payloads and exception strings are never serialized.
- Returned strings have explicit length bounds and are JSON-escaped by the tool
  boundary.
- URLs, UUIDs, coordinates, headers, tokens, and GPX data are excluded.
- Calendar labels are documented as untrusted facts, not executable guidance.
- The service has a fixed request ceiling, a 100-event output ceiling, and
  fixed event-field bounds.
- The normalizer does not mutate provider dictionaries.

## Documentation

Add `docs/ai-target-events.md` and link it from the README's designed workflow
and documentation sections. The guide must state:

- the exact signature, default, limits, and date semantics;
- that the operation is an explicit read separate from training context;
- the request budget and possible pinned-client retries;
- the exact response fields, status, availability, errors, and warnings;
- the 100-event limit and explicit `events_truncated` signal;
- that `primary_event` is Garmin-provided and no other priority is inferred;
- that missing events do not prove the athlete has no goal outside Garmin;
- that titles and locations are untrusted labels;
- that the tool does not make a coaching recommendation; and
- that writes still require the existing confirmation flow.

README examples should show `get_training_context` for current state followed by
`get_target_events` when the user asks for event-aware planning. Existing tool
roles and boundaries remain intact.

## Verification strategy

### Pure unit tests

Cover:

1. exact `days` bounds, Boolean rejection at the tool schema, period arithmetic,
   leap years, and injected-date misuse;
2. chronological month enumeration with year boundaries and the 13-request
   maximum;
3. exact event filtering, period clipping, deterministic sorting, UUID and
   fallback deduplication, the 100-event limit, and nearest-event retention;
4. every supported field mapping and nullable optional-field behavior;
5. non-finite, negative, Boolean, subclassed, oversized, malformed-date, and
   malformed-time inputs;
6. provider dictionaries remaining unchanged;
7. warning coalescing to at most one per month and stable warning order;
8. valid empty, mixed success, malformed-event, partial-provider, all-provider,
   invalid-input, and missing-client status matrices; and
9. output sanitization against raw exceptions, URLs, tokens, headers, request
   identifiers, UUIDs, and oversized strings.

### Provider and integration tests

Cover:

- exact `get_scheduled_workouts(year, month)` arguments and sequential order;
- empty, `calendarItems: null`, valid list, wrong root, wrong collection, and
  raised-provider responses;
- FastMCP tool schema and JSON serialization;
- configured client isolation;
- exact 17-tool `ai-coach` profile and unchanged filter precedence;
- explicit `upstream-full` registration; and
- no calendar calls after invalid service input.

### Documentation and gates

- Parse every JSON example in the new guide.
- Pin README/profile claims and prevent stale 16-tool text.
- Run focused tests during development.
- Run `uv run ruff check src tests`.
- Run `uv run pytest -m "not e2e"`.
- Run `uv build` and confirm the wheel contains `garmin_mcp/ai_events`.
- A live Garmin account is optional and not required for acceptance.

## Explicitly deferred

V1 does not add:

- automatic inclusion in `get_training_context`;
- event creation, editing, deletion, subscription, or sync;
- course lookup, GPX download, elevation, waypoints, or route data;
- event-to-course, event-to-plan, or event-to-workout linkage;
- inferred race priority when `primary_event` is absent;
- training phase, taper, pacing, nutrition, or readiness calculations;
- a generic arbitrary-date `start_date`/`end_date` calendar browser; or
- automatic retries or caching.

Course-aware preparation is the natural follow-up only after this event contract
has real-account evidence and a separate privacy/request-budget design.

## Acceptance criteria

The feature is complete when:

1. `get_target_events(days=180)` is a strict, explicit, read-only MCP tool;
2. valid requests perform only the bounded monthly provider reads;
3. the public response follows the exact stable envelope and supported fields;
4. missing, malformed, and failed months remain distinguishable from a valid
   empty calendar;
5. output is capped at 100 events with explicit truncation metadata;
6. no raw provider data, errors, URLs, UUIDs, credentials, or GPX data escape;
7. the default `ai-coach` profile exposes exactly 17 tools;
8. `get_training_context` remains byte-for-byte contract-compatible;
9. documentation clearly separates factual event evidence from coaching advice;
10. focused and full offline verification pass; and
11. the built package contains the new isolated feature.
