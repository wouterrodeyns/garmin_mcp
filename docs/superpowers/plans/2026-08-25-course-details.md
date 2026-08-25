# Course Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one opt-in, read-only `get_course_details(course_id)` MCP tool that returns a bounded, privacy-safe scalar summary of one Garmin course while leaving the existing course upload/list/delete behavior unchanged.

**Architecture:** Keep the feature in a new isolated `src/garmin_mcp/course_details.py`. The module contains a narrow provider seam that performs exactly one `connectapi("/course-service/course/{course_id}")` read, a pure normalizer that allowlists scalar fields into a fixed envelope, and a thin FastMCP adapter. Register the module in the root server without adding it to the existing 17-tool `ai-coach` profile; the existing `upstream-full` and explicit allowlist semantics provide opt-in exposure.

**Tech Stack:** Python 3.12+, pinned `garminconnect==0.3.10`, FastMCP 1.x, Pydantic strict annotations, Python standard library (`json`, `math`, `dataclasses`/typing), pytest, pytest-asyncio, and uv. No new dependencies.

---

## File map and fixed contracts

- Create `src/garmin_mcp/course_details.py`: provider seam, strict ID validation, response normalization, fixed errors/warnings, and `get_course_details` registration. Keep the module compact and under roughly 500 lines.
- Modify `src/garmin_mcp/__init__.py:15-36,555-574,600-619`: import, configure, and register the isolated module. Do not modify `courses.py`.
- Create `tests/unit/test_course_details.py`: pure service, provider-suppression, validation, mapping, privacy, bounds, and zero-I/O tests.
- Create `tests/integration/test_course_details_tools.py`: FastMCP schema, serialization, one-call/read-only behavior, and adapter tests.
- Modify `tests/unit/test_server_startup.py:40-65`: include the new module in the unfiltered reference and test profile/allowlist exposure.
- Modify `tests/unit/test_tool_filter.py` only if a small explicit exclusion assertion improves readability; the existing exact 17-name assertion remains authoritative.
- Create `docs/course-details.md`: advanced opt-in tool contract, privacy boundary, mappings, warnings, errors, and usage.
- Modify `README.md` and `docs/setup.md`: link the advanced guide and state opt-in exposure without changing the documented 17-tool profile.
- Create `tests/unit/test_course_details_docs.py`: parse and pin the guide’s public contract.
- Do not modify `src/garmin_mcp/courses.py`, `pyproject.toml`, `uv.lock`, the historical specs, or the user-owned untracked AI-target-events plan.
- The implementation branch must be created from `docs/course-details-design`, so the approved design spec and this plan are present in the eventual fork PR.

The public service function is:

```python
get_course_details_service(client: Any, course_id: Any) -> dict[str, Any]
```

The MCP adapter uses this exact strict input annotation:

```python
get_course_details(course_id: StrictInt | StrictStr) -> str
```

Every completed call has exactly these top-level keys, in this order:

```python
{
    "status": "success" | "partial_success" | "error",
    "error": None | {"code": str, "message": str},
    "course": None | {
        "course_id": int,
        "name": str | None,
        "activity": str | None,
        "distance_m": int | float | None,
        "elevation_gain_m": int | float | None,
        "elevation_loss_m": int | float | None,
    },
    "warnings": list[{"code": str, "message": str}],
}
```

The only allowed provider call is `client.connectapi(f"/course-service/course/{validated_id}")`. The provider catches every exception and discards the exception object and text. It never accesses `client.client`, calls `post`/`delete`, downloads or exports a course, logs the provider response, or inspects geometry.

### Task 0: Create the implementation branch from the approved docs branch

**Files:**

- Verify only: Git worktree/branch metadata; do not edit source files in this step.

- [ ] **Step 1: Verify the source docs branch and create an isolated implementation worktree.**

  From the repository root, verify the current docs worktree is based on the committed approved spec/plan, then create the implementation worktree from that branch:

  ```bash
  git -C /Users/wouterrodeyns/Documents/Personal/garmin_mcp branch --show-current
  git -C /Users/wouterrodeyns/Documents/Personal/garmin_mcp show --stat --oneline docs/course-details-design
  git -C /Users/wouterrodeyns/Documents/Personal/garmin_mcp worktree add \
    /Users/wouterrodeyns/Documents/Personal/garmin_mcp/.worktrees/course-details-implementation \
    -b feat/course-details docs/course-details-design
  ```

  Expected: `docs/course-details-design` is the source branch, `feat/course-details` is created once, and the new worktree contains both `docs/superpowers/specs/2026-08-25-course-details-design.md` and `docs/superpowers/plans/2026-08-25-course-details.md`. If the target branch/worktree already exists, inspect it and continue only when its HEAD is the approved docs branch; do not reset or overwrite it.

