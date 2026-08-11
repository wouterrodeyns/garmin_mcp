# AI Activity Analysis v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded, factual, read-only `analyze_activity(activity_id)` MCP tool that returns a stable summary and sport-relevant Garmin breakdown for one completed activity.

**Architecture:** Keep all fork-owned behavior in `src/garmin_mcp/ai_activity/`. Five provider seams call only the pinned Garmin client methods; a service owns input validation, sport gating, normalization, warnings, status, and mechanical split derivations; the MCP adapter only configures the shared proxied client and JSON-encodes the result. Integrate the package in `garmin_mcp/__init__.py` without rewriting upstream-oriented modules.

**Tech Stack:** Python 3.10+, `garminconnect==0.3.2`, FastMCP, pytest, pytest-asyncio, dataclasses, JSON.

---

## File map

- Create `src/garmin_mcp/ai_activity/__init__.py`: public constants plus configure/register entry points.
- Create `src/garmin_mcp/ai_activity/providers.py`: immutable provider result and five direct client-read wrappers.
- Create `src/garmin_mcp/ai_activity/service.py`: identifier validation, family classification, stable envelope, normalization, gating, warnings, and derived pace comparison.
- Create `src/garmin_mcp/ai_activity/tools.py`: configured-client storage and the exact async MCP signature.
- Create `tests/unit/ai_activity/test_providers.py` and `tests/unit/ai_activity/test_service.py`: seam and service contract tests.
- Create `tests/integration/test_ai_activity_tools.py`: FastMCP schema, JSON, registration, and read-only tests.
- Create `docs/ai-activity.md` and `tests/unit/test_ai_activity_docs.py`: live feature documentation and contract tests.
- Modify `src/garmin_mcp/__init__.py`, `tests/unit/test_tool_filter.py`, `tests/unit/test_server_startup.py`, `tests/unit/test_readme_docs.py`, `tests/unit/test_ai_training_docs.py`, `README.md`, `docs/setup.md`, `docs/ai-training.md`, and `docs/ai-workouts.md` for package integration and the exact 12-tool profile.

### Task 1: Provider seams

**Files:**
- Create: `tests/unit/ai_activity/test_providers.py`
- Create: `src/garmin_mcp/ai_activity/__init__.py`
- Create: `src/garmin_mcp/ai_activity/providers.py`

- [ ] **Step 1: Write failing provider seam tests.** Use a recording client that raises on unknown attributes and assert every wrapper passes the normalized integer directly to the pinned method, preserves raw data, converts exceptions to `ProviderResult(data=None, failed=True)`, and never exposes exception text. Pin the public family constants and cap:

```python
def test_provider_methods_are_direct_reads_in_fixed_order():
    calls = []
    client = SimpleNamespace(
        get_activity=lambda value: (calls.append(("activity", value)), {"activityId": value})[1],
        get_activity_splits=lambda value: (calls.append(("splits", value)), {"lapDTOs": []})[1],
        get_activity_hr_in_timezones=lambda value: (calls.append(("heart_rate_zones", value)), [])[1],
        get_activity_power_in_timezones=lambda value: (calls.append(("power_zones", value)), [])[1],
        get_activity_exercise_sets=lambda value: (calls.append(("strength", value)), {"exercises": []})[1],
    )
    assert get_activity(client, 42).data == {"activityId": 42}
    assert get_splits(client, 42).data == {"lapDTOs": []}
    assert get_heart_rate_zones(client, 42).data == []
    assert get_power_zones(client, 42).data == []
    assert get_strength(client, 42).data == {"exercises": []}
    assert calls == [("activity", 42), ("splits", 42), ("heart_rate_zones", 42), ("power_zones", 42), ("strength", 42)]

def test_provider_exception_is_bounded():
    def raise_secret(_id):
        raise RuntimeError("token=secret@example.com")
    client = SimpleNamespace(get_activity=raise_secret)
    result = get_activity(client, 7)
    assert result.failed is True
    assert result.data is None
    assert "secret@example.com" not in str(result)
```

Also test `ProviderResult` is frozen and assert `RUNNING_TYPE_KEYS`, `WALKING_TYPE_KEYS`, `CYCLING_TYPE_KEYS`, `STRENGTH_TYPE_KEYS`, and `MAX_RETURNED_SPLITS == 100` exactly match the spec.

- [ ] **Step 2: Run the focused tests and verify the expected failure.**

