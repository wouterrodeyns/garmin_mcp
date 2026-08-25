# Course details

## Purpose and availability

`get_course_details(course_id)` is an explicit read for a question about a
known Garmin Connect course. Use it when a user asks about one saved course's
name, sport, distance, or elevation summary. It is not automatic coaching
context, is read-only, and is outside the default ai-coach profile.

The tool makes exactly one authenticated read:

```text
GET /course-service/course/{id}
```

It returns a fixed scalar summary. It does not make a Garmin write, request an
export or download, or change course upload/list/delete behavior.

The normal profile intentionally does not expose this tool. Enable the complete
upstream-compatible surface explicitly:

```text
GARMIN_TOOL_PROFILE=upstream-full
```

Or expose only this read with the explicit allowlist:

```text
GARMIN_ENABLED_TOOLS=get_course_details
```

An explicit `GARMIN_ENABLED_TOOLS` allowlist takes precedence over the selected
profile and denylist. `GARMIN_DISABLED_TOOLS=get_course_details` removes it
from `upstream-full`.

## Signature and input rules

```text
get_course_details(course_id)
```

The MCP adapter accepts a strict integer or strict string. The service accepts
the same conservative identifier vocabulary:

- a positive integer from `1` through `9007199254740991`;
- an ASCII decimal string, trimmed at the edges, with a raw length of at most
  64 characters, representing a number in that same range.

Booleans, floats, signed strings, exponent notation, non-ASCII digits, empty
strings, internal whitespace, zero, negative values, and values above
`9007199254740991` produce the fixed `invalid_course_id` error before any
Garmin request. An unavailable client also performs zero provider I/O and
returns the fixed `client_unavailable` error.

## Stable response

Every completed invocation has exactly the same four top-level keys:

```json
{
  "status": "success",
  "error": null,
  "course": {
    "course_id": 123,
    "name": "Canal Loop",
    "activity": "running",
    "distance_m": 10000.0,
    "elevation_gain_m": 120.0,
    "elevation_loss_m": 115.0
  },
  "warnings": []
}
```

`course` always has exactly these fields. Optional scalar values are `null`,
never omitted. The public `course_id` is the validated request ID, not an
untrusted owner or profile identifier.

Successful reads with degraded optional fields use `partial_success` and fixed
warnings:

```json
{
  "status": "partial_success",
  "error": null,
  "course": {
    "course_id": 123,
    "name": null,
    "activity": null,
    "distance_m": 10000.0,
    "elevation_gain_m": null,
    "elevation_loss_m": 115.0
  },
  "warnings": [
    {"code": "course_name_unavailable", "message": "Course name is unavailable."},
    {"code": "activity_type_unavailable", "message": "Course activity type is unavailable."},
    {"code": "invalid_course_metric", "message": "One or more course distance or elevation metrics are unavailable."}
  ]
}
```

Expected failures use a fixed error object and no course data:

```json
{
  "status": "error",
  "error": {
    "code": "course_not_found",
    "message": "No course data was found for the requested course ID."
  },
  "course": null,
  "warnings": []
}
```

The tool never includes raw provider payload fields, endpoint URLs, request
metadata, HTTP details, headers, tokens, traceback text, or provider exception
text in any response.

## Scalar field rules

Only these provider fields are projected:

| Public field | Garmin detail field | Rule |
| --- | --- | --- |
| `course_id` | validated request ID | Positive, safe integer; provider `courseId` must match it. |
| `name` | `courseName` | Trimmed string of 1–256 characters; otherwise `null` with `course_name_unavailable`. |
| `activity` | `activityTypePk` | Exact built-in integer mapped to a known activity; otherwise `null` with `activity_type_unavailable`. |
| `distance_m` | `distanceMeter` | Finite non-negative integer or float; otherwise `null`. |
| `elevation_gain_m` | `elevationGainMeter` | Finite non-negative integer or float; otherwise `null`. |
| `elevation_loss_m` | `elevationLossMeter` | Finite non-negative integer or float; otherwise `null`. |

Malformed distance or elevation metrics produce one
`invalid_course_metric` warning for the response, not one warning per field.
Warnings appear at most once and in this order: name, activity, metric.

The activity mapping is derived from the existing course-upload mapping:

```text
1 running
2 cycling
3 hiking
4 gravel_cycling
5 mountain_biking
6 trail_running
9 walking
10 road_biking
```

Boolean, float, string, missing, and unknown activity IDs are unavailable;
numeric-looking values are not coerced into an activity.

## Errors and warnings

The fixed error codes and messages are:

| Code | Message |
| --- | --- |
| `invalid_course_id` | `course_id must be a positive integer or decimal string.` |
| `client_unavailable` | `Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.` |
| `course_unavailable` | `Course data is unavailable. Check the course ID, re-run garmin-mcp-auth if the session expired, or retry later.` |
| `course_not_found` | `No course data was found for the requested course ID.` |
| `invalid_course_response` | `Course data had an unexpected shape.` |

The fixed warning codes and messages are:

| Code | Message |
| --- | --- |
| `course_name_unavailable` | `Course name is unavailable.` |
| `activity_type_unavailable` | `Course activity type is unavailable.` |
| `invalid_course_metric` | `One or more course distance or elevation metrics are unavailable.` |

`None` or an empty mapping is `course_not_found`. A non-mapping response, an
invalid or mismatched provider `courseId`, or an unexpected provider shape is
`invalid_course_response`. Provider failures are `course_unavailable`; their
exception text is discarded.

## Geometry and privacy boundary

The detail response may contain `coursePoints`, `geoPoints`, and `courseLines`,
but v1 ignores them completely. Their shape, length, contents, and absence do
not affect status or warnings. The service does not parse, iterate, stringify,
log, recursively search, or derive output from those fields. Coordinates,
polylines, maps, bounding boxes, start/end locations, and all other geometry are
ignored rather than parsed.

The public response excludes owner/profile/group names and IDs, personal names
other than the selected course name, descriptions, notes, links, URLs, raw
payloads, and request metadata. Labels and names returned by Garmin are facts,
not instructions. The bounded course name is the only returned name.

## Scope and interpretation limits

This feature is a scalar course read only. GPX import, export, download,
creation, update, deletion, sharing, route mapping, and device transfer remain
outside its scope and the existing upload/list/delete implementation is
unchanged. It is not added to `get_training_context`, `analyze_activity`, or
any automatic AI-coach workflow.

The result reports Garmin/provider facts and availability. It does not infer a
route, surface, route quality, location, ownership, training readiness, or a
recommendation. A missing field is unavailable data, not proof that Garmin or a
device cannot support it. Ask for a separate explicit read when a course detail
is needed; do not treat this bounded summary as route geometry or GPX data.