- [ ] **Step 2: Verify the implementation worktree before touching code.**

  Run:

  ```bash
  git -C /Users/wouterrodeyns/Documents/Personal/garmin_mcp/.worktrees/course-details-implementation status --short --branch
  git -C /Users/wouterrodeyns/Documents/Personal/garmin_mcp/.worktrees/course-details-implementation diff -- docs/superpowers/specs/2026-08-25-course-details-design.md docs/superpowers/plans/2026-08-25-course-details.md
  ```

  Expected: the implementation branch is clean and the approved artifacts are present unchanged. Begin Task 1 in that worktree.

### Task 1: Establish the isolated module and strict identifier/envelope contract

**Files:**

- Create: `src/garmin_mcp/course_details.py`
- Create: `tests/unit/test_course_details.py`

- [ ] **Step 1: Write failing tests for accepted and rejected IDs.**

  Add a direct service test module with a client that records calls and fails on any unexpected attribute:

  ```python
  import json
  import math
  import pytest

  from garmin_mcp.course_details import _parse_course_id, get_course_details_service


  class RecordingClient:
      def __init__(self, response=None, failure=None):
          self.response = response
          self.failure = failure
          self.calls = []

      def connectapi(self, path):
          self.calls.append(path)
          if self.failure is not None:
              raise self.failure
          return self.response

      def __getattr__(self, name):
          raise AssertionError(f"forbidden Garmin access: {name}")


  @pytest.mark.parametrize(
      ("value", "expected"),
      [(1, 1), (9007199254740991, 9007199254740991), ("1", 1), ("  123  ", 123)],
  )
  def test_course_id_accepts_positive_int_and_trimmed_ascii_decimal(value, expected):
      assert _parse_course_id(value) == expected


  @pytest.mark.parametrize(
      "value",
      [True, False, 1.0, 0, -1, "", "   ", "+1", "-1", "1e2", "١", "12.0", "9" * 65],
  )
  def test_course_id_rejects_nonconservative_values_without_io(value):
      client = RecordingClient()
      result = get_course_details_service(client, value)
      assert result == {
          "status": "error",
          "error": {
              "code": "invalid_course_id",
              "message": "course_id must be a positive integer or decimal string.",
          },
          "course": None,
          "warnings": [],
      }
      assert client.calls == []
  ```

  Add cases for `9007199254740992`, a 64-character raw string that trims to digits, and a string containing internal whitespace. The raw string length limit is checked before trimming; only ASCII characters between `0` and `9` are accepted after trimming.

- [ ] **Step 2: Run the focused RED test.**

  Run: `uv run pytest tests/unit/test_course_details.py -q`

  Expected: collection fails because `garmin_mcp.course_details` does not exist.

- [ ] **Step 3: Add the module constants, strict parser, and envelope builders.**

  Create the module with no I/O at import time. Use exact built-in types for direct service validation, the JavaScript-safe maximum, and fixed trusted messages:

  ```python
  import json
  from collections.abc import Mapping
  from math import isfinite
  from typing import Any

  from pydantic import StrictInt, StrictStr

  garmin_client: Any = None
  MAX_SAFE_COURSE_ID = 9007199254740991

  ERROR_MESSAGES = {
      "invalid_course_id": "course_id must be a positive integer or decimal string.",
      "client_unavailable": "Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.",
      "course_unavailable": "Course data is unavailable. Check the course ID, re-run garmin-mcp-auth if the session expired, or retry later.",
      "course_not_found": "No course data was found for the requested course ID.",
      "invalid_course_response": "Course data had an unexpected shape.",
  }

  WARNING_MESSAGES = {
      "course_name_unavailable": "Course name is unavailable.",
      "activity_type_unavailable": "Course activity type is unavailable.",
      "invalid_course_metric": "One or more course distance or elevation metrics are unavailable.",
  }

  def _parse_course_id(value: Any) -> int | None:
      if type(value) is int:
          return value if 0 < value <= MAX_SAFE_COURSE_ID else None
      if type(value) is not str or len(value) > 64:
          return None
      text = value.strip()
      if not text or not all("0" <= char <= "9" for char in text):
          return None
      parsed = int(text)
      return parsed if 0 < parsed <= MAX_SAFE_COURSE_ID else None

  def _error(code: str) -> dict[str, Any]:
      return {"status": "error", "error": {"code": code, "message": ERROR_MESSAGES[code]}, "course": None, "warnings": []}

  def _warning(code: str) -> dict[str, str]:
      return {"code": code, "message": WARNING_MESSAGES[code]}
  ```

  Add `configure(client)` and `_course_template(course_id)` so all public responses use the exact key sets. `_course_template` must not accept or echo a provider ID.