Run: `uv run pytest tests/unit/ai_activity/test_providers.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'garmin_mcp.ai_activity'`.

- [ ] **Step 3: Implement the five wrappers and constants.** Define `ProviderResult(data, failed=False)` as a frozen dataclass. Each function must call exactly one method: `get_activity`, `get_activity_splits`, `get_activity_hr_in_timezones`, `get_activity_power_in_timezones`, or `get_activity_exercise_sets`; catch `Exception` and return `ProviderResult(None, failed=True)`. Do not parse payloads, call `connectapi`, call raw request methods, or return JSON.

```python
def _read(client: Any, method_name: str, activity_id: int) -> ProviderResult:
    try:
        return ProviderResult(getattr(client, method_name)(activity_id))
    except Exception:
        return ProviderResult(None, failed=True)

def get_activity(client: Any, activity_id: int) -> ProviderResult:
    return _read(client, "get_activity", activity_id)
```

Export all five wrappers and constants from `__init__.py`; leave `configure` and `register_tools` as imports that are added when `tools.py` exists.

- [ ] **Step 4: Run the provider tests and commit.**

Run: `uv run pytest tests/unit/ai_activity/test_providers.py -q`

Expected: `PASS` with all provider seam tests green.

```bash
git add src/garmin_mcp/ai_activity/__init__.py src/garmin_mcp/ai_activity/providers.py tests/unit/ai_activity/test_providers.py
git commit -m "feat: add ai activity provider seams"
```

### Task 2: Base service and stable activity envelope

**Files:**
- Create: `tests/unit/ai_activity/test_service.py`
- Create: `src/garmin_mcp/ai_activity/service.py`

- [ ] **Step 1: Write failing base-service tests first.** Cover accepted integer/trimmed ASCII decimal IDs and rejection of booleans, zero, negatives, floats, signed/decimal/exponent/Unicode-digit strings, empty strings, lists, and objects before any provider call. Add tests for `client_unavailable`, empty base (`activity_not_found`), malformed/mismatched IDs (`invalid_activity_response`), the exact 10-key top-level envelope, null optional sections, and all mapped base fields including alternate `activityType.typeKey`/`eventType.typeKey` fallbacks.

```python
def test_invalid_ids_make_no_garmin_call(monkeypatch, bad_id):
    activity = Mock()
    monkeypatch.setattr(service, "get_activity", activity)
    result = analyze_activity_service(Mock(), bad_id)
    assert result["status"] == "error"
    assert result["error"] == {"code": "invalid_activity_id", "message": "activity_id must be a positive integer or decimal string."}
    activity.assert_not_called()

def test_base_mapping_has_stable_nested_nulls(monkeypatch):
    monkeypatch.setattr(service, "get_activity", lambda _client, value: ProviderResult({
        "activityId": value, "activityName": " Run ", "activityTypeDTO": {"typeKey": "running"},
        "eventTypeDTO": {"typeKey": "training"}, "summaryDTO": {"duration": 259.6, "distance": 1000, "averageHR": 151},
    }))
    result = analyze_activity_service(Mock(), " 42 ")
    assert result["activity"]["id"] == 42
    assert result["activity"]["name"] == "Run"
    assert result["activity"]["heart_rate"] == {"average_bpm": 151, "max_bpm": None, "min_bpm": None}
    assert result["activity"]["distance_km"] == 1.0
    assert result["activity"]["duration_minutes"] == 4.3
```

Use hard-coded expected values and fixtures containing secret-like strings to prove names/descriptions are trimmed and bounded without leaking them in errors.

- [ ] **Step 2: Run the service tests to capture the expected failure.**

Run: `uv run pytest tests/unit/ai_activity/test_service.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'garmin_mcp.ai_activity.service'`.

- [ ] **Step 3: Implement identifier validation and the base envelope.** Define `analyze_activity_service(client, activity_id) -> dict[str, Any]`, `_normalize_activity_id`, `_empty_result`, `_normalize_activity`, `_classify_sport`, `_finite`, `_text`, and the fixed error messages. Accept only `int` (not `bool`) greater than zero or `str.strip().isdigit()` whose every character is ASCII `0-9` and whose integer is positive. Call `get_activity` once with the normalized integer. A missing client, raised provider, empty response, non-object response, missing/non-positive/mismatched `activityId`, or non-finite required ID returns the specified error envelope; no optional provider is called.

