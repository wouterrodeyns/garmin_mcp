# AI Workouts v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one LLM-friendly `create_workout` operation that compiles a compact workout DSL, passes it through Taxuspt's safety gate, uploads it, and optionally schedules it.

**Architecture:** Fork-specific code lives in `garmin_mcp.ai_workouts`, split into normalized schema, parsing, Garmin compilation, orchestration, and MCP registration. Existing `workouts.py` gains only reusable preparation and idempotent scheduling seams; the current filter gains an opt-in `ai-coach` profile without changing defaults.

**Tech Stack:** Python 3.10+, standard-library dataclasses/regex/date parsing, FastMCP 1.x, pinned `garminconnect==0.3.2`, pytest, pytest-asyncio, unittest.mock.

---

## File Map

Create:

- `src/garmin_mcp/ai_workouts/{__init__,schema,parsing,compiler,service,tools}.py`
- `tests/unit/ai_workouts/{__init__,test_parsing,test_compiler}.py`
- `tests/integration/test_ai_workouts_tools.py`
- `tests/unit/test_ai_workouts_docs.py`
- `docs/ai-workouts.md`

Modify:

- `src/garmin_mcp/workouts.py`
- `src/garmin_mcp/__init__.py`
- `tests/integration/test_workouts_tools.py`
- `tests/unit/test_tool_filter.py`
- `tests/unit/test_server_startup.py`
- `.gitignore`
- `README.md`

## Task 1: Friendly schema and parser registry

**Files:**

- Create: `src/garmin_mcp/ai_workouts/__init__.py`
- Create: `src/garmin_mcp/ai_workouts/schema.py`
- Create: `src/garmin_mcp/ai_workouts/parsing.py`
- Create: `tests/unit/ai_workouts/__init__.py`
- Create: `tests/unit/ai_workouts/test_parsing.py`

- [ ] **Step 1: Write failing primitive parser tests**

Create tests for the exact public contract:

```python
def test_parse_duration_supports_seconds_minutes_and_hours():
    assert parse_duration("90s") == 90.0
    assert parse_duration("15m") == 900.0
    assert parse_duration("1.5h") == 5400.0

def test_parse_distance_supports_metres_and_kilometres():
    assert parse_distance("800m") == 800.0
    assert parse_distance("5km") == 5000.0

def test_parse_pace_returns_faster_then_slower_mps():
    assert parse_pace("4:20-4:30/km") == pytest.approx((1000 / 260, 1000 / 270))

def test_parse_ranges_zones_and_date():
    assert parse_heart_rate("150-165bpm") == (150.0, 165.0)
    assert parse_power("220-250W") == (220.0, 250.0)
    assert parse_zone("Z3", maximum=5, field="heart_rate_zone") == 3
    assert parse_zone(7, maximum=7, field="power_zone") == 7
    assert parse_date("2026-08-10").isoformat() == "2026-08-10"

@pytest.mark.parametrize("value", ["15", "m15", "0m", "-2m", "1 minute"])
def test_parse_duration_rejects_malformed_values(value):
    with pytest.raises(ValueError, match="duration"):
        parse_duration(value)

@pytest.mark.parametrize("value", ["4:20/km", "4:70-5:00/km", "4:30-4:20/km"])
def test_parse_pace_rejects_malformed_or_inverted_values(value):
    with pytest.raises(ValueError, match="pace"):
        parse_pace(value)

def test_parse_date_rejects_impossible_date():
    with pytest.raises(ValueError, match="schedule_date"):
        parse_date("2026-02-30")
```