- [ ] **Step 4: Implement the zero-I/O service guard.**

  Add `get_course_details_service` with this control flow: parse the request; return `_error("invalid_course_id")` before touching the client; return `_error("client_unavailable")` for `None`; and leave valid-client response handling to the provider/normalization slice in Task 2. Add `test_unavailable_client_returns_fixed_error_without_io`: call the service with `None` and a valid ID, assert the exact `client_unavailable` code/message, `course is None`, `warnings == []`, and no provider method is attempted. The Task 1 tests must exercise only invalid-ID and unavailable-client paths, so no temporary success implementation is needed.

- [ ] **Step 5: Run GREEN and commit the first isolated slice.**

  Run: `uv run pytest tests/unit/test_course_details.py -q`

  Expected: all ID, envelope, invalid-client, and zero-I/O tests pass.

  ```bash
  git add src/garmin_mcp/course_details.py tests/unit/test_course_details.py
  git commit -m "feat(courses): establish safe course details contract"
  ```

### Task 2: Add the one-call provider seam and response-root validation

**Files:**

- Modify: `src/garmin_mcp/course_details.py`
- Modify: `tests/unit/test_course_details.py`

- [ ] **Step 1: Write provider and root-validation RED tests.**

  Add these named tests:

  - `test_provider_calls_exact_detail_endpoint_once`: with request ID `123`, assert exactly `client.calls == ["/course-service/course/123"]` and no other method is reached.
  - `test_provider_failure_returns_fixed_course_unavailable`: raise `RuntimeError("https://private/?token=sentinel request-id=secret")`; assert the exact fixed `course_unavailable` envelope and that none of the sentinels occur in `json.dumps(result)`.
  - `test_none_and_empty_mapping_are_course_not_found`: assert the exact `course_not_found` envelope and one call for both `None` and `{}`.
  - `test_non_mapping_root_is_invalid_course_response`: parameterize a list, tuple, string, and integer; assert fixed `invalid_course_response` and no raw value leakage. Keep `None` in `test_none_and_empty_mapping_are_course_not_found`. Add `test_mapping_subclass_is_accepted_without_recursive_inspection` using a read-only `collections.abc.Mapping` implementation whose iteration raises if accessed outside the five allowlisted scalar keys; assert the scalar projection succeeds. The approved contract accepts mappings, not only exact built-in dictionaries.
  - `test_missing_invalid_and_mismatched_provider_course_id_are_invalid`: cover missing ID, `True`, `0`, negative, over-safe integer, string ID, and an ID different from the request.

- [ ] **Step 2: Run the focused RED tests.**

  Run: `uv run pytest tests/unit/test_course_details.py -k 'provider or not_found or root or mismatched' -q`

  Expected: failures show that no exact endpoint seam/root validation exists yet.

- [ ] **Step 3: Implement the provider result and exact endpoint call.**

  Add a private result representation and call only the configured proxy:

  ```python
  class _ProviderResult:
      def __init__(self, data: Any = None, failed: bool = False):
          self.data = data
          self.failed = failed


  def _fetch_course(client: Any, course_id: int) -> _ProviderResult:
      try:
          return _ProviderResult(client.connectapi(f"/course-service/course/{course_id}"))
      except Exception:
          return _ProviderResult(failed=True)
  ```

  Do not include the exception in the result, warning, log, or response. Keep the provider call synchronous inside the service, matching the existing Garmin client APIs.

- [ ] **Step 4: Implement root and provider-ID validation.**

  Import `Mapping` from `collections.abc` and accept any `Mapping` root. Treat `None` and an empty mapping as `course_not_found`; treat non-empty non-mappings as `invalid_course_response`. Read only the allowlisted scalar keys from the mapping. Require `courseId` to be an exact built-in positive `int`, no larger than `MAX_SAFE_COURSE_ID`, and equal to the validated request ID. Return `_error("invalid_course_response")` for all other ID/root states. Build the public `course_id` from the validated request only. Never recursively iterate, stringify, copy, or inspect unallowlisted mapping values.

