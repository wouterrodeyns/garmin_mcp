# AI-Friendly Workout Update v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one patch-style `update_workout` MCP tool that accepts the existing friendly workout schema, performs a true in-place Garmin update, and preserves the workout ID and schedules.

**Architecture:** Extend the fork-owned `ai_workouts` package. The service validates a strict numeric workout ID and patch, fetches the complete existing workout, either renames its copied Garmin document or compiles replacement friendly steps, always calls Taxuspt's `prepare_workout_for_upload`, and then invokes the pinned client's public `update_workout` method exactly once. Tool/profile wiring and documentation expose this as the thirteenth curated AI-coach tool without changing upstream-oriented raw workout modules.

**Tech Stack:** Python 3.12, `garminconnect==0.3.10`, FastMCP 1.28, Pydantic strict types, pytest/pytest-asyncio, existing Taxuspt workout normalizers.

---

## File map

- Modify `src/garmin_mcp/ai_workouts/service.py`: strict update validation, existing-workout normalization, patch construction, provider calls, and stable results.
- Modify `src/garmin_mcp/ai_workouts/__init__.py`: export the update service and stable update constants needed by tests.
- Modify `src/garmin_mcp/ai_workouts/tools.py`: register the strict FastMCP `update_workout` tool next to `create_workout`.
- Modify `src/garmin_mcp/__init__.py`: add the new tool name to the exact AI-coach profile; existing package configure/register calls already cover it.
- Create `tests/unit/ai_workouts/test_update_service.py`: direct service tests, hostile/malformed provider shapes, immutability, response semantics, and read/write allowlist harness.
- Modify `tests/integration/test_ai_workouts_tools.py`: real FastMCP schema, omitted/explicit arguments, strict ID behavior, and concise JSON envelopes.
- Modify `tests/unit/test_tool_filter.py`: exact 13-name profile contract.
- Modify `tests/unit/test_server_startup.py`: actual registration equality and package configure/register evidence.
- Modify `README.md`, `docs/ai-workouts.md`, and `docs/ai-training.md`: update workflow, profile count, ID distinction, and ambiguous-write guidance.
- Modify `tests/unit/test_ai_workouts_docs.py`, `tests/unit/test_ai_training_docs.py`, and `tests/unit/test_readme_docs.py`: pin the public documentation contract.

### Task 1: Strict update request and existing-workout validation

**Files:**
- Create: `tests/unit/ai_workouts/test_update_service.py`
- Modify: `src/garmin_mcp/ai_workouts/service.py`
- Modify: `src/garmin_mcp/ai_workouts/__init__.py`

- [ ] **Step 1: Write failing tests for identifiers, patch shape, and fetched workout validation**

Create `tests/unit/ai_workouts/test_update_service.py` with the following initial content:

```python
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from garmin_mcp.ai_workouts import update_workout_service


EXISTING_RUNNING = {
    "workoutId": 123,
    "workoutName": "Threshold 4x6",
    "description": "Keep this coaching note",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "estimatedDuration": 3600,
    "createdDate": "2026-08-01T12:00:00.0",
    "workoutProvider": "GARMIN",
    "workoutSegments": [
        {
            "segmentOrder": 1,
            "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
            "workoutSteps": [
                {
                    "type": "ExecutableStepDTO",
                    "stepId": 501,
                    "stepOrder": 1,
                    "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                    "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                    "endConditionValue": 360.0,
                    "targetType": {
                        "workoutTargetTypeId": 6,
                        "workoutTargetTypeKey": "pace.zone",
                    },
                    "targetValueOne": 3.70,
                    "targetValueTwo": 3.85,
                }
            ],
        }
    ],
}


class ExplodingDict(dict):
    def __bool__(self):
        raise RuntimeError("token=truthiness-private")

    def get(self, *args, **kwargs):
        raise RuntimeError("token=get-private")


@pytest.mark.parametrize("value", [123, "123", " 123 "])
def test_update_accepts_strict_positive_workout_ids(value):
    client = MagicMock()
    client.get_workout_by_id.return_value = deepcopy(EXISTING_RUNNING)
    client.update_workout.return_value = {
        "workoutId": 123,
        "workoutName": "Renamed",
    }

    result = update_workout_service(client, value, name="Renamed")

    assert result["status"] == "success"
    client.get_workout_by_id.assert_called_once_with(123)


@pytest.mark.parametrize(
    "value",
    [True, False, 0, -1, 1.0, "", " ", "+1", "1.0", "1e2", "1_000", "１２３", [], {}],
)
def test_invalid_workout_id_returns_error_before_provider_access(value):
    client = MagicMock()

    result = update_workout_service(client, value, name="Renamed")

    assert result == {
        "status": "error",
        "message": "workout_id must be a positive integer or ASCII decimal string",
    }
    client.get_workout_by_id.assert_not_called()
    client.update_workout.assert_not_called()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "at least one of name or steps is required"),
        ({"sport": "cycling"}, "sport can be supplied only when steps is supplied"),
        ({"name": "Renamed", "sport": "cycling"}, "sport can be supplied only when steps is supplied"),
        ({"name": ""}, "name must be a non-empty string"),
        ({"name": 123}, "name must be a non-empty string"),
    ],
)
def test_invalid_patch_returns_error_before_provider_access(kwargs, message):
    client = MagicMock()

    result = update_workout_service(client, 123, **kwargs)

    assert result == {"status": "error", "workout_id": 123, "message": message}
    client.get_workout_by_id.assert_not_called()
    client.update_workout.assert_not_called()


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {**EXISTING_RUNNING, "workoutId": 999},
        {**EXISTING_RUNNING, "workoutName": ""},
        {**EXISTING_RUNNING, "sportType": []},
        {**EXISTING_RUNNING, "sportType": {"sportTypeKey": "swimming"}},
        {**EXISTING_RUNNING, "workoutSegments": []},
    ],
)
def test_invalid_existing_workout_returns_sanitized_error_without_update(raw):
    client = MagicMock()
    client.get_workout_by_id.return_value = raw

    result = update_workout_service(client, 123, name="Renamed")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": "Could not retrieve a valid existing workout from Garmin.",
    }
    assert "999" not in str(result)
    client.update_workout.assert_not_called()


def test_nested_hostile_mapping_is_rejected_without_protocol_access_or_secret_echo():
    raw = deepcopy(EXISTING_RUNNING)
    raw["metadata"] = ExplodingDict(secret="token=private")
    client = MagicMock()
    client.get_workout_by_id.return_value = raw

    result = update_workout_service(client, 123, name="Renamed")

    assert result["message"] == "Could not retrieve a valid existing workout from Garmin."
    assert "token=" not in str(result)
    client.update_workout.assert_not_called()


def test_missing_client_returns_prewrite_error():
    result = update_workout_service(None, 123, name="Renamed")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": "Could not retrieve a valid existing workout from Garmin.",
    }
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/unit/ai_workouts/test_update_service.py -q
```

Expected: collection fails because `update_workout_service` is not exported.

- [ ] **Step 3: Add the minimal validation and service skeleton**

In `src/garmin_mcp/ai_workouts/service.py`, add imports/constants/helpers and the update skeleton below while retaining `create_workout_service` unchanged:

```python
from copy import deepcopy


RAW_TO_FRIENDLY_SPORT = {
    "running": "running",
    "cycling": "cycling",
    "walking": "walking",
    "strength_training": "strength",
}

INVALID_WORKOUT_ID_MESSAGE = (
    "workout_id must be a positive integer or ASCII decimal string"
)
INVALID_EXISTING_WORKOUT_MESSAGE = (
    "Could not retrieve a valid existing workout from Garmin."
)
UPDATE_FAILED_MESSAGE = (
    "Garmin could not confirm the workout update; read the workout before retrying."
)
INVALID_UPDATE_RESPONSE_MESSAGE = (
    "Garmin returned an unexpected update response; read the workout before retrying."
)


def _normalize_workout_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(INVALID_WORKOUT_ID_MESSAGE)
    if isinstance(value, int):
        if value > 0:
            return value
        raise ValueError(INVALID_WORKOUT_ID_MESSAGE)
    if isinstance(value, str):
        candidate = value.strip()
        if candidate and candidate.isascii() and candidate.isdecimal():
            normalized = int(candidate)
            if normalized > 0:
                return normalized
    raise ValueError(INVALID_WORKOUT_ID_MESSAGE)


def _validate_update_patch(
    name: Any,
    sport: Any,
    steps: Any,
) -> str | None:
    if name is None and steps is None:
        raise ValueError("at least one of name or steps is required")
    if sport is not None and steps is None:
        raise ValueError("sport can be supplied only when steps is supplied")
    if name is None:
        return None
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    return name.strip()


def _is_plain_bounded_json(value: Any) -> bool:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > 10_000 or depth > 20:
            return False
        if type(current) in {str, int, float, bool, type(None)}:
            continue
        if type(current) is list:
            stack.extend((item, depth + 1) for item in current)
            continue
        if type(current) is dict and all(type(key) is str for key in current):
            stack.extend((item, depth + 1) for item in current.values())
            continue
        return False
    return True


def _validated_existing_workout(raw: Any, workout_id: int) -> tuple[dict[str, Any], str, str]:
    if type(raw) is not dict or not _is_plain_bounded_json(raw):
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE)
    try:
        returned_id = _normalize_workout_id(raw.get("workoutId"))
    except ValueError as exc:
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE) from exc
    name = raw.get("workoutName")
    sport_type = raw.get("sportType")
    segments = raw.get("workoutSegments")
    if (
        returned_id != workout_id
        or not isinstance(name, str)
        or not name.strip()
        or type(sport_type) is not dict
        or type(segments) is not list
        or not segments
    ):
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE)
    friendly_sport = RAW_TO_FRIENDLY_SPORT.get(sport_type.get("sportTypeKey"))
    if friendly_sport is None:
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE)
    return deepcopy(raw), name.strip(), friendly_sport


def _update_error(message: str, workout_id: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "error"}
    if workout_id is not None:
        result["workout_id"] = workout_id
    result["message"] = message
    return result


def update_workout_service(
    client: Any,
    workout_id: Any,
    name: Any = None,
    sport: Any = None,
    steps: Any = None,
) -> dict[str, Any]:
    try:
        normalized_id = _normalize_workout_id(workout_id)
    except ValueError as exc:
        return _update_error(str(exc))
    try:
        normalized_name = _validate_update_patch(name, sport, steps)
    except ValueError as exc:
        return _update_error(str(exc), normalized_id)
    if client is None:
        return _update_error(INVALID_EXISTING_WORKOUT_MESSAGE, normalized_id)
    try:
        raw = client.get_workout_by_id(normalized_id)
    except Exception:
        return _update_error(INVALID_EXISTING_WORKOUT_MESSAGE, normalized_id)
    try:
        existing, existing_name, existing_sport = _validated_existing_workout(
            raw, normalized_id
        )
    except ValueError:
        return _update_error(INVALID_EXISTING_WORKOUT_MESSAGE, normalized_id)

    effective_name = normalized_name or existing_name
    prepared = deepcopy(existing)
    prepared["workoutName"] = effective_name
    try:
        prepared = prepare_workout_for_upload(prepared)
    except ValueError:
        return _update_error(INVALID_EXISTING_WORKOUT_MESSAGE, normalized_id)

    try:
        updated = client.update_workout(normalized_id, prepared)
    except Exception:
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": UPDATE_FAILED_MESSAGE,
            "update_may_have_applied": True,
        }

    try:
        returned_id = (
            _normalize_workout_id(updated.get("workoutId"))
            if type(updated) is dict
            else None
        )
    except ValueError:
        returned_id = None
    if returned_id != normalized_id:
        return {
            "status": "partial_success",
            "workout_id": normalized_id,
            "name": effective_name,
            "sport": existing_sport,
            "schedules_preserved": True,
            "message": INVALID_UPDATE_RESPONSE_MESSAGE,
        }
    return {
        "status": "success",
        "workout_id": normalized_id,
        "name": effective_name,
        "sport": existing_sport,
        "schedules_preserved": True,
    }
```

In `src/garmin_mcp/ai_workouts/__init__.py`, import/export `update_workout_service` and the four stable message constants.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/unit/ai_workouts/test_update_service.py -q
```

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/garmin_mcp/ai_workouts/service.py src/garmin_mcp/ai_workouts/__init__.py tests/unit/ai_workouts/test_update_service.py
git commit -m "feat(ai-workouts): validate friendly workout updates"
```

### Task 2: Rename-only update and bounded failure semantics

**Files:**
- Modify: `tests/unit/ai_workouts/test_update_service.py`
- Modify: `src/garmin_mcp/ai_workouts/service.py`

- [ ] **Step 1: Add the recording client and failing rename/failure tests**

Append this harness and tests:

```python
class _RawWriteTrap:
    def __init__(self, owner):
        self.owner = owner

    def post(self, *args, **kwargs):
        self.owner.forbidden.append("client.post")
        raise AssertionError("forbidden client.post")

    def put(self, *args, **kwargs):
        self.owner.forbidden.append("client.put")
        raise AssertionError("forbidden client.put")

    def delete(self, *args, **kwargs):
        self.owner.forbidden.append("client.delete")
        raise AssertionError("forbidden client.delete")


_UPDATE_RESULT_UNSET = object()


class RecordingUpdateClient:
    def __init__(self, existing=None, update_result=_UPDATE_RESULT_UNSET):
        self.existing = deepcopy(existing if existing is not None else EXISTING_RUNNING)
        self.update_result = (
            {"workoutId": 123}
            if update_result is _UPDATE_RESULT_UNSET
            else update_result
        )
        self.calls = []
        self.forbidden = []
        self.client = _RawWriteTrap(self)

    def get_workout_by_id(self, workout_id):
        self.calls.append(("get_workout_by_id", workout_id))
        return self.existing

    def update_workout(self, workout_id, payload):
        self.calls.append(("update_workout", workout_id, payload))
        return self.update_result

    def _forbid(self, name):
        self.forbidden.append(name)
        raise AssertionError(f"forbidden {name}")

    def upload_workout(self, *args, **kwargs):
        return self._forbid("upload_workout")

    def schedule_workout(self, *args, **kwargs):
        return self._forbid("schedule_workout")

    def unschedule_workout(self, *args, **kwargs):
        return self._forbid("unschedule_workout")

    def delete_workout(self, *args, **kwargs):
        return self._forbid("delete_workout")


def test_rename_updates_copied_complete_document_once_and_preserves_schedule_identity():
    client = RecordingUpdateClient()
    before = deepcopy(client.existing)

    result = update_workout_service(client, 123, name="  Threshold 5x5  ")

    assert result == {
        "status": "success",
        "workout_id": 123,
        "name": "Threshold 5x5",
        "sport": "running",
        "schedules_preserved": True,
    }
    assert client.calls[0] == ("get_workout_by_id", 123)
    _, update_id, payload = client.calls[1]
    assert update_id == 123
    assert payload == before | {"workoutName": "Threshold 5x5"}
    assert client.existing == before
    assert client.forbidden == []


def test_fetch_exception_is_sanitized_and_never_writes():
    client = RecordingUpdateClient()
    client.get_workout_by_id = MagicMock(
        side_effect=RuntimeError("token=private fetch response")
    )

    result = update_workout_service(client, 123, name="Renamed")

    assert result["status"] == "error"
    assert result["message"] == "Could not retrieve a valid existing workout from Garmin."
    assert "token=private" not in str(result)
    assert not any(call[0] == "update_workout" for call in client.calls)
    assert client.forbidden == []


def test_update_exception_is_sanitized_and_marks_ambiguous_outcome():
    client = RecordingUpdateClient()
    client.update_workout = MagicMock(
        side_effect=RuntimeError("token=private update response")
    )

    result = update_workout_service(client, 123, name="Renamed")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": "Garmin could not confirm the workout update; read the workout before retrying.",
        "update_may_have_applied": True,
    }
    assert "token=private" not in str(result)
    client.update_workout.assert_called_once()
    assert client.forbidden == []


@pytest.mark.parametrize("update_result", [None, [], {}, {"workoutId": 999}])
def test_unexpected_update_response_is_sanitized_partial_success(update_result):
    client = RecordingUpdateClient(update_result=update_result)

    result = update_workout_service(client, 123, name="Renamed")

    assert result == {
        "status": "partial_success",
        "workout_id": 123,
        "name": "Renamed",
        "sport": "running",
        "schedules_preserved": True,
        "message": "Garmin returned an unexpected update response; read the workout before retrying.",
    }
    assert "999" not in str(result)
    assert client.forbidden == []
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/unit/ai_workouts/test_update_service.py \
  -k 'rename_updates or fetch_exception or update_exception or unexpected_update_response' \
  -q
```

Expected: the rename behavior and explicit falsey update-response cases fail
until the service's rename and response paths are complete.

- [ ] **Step 3: Correct the harness and make rename behavior minimal and explicit**

Use the `_UPDATE_RESULT_UNSET` implementation shown in Step 1 so explicit
`None`, lists, and empty dictionaries reach the response classifier. Keep the
service's rename path as a deep copy followed by
`prepare_workout_for_upload`; do not add any calendar or raw-client call. If
`prepare_workout_for_upload` raises a documented data-shape or validation
error for the fetched document, map it to `INVALID_EXISTING_WORKOUT_MESSAGE`
before the PUT; unrelated internal exceptions must remain visible to tests.

- [ ] **Step 4: Run all update-service tests and verify GREEN**

```bash
.venv/bin/pytest tests/unit/ai_workouts/test_update_service.py -q
```

