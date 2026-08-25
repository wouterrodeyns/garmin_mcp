# Course details: safe selective read design

## Summary

Add one opt-in, read-only MCP tool, `get_course_details(course_id)`, that
returns a small, stable scalar summary of one saved Garmin course. It is
designed for an explicit question about a known course, not for route export,
mapping, GPX handling, or automated coaching context.

The tool uses the authenticated Garmin endpoint:

```text
GET /course-service/course/{id}
```

An authenticated live probe confirmed that endpoint returns HTTP 200. Its
top-level detail response uses `activityTypePk`, `distanceMeter`,
`elevationGainMeter`, and `elevationLossMeter`; it also contains `geoPoints`
and `courseLines`. The sampled response's `coursePoints` value was not a list.
The implementation must therefore treat route geometry and the detailed course
point representation as private, untrusted provider data, not as a public
contract. V1 ignores those fields completely.

## Goals

- Expose a single, bounded fact read for a selected course ID.
- Return course name, normalized activity, distance, elevation gain, and
  elevation loss only.
- Provide one stable JSON envelope for normal results, partial results, and
  expected failures.
- Never make a Garmin write or request an export/download.
- Keep the tool available in `upstream-full` and through an explicit
  `GARMIN_ENABLED_TOOLS` allowlist.
- Keep the default `ai-coach` profile at its existing 17-tool surface.
- Ensure no provider exception text, URL, request metadata, raw payload, or
  private geometry can reach the MCP response.

## Non-goals

- No GPX import, export, download, creation, update, deletion, sharing, or
  upload change. `upload_course`, `_build_course_payload`, and the current
  course creation flow remain behaviorally unchanged.
- No map, route, bounding box, start/end location, coordinate, polyline,
  `geoPoints`, `courseLines`, `coursePoints`, or any derived route-point output.
- No owner/profile/group names or IDs, personal names other than the selected
  course's own name, descriptions, notes, links, or URLs.
- No addition to `get_training_context`, `analyze_activity`, or any automatic
  AI-coach workflow.
- No parsing, validation, warning, or inference based on `coursePoints`,
  `geoPoints`, `courseLines`, or any other geometry-bearing provider field.

## Alternatives considered

### 1. Add the tool directly to `courses.py`

This is the smallest source change, but it places a privacy-sensitive read next
to the upload and deletion tools. That module currently includes compatibility
error paths that interpolate exception text. It would be too easy to inherit
that behavior accidentally, and its upload-specific helpers would obscure the
new read boundary.

### 2. Add an isolated course-details provider, service, and MCP adapter

This is the chosen approach. It follows the bounded AI activity feature shape:
a provider seam catches all provider exceptions, a pure normalizer allowlists
the response, and a thin tool adapter serializes the public envelope. The
separation makes the read-only call budget, privacy contract, error vocabulary,
and tests independently auditable while leaving the upload implementation
untouched.

The implementation may live as a compact `course_details.py` module or a small
`course_details/` package if splitting the provider, service, and adapter keeps
each file focused. The logical boundaries below are required regardless of that
file layout.

### 3. Expand `get_courses` with detail data

Rejected. The list tool is not a selected-course request, would encourage
unbounded per-course reads, and would mix a compatibility list response with a
new privacy-bounded contract.

## Architecture and provider seam

The new feature has three responsibilities.

1. **Provider seam:** Accept the configured Garmin client and a validated
   course ID. Make exactly one call to
   `garmin_client.connectapi("/course-service/course/{course_id}")` on the
   configured `_GarminProxy`. Catch all exceptions and return only a
   success/failure result object; discard the exception and its text.
2. **Normalization service:** Validate the input, interpret the returned root,
   project only allowlisted scalar fields, and build the fixed envelope. This
   service performs no I/O other than the provider seam's one read.
3. **MCP adapter:** Register `get_course_details`, call the service, and return
   `json.dumps(result, separators=(",", ":"), ensure_ascii=False)`. It does not
   catch and reformat provider exceptions because none leave the provider seam.

The only permitted Garmin method is `connectapi` on the configured proxy and
the only permitted path is the exact course-detail path above. The test fake
must fail if any POST, DELETE, file, export, download, raw-request, nested
client access, or unrelated client method is reached.

The implementation must not reuse the compatibility-style `except Exception as
e: return f"Error: {str(e)}"` pattern in `courses.py`. The global `_GarminProxy` can
decorate known exception messages with underlying details, so the new provider
seam must catch exceptions before any text is serialized into the tool result.

## Public MCP contract

### Input