- [ ] **Step 5: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/test_course_details.py -q`

  Expected: provider, root, ID, and previous service tests pass; the only Garmin call is the exact GET-style `connectapi` path.

  ```bash
  git add src/garmin_mcp/course_details.py tests/unit/test_course_details.py
  git commit -m "feat(courses): isolate course detail provider reads"
  ```

### Task 3: Implement the allowlisted scalar projection, warnings, and privacy boundary

**Files:**

- Modify: `src/garmin_mcp/course_details.py`
- Modify: `tests/unit/test_course_details.py`

- [ ] **Step 1: Write RED tests for field mapping and warning order.**

  Add these named tests:

  - `test_activity_type_maps_every_existing_upload_id`: parameterize `(1, "running"), (2, "cycling"), (3, "hiking"), (4, "gravel_cycling"), (5, "mountain_biking"), (6, "trail_running"), (9, "walking"), (10, "road_biking")`; each response must expose only the normalized key.
  - `test_activity_type_requires_exact_int_and_known_id`: parameterize `True`, `1.0`, `"1"`, `0`, `999`, and `None`; assert `activity is None`, `partial_success`, and exactly one `activity_type_unavailable` warning for each. The existing eight known integer IDs must remain covered by the preceding mapping test.
  - `test_course_name_is_trimmed_and_limited`: cover one-character, 256-character, whitespace-trimmed, empty, whitespace-only, overlong, null, and non-string names. Invalid names yield one `course_name_unavailable` warning and `partial_success`.
  - `test_metrics_accept_finite_nonnegative_int_or_float`: cover integer, float, and zero for all three fields.
  - `test_metrics_reject_bool_nan_infinity_negative_and_other_types`: assert all malformed metrics become `None`, produce one total `invalid_course_metric` warning, and do not create one warning per field.
  - `test_warning_order_is_name_activity_metric`: make all three categories malformed and assert warning codes occur in exactly that order.

- [ ] **Step 2: Write RED tests for privacy and geometry isolation.**

  Add `test_projection_excludes_all_private_and_geometry_fields`. Supply `geoPoints`, `courseLines`, `coursePoints`, `boundingBox`, `startPoint`, owner/profile/group IDs, first/last names, description, notes, URL fields, and a unique raw sentinel. Use a geometry object whose iteration/string conversion raises `AssertionError`; assert the service returns valid scalar data without touching it. Assert every forbidden field and sentinel is absent from `json.dumps(result)`.

  Add `test_geometry_shape_and_size_do_not_change_status_or_warnings` with `coursePoints=None`, a non-list object, an empty list, and a list containing hostile values. Every case must produce the same scalar response and warning list.

- [ ] **Step 3: Run RED and inspect exact failures.**

  Run: `uv run pytest tests/unit/test_course_details.py -k 'activity or name or metric or warning or privacy or geometry' -q`

  Expected: failures show unimplemented mapping, scalar validation, warning ordering, or geometry isolation.

- [ ] **Step 4: Derive the activity inverse from the existing upload map.**

  Import the existing mapping without changing it:

  ```python
  from .courses import _ACTIVITY_TYPE_IDS

  _ACTIVITY_BY_ID = {value: key for key, value in _ACTIVITY_TYPE_IDS.items()}
  ```

  This is the only allowed relationship to `courses.py`; do not edit that file or duplicate a second numeric table. Before inverse lookup, require `type(value) is int`; this excludes booleans, floats, strings, and other numeric-like values. For a missing, non-int, or unknown `activityTypePk`, use `activity: None` and append `_warning("activity_type_unavailable")` once.

- [ ] **Step 5: Implement scalar normalizers and fixed warning accumulation.**

  Use exact built-in checks and finite/nonnegative validation:

  ```python
  def _text(value: Any) -> str | None:
      if type(value) is not str:
          return None
      value = value.strip()
      return value if 1 <= len(value) <= 256 else None


  def _metric(value: Any) -> int | float | None:
      if type(value) not in (int, float):
          return None
      return value if isfinite(value) and value >= 0 else None
  ```

  Normalize only `courseName`, `activityTypePk`, `distanceMeter`, `elevationGainMeter`, and `elevationLossMeter`. For `activityTypePk`, first require `type(value) is int`, then perform the inverse lookup. Never recursively walk, stringify, copy, log, or otherwise inspect geometry/private fields. Append each warning code at most once in the fixed order `course_name_unavailable`, `activity_type_unavailable`, `invalid_course_metric`; any warning changes status to `partial_success`.

- [ ] **Step 6: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/test_course_details.py -q`

  Expected: all service tests pass, including hostile geometry/privacy and fixed-warning tests.

  ```bash
  git add src/garmin_mcp/course_details.py tests/unit/test_course_details.py
  git commit -m "feat(courses): normalize safe course detail fields"
  ```