- [ ] **Step 2: Run parser tests and verify RED**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/ai_workouts/test_parsing.py -v`

Expected: `ModuleNotFoundError: No module named 'garmin_mcp.ai_workouts'`.

- [ ] **Step 3: Implement primitive parsers and extension registries**

Use anchored regexes. Require positive quantities and low `<` high for HR/power. Require the first pace to be no slower than the second. `parse_date` must call `date.fromisoformat` and require canonical `YYYY-MM-DD`.

```python
END_CONDITION_PARSERS = {
    "duration": parse_duration,
    "distance": parse_distance,
    "reps": parse_reps,
    "lap_button": parse_lap_button,
}
TARGET_PARSERS = {
    "pace": parse_pace,
    "heart_rate_zone": lambda value: parse_zone(value, 5, "heart_rate_zone"),
    "heart_rate": parse_heart_rate,
    "power_zone": lambda value: parse_zone(value, 7, "power_zone"),
    "power": parse_power,
}
```

- [ ] **Step 4: Run primitive tests and verify GREEN**

Run the Step 2 command. Expected: all primitive parser tests pass.

- [ ] **Step 5: Write failing raw-schema normalization tests**

Define this module constant before the tests:

```python
THRESHOLD_STEPS = [
    {"warmup": {"duration": "15m"}},
    {"repeat": 4, "steps": [
        {"run": {"duration": "6m", "pace": "4:20-4:30/km"}},
        {"recovery": {"duration": "2m"}},
    ]},
    {"cooldown": {"duration": "10m"}},
]
```

```python
def test_validate_threshold_workout_builds_normalized_steps():
    workout = validate_workout("Threshold 4x6", "running", THRESHOLD_STEPS, "2026-08-10")
    assert workout.sport == "running"
    assert isinstance(workout.steps[0], ActionStep)
    assert workout.steps[0].end_condition.value == 900.0
    assert isinstance(workout.steps[1], RepeatStep)
    assert workout.steps[1].iterations == 4
    assert workout.steps[1].steps[0].target.kind == "pace"

@pytest.mark.parametrize("count", [0, -1, 1.5, True])
def test_validate_rejects_invalid_repeat_count(count):
    with pytest.raises(ValueError, match="repeat"):
        validate_workout("Bad", "running", [{"repeat": count, "steps": [{"run": {"duration": "1m"}}]}])

def test_validate_rejects_ambiguous_end_conditions_and_targets():
    with pytest.raises(ValueError, match="exactly one end condition"):
        validate_workout("Bad", "running", [{"run": {"duration": "5m", "distance": "1km"}}])
    with pytest.raises(ValueError, match="at most one target"):
        validate_workout("Bad", "running", [{"run": {"duration": "5m", "pace": "5:00-5:10/km", "heart_rate_zone": "Z3"}}])

def test_validate_rejects_incompatible_targets_and_metadata():
    with pytest.raises(ValueError, match="power"):
        validate_workout("Bad", "running", [{"run": {"duration": "5m", "power": "220-250W"}}])
    with pytest.raises(ValueError, match="pace"):
        validate_workout("Bad", "walking", [{"work": {"duration": "5m", "pace": "8:00-8:30/km"}}])
    with pytest.raises(ValueError, match="exercise"):
        validate_workout("Bad", "running", [{"run": {"reps": 10, "exercise": "SQUAT"}}])

def test_validate_strength_keeps_conservative_metadata():
    workout = validate_workout("Strength A", "strength", [{"work": {"reps": 10, "exercise": "BARBELL_SQUAT", "category": "SQUAT"}}])
    assert workout.steps[0].exercise == "BARBELL_SQUAT"
    assert workout.steps[0].category == "SQUAT"
```

- [ ] **Step 6: Run schema tests and verify RED**

Expected: missing dataclasses or `validate_workout`.

- [ ] **Step 7: Implement immutable normalized schema**

Define `EndCondition(kind, value)`, `Target(kind, values=None, zone=None)`, `ActionStep(action, end_condition, target=None, exercise=None, category=None)`, recursive `RepeatStep(iterations, steps)`, and `WorkoutDefinition(name, sport, steps, schedule_date=None)` as frozen dataclasses. `validate_workout` must use exact-key validation, recurse repeats, reject booleans as integers, normalize `strength_training` to `strength`, and use parser registries rather than one monolithic parsing branch.

- [ ] **Step 8: Run all Task 1 tests and verify GREEN**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/ai_workouts/test_parsing.py -v`

- [ ] **Step 9: Commit Task 1**

```bash
git add src/garmin_mcp/ai_workouts tests/unit/ai_workouts
git commit --no-gpg-sign -m "feat(ai-workouts): validate friendly workout schema"
```

## Task 2: Garmin workout compiler

**Files:**

- Create: `src/garmin_mcp/ai_workouts/compiler.py`
- Create: `tests/unit/ai_workouts/test_compiler.py`
- Modify: `src/garmin_mcp/ai_workouts/__init__.py`