`course_id` accepts the same conservative identifier vocabulary as the bounded
activity reads: an exact positive integer or an ASCII decimal string. Booleans,
floats, signed strings, exponent notation, non-ASCII digits, empty strings,
zero, negative values, and values greater than `9007199254740991` are invalid.
String validation occurs before and after trimming; the raw string is limited to
64 characters.

Use a strict `StrictInt | StrictStr` adapter annotation so callers receive a
clear MCP argument error for non-string/non-integer JSON types. The service
still validates every accepted value and emits the fixed `invalid_course_id`
envelope for invalid numeric/string content.

### Response envelope

Every completed invocation returns a JSON object with exactly these top-level
keys:

```json
{
  "status": "success | partial_success | error",
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

On an error, `course` is `null`, `warnings` is an empty list unless a prior
trusted partial result exists (none do in v1), and `error` is a fixed object.
On success or partial success, `error` is `null`. Optional/missing course
fields are represented by `null`, never omitted. `warnings` contains only
fixed, trusted objects in the deterministic order defined below.

`course` always has exactly these keys:

| Field | Contract |
| --- | --- |
| `course_id` | The validated request ID, never an untrusted owner/profile ID. |
| `name` | Trimmed course name, at most 256 characters, else `null`. This is the only returned name. |
| `activity` | A known normalized activity key or `null`; raw provider codes are not returned. |
| `distance_m` | Finite non-negative number from `distanceMeter`, else `null`. |
| `elevation_gain_m` | Finite non-negative number from `elevationGainMeter`, else `null`. |
| `elevation_loss_m` | Finite non-negative number from `elevationLossMeter`, else `null`. |

## Field mapping and validation

The existing course upload mapping is the source of truth:

```python
_ACTIVITY_TYPE_IDS = {
    "running": 1,
    "cycling": 2,
    "hiking": 3,
    "walking": 9,
    "trail_running": 6,
    "mountain_biking": 5,
    "road_biking": 10,
    "gravel_cycling": 4,
}
```

The detail normalizer derives an inverse mapping rather than maintaining a
second table. `activityTypePk` therefore maps as follows: 1 running, 2 cycling,
3 hiking, 4 gravel_cycling, 5 mountain_biking, 6 trail_running, 9 walking, and
10 road_biking. A missing or unknown value results in `activity: null` and the
fixed `activity_type_unavailable` warning.

The provider response must be a mapping. A null/empty response is
`course_not_found`. `courseId` is valid only when its exact built-in type is
`int` (not `bool`), its value is positive, it is at most `9007199254740991`,
and it equals the already validated requested ID. A non-mapping root or any
other `courseId` state is `invalid_course_response`. The provider ID is used
only for validation; the public response returns the already validated request
ID. This avoids reflecting untrusted IDs.

`courseName` is valid only when it is a string that trims to 1 through 256
characters. Any other value produces `name: null`, exactly one
`course_name_unavailable` warning, and `partial_success`.

Number normalization accepts exact `int` or `float` values excluding booleans,
requires finite values, and requires values greater than or equal to zero.
Malformed optional metrics become `null` with one
`invalid_course_metric` warning per response, not one warning per field.

## Bounds and privacy

V1 does not parse `coursePoints`, `geoPoints`, `courseLines`, or any nested
geometry. Their shape, length, contents, and absence have no effect on status,
warnings, or output. The service does not iterate, stringify, log, recursively
search, or otherwise inspect them.

The serialized result is bounded to a 256-character course name and fixed
scalar fields. Owner/profile/group names and IDs, personal names other than the
course name, description, notes, links, URLs, map data, and all raw provider
payload fields are excluded. The provider response is not logged or echoed by
this feature.

## Errors and warnings

`error` values are fixed trusted objects:

| Code | Message |
| --- | --- |
| `invalid_course_id` | `course_id must be a positive integer or decimal string.` |
| `client_unavailable` | `Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.` |
| `course_unavailable` | `Course data is unavailable. Check the course ID, re-run garmin-mcp-auth if the session expired, or retry later.` |
| `course_not_found` | `No course data was found for the requested course ID.` |
| `invalid_course_response` | `Course data had an unexpected shape.` |

Warnings are likewise fixed trusted objects with `code` and `message` only:

| Code | Message |
| --- | --- |
| `course_name_unavailable` | `Course name is unavailable.` |
| `activity_type_unavailable` | `Course activity type is unavailable.` |
| `invalid_course_metric` | `One or more course distance or elevation metrics are unavailable.` |

For any warning, use concise fixed messages in source code and documentation;
never include the provider's value, exception text, request ID, HTTP status,
headers, endpoint URL, token, or traceback. An unavailable name, malformed
optional metric, or unknown activity type makes the response `partial_success`.
Multiple warnings are emitted at most once each in the order listed above.

## Tool filtering and registration

Import, configure, and register the new module with the root server in the same
order as other feature modules. Do not add `get_course_details` to
`TOOL_PROFILES["ai-coach"]`; its exact membership and count remain 17.

The existing filter semantics already provide the intended exposure:

1. `GARMIN_TOOL_PROFILE=upstream-full` registers the full maintained surface,
   including `get_course_details`.
2. `GARMIN_ENABLED_TOOLS=get_course_details` registers this one tool regardless
   of selected profile or denylist, because explicit allowlists take precedence.
3. Default, blank, and explicit `ai-coach` profile configurations do not
   register it.
4. `GARMIN_DISABLED_TOOLS=get_course_details` removes it from `upstream-full`.

No new profile, environment variable, or filtering rule is needed.

## Test strategy

Tests must be offline and use recording fakes rather than a Garmin account.

### Unit tests

- Identifier validation: positive integers and trimmed ASCII decimals; reject
  booleans, floats, signs, exponents, non-ASCII decimal characters, empty
  strings, zero, negatives, and values above the maximum.
- Exact fixed error envelope for invalid input, absent client, provider failure,
  empty payload, wrong root type, missing course ID, and mismatched course ID.
- Valid mapping for every ID in the inverse existing upload mapping and the
  unknown/missing mapping warning behavior.
- Exact provider `courseId` validation: exact `int` only, not boolean;
  positive; at most the JavaScript-safe maximum; and equal to the request.
- Name semantics: valid trimmed lengths 1 and 256, invalid empty/whitespace,
  overlong, non-string, and null values; exact single warning and partial
  status.
- Exact handling for each top-level metric: valid integer/float, zero,
  `null`, boolean, non-finite, negative, and malformed value.
- Geometry isolation: hostile or enormous `coursePoints`, `geoPoints`, and
  `courseLines` values do not appear in output and do not change status or
  warnings.
- Privacy projection assertions: the serialized result contains none of the
  supplied owner fields, profile/group IDs, personal names, description, notes,
  URL fields, coordinates, geometry, `geoPoints`, `courseLines`, or arbitrary
  raw payload sentinel values.
- Provider exception suppression: a thrown exception containing an endpoint,
  token-like marker, request ID, and unique sentinel must not appear anywhere
  in the response.
- Invalid IDs perform zero I/O: the recording proxy receives no method call.
- An unavailable client performs zero I/O and returns `client_unavailable`.

### Integration and registration tests

- Invoke the FastMCP tool and assert its strict input schema, one argument,
  exact response shape, and JSON serialization.
- Use a recording configured proxy to assert the only call is one
  `connectapi("/course-service/course/{id}")`; make nested-client access,
  `post`, `delete`, export, download, and unknown methods fail the test if
  called.
- Add the module to the full unfiltered registration reference. Verify
  `upstream-full` includes `get_course_details`.
- Assert default and explicit `ai-coach` registration still equal exactly the
  existing 17 names and exclude `get_course_details`.
- Assert an explicit allowlist exposes only `get_course_details` and has its
  established precedence over profile and denylist; assert the upstream-full
  denylist removes it.

## Documentation

Add `docs/course-details.md` as an advanced, opt-in feature guide. It must
state the input rules, one-call read-only source, fixed scalar schema, activity
mapping, exact name/null/partial-success semantics, all warning/error codes,
and the explicit privacy exclusions. It must clearly say that `coursePoints`,
`geoPoints`, `courseLines`, and all geometry are ignored rather than parsed.
It must also say that the tool is outside `ai-coach` and is available with
`upstream-full` or an explicit allowlist.

Link the guide from README and the setup reference as an advanced course read.
Keep all current AI-coach profile lists and assertions at exactly 17 tools; do
not present this feature as coaching context. Document that upload/import/export
behavior is outside this feature's scope and unchanged.

## Acceptance criteria

- `get_course_details` is one read-only tool with one bounded provider call.
- A successful response contains only the allowlisted schema and never raw
  course structures or private route/owner data.
- `coursePoints`, `geoPoints`, and `courseLines` are ignored completely,
  including their sampled non-list `coursePoints` representation.
- No exception text or provider request detail can reach any error or warning.
- Invalid input and unavailable-client paths perform zero provider I/O.
- Existing course upload behavior is unchanged.
- The tool is exposed through upstream-full/explicit allowlist only, never the
  default AI-coach profile.
- Offline unit, integration, filter, startup, and documentation contract tests
  cover the public contract and privacy boundary.