Expected: all tests pass and `client.forbidden` remains empty.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/garmin_mcp/ai_workouts/service.py tests/unit/ai_workouts/test_update_service.py
git commit -m "feat(ai-workouts): update workout names in place"
```

### Task 3: Friendly step replacement through the existing compiler

Replacement compilation deliberately drops stale estimates, timestamps,
provider metadata, and prior step IDs while retaining only a valid string
description.

**Files:**
- Modify: `tests/unit/ai_workouts/test_update_service.py`
- Modify: `src/garmin_mcp/ai_workouts/service.py`

- [ ] **Step 1: Write failing tests for inherited and explicit replacement fields**

Append:

```python
THRESHOLD_5X5 = [
    {"warmup": {"duration": "15m"}},
    {
        "repeat": 5,
        "steps": [
            {"run": {"duration": "5m", "pace": "4:20-4:30/km"}},
            {"recovery": {"duration": "2m"}},
        ],
    },
    {"cooldown": {"duration": "10m"}},
]


def test_steps_patch_inherits_name_and_sport_and_compiles_friendly_steps():
    client = RecordingUpdateClient()
    caller_steps = deepcopy(THRESHOLD_5X5)

    result = update_workout_service(client, 123, steps=caller_steps)

    assert result["status"] == "success"
    assert result["name"] == "Threshold 4x6"
    assert result["sport"] == "running"
    _, _, payload = client.calls[1]
    assert payload["workoutName"] == "Threshold 4x6"
    assert payload["description"] == "Keep this coaching note"
    assert payload["sportType"] == {"sportTypeId": 1, "sportTypeKey": "running"}
    repeat = payload["workoutSegments"][0]["workoutSteps"][1]
    assert repeat["numberOfIterations"] == 5
    pace = repeat["workoutSteps"][0]
    assert pace["targetValueOne"] == pytest.approx(1000 / 270)
    assert pace["targetValueTwo"] == pytest.approx(1000 / 260)
    assert caller_steps == THRESHOLD_5X5
    for stale in ("estimatedDuration", "createdDate", "workoutProvider"):
        assert stale not in payload
    assert "stepId" not in str(payload)
    assert client.forbidden == []


def test_steps_patch_can_replace_name_and_sport_together():
    client = RecordingUpdateClient()

    result = update_workout_service(
        client,
        123,
        name="Bike Tempo",
        sport="cycling",
        steps=[{"work": {"duration": "20m", "power": "220-250W"}}],
    )

    assert result == {
        "status": "success",
        "workout_id": 123,
        "name": "Bike Tempo",
        "sport": "cycling",
        "schedules_preserved": True,
    }
    payload = client.calls[1][2]
    assert payload["sportType"] == {"sportTypeId": 2, "sportTypeKey": "cycling"}
    step = payload["workoutSegments"][0]["workoutSteps"][0]
    assert step["targetType"] == {
        "workoutTargetTypeId": 2,
        "workoutTargetTypeKey": "power.zone",
    }
    assert (step["targetValueOne"], step["targetValueTwo"]) == (220.0, 250.0)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (
            {"heart_rate_zone": "Z3"},
            {"zoneNumber": 3},
        ),
        (
            {"heart_rate": "150-165bpm"},
            {"targetValueOne": 150.0, "targetValueTwo": 165.0},
        ),
    ],
)
def test_steps_patch_preserves_named_and_custom_hr_target_shapes(target, expected):
    client = RecordingUpdateClient()
    step = {"duration": "20m"} | target

    result = update_workout_service(client, 123, steps=[{"run": step}])

    assert result["status"] == "success"
    compiled = client.calls[1][2]["workoutSegments"][0]["workoutSteps"][0]
    assert compiled["targetType"] == {
        "workoutTargetTypeId": 4,
        "workoutTargetTypeKey": "heart.rate.zone",
    }
    for key, value in expected.items():
        assert compiled[key] == value
    if "zoneNumber" in expected:
        assert "targetValueOne" not in compiled
        assert "targetValueTwo" not in compiled
    else:
        assert "zoneNumber" not in compiled


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [{"run": {"duration": "broken"}}],
        [{"repeat": 51, "steps": [{"run": {"duration": "1m"}}]}],
    ],
)
def test_invalid_replacement_steps_return_precise_prewrite_error(steps):
    client = RecordingUpdateClient()

    result = update_workout_service(client, 123, steps=steps)

    assert result["status"] == "error"
    assert result["workout_id"] == 123
    assert len(client.calls) == 1
    assert client.calls[0] == ("get_workout_by_id", 123)
    assert client.forbidden == []


