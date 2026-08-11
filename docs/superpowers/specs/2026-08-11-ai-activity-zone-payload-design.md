# AI Activity Zone Payload Fix Design

## Problem

`analyze_activity` reads Garmin time-in-zone data, but its normalizer only
recognizes the aliases `zone` and `timeInZone`. The pinned Garmin client can
return `zoneNumber` and `secsInZone` instead. As a result, real zone numbers and
durations are discarded even though Garmin supplied them.

That missing evidence also makes it easier for an AI coach to estimate time in
zone from split-average heart rate or claim heart-rate drift/decoupling from
split averages. Those are not valid substitutes for measured zone duration or
time-series data.

## Scope

Keep the existing read-only activity-analysis architecture and provider calls.
Change only the zone normalization and its user-facing interpretation guidance.

- Normalize `zone` or `zoneNumber` into `zone`.
- Normalize `timeInZone` or `secsInZone` into `duration_seconds`.
- Preserve zero-second zones.
- Continue deriving only `duration_minutes` from a returned duration.
- Leave percentage and upper boundary null when Garmin omits them.
- Keep the existing output envelope and warning semantics.
- Apply the shared behavior to heart-rate and power zones.

When both an existing alias and its Garmin alias are present, prefer the
existing canonical input (`zone` and `timeInZone`) for backward compatibility.

## AI interpretation boundary

The MCP metadata and guide must tell the coach that returned zone durations are
authoritative. It must not estimate time in zone from split-average heart rate.
Split averages do not establish heart-rate drift or cardiovascular decoupling,
so the coach must not calculate or claim those metrics from this response.

## Verification

Add a realistic five-zone regression containing `zoneNumber`, `secsInZone`, and
`zoneLowBoundary`, including zero-second zones. Pin the interpretation boundary
in both FastMCP metadata and documentation tests. Run focused activity-analysis
tests, the complete offline suite, and a package build.

## Deferred

Second-by-second activity details, time-series drift/decoupling analysis, and
new Garmin reads remain out of scope for this fix.