The successful activity object must always contain `id`, `name`, `description`, `sport`, `sport_family`, `event_type`, `start_time_local`, `duration_minutes`, `moving_duration_minutes`, `elapsed_duration_minutes`, `distance_km`, `average_speed_kph`, `max_speed_kph`, `average_pace`, nested `heart_rate`, `power`, `cadence`, `elevation`, `training_effect`, `workout_feedback`, `recovery`, and `reported_lap_count`, with absent values `None`. Apply physical validity, raw-first conversions, and string bounds (description 500, name 200, other strings 100). Keep `derived` six keys all null until split processing.

```python
def _envelope() -> dict[str, Any]:
    return {"status": "success", "error": None, "activity": None,
            "availability": {key: False for key in AVAILABILITY_KEYS},
            "splits": None, "heart_rate_zones": None, "power_zones": None,
            "strength": None, "derived": dict.fromkeys(DERIVED_KEYS), "warnings": []}
```

- [ ] **Step 4: Run the focused service tests and commit.**

Run: `uv run pytest tests/unit/ai_activity/test_service.py -q`

Expected: `PASS` for input validation, base failure envelopes, mapping, null semantics, and normalization tests.

```bash
git add src/garmin_mcp/ai_activity/service.py tests/unit/ai_activity/test_service.py
git commit -m "feat: normalize ai activity base summaries"
```

### Task 3: Splits, gating, cap, and mechanical pace derivations

**Files:**
- Modify: `tests/unit/ai_activity/test_service.py`
- Modify: `src/garmin_mcp/ai_activity/service.py`

- [ ] **Step 1: Add failing split tests before implementation.** Assert running/walking split gating, literal `metadataDTO.hasSplits is False` suppression, missing/null metadata still allowing the call, fixed provider order, 0/1/100/101 source laps, invalid item dropping with one warning, `None`/`{}` absence without warning, wrong non-empty roots as `partial_success`, exact split fields, source order, and hard-coded raw-first fastest/slowest/range values with source-order tie breaking. Assert cycling and generic families never populate pace-derived fields.

```python
def test_101_laps_keep_first_100_and_clear_derived_comparisons(monkeypatch):
    monkeypatch.setattr(service, "get_activity", lambda _c, value: ProviderResult(base("running", value)))
    monkeypatch.setattr(service, "get_splits", lambda _c, _value: ProviderResult({"lapDTOs": [lap(i) for i in range(101)]}))
    result = analyze_activity_service(Mock(), 42)
    assert result["splits"]["total_count"] == 101
    assert result["splits"]["returned_count"] == 100
    assert result["splits"]["truncated"] is True
    assert result["derived"] == {key: None for key in DERIVED_KEYS}
    assert [warning["code"] for warning in result["warnings"]] == ["splits_truncated"]
    assert result["status"] == "success"
```

- [ ] **Step 2: Run the split tests and verify the expected failures.**

Run: `uv run pytest tests/unit/ai_activity/test_service.py -k split -q`

Expected: FAIL because optional split reads and split normalization/derivation are not implemented; the base-only result has `splits is None`.

- [ ] **Step 3: Implement split normalization and gating.** After a valid base, call `get_splits` only for running, walking, or cycling, unless `metadataDTO.hasSplits` is the literal `False`; call it before applicable zones. Accept only an object with a list `lapDTOs`; `None`/`{}` is legitimate absence, an explicitly empty list is available, other non-empty roots are malformed. Normalize the exact lap table, convert metres/seconds, calculate run/walk pace from raw duration and distance, retain usable objects, emit one fixed warning for malformed entries, cap source order at `MAX_RETURNED_SPLITS`, and add `splits_truncated` without changing success status.

Implement `_pace(duration_seconds, distance_meters)` as `int(round(duration_seconds / (distance_meters / 1000)))` formatted `M:SS/km`; calculate extrema only over positive raw duration/distance, use `lap_number` when positive otherwise returned position, and calculate range from raw pace values. Set `derived.scope` to `all_returned_splits` only when comparisons exist and the response was not truncated.

- [ ] **Step 4: Run split tests and commit.**

Run: `uv run pytest tests/unit/ai_activity/test_service.py -k split -q`

Expected: `PASS` with call-order, cap, warning, and derivation assertions green.

```bash
git add src/garmin_mcp/ai_activity/service.py tests/unit/ai_activity/test_service.py
git commit -m "feat: add bounded activity split analysis"
```

### Task 4: Heart-rate/power zones and strength sets

**Files:**
- Modify: `tests/unit/ai_activity/test_service.py`
- Modify: `src/garmin_mcp/ai_activity/service.py`