### Task 4: Register the strict FastMCP adapter and prove read-only invocation

**Files:**

- Modify: `src/garmin_mcp/course_details.py`
- Create: `tests/integration/test_course_details_tools.py`

- [ ] **Step 1: Write integration RED tests for registration and schema.**

  Create a FastMCP fixture that calls `configure(recording_proxy)` and `register_tools(app)`. Add:

  - `test_get_course_details_is_registered_with_one_strict_argument`: list tools, find `get_course_details`, assert only `course_id` exists in the input schema and its schema accepts only integer/string input types (no broad number/boolean coercion).
  - `test_get_course_details_serializes_exact_success_envelope`: call with `{"course_id": "123"}`, parse the text, and assert exact top-level/course keys, compact JSON serialization, and request ID `123`.
  - `test_get_course_details_delegates_to_service_and_returns_json`: monkeypatch `get_course_details_service`, assert it receives the configured client and original strict argument and that the returned JSON contains exactly the service result.

  Use the existing result extraction style from `tests/integration/test_courses_tools.py:25-27`.

- [ ] **Step 2: Add the actively trapped read-only integration fake.**

  Define a fake with only `connectapi`:

  ```python
  class RecordingProxy:
      def __init__(self, response):
          self.response = response
          self.calls = []

      def connectapi(self, path):
          self.calls.append(path)
          return self.response

      def __getattr__(self, name):
          raise AssertionError(f"forbidden client access: {name}")
  ```

  Add `test_tool_makes_one_detail_read_and_no_mutation_or_nested_client_access`: call the real tool, assert `calls == ["/course-service/course/123"]`, and assert no `post`, `delete`, export, download, raw-request, or nested-client path can be reached. Add `test_tool_suppresses_provider_exception_details` through the same FastMCP path.

- [ ] **Step 3: Run RED.**

  Run: `uv run pytest tests/integration/test_course_details_tools.py -q`

  Expected: collection or registration failures show the adapter is not yet present.

- [ ] **Step 4: Implement `register_tools`.**

  Add the thin adapter and return the app:

  ```python
  def register_tools(app: Any) -> Any:
      registered_client = garmin_client

      @app.tool()
      async def get_course_details(course_id: StrictInt | StrictStr) -> str:
          """Return a bounded, read-only scalar summary for one saved course.

          This explicit read ignores route geometry, GPX, map data, owner data,
          and private provider fields. It is outside the default ai-coach
          profile and performs one Garmin detail read at most.
          """
          result = get_course_details_service(registered_client, course_id)
          return json.dumps(result, separators=(",", ":"), ensure_ascii=False)

      return app
  ```

  The adapter must not add another exception handler around the service: provider exceptions are already suppressed at the provider boundary.

- [ ] **Step 5: Run GREEN and commit.**

  Run: `uv run pytest tests/integration/test_course_details_tools.py tests/unit/test_course_details.py -q`

  Expected: all unit and FastMCP tests pass; the recording fake observes exactly one permitted call.

  ```bash
  git add src/garmin_mcp/course_details.py tests/integration/test_course_details_tools.py
  git commit -m "feat(courses): expose safe course detail tool"
  ```

### Task 5: Wire root registration without changing the 17-tool default

**Files:**

- Modify: `src/garmin_mcp/__init__.py:15-36,555-574,600-619`
- Modify: `tests/unit/test_server_startup.py:40-65,344-360,398-433`
- Modify: `tests/unit/test_tool_filter.py:100-135` only for an explicit exclusion assertion if needed