- [ ] **Step 1: Write failing compiler tests**

Copy `THRESHOLD_STEPS` from Task 1 into this independently runnable module and
define:

```python
def compile_friendly(name, sport, steps):
    return compile_workout(validate_workout(name, sport, steps))

def first_step(workout):
    return workout["workoutSegments"][0]["workoutSteps"][0]
```

Test simple easy run, warmup/work/cooldown, time repeats, distance repeats, pace conversion, named/custom HR, cycling power zone/watts, walking sport ID 12, strength reps/exercise/category, and lap button with no value.

```python
def test_compile_threshold_repeat_and_pace():
    result = compile_friendly("Threshold 4x6", "running", THRESHOLD_STEPS)
    top = result["workoutSegments"][0]["workoutSteps"]
    assert [step["stepOrder"] for step in top] == [1, 2, 3]
    repeat = top[1]
    assert repeat["type"] == "RepeatGroupDTO"
    assert repeat["numberOfIterations"] == 4
    assert repeat["endCondition"] == {"conditionTypeId": 7, "conditionTypeKey": "iterations"}
    assert repeat["endConditionValue"] == 4.0
    interval = repeat["workoutSteps"][0]
    assert interval["targetType"] == {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"}
    assert interval["targetValueOne"] == pytest.approx(1000 / 260)
    assert interval["targetValueTwo"] == pytest.approx(1000 / 270)

def test_compile_hr_forms_do_not_mix_fields():
    named = first_step(compile_friendly("Z3", "running", [{"run": {"duration": "10m", "heart_rate_zone": "Z3"}}]))
    custom = first_step(compile_friendly("Custom", "running", [{"run": {"duration": "10m", "heart_rate": "150-165bpm"}}]))
    assert named["zoneNumber"] == 3 and "targetValueOne" not in named
    assert (custom["targetValueOne"], custom["targetValueTwo"]) == (150.0, 165.0)
    assert "zoneNumber" not in custom

def test_compile_cycling_power_forms_use_distinct_ids():
    zone = first_step(compile_friendly("Z4", "cycling", [{"work": {"duration": "10m", "power_zone": "Z4"}}]))
    watts = first_step(compile_friendly("Watts", "cycling", [{"work": {"duration": "10m", "power": "220-250W"}}]))
    assert zone["targetType"] == {"workoutTargetTypeId": 2, "workoutTargetTypeKey": "power.zone"}
    assert watts["targetType"] == {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "power.between"}

def test_compile_distance_walking_strength_and_lap_button():
    distance = first_step(compile_friendly("800s", "running", [{"run": {"distance": "800m"}}]))
    walking = compile_friendly("Walk", "walking", [{"work": {"duration": "30m", "heart_rate_zone": "Z2"}}])
    strength = first_step(compile_friendly("Lift", "strength", [{"work": {"reps": 10, "exercise": "BARBELL_SQUAT", "category": "SQUAT"}}]))
    lap = first_step(compile_friendly("Open", "running", [{"warmup": {"lap_button": True}}]))
    assert distance["endCondition"] == {"conditionTypeId": 3, "conditionTypeKey": "distance"}
    assert distance["endConditionValue"] == 800.0
    assert walking["sportType"] == {"sportTypeId": 12, "sportTypeKey": "walking"}
    assert strength["endCondition"] == {"conditionTypeId": 10, "conditionTypeKey": "reps"}
    assert strength["exerciseName"] == "BARBELL_SQUAT"
    assert strength["category"] == "SQUAT"
    assert lap["endCondition"] == {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}
    assert "endConditionValue" not in lap
```

- [ ] **Step 2: Run compiler tests and verify RED**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/ai_workouts/test_compiler.py -v`

Expected: missing compiler module.

- [ ] **Step 3: Implement centralized compiler mappings and target handlers**

Use exact mappings: sports `running=(1,running)`, `cycling=(2,cycling)`, `strength=(5,strength_training)`, `walking=(12,walking)`; steps `warmup=1`, `cooldown=2`, work aliases `interval=3`, `recovery=4`, `rest=5`; conditions `lap=1`, `time=2`, `distance=3`, `reps=10`. Use a `TARGET_COMPILERS` registry. Repeats always emit iteration ID/key/value plus `numberOfIterations`. Emit target values only at step level.

- [ ] **Step 4: Run parser/compiler tests and verify GREEN**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/ai_workouts -v`