def test_non_string_existing_description_is_not_copied_into_replacement():
    existing = deepcopy(EXISTING_RUNNING)
    existing["description"] = {"raw": "secret"}
    client = RecordingUpdateClient(existing=existing)

    result = update_workout_service(client, 123, steps=[{"run": {"duration": "30m"}}])

    assert result["status"] == "success"
    assert "description" not in client.calls[1][2]
    assert "secret" not in str(client.calls[1][2])
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/unit/ai_workouts/test_update_service.py -q
```

Expected: replacement tests fail because the service still sends the fetched step structure.

- [ ] **Step 3: Implement replacement compilation without stale metadata**

Replace the payload-construction block in `update_workout_service` with:

```python
effective_name = normalized_name or existing_name
effective_sport = existing_sport
if steps is None:
    candidate = deepcopy(existing)
    candidate["workoutName"] = effective_name
    invalid_candidate_message = INVALID_EXISTING_WORKOUT_MESSAGE
else:
    try:
        definition = validate_workout(
            effective_name,
            sport if sport is not None else existing_sport,
            steps,
        )
        effective_sport = definition.sport
        candidate = compile_workout(definition)
    except ValueError as exc:
        return _update_error(str(exc), normalized_id)
    description = existing.get("description")
    if isinstance(description, str) and description.strip():
        candidate["description"] = description
    invalid_candidate_message = "Workout update validation failed."

try:
    prepared = prepare_workout_for_upload(candidate)
except ValueError as exc:
    message = (
        invalid_candidate_message
        if steps is None
        else str(exc)
    )
    return _update_error(message, normalized_id)
```

Use `effective_sport`, not `existing_sport`, in success and partial-success responses. Retain the existing update-call and response-validation code unchanged.

- [ ] **Step 4: Run compiler, parsing, create, and update suites**

```bash
.venv/bin/pytest tests/unit/ai_workouts tests/integration/test_ai_workouts_tools.py -q
```

Expected: existing create-workout behavior remains green and all update tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/garmin_mcp/ai_workouts/service.py tests/unit/ai_workouts/test_update_service.py
git commit -m "feat(ai-workouts): replace workout steps safely"
```

### Task 4: FastMCP tool and exact AI-coach profile

**Files:**
- Modify: `src/garmin_mcp/ai_workouts/tools.py`
- Modify: `src/garmin_mcp/__init__.py`
- Modify: `tests/integration/test_ai_workouts_tools.py`
- Modify: `tests/unit/test_tool_filter.py`
- Modify: `tests/unit/test_server_startup.py`

- [ ] **Step 1: Write failing FastMCP tests**

Extend `tests/integration/test_ai_workouts_tools.py`, importing `deepcopy` from
`copy` and `ToolError` from `mcp.server.fastmcp.exceptions`. Add this compact
existing-workout fixture before the tests:

```python
EXISTING_RUNNING = {
    "workoutId": 123,
    "workoutName": "Threshold 4x6",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [
        {
            "segmentOrder": 1,
            "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
            "workoutSteps": [
                {
                    "type": "ExecutableStepDTO",
                    "stepOrder": 1,
                    "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                    "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                    "endConditionValue": 360.0,
                    "targetType": {
                        "workoutTargetTypeId": 1,
                        "workoutTargetTypeKey": "no.target",
                    },
                }
            ],
        }
    ],
}


@pytest.mark.asyncio
async def test_update_workout_tool_accepts_patch_style_name(app_with_ai_workouts, mock_garmin_client):
    mock_garmin_client.get_workout_by_id.return_value = deepcopy(EXISTING_RUNNING)
    mock_garmin_client.update_workout.return_value = {"workoutId": 123}

    response = await app_with_ai_workouts.call_tool(
        "update_workout",
        {"workout_id": 123, "name": "Renamed"},
    )

    data = json.loads(response[0][0].text)
    assert data == {
        "status": "success",
        "workout_id": 123,
        "name": "Renamed",
        "sport": "running",
        "schedules_preserved": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [True, 1.0])
async def test_update_workout_tool_schema_rejects_coercible_ids(
    app_with_ai_workouts, mock_garmin_client, bad_id
):
    with pytest.raises(ToolError, match="workout_id"):
        await app_with_ai_workouts.call_tool(
            "update_workout",
            {"workout_id": bad_id, "name": "Renamed"},
        )
    mock_garmin_client.get_workout_by_id.assert_not_called()
    mock_garmin_client.update_workout.assert_not_called()


@pytest.mark.asyncio
async def test_update_workout_tool_accepts_explicit_friendly_steps(
    app_with_ai_workouts, mock_garmin_client
):
    mock_garmin_client.get_workout_by_id.return_value = deepcopy(EXISTING_RUNNING)
    mock_garmin_client.update_workout.return_value = {"workoutId": 123}

    response = await app_with_ai_workouts.call_tool(
        "update_workout",
        {
            "workout_id": "123",
            "steps": [{"run": {"duration": "30m", "heart_rate_zone": "Z2"}}],
        },
    )

    assert json.loads(response[0][0].text)["status"] == "success"
```