- [ ] **Step 1: Add startup RED expectations.**

  Update `_register_unfiltered_reference_tools()` to include `garmin_mcp.course_details` in the same position as the production registration. Add these tests:

  - `test_main_explicit_allowlist_registers_only_course_details`: set `GARMIN_ENABLED_TOOLS=get_course_details`, use a mocked client and captured `FastMCP.run`, assert the tool set is exactly `{"get_course_details"}`.
  - `test_main_ai_coach_excludes_course_details`: retain the current exact 17-name assertion and add `assert "get_course_details" not in run_calls[0]`.
  - `test_main_upstream_full_includes_course_details`: use the existing `_register_unfiltered_reference_tools()` comparison and assert the resulting set contains `get_course_details`.
  - `test_upstream_full_denylist_removes_course_details`: set `GARMIN_TOOL_PROFILE=upstream-full` and `GARMIN_DISABLED_TOOLS=get_course_details`, capture startup registration, and assert the resulting set equals `_register_unfiltered_reference_tools() - {"get_course_details"}`.

- [ ] **Step 2: Run RED.**

  Run: `uv run pytest tests/unit/test_server_startup.py tests/unit/test_tool_filter.py -q`

  Expected: the allowlist/upstream-full tests fail because the root does not import, configure, or register the module yet.

- [ ] **Step 3: Add root import/configure/registration.**

  In `src/garmin_mcp/__init__.py`, add `from garmin_mcp import course_details` beside `courses`; call `course_details.configure(garmin_client)` beside `courses.configure(...)`; and call `app = course_details.register_tools(app)` beside `courses.register_tools(...)`. Do not add the tool to `TOOL_PROFILES["ai-coach"]`, change `_ToolFilter`, alter profile precedence, or change existing course registration.

- [ ] **Step 4: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/test_server_startup.py tests/unit/test_tool_filter.py tests/integration/test_course_details_tools.py -q`

  Expected: ai-coach remains exactly 17 tools, upstream-full includes the new tool, explicit allowlist exposes only it, and denylist removal works.

  ```bash
  git add src/garmin_mcp/__init__.py tests/unit/test_server_startup.py tests/unit/test_tool_filter.py
  git commit -m "feat(server): register opt-in course details tool"
  ```

### Task 6: Document the advanced opt-in contract and add documentation gates

**Files:**

- Create: `docs/course-details.md`
- Modify: `README.md`
- Modify: `docs/setup.md`
- Create: `tests/unit/test_course_details_docs.py`

- [ ] **Step 1: Write documentation RED tests.**

  Add named tests:

  - `test_course_details_guide_exists_and_names_signature`: require `get_course_details(course_id)`, the exact endpoint path, and read-only/one-call language.
  - `test_guide_documents_exact_schema_and_all_fixed_codes`: parse every JSON example and require top-level keys `status`, `error`, `course`, `warnings`; require all five error codes and all three warning codes.
  - `test_guide_documents_input_bounds_and_activity_mapping`: require the positive integer/ASCII decimal rules, 64-character raw limit, JavaScript-safe maximum, name limit, finite nonnegative metric rules, and all eight activity mappings.
  - `test_guide_documents_geometry_and_privacy_exclusions`: require explicit statements that `coursePoints`, `geoPoints`, `courseLines`, coordinates, owner/profile/group fields, names other than the course name, URLs, notes, raw payloads, and exception text are excluded/ignored.
  - `test_guide_documents_profile_opt_in_without_changing_ai_coach`: require `upstream-full` and `GARMIN_ENABLED_TOOLS=get_course_details`, and assert the README/setup profile lists still state exactly 17 tools and do not list `get_course_details` among them.

- [ ] **Step 2: Run RED.**

  Run: `uv run pytest tests/unit/test_course_details_docs.py -q`

  Expected: collection or guide assertions fail because the new guide/test does not exist.

- [ ] **Step 3: Write the guide and current-doc links.**

  `docs/course-details.md` must contain: purpose and explicit-question workflow; exact signature; one-call endpoint; success/partial/error examples; every fixed error/warning code and message; activity mapping table; name and metric null/partial semantics; ID validation; geometry ignored rather than parsed; privacy exclusions; no GPX/export/write behavior; and explicit availability through `upstream-full` or `GARMIN_ENABLED_TOOLS=get_course_details` only. State that it is outside `ai-coach` and is not added to training context or automatic coaching.

  Add one advanced-course-read link to the documentation/development area of `README.md` and one link plus opt-in paragraph to the runtime section of `docs/setup.md`. Do not change the existing 17-tool names, count, profile semantics, or current AI guide claims.

- [ ] **Step 4: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/test_course_details_docs.py tests/unit/test_readme_docs.py tests/unit/test_ai_target_events_docs.py -q`

  Expected: the new guide contract and existing profile/documentation contracts pass.

  ```bash
  git add README.md docs/setup.md docs/course-details.md tests/unit/test_course_details_docs.py
  git commit -m "docs(courses): document opt-in course details"
  ```