- [ ] **Step 5: Commit Task 2**

```bash
git add src/garmin_mcp/ai_workouts tests/unit/ai_workouts/test_compiler.py
git commit --no-gpg-sign -m "feat(ai-workouts): compile friendly workouts to Garmin JSON"
```

## Task 3: Shared Taxuspt preparation and scheduling seams

**Files:**

- Modify: `src/garmin_mcp/workouts.py`
- Modify: `tests/integration/test_workouts_tools.py`

- [ ] **Step 1: Write failing preparation tests**

```python
def test_prepare_workout_for_upload_returns_normalized_copy():
    original = _running_workout_with_steps([_distance_pace_step_with_nested_bounds()])
    prepared = prepare_workout_for_upload(original)
    original_step = original["workoutSegments"][0]["workoutSteps"][0]
    prepared_step = prepared["workoutSegments"][0]["workoutSteps"][0]
    assert "targetValueOne" not in original_step
    assert "targetValueOne" in original_step["targetType"]
    assert prepared_step["targetValueOne"] == pytest.approx(2.0833333)
    assert "targetValueOne" not in prepared_step["targetType"]

def test_prepare_rejects_mismatch_without_mutation():
    workout = _running_workout_with_steps([_timed_interval_step({"workoutTargetTypeId": 2, "workoutTargetTypeKey": "pace.zone"})])
    before = copy.deepcopy(workout)
    with pytest.raises(ValueError, match="targetType mismatch"):
        prepare_workout_for_upload(workout)
    assert workout == before
```

- [ ] **Step 2: Run focused tests and verify RED**

Run the two new node IDs with `UV_CACHE_DIR=.uv-cache uv run pytest ... -v`.

Expected: missing `prepare_workout_for_upload`.

- [ ] **Step 3: Implement the preparation gate**

```python
def prepare_workout_for_upload(workout_data: dict) -> dict:
    """Return a normalized, validated copy ready for Garmin upload."""
    prepared = deepcopy(workout_data)
    _normalize_workout_steps(prepared)
    _validate_end_condition_steps(prepared)
    _validate_target_type_steps(prepared)
    return prepared
```

Do not change raw-upload behavior in this step.

- [ ] **Step 4: Run preparation tests and verify GREEN**

Run the Step 2 command. Expected: both pass.

- [ ] **Step 5: Write failing reusable scheduling tests**

```python
def test_schedule_workout_for_date_is_idempotent(mock_garmin_client):
    workouts.configure(mock_garmin_client)
    mock_garmin_client.query_garmin_graphql.return_value = {
        "data": {"workoutScheduleSummariesScalar": [{"workoutId": 123, "scheduleDate": "2026-08-10"}]}
    }
    result = schedule_workout_for_date(123, "2026-08-10")
    assert result["status"] == "success"
    assert result["idempotent"] is True
    mock_garmin_client.client.post.assert_not_called()

def test_schedule_workout_for_date_reports_http_failure(mock_garmin_client):
    workouts.configure(mock_garmin_client)
    mock_garmin_client.query_garmin_graphql.return_value = {"data": {"workoutScheduleSummariesScalar": []}}
    mock_garmin_client.client.post.return_value.status_code = 500
    result = schedule_workout_for_date(123, "2026-08-10")
    assert result["status"] == "failed"
    assert result["http_status"] == 500
```

- [ ] **Step 6: Run new scheduling tests and existing single-schedule tests; verify RED**

Expected: missing `schedule_workout_for_date`.

- [ ] **Step 7: Extract helper and route existing single tool through it**

Move the current date validation, GraphQL pre-check, POST, and response shaping into synchronous `schedule_workout_for_date(workout_id, calendar_date) -> dict`. Keep every current response key/message. The MCP wrapper JSON-encodes the helper result and retains its exception handling. Do not refactor batch scheduling in this PR.