- [ ] **Step 2: Pin the exact 13-name profile and startup registration**

Update the literal expected set in `tests/unit/test_tool_filter.py` to include `"update_workout"` and assert its length is 13. In `tests/unit/test_server_startup.py`, add `"update_workout"` to the startup tool-name expectation and retain the assertion that actual registered names equal `TOOL_PROFILES["ai-coach"]`.

Run:

```bash
.venv/bin/pytest tests/integration/test_ai_workouts_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py -q
```

Expected: failures report missing FastMCP tool and missing profile member.

- [ ] **Step 3: Register the strict tool and profile member atomically**

In `src/garmin_mcp/ai_workouts/tools.py`, import `StrictInt` and `StrictStr`, import `update_workout_service`, and add inside `register_tools`:

```python
@app.tool()
async def update_workout(
    workout_id: StrictInt | StrictStr,
    name: Optional[StrictStr] = None,
    sport: Optional[StrictStr] = None,
    steps: Optional[list[dict]] = None,
) -> str:
    """Update an existing regular Garmin workout in place with friendly fields.

    workout_id is the numeric workout template ID, not scheduled_workout_id.
    Supply name to rename, and/or steps to replace the workout structure. When
    replacing steps, omit sport to retain the current supported sport or supply
    running, cycling, walking, or strength. Steps use the same actions, units,
    targets, repeat limits, and safety validation as create_workout.

    The server fetches Garmin's complete workout, performs the required
    whole-document PUT, keeps the same workout ID, and does not touch calendar
    entries. Existing schedules therefore remain attached. If the result says
    the update may have applied or is partial_success, read the workout before
    retrying. UUID Garmin Coach/adaptive workouts are not supported.
    """
    result = update_workout_service(
        garmin_client,
        workout_id,
        name=name,
        sport=sport,
        steps=steps,
    )
    return json.dumps(result, indent=2)
```

In `src/garmin_mcp/__init__.py`, add `"update_workout"` to `TOOL_PROFILES["ai-coach"]`. Do not add new configure/register calls: `ai_workouts.register_tools` owns both friendly workout tools.

- [ ] **Step 4: Run FastMCP/profile/startup tests and verify GREEN**

```bash
.venv/bin/pytest tests/integration/test_ai_workouts_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py -q
```

Expected: all tests pass with exactly 13 AI-coach tools.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/garmin_mcp/ai_workouts/tools.py src/garmin_mcp/__init__.py tests/integration/test_ai_workouts_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
git commit -m "feat(server): expose friendly workout updates"
```

### Task 5: Public documentation and documentation-pinning tests

**Files:**
- Modify: `README.md`
- Modify: `docs/ai-workouts.md`
- Modify: `docs/ai-training.md`
- Modify: `tests/unit/test_ai_workouts_docs.py`
- Modify: `tests/unit/test_ai_training_docs.py`
- Modify: `tests/unit/test_readme_docs.py`

- [ ] **Step 1: Write failing documentation tests**

Add exact assertions that:

```python
assert "exactly 13 tools" in ai_workouts_docs
assert "update_workout" in ai_workouts_docs
assert "scheduled_workout_id" in ai_workouts_docs
assert "read the workout before retrying" in ai_workouts_docs.lower()
assert "Update (deferred)" not in ai_workouts_docs

assert "13-tool surface" in readme
assert "update_workout" in readme
assert "preserves" in readme.lower()