### Task 7: Independent review checkpoint and regression fixes

**Files:**

- Review all changed feature/source/test/docs files.
- Modify only files implicated by concrete review findings.

- [ ] **Step 1: Run the focused feature matrix before review.**

  Run:

  ```bash
  uv run pytest tests/unit/test_course_details.py \
    tests/integration/test_course_details_tools.py \
    tests/unit/test_server_startup.py \
    tests/unit/test_tool_filter.py \
    tests/unit/test_course_details_docs.py -q
  ```

  Expected: all feature, registration, filter, and documentation tests pass offline.

- [ ] **Step 2: Have an independent reviewer audit the diff against the approved spec.**

  Ask an independent subagent to inspect the branch diff with `git diff main...HEAD` and report only concrete findings. The review must explicitly check: strict ID edge cases; exact provider path and one-call budget; provider exception suppression; exact root/provider-ID validation; warning order and deduplication; finite numeric handling; no geometry inspection; no raw/private field leakage; exact response keys; FastMCP strict schema; ai-coach 17-tool preservation; upstream-full/allowlist/denylist exposure; and docs/spec consistency.

- [ ] **Step 3: Convert every real finding into a RED regression test before fixing it.**

  For each accepted finding, add a named test to `tests/unit/test_course_details.py` or `tests/integration/test_course_details_tools.py`, run that test alone and record the failure, then apply the smallest production patch. Do not weaken the fixed contract to satisfy a test. If the review has no findings, make no empty commit.

- [ ] **Step 4: Run GREEN after review fixes and commit narrowly.**

  Run the focused matrix from Step 1. For each fix, use a Conventional Commit such as:

  ```bash
  git add src/garmin_mcp/course_details.py tests/unit/test_course_details.py
  git commit -m "fix(courses): harden course detail boundary"
  ```

### Task 8: Full verification and fork PR readiness

**Files:**

- Verify the complete branch; modify only files implicated by failing checks.

- [ ] **Step 1: Run all offline tests and packaging checks.**

  Run each command separately:

  ```bash
  uv run pytest -m "not e2e" -q
  uv lock --check
  uv build
  git diff --check main...HEAD
  git status --short
  ```

  Expected: the offline suite passes with e2e tests deselected; lock check and build pass; diff check is clean; only intentional committed branch state remains. Do not run live Garmin calls as part of the normal gate.

- [ ] **Step 2: Inspect the final diff and verify `courses.py` is unchanged.**

  Run:

  ```bash
  git diff --name-only main...HEAD
  git diff --stat main...HEAD
  git diff -- src/garmin_mcp/courses.py
  ```

  Expected changed paths are limited to the new module, root registration, focused tests, README/setup, course-details docs, and the approved design/plan artifacts if they are intentionally carried onto the implementation branch; `git diff -- src/garmin_mcp/courses.py` is empty.

- [ ] **Step 3: Prepare the fork PR body with a human editing pass.**

  The body must state: one read-only detail endpoint call; fixed scalar/privacy projection; geometry ignored; no upload/list/delete changes; default ai-coach remains 17 tools; upstream-full/explicit allowlist exposure; offline test/build evidence; and no upstream PR is being opened from this branch. Do not include raw Garmin IDs, account data, exception text, or live payloads.

- [ ] **Step 4: Push and open the fork PR only after the branch is verified.**

  ```bash
  git push -u origin feat/course-details
  gh pr create --base main --head feat/course-details \
    --title "feat: add opt-in safe course details read" \
    --body-file /tmp/garmin-course-details-pr.md
  ```

  Use `gh pr view` and `gh pr diff` to inspect the created PR. Do not create an upstream PR in this task.

- [ ] **Step 5: Inspect fork CI and hand off merge readiness.**

  Run:

  ```bash
  gh pr view --json number,title,state,mergeable,statusCheckRollup
  gh run list --branch feat/course-details --limit 10
  ```

  If CI fails, inspect the failing run, add a regression test where appropriate, fix the root cause, rerun the full offline gate, push the fix, and re-check the PR. Do not merge until required fork checks are green and the independent review has no unresolved findings.