- [ ] **Step 8: Run complete workout integration module**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/integration/test_workouts_tools.py -v`

Expected: all tests pass.

- [ ] **Step 9: Commit Task 3**

```bash
git add src/garmin_mcp/workouts.py tests/integration/test_workouts_tools.py
git commit --no-gpg-sign -m "refactor(workouts): expose safe prepare and schedule seams"
```

## Task 4: Create/upload/schedule service and MCP tool

**Files:**

- Create: `src/garmin_mcp/ai_workouts/service.py`
- Create: `src/garmin_mcp/ai_workouts/tools.py`
- Create: `tests/integration/test_ai_workouts_tools.py`
- Modify: `src/garmin_mcp/ai_workouts/__init__.py`

- [ ] **Step 1: Write failing service tests**

Define the same `THRESHOLD_STEPS` constant in this module. Cover create-only, create-and-schedule, impossible date before write, malformed step before write, missing upload ID, upload exception, and schedule partial success.

```python
def test_service_uploads_prepared_payload(mock_garmin_client):
    mock_garmin_client.upload_workout.return_value = {"workoutId": 123, "workoutName": "Easy 30"}
    result = create_workout_service(mock_garmin_client, "Easy 30", "running", [{"run": {"duration": "30m"}}])
    assert result == {"status": "success", "workout_id": 123, "name": "Easy 30"}
    payload = mock_garmin_client.upload_workout.call_args.args[0]
    assert payload["workoutSegments"][0]["workoutSteps"][0]["endConditionValue"] == 1800.0

def test_service_uploads_then_schedules(mock_garmin_client, mocker):
    mock_garmin_client.upload_workout.return_value = {"workoutId": 123, "workoutName": "Threshold 4x6"}
    schedule = mocker.patch("garmin_mcp.ai_workouts.service.schedule_workout_for_date", return_value={"status": "success"})
    result = create_workout_service(mock_garmin_client, "Threshold 4x6", "running", THRESHOLD_STEPS, "2026-08-10")
    schedule.assert_called_once_with(123, "2026-08-10")
    assert result["scheduled_date"] == "2026-08-10"

def test_service_returns_partial_success_without_delete(mock_garmin_client, mocker):
    mock_garmin_client.upload_workout.return_value = {"workoutId": 123, "workoutName": "Easy"}
    mocker.patch("garmin_mcp.ai_workouts.service.schedule_workout_for_date", return_value={"status": "failed", "message": "HTTP 500"})
    result = create_workout_service(mock_garmin_client, "Easy", "running", [{"run": {"duration": "30m"}}], "2026-08-10")
    assert result == {"status": "partial_success", "workout_id": 123, "name": "Easy", "scheduled_date": "2026-08-10", "scheduling_error": "HTTP 500"}
    mock_garmin_client.delete_workout.assert_not_called()

@pytest.mark.parametrize("bad_date", ["2026-02-30", "10-08-2026"])
def test_service_rejects_bad_date_before_upload(mock_garmin_client, bad_date):
    result = create_workout_service(mock_garmin_client, "Easy", "running", [{"run": {"duration": "30m"}}], bad_date)
    assert result["status"] == "error"
    mock_garmin_client.upload_workout.assert_not_called()

def test_service_rejects_missing_upload_id_before_schedule(mock_garmin_client, mocker):
    mock_garmin_client.upload_workout.return_value = {"workoutName": "Easy"}
    schedule = mocker.patch("garmin_mcp.ai_workouts.service.schedule_workout_for_date")
    result = create_workout_service(mock_garmin_client, "Easy", "running", [{"run": {"duration": "30m"}}], "2026-08-10")
    assert result["status"] == "error"
    assert "workout_id" in result["message"]
    schedule.assert_not_called()
```

Validation tests assert `upload_workout.assert_not_called()`. Missing `workoutId` returns `status: error` and skips scheduling.

- [ ] **Step 2: Run integration module and verify RED**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/integration/test_ai_workouts_tools.py -v`

Expected: missing service/tools modules.

- [ ] **Step 3: Implement orchestration boundary**

Implement `create_workout_service(client, name, sport, steps, schedule_date=None) -> dict` as validate → compile → prepare → upload → optional schedule. Require a dict response with `workoutId`. On schedule failure return `partial_success`, keep the uploaded ID, and never call delete. Catch exceptions only at this boundary; pure functions continue raising precise `ValueError`s.