assert "exactly 13 tools" in ai_training_docs
```

Also update any literal profile-name set in `tests/unit/test_readme_docs.py` to include `update_workout` and assert equality with `TOOL_PROFILES["ai-coach"]`, not merely subset membership.

- [ ] **Step 2: Run documentation tests and verify RED**

```bash
.venv/bin/pytest tests/unit/test_ai_workouts_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_readme_docs.py -q
```

Expected: failures identify the stale 12-tool count and deferred-update wording.

- [ ] **Step 3: Update README and guides with the approved contract**

Make these concrete documentation changes:

- change all current AI-coach counts from 12 to 13;
- add `update_workout` immediately after `create_workout` in every exact profile list;
- describe the workout-hands role as create plus in-place update;
- replace `docs/ai-workouts.md`'s `Update (deferred)` section with patch-style name and step examples;
- state that `workout_id` is used for update and `scheduled_workout_id` only for unscheduling;
- state that the ID and existing schedules are preserved and no calendar call is made;
- state that an ambiguous update outcome must be checked with `get_workout_by_id` before retrying;
- keep move semantics explicitly deferred;
- state that UUID adaptive/Garmin Coach and unsupported-sport updates are outside v1.

Use this example in `docs/ai-workouts.md`:

```json
{
  "workout_id": 123456789,
  "name": "Threshold 5x5",
  "steps": [
    {"warmup": {"duration": "15m"}},
    {
      "repeat": 5,
      "steps": [
        {"run": {"duration": "5m", "pace": "4:20-4:30/km"}},
        {"recovery": {"duration": "2m"}}
      ]
    },
    {"cooldown": {"duration": "10m"}}
  ]
}
```

- [ ] **Step 4: Run docs plus profile tests and verify GREEN**

```bash
.venv/bin/pytest tests/unit/test_ai_workouts_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_readme_docs.py tests/unit/test_tool_filter.py -q
```

Expected: public docs and runtime profile agree on exactly 13 tools.

- [ ] **Step 5: Commit Task 5**

```bash
git add README.md docs/ai-workouts.md docs/ai-training.md tests/unit/test_ai_workouts_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_readme_docs.py
git commit -m "docs(ai-workouts): document in-place updates"
```

### Task 6: Final contract audit and branch verification

**Files:**
- Modify only if verification finds a feature-scope defect.

- [ ] **Step 1: Run the complete focused feature suite**

```bash
.venv/bin/pytest \
  tests/unit/ai_workouts \
  tests/integration/test_ai_workouts_tools.py \
  tests/unit/test_ai_workouts_docs.py \
  tests/unit/test_ai_training_docs.py \
  tests/unit/test_readme_docs.py \
  tests/unit/test_tool_filter.py \
  tests/unit/test_server_startup.py \
  tests/unit/test_garminconnect_contract.py \
  -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete offline suite**

```bash
.venv/bin/pytest -m "not e2e" -q
```

Expected: all selected tests pass; only the 20 E2E tests are deselected.

- [ ] **Step 3: Verify formatting, committed diff, and package contents**

```bash
git diff --check origin/main...HEAD
git status --short
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv build --out-dir /private/tmp/garmin-mcp-update-dist
unzip -l /private/tmp/garmin-mcp-update-dist/*.whl | rg "ai_workouts/(service|tools|__init__)\.py"
```

Expected: no whitespace errors, clean worktree, successful wheel build, and all modified `ai_workouts` modules present.

- [ ] **Step 4: Audit the diff against the design spec**

Read `docs/superpowers/specs/2026-08-11-ai-workout-update-v1-design.md` and verify each requirement has a test or explicit implementation. Confirm especially:

- no raw DTO input;
- every payload passes through `prepare_workout_for_upload`;
- exactly one read and at most one public update call;
- no automatic retry;
- no calendar/upload/delete/raw-client mutation;
- fixed provider error messages;
- exact 13-tool profile;
- move remains deferred.

- [ ] **Step 5: Commit any verification-only correction, if one was necessary**

If and only if Step 1-4 exposed a defect, add the failing regression test
first, observe RED, apply the minimal fix, rerun GREEN, and commit only those
files with `git commit -m "fix(ai-workouts): correct verified update contract"`.
Otherwise create no empty commit.

- [ ] **Step 6: Request independent code review before PR creation**

Review the full `origin/main...HEAD` diff against the approved design, with findings ordered by severity and exact file/line references. Resolve every Critical or Important finding through a fresh red-green test cycle, then rerun Steps 1-3.

- [ ] **Step 7: Push and open a ready-for-review PR**

```bash
git push -u origin feat/ai-workout-update-v1
gh pr create \
  --base main \
  --head feat/ai-workout-update-v1 \
  --title "feat: add AI-friendly workout updates" \
  --body-file /private/tmp/ai-workout-update-pr-body.md
```

The PR is opened ready for review, not as a draft. Its body summarizes architecture, schedule preservation, ambiguous-write semantics, tests, pinned Garmin assumptions, and explicitly deferred move/UUID/new-sport behavior.