- [ ] **Step 1: Add failing zone and strength tests.** Pin all cycling keys and running/walking keys, positive finite HR/power signal gating (booleans do not count), exactly four cycling calls when both signals exist, signal-specific skips without warnings, strength’s exactly two calls, empty/absent roots, mixed invalid entries, explicit units/boundaries, one-decimal durations/percentages, no zone labels, and strength counts distinguishing missing reps from known zero while omitting weight/volume.

```python
def test_strength_normalizes_counts_without_weight(monkeypatch):
    monkeypatch.setattr(service, "get_activity", lambda _c, value: ProviderResult(base("strength_training", value)))
    monkeypatch.setattr(service, "get_strength", lambda _c, _value: ProviderResult({"exercises": [{
        "exerciseName": " Bench Press ", "sets": [
            {"setNumber": 1, "reps": 10, "weight": 80}, {"setNumber": 2, "reps": 0}, {"setNumber": 3}
        ]}]}))
    result = analyze_activity_service(Mock(), 22334455)
    assert result["strength"]["set_count"] == 3
    assert result["strength"]["repetition_count"] == 10
    assert "weight" not in result["strength"]["items"][0]["sets"][0]
    assert result["availability"] == {"activity": True, "splits": False, "heart_rate_zones": False, "power_zones": False, "strength": True}
```

- [ ] **Step 2: Run the new tests and verify the expected failures.**

Run: `uv run pytest tests/unit/ai_activity/test_service.py -k 'zone or strength or cycling or signal' -q`

Expected: FAIL because zone and exercise-set sections remain null and the service has no sport-specific follow-up normalization.

- [ ] **Step 3: Implement zone and strength normalization.** For HR/power roots accept a top-level list or `{ "zones": list }`; for strength accept an object containing `exercises: list`. Treat `None`/`{}` as unavailable without warnings and recognized empty lists as available empty sections. Retain objects with at least one valid recognized value, drop invalid entries, emit one provider-level `invalid_provider_response`, and set `partial_success` when a non-empty attempted response is malformed. Validate positive integer zone numbers, finite non-negative seconds/boundaries, percentages 0–100, positive integer set numbers, non-negative integer reps, and trimmed bounded names. Convert seconds to one-decimal minutes and preserve Garmin percentages without renormalizing. Ignore all strength weight/resistance/unit/duration/volume fields.

Signal helpers must accept a finite number greater than zero from the exact summary paths and reject booleans. Call optional providers in this order: splits, HR zones, power zones, strength; strength is mutually exclusive with endurance providers.

- [ ] **Step 4: Run focused tests and commit.**

Run: `uv run pytest tests/unit/ai_activity/test_service.py -k 'zone or strength or cycling or signal' -q`

Expected: `PASS` with exact call budgets (run/walk 3, cycling 4, strength 2, generic 1) and normalized section assertions green.

```bash
git add src/garmin_mcp/ai_activity/service.py tests/unit/ai_activity/test_service.py
git commit -m "feat: normalize activity zones and strength sets"
```

### Task 5: Failure/status matrix and read-only guarantees

**Files:**
- Modify: `tests/unit/ai_activity/test_service.py`
- Modify: `src/garmin_mcp/ai_activity/service.py`

- [ ] **Step 1: Add failing failure and security tests.** Pin base raises as sanitized `activity_unavailable` with no optional calls; missing client, empty base, malformed base, and mismatched IDs; each optional provider raising or returning a wrong non-empty root as `partial_success`; ordered fixed warnings for multiple failures; no raw exception, URL, token, email, header, or request identifier; and a recording client whose common write/raw-request attributes raise immediately.

```python
def test_optional_failure_continues_in_order_and_sanitizes(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "get_activity", lambda _c, value: (calls.append("activity"), ProviderResult(base("cycling", value, averageHR=140, averagePower=200)))[1])
    monkeypatch.setattr(service, "get_splits", lambda *_: (calls.append("splits"), ProviderResult({}, failed=True))[1])
    monkeypatch.setattr(service, "get_heart_rate_zones", lambda *_: (calls.append("heart_rate_zones"), ProviderResult(None, failed=True))[1])
    monkeypatch.setattr(service, "get_power_zones", lambda *_: (calls.append("power_zones"), ProviderResult([]))[1])
    result = analyze_activity_service(RecordingReadOnlyClient(), 9)
    assert result["status"] == "partial_success"
    assert calls == ["activity", "splits", "heart_rate_zones", "power_zones"]
    assert [item["provider"] for item in result["warnings"]] == ["splits", "heart_rate_zones"]
    assert "token=" not in json.dumps(result)
```