```python
result = {"status": "success", "workout_id": workout_id, "name": uploaded.get("workoutName") or name}
if definition.schedule_date:
    scheduled = schedule_workout_for_date(workout_id, definition.schedule_date)
    if scheduled.get("status") != "success":
        return {**result, "status": "partial_success", "scheduled_date": definition.schedule_date, "scheduling_error": scheduled.get("message", "Unknown scheduling error")}
    result["scheduled_date"] = definition.schedule_date
    if scheduled.get("idempotent"):
        result["idempotent"] = True
return result
```

- [ ] **Step 4: Run service tests and verify GREEN**

Run the Step 2 command. Expected: service tests pass; MCP registration test may still fail.

- [ ] **Step 5: Write failing FastMCP registration test**

Configure/register on a test FastMCP app, call `create_workout` with the full threshold payload, decode JSON, and assert the concise response, nested `RepeatGroupDTO`, and one scheduling attempt. Malformed input must return `status: error`, not crash MCP.

- [ ] **Step 6: Run FastMCP test and verify RED**

Expected: `create_workout` is not registered.

- [ ] **Step 7: Implement module configure/register functions**

Register exactly:

```python
@app.tool()
async def create_workout(
    name: str,
    sport: str,
    steps: list[dict],
    schedule_date: Optional[str] = None,
) -> str:
    return json.dumps(
        create_workout_service(garmin_client, name, sport, steps, schedule_date),
        indent=2,
    )
```

The docstring enumerates friendly sports/actions/end conditions/targets and `partial_success`; it contains no raw DTO instructions.

- [ ] **Step 8: Run all AI workout tests and verify GREEN**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/ai_workouts tests/integration/test_ai_workouts_tools.py -v`

- [ ] **Step 9: Commit Task 4**

```bash
git add src/garmin_mcp/ai_workouts tests/integration/test_ai_workouts_tools.py
git commit --no-gpg-sign -m "feat(ai-workouts): create and schedule workouts in one call"
```

## Task 5: Named AI-coach profile and server wiring

**Files:**

- Modify: `src/garmin_mcp/__init__.py`
- Modify: `tests/unit/test_tool_filter.py`
- Modify: `tests/unit/test_server_startup.py`

- [ ] **Step 1: Write failing profile tests**

```python
def test_ai_coach_profile_is_narrow():
    enabled, disabled = _resolve_tool_filters("ai-coach", "", "")
    assert {"create_workout", "get_activities", "get_workouts", "schedule_workout"} <= enabled
    assert {"upload_workout", "upload_workouts", "delete_workouts", "create_manual_activity"}.isdisjoint(enabled)
    assert disabled == set()

def test_explicit_allowlist_overrides_profile():
    assert _resolve_tool_filters("ai-coach", "get_sleep_data", "") == ({"get_sleep_data"}, set())

def test_denylist_subtracts_from_profile():
    enabled, disabled = _resolve_tool_filters("ai-coach", "", "delete_workout")
    assert "delete_workout" not in enabled
    assert disabled == set()

def test_unset_profile_preserves_existing_filter_behavior():
    assert _resolve_tool_filters("", "", "get_sleep_data") == (set(), {"get_sleep_data"})

def test_unknown_profile_raises_clear_error():
    with pytest.raises(ValueError, match="Unknown GARMIN_TOOL_PROFILE"):
        _resolve_tool_filters("wide-open", "", "")
```

- [ ] **Step 2: Run filter tests and verify RED**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/test_tool_filter.py -v`

Expected: missing `_resolve_tool_filters`.

- [ ] **Step 3: Implement exact profile and precedence**

`TOOL_PROFILES["ai-coach"]` contains exactly: `create_workout`, `get_activities`, `get_activities_by_date`, `get_activity`, `get_workouts`, `get_workout_by_id`, `get_scheduled_workouts`, `schedule_workout`, `unschedule_workout`, `delete_workout`.

`_resolve_tool_filters(profile, enabled, disabled)` parses all strings. Explicit allowlist wins; otherwise a profile allowlist has disabled names subtracted; otherwise preserve current denylist behavior. Unknown non-empty profile raises `ValueError`. Populate module globals from the three environment variables.

- [ ] **Step 4: Run filter tests and verify GREEN**

Run the Step 2 command. Expected: all pass.

- [ ] **Step 5: Write failing startup wiring assertions**