- [ ] **Step 6: Merge the green fork PR and confirm the remote merged state.**

  After required fork CI is green and the independent review has no unresolved findings, merge with the requested merge commit and remote branch cleanup:

  ```bash
  gh pr merge "$PR_NUMBER" --merge --delete-branch
  gh pr view "$PR_NUMBER" --json number,state,mergedAt,mergeCommit
  ```

  Expected: `state` is `MERGED`, `mergedAt` is non-null, and `mergeCommit` is present. If the PR is not mergeable or checks are not green, stop and report the exact blocker; do not force-merge or delete branches manually.

- [ ] **Step 7: Safely fast-forward local `main` while preserving the user-owned untracked plan.**

  Record the untracked plan’s hash before switching branches, fast-forward only, and verify the file afterward:

  ```bash
  repo=/Users/wouterrodeyns/Documents/Personal/garmin_mcp
  target_plan="$repo/docs/superpowers/plans/2026-08-21-ai-target-events.md"
  target_plan_hash_before=$(shasum -a 256 "$target_plan" | awk '{print $1}')
  git -C "$repo" status --short --branch
  git -C "$repo" fetch origin main
  git -C "$repo" switch main
  git -C "$repo" merge --ff-only origin/main
  test -f "$target_plan"
  test "$(shasum -a 256 "$target_plan" | awk '{print $1}')" = "$target_plan_hash_before"
  git -C "$repo" status --short --branch
  ```

  Expected: local `main` equals `origin/main`, the untracked plan still exists with the same hash, and no reset/restore/clean operation was used.

- [ ] **Step 8: Run focused post-merge verification.**

  From local `main`, rerun the feature and registration gates:

  ```bash
  cd /Users/wouterrodeyns/Documents/Personal/garmin_mcp
  uv run pytest tests/unit/test_course_details.py \
    tests/integration/test_course_details_tools.py \
    tests/unit/test_server_startup.py \
    tests/unit/test_tool_filter.py \
    tests/unit/test_course_details_docs.py -q
  git status --short --branch
  ```

  Expected: all focused tests pass after the merge and the only remaining untracked file is the preserved user-owned AI-target-events plan.

### Task 9: Read-only evaluation of a separate narrowed upstream contribution

**Files:**

- Read-only: merged fork PR, original upstream course PR/context, and the final fork diff.
- Modify: none.

- [ ] **Step 1: Inspect current upstream context without creating or commenting on a PR.**

  Use read-only commands to compare the merged scalar contract with the original upstream course work:

  ```bash
  gh pr view 260 --repo Taxuspt/garmin_mcp --json number,title,state,headRefName,baseRefName,mergeable,body
  gh pr diff 260 --repo Taxuspt/garmin_mcp
  git -C /Users/wouterrodeyns/Documents/Personal/garmin_mcp show --stat --oneline HEAD
  ```

  Confirm whether the upstream project could accept only the isolated scalar read without importing fork-specific profiles, privacy defaults, docs, or unrelated course upload behavior. Record concrete compatibility differences, test portability, and maintainer-facing scope.

- [ ] **Step 2: Decide whether a separate narrowed upstream PR is justified, without opening one.**

  Recommend `not suitable` when the upstream API/client contract, project architecture, or maintainer scope would require bundling fork-only behavior; recommend `potentially suitable` only when the scalar read can stand alone with its fixed privacy boundary and upstream-compatible tests. Do not run `gh pr create`, `gh pr comment`, or any other upstream write. A new explicit user decision is required before any upstream PR is drafted or created.

## Plan self-review checklist

- The plan covers every spec requirement: strict IDs, fixed envelope, one provider call, all error/warning codes, field mapping, privacy/geometry isolation, no writes, and exact filter behavior.
- Every source behavior begins with a named RED test, has a concrete GREEN command, and uses a small Conventional Commit.
- The plan never edits or proposes edits to `courses.py`, adds no dependency, and preserves the exact 17-tool ai-coach profile.
- The full registration reference is updated so upstream-full cannot silently omit the tool.
- Documentation and docs tests cover the opt-in boundary without presenting the feature as coaching context.
- Review, full offline verification, fork PR/CI/merge/post-merge steps, and the explicit read-only upstream-evaluation/no-PR boundary are included.