- [ ] **Step 2: Run the failure/security tests and verify expected failures.**

Run: `uv run pytest tests/unit/ai_activity/test_service.py -k 'failure or unavailable or warning or read_only' -q`

Expected: FAIL where optional provider results are not yet converted to the complete warning/status matrix; no implementation should invoke a write method.

- [ ] **Step 3: Complete status, warning, and envelope handling.** Centralize fixed provider/code messages and error messages from the spec. Preserve the complete envelope on every error with `activity: None`, five false availability flags, null detail sections, six null derived fields, and empty warnings. For valid bases continue all applicable optional reads after an individual failure; set `partial_success` iff an attempted provider raised or was malformed, except truncation alone remains `success`. Never include exception text or raw payloads in output.

- [ ] **Step 4: Run the full unit service/security slice and commit.**

Run: `uv run pytest tests/unit/ai_activity -q`

Expected: `PASS` for all provider, service, warning, status, and read-only tests; every selected test executes.

```bash
git add src/garmin_mcp/ai_activity/service.py tests/unit/ai_activity/test_service.py
git commit -m "feat: harden activity analysis failures and warnings"
```

### Task 6: MCP adapter, package integration, and ai-coach profile

**Files:**
- Create: `src/garmin_mcp/ai_activity/tools.py`
- Modify: `src/garmin_mcp/ai_activity/__init__.py`
- Modify: `src/garmin_mcp/__init__.py`
- Create: `tests/integration/test_ai_activity_tools.py`
- Modify: `tests/unit/test_tool_filter.py`
- Modify: `tests/unit/test_server_startup.py`

- [ ] **Step 1: Add failing MCP/profile tests.** Assert `analyze_activity` has the required argument-only schema, exact async annotation/signature, a description containing read-only/factual/bounded/sport-aware/null interpretation language, exact top-level JSON keys, and no cap/sport/provider/date arguments. Assert startup configures/registers the package, and `TOOL_PROFILES["ai-coach"]` equals exactly the 12 names in the spec with no tool removed.

```python
@pytest.mark.asyncio
async def test_analyze_activity_schema_and_json(monkeypatch):
    client = recording_client_with_base("running", 42)
    ai_activity.configure(client)
    app = FastMCP("test")
    ai_activity.register_tools(app)
    tool = {item.name: item for item in await app.list_tools()}["analyze_activity"]
    assert set(tool.inputSchema["properties"]) == {"activity_id"}
    assert tool.inputSchema["required"] == ["activity_id"]
    payload = json.loads((await app.call_tool("analyze_activity", {"activity_id": " 42 "}))[0][0].text)
    assert list(payload) == ["status", "error", "activity", "availability", "splits", "heart_rate_zones", "power_zones", "strength", "derived", "warnings"]
```

- [ ] **Step 2: Run the MCP/profile tests and verify expected failures.**

Run: `uv run pytest tests/integration/test_ai_activity_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py -q`

Expected: FAIL with `KeyError: 'analyze_activity'` or an absent registered tool/profile member because the adapter and root integration do not yet exist.

- [ ] **Step 3: Implement the adapter and atomic root integration.** In `tools.py`, store `garmin_client`, expose `configure(client)`, and register exactly:

```python
@app.tool()
async def analyze_activity(activity_id: int | str) -> str:
    """Read one completed Garmin activity as bounded factual, sport-aware evidence.

    This tool is read-only; optional Garmin detail may be null or unavailable.
    Interpret the returned facts as evidence rather than coaching advice.
    """
    return json.dumps(analyze_activity_service(garmin_client, activity_id), indent=2)
```

Import the package in `src/garmin_mcp/__init__.py`, call `ai_activity.configure(garmin_client)` with the other modules, and register it in the same startup path. Add `"analyze_activity"` to `TOOL_PROFILES["ai-coach"]` in the same change, preserving every existing member and allowlist/denylist precedence. Export configure/register from package `__init__.py` without importing a live client.

- [ ] **Step 4: Run integration/profile/startup tests and commit.**

Run: `uv run pytest tests/integration/test_ai_activity_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py -q`

Expected: `PASS`; the profile registration test must report the exact 12-tool set and startup must report no unknown configured tool.