Extend startup coverage to require `ai_workouts.configure(mock_proxy)`, `ai_workouts.register_tools(app)`, and `create_workout` registration while retaining representative existing tool assertions.

- [ ] **Step 6: Run startup tests and verify RED**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/test_server_startup.py -v`

Expected: missing module wiring.

- [ ] **Step 7: Configure and register AI workouts in main**

Import the package, configure it beside `workouts`, and register it after `workouts` and before legacy `workout_builders`. Do not change authentication or client initialization.

- [ ] **Step 8: Run filter/startup tests and verify GREEN**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/test_tool_filter.py tests/unit/test_server_startup.py -v`

- [ ] **Step 9: Commit Task 5**

```bash
git add src/garmin_mcp/__init__.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
git commit --no-gpg-sign -m "feat(server): add narrow AI coach tool profile"
```

## Task 6: User and maintainer documentation

**Files:**

- Modify: `.gitignore`
- Create: `docs/ai-workouts.md`
- Create: `tests/unit/test_ai_workouts_docs.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing documentation contract test**

Assert README contains `GARMIN_TOOL_PROFILE`, `ai-coach`, `create_workout`, and a link to `docs/ai-workouts.md`. Assert that document contains threshold JSON fields, `partial_success`, `garminconnect==0.3.2`, and explicit deferred sections for update, move, and training context.

- [ ] **Step 2: Run docs test and verify RED**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/test_ai_workouts_docs.py -v`

Expected: missing document/README content.

- [ ] **Step 3: Write focused product documentation**

Add `!docs/ai-workouts.md` after `docs/*` in `.gitignore`. The new document includes the one-call example, supported syntax, strength limitation, safety data flow, all result statuses, exact profile allowlist and precedence, pinned API assumptions, and deferred update/move/training context. README adds a concise profile example and links to the document, explicitly preserving default full-tool registration.

- [ ] **Step 4: Run docs and focused feature tests**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/test_ai_workouts_docs.py tests/unit/ai_workouts tests/integration/test_ai_workouts_tools.py -v`

Expected: all pass.

- [ ] **Step 5: Commit Task 6**

```bash
git add .gitignore README.md docs/ai-workouts.md tests/unit/test_ai_workouts_docs.py
git commit --no-gpg-sign -m "docs: explain AI-friendly workout creation"
```

## Task 7: Final compatibility verification and draft PR

**Files:**

- Modify only if verification reveals a regression; add a failing regression test before any production fix.

- [ ] **Step 1: Run focused feature coverage**

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/unit/ai_workouts tests/unit/test_ai_workouts_docs.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py tests/integration/test_ai_workouts_tools.py tests/integration/test_workouts_tools.py -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run complete offline suite**

Run: `UV_CACHE_DIR=.uv-cache uv run pytest -m "not e2e"`

Expected: zero failures; E2E tests remain deselected and no Garmin credentials are used.

- [ ] **Step 3: Check patch hygiene**

```bash
git status --short
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git log --oneline origin/main..HEAD
```

Expected: only planned files changed, no whitespace errors, no cache/credential files, and scoped commits.

- [ ] **Step 4: Verify requirements line by line**

Confirm with code/tests: one-call threshold flow; no raw DTO argument; mandatory preparation gate; returned ID/date; `partial_success` without delete; profile exclusions; unchanged default; documented-but-unexposed update/move/training context; no live-account requirement.

- [ ] **Step 5: Request final two-stage review**

Dispatch a Terra spec-compliance reviewer with the approved spec and `origin/main...HEAD`. After approval, dispatch a separate Terra code-quality reviewer. Fix all Critical/Important findings via the original implementer, rerun affected tests, and re-review until approved.

- [ ] **Step 6: Commit review fixes if required**

Use test-first scoped commits. Do not create an empty commit when no files change.

- [ ] **Step 7: Push and create requested draft PR**

Prepare a PR body summarizing architecture, changed files, verification, pinned API assumptions, upstream isolation, and deferred work. Then run:

```bash
git push -u origin feat/ai-workouts-v1
gh pr create --draft --base main --head feat/ai-workouts-v1 --title "feat: add AI-friendly Garmin workout creation" --body-file /tmp/garmin-ai-workouts-pr.md
```
