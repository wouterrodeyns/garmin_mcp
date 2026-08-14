# Current-day wellness heart-rate time provenance

## Problem

Garmin's `get_heart_rates(date)` response for an in-progress current day uses
different meanings for its end bounds. `endTimestampGMT` is the latest synced
instant, while `endTimestampLocal` is already the next local midnight. The
wellness service currently requires both start and end bound pairs to imply the
same UTC offset. It therefore rejects otherwise valid current-day local-time
windows and replaces the day with a fixed empty result, hiding the source sample
count.

The observed 2026-08-14 payload had 410 source samples. Its start bounds implied
UTC+02:00, but its incomplete end bounds did not form a corresponding pair. A
raw request returned the samples with local time unavailable; the same request
with a local window returned an error and synthetic `source_points: 0`.

## Scope

This is a read-only bug fix inside `ai_training`. It does not change provider
calls, date-range limits, point/bin limits, serialized-size limits, resolution
choices, or the binned response representation.

## Chosen behavior

The service keeps complete-day provenance as the preferred path: both Garmin
bound pairs must imply the same whole-minute offset.

When that path fails, the service may use the start-bound offset only when all of
these conditions hold:

1. the requested date equals the service's effective current date;
2. `startTimestampGMT` and `startTimestampLocal` are valid naive datetimes and
   imply a whole-minute offset in the existing supported range;
3. `endTimestampLocal` is exactly one local day after the local start;
4. `endTimestampGMT` is at or after the GMT start and strictly before the
   full-day GMT end implied by the start offset.

This identifies Garmin's incomplete current-day shape without accepting an
inconsistent completed historical day. The internal service API gains an
optional injected `today: date | None` seam for deterministic tests; the MCP
tool does not expose it.

The fallback is explicitly provisional:

- `time_provenance.local_offset_minutes` contains the start-bound offset;
- `time_provenance.local_time_available` is `true`;
- new stable field `time_provenance.local_time_basis` is
  `"current_day_start_bound"`;
- complete bounds use `"complete_bounds"`;
- unavailable provenance uses `null`;
- a structured `local_time_provisional` warning explains the limitation;
- warnings alone do not change `success` to `partial_success`.

Local windows remain local windows. The service does not reinterpret them as
UTC and does not fetch or borrow the previous day's offset. The latter could be
wrong after travel or a daylight-saving transition.

## Unavailable provenance

When a local window or binned request still cannot establish local provenance,
the day remains unavailable. Its stable empty result must preserve the validated
Garmin `source_points` count while leaving filtered counts unknown and returning
no points. Provider failures and invalid DTOs, where no validated collection is
available, continue to report zero source points.

## Testing

Tests must pin:

- the observed incomplete current-day bound shape succeeds for raw local-window
  and binned requests using UTC+02:00;
- filtering is performed in provisional local time, never UTC;
- source counts and selected points remain truthful;
- the provisional basis and warning are stable and sanitized;
- the same incomplete shape is not accepted for a non-current date;
- completed-day disagreement remains unavailable;
- unavailable local provenance preserves a validated source count;
- one provider read per requested date remains the only Garmin access;
- MCP arguments remain unchanged and documentation explains provisional time;
- the focused and complete offline test suites pass without a Garmin account.

## Deferred

Response compaction, pagination, lower client-specific display limits, and
changes to UTC timestamp fields are separate product decisions. The existing
exact 262,144-byte serialized response cap remains unchanged.