```bash
git add src/garmin_mcp/ai_activity src/garmin_mcp/__init__.py tests/integration/test_ai_activity_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
git commit -m "feat: register analyze activity MCP tool"
```

### Task 7: Documentation contracts and final verification

**Files:**
- Create: `docs/ai-activity.md`
- Create: `tests/unit/test_ai_activity_docs.py`
- Modify: `README.md`
- Modify: `docs/setup.md`
- Modify: `docs/ai-training.md`
- Modify: `docs/ai-workouts.md`
- Modify: `tests/unit/test_readme_docs.py`
- Modify: `tests/unit/test_ai_training_docs.py`

- [ ] **Step 1: Write failing documentation contract tests.** Require `docs/ai-activity.md` to state the feedback-loop role, four sport families and exact provider gating, stable envelope/availability/null semantics, warning/status meanings, raw-first conversions and 100-lap cap, mechanical (not coaching) derivations, read-only guarantee, device/account variability, workout-sport translation, all v1 exclusions, and the identify → analyze → interpret → confirm → create workflow. Require all current published 12-tool lists to equal the profile and reject current-facing `exactly 11` claims.

```python
def test_activity_docs_pin_read_only_bounds_and_non_goals():
    text = Path("docs/ai-activity.md").read_text().lower()
    for phrase in ("analyze_activity", "read-only", "running", "walking", "cycling", "strength", "null", "100 laps", "mechanical", "weight", "fit", "create_workout.sport"):
        assert phrase in text

def test_live_docs_use_twelve_tool_profile():
    for path in ("README.md", "docs/setup.md", "docs/ai-training.md", "docs/ai-workouts.md"):
        text = Path(path).read_text().lower()
        assert "analyze_activity" in text
        assert "exactly 11 tools" not in text
```

- [ ] **Step 2: Run docs tests and verify expected failures.**

Run: `uv run pytest tests/unit/test_ai_activity_docs.py tests/unit/test_readme_docs.py tests/unit/test_ai_training_docs.py -q`

Expected: FAIL because `docs/ai-activity.md` and the new tool/profile wording do not exist yet; existing historical specs/plans are intentionally not changed.

- [ ] **Step 3: Implement the documentation and update live tool lists.** Write the complete feature guide with the exact response contract, gating table, warning/error vocabulary, missing-vs-zero rules, transparent conversions, cap/truncation behavior, non-goals, read-only/security behavior, raw Garmin type keys versus `create_workout.sport`, and the confirmation workflow. Update live README/setup/training/workout text so `get_training_context` remains the coach’s eyes, `create_workout` remains its hands, and `analyze_activity` is the completed-session feedback read. Every 12-tool list must exactly match the profile; do not rewrite historical design records.

- [ ] **Step 4: Run mandatory verification and inspect the diff.**

Run: `uv run pytest tests/unit/ai_activity tests/integration/test_ai_activity_tools.py tests/unit/test_ai_activity_docs.py tests/unit/test_server_startup.py tests/unit/test_tool_filter.py`

Expected: `PASS` with no failures and exact profile/startup assertions green.

Run: `uv run pytest -m "not e2e"`

Expected: `PASS`; existing authentication, filtering, legacy activity, workout, and offline tests remain green.

Run: `git diff --check && rg -n "exactly 11|analyze_activity|TOOL_PROFILES" README.md docs src/garmin_mcp tests/unit tests/integration`

Expected: no whitespace errors; all current-facing lists mention `analyze_activity`, no current docs claim exactly 11, and the only profile has 12 members. Review `git diff --stat` to ensure only the paths in this plan changed.

- [ ] **Step 5: Commit the complete documentation and verified implementation.**

```bash
git add README.md docs/ai-activity.md docs/setup.md docs/ai-training.md docs/ai-workouts.md tests/unit/test_ai_activity_docs.py tests/unit/test_readme_docs.py tests/unit/test_ai_training_docs.py
git commit -m "docs: document ai activity analysis"
```

## Self-review checklist

- [ ] The five provider methods, fixed sport vocabulary, identifier rules, stable envelope, all base mappings, optional gating, normalization rules, warnings/status matrix, caps, mechanical derivations, read-only guarantees, MCP schema, profile, and documentation requirements each have a test-first task above.
- [ ] Every code-changing step names an exact file and includes a representative implementation/test snippet; every test step includes an exact command and expected failure or success.
- [ ] No runtime code is changed while writing this plan, every instruction is concrete, and commits are split at each independently testable milestone.
