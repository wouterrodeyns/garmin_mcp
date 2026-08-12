"""Direct service coverage for safe friendly-workout updates."""

from copy import deepcopy

import pytest

from garmin_mcp.ai_workouts import service
from garmin_mcp.ai_workouts import (
    INVALID_EXISTING_WORKOUT_MESSAGE,
    INVALID_UPDATE_RESPONSE_MESSAGE,
    INVALID_WORKOUT_ID_MESSAGE,
    RAW_TO_FRIENDLY_SPORT,
    UPDATE_FAILED_MESSAGE,
    update_workout_service,
)


EXISTING_RUNNING = {
    "workoutId": 123,
    "workoutName": "Original aerobic run",
    "description": "Keep this user-written note",
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
                    "endConditionValue": 1800.0,
                    "targetType": {
                        "workoutTargetTypeId": 1,
                        "workoutTargetTypeKey": "no.target",
                    },
                }
            ],
        }
    ],
    "estimatedDuration": 1800.0,
    "estimatedDistance": 5000.0,
    "createdDate": "2026-08-01T10:00:00.000Z",
    "updatedDate": "2026-08-02T10:00:00.000Z",
    "workoutProvider": "GARMIN",
}


_DEFAULT_RESPONSE = object()


class RecordingClient:
    def __init__(self, existing=EXISTING_RUNNING, update_response=_DEFAULT_RESPONSE):
        self.existing = existing
        self.update_response = (
            {"workoutId": 123} if update_response is _DEFAULT_RESPONSE else update_response
        )
        self.read_ids = []
        self.updates = []

    def get_workout_by_id(self, workout_id):
        self.read_ids.append(workout_id)
        return self.existing

    def update_workout(self, workout_id, document):
        self.updates.append((workout_id, document))
        return self.update_response


@pytest.mark.parametrize("workout_id", [123, "123", " 123 "])
def test_accepted_ids_are_normalized_before_read_and_rename(workout_id):
    client = RecordingClient()

    result = update_workout_service(client, workout_id, name="  New name  ")

    assert result == {
        "status": "success",
        "workout_id": 123,
        "name": "New name",
        "sport": "running",
        "schedules_preserved": True,
    }
    assert client.read_ids == [123]
    assert len(client.updates) == 1
    assert client.updates[0][0] == 123


@pytest.mark.parametrize(
    "workout_id",
    [
        True,
        False,
        0,
        -1,
        1.0,
        "",
        "  ",
        "+1",
        "-1",
        "1.0",
        "1e2",
        "1_000",
        "550e8400-e29b-41d4-a716-446655440000",
        "١٢٣",
        "１２３",
        [],
        {},
    ],
)
def test_invalid_ids_are_rejected_without_provider_access(workout_id):
    client = RecordingClient()

    result = update_workout_service(client, workout_id, name="New name")

    assert result == {"status": "error", "message": INVALID_WORKOUT_ID_MESSAGE}
    assert client.read_ids == []
    assert client.updates == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "at least one of name or steps is required"),
        ({"sport": "running"}, "sport can be supplied only when steps is supplied"),
        ({"name": "Kept", "sport": "running"}, "sport can be supplied only when steps is supplied"),
        ({"name": 1}, "name must be a non-empty string"),
        ({"name": "  "}, "name must be a non-empty string"),
    ],
)
def test_invalid_patch_is_rejected_before_provider_access(kwargs, message):
    client = RecordingClient()

    result = update_workout_service(client, "123", **kwargs)

    assert result == {"status": "error", "workout_id": 123, "message": message}
    assert client.read_ids == []
    assert client.updates == []


def test_missing_client_returns_sanitized_read_error():
    result = update_workout_service(None, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }


@pytest.mark.parametrize(
    "existing",
    [
        None,
        [],
        {**EXISTING_RUNNING, "workoutId": 999},
        {**EXISTING_RUNNING, "workoutName": ""},
        {**EXISTING_RUNNING, "sportType": {"sportTypeKey": "swimming"}},
        {**EXISTING_RUNNING, "workoutSegments": []},
    ],
)
def test_invalid_existing_response_never_updates(existing):
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert client.updates == []


def test_hostile_nested_provider_container_is_sanitized_without_update():
    class ExplodingDict(dict):
        def __bool__(self):
            raise RuntimeError("secret: should not leak")

        def get(self, *_args, **_kwargs):
            raise RuntimeError("secret: should not leak")

    existing = deepcopy(EXISTING_RUNNING)
    existing["workoutSegments"] = [ExplodingDict({"x": "y"})]
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert client.updates == []


@pytest.mark.parametrize(
    "mutate_existing",
    [
        pytest.param(
            lambda existing: existing.update({"oversized": list(range(10_001))}),
            id="more-than-ten-thousand-nodes",
        ),
        pytest.param(
            lambda existing: existing.update({"nested": {"value": float("nan")}}),
            id="nested-nan",
        ),
        pytest.param(
            lambda existing: existing.update({"nested": {"value": float("inf")}}),
            id="nested-infinity",
        ),
        pytest.param(
            lambda existing: existing.update({"nested": {1: "not-json"}}),
            id="nested-non-string-dict-key",
        ),
    ],
)
def test_invalid_plain_provider_json_tree_is_sanitized_without_update(mutate_existing):
    existing = deepcopy(EXISTING_RUNNING)
    mutate_existing(existing)
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert client.updates == []


def test_provider_tree_deeper_than_limit_is_sanitized_without_update():
    existing = deepcopy(EXISTING_RUNNING)
    deeply_nested = "leaf"
    for _ in range(21):
        deeply_nested = {"nested": deeply_nested}
    existing["nested"] = deeply_nested
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert client.updates == []


@pytest.mark.parametrize("container_kind", ["root_dict", "root_list", "nested_list"])
def test_hostile_provider_containers_never_invoke_protocols_or_echo_secrets(container_kind):
    class ExplodingDict(dict):
        def __bool__(self):
            raise RuntimeError("secret: bool")

        def get(self, *_args, **_kwargs):
            raise RuntimeError("secret: get")

        def items(self):
            raise RuntimeError("secret: items")

        def __iter__(self):
            raise RuntimeError("secret: iter")

    class ExplodingList(list):
        def __bool__(self):
            raise RuntimeError("secret: bool")

        def __iter__(self):
            raise RuntimeError("secret: iter")

    existing = deepcopy(EXISTING_RUNNING)
    if container_kind == "root_dict":
        existing = ExplodingDict(existing)
    elif container_kind == "root_list":
        existing = ExplodingList([existing])
    else:
        existing["workoutSegments"] = ExplodingList(existing["workoutSegments"])
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert "secret" not in str(result)
    assert client.updates == []


def test_read_exception_is_sanitized_without_update():
    class RaisingReadClient(RecordingClient):
        def get_workout_by_id(self, _workout_id):
            raise RuntimeError("token=super-secret")

    client = RaisingReadClient()

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert "secret" not in str(result)
    assert client.updates == []


def test_internal_existing_validation_error_propagates(monkeypatch):
    client = RecordingClient()

    def fail_validation(*_args):
        raise RuntimeError("internal validation sentinel")

    monkeypatch.setattr(service, "_validated_existing_workout", fail_validation)

    with pytest.raises(RuntimeError, match="internal validation sentinel"):
        update_workout_service(client, 123, name="New name")

    assert client.updates == []


def test_rename_copies_complete_existing_document_without_mutation():
    existing = deepcopy(EXISTING_RUNNING)
    client = RecordingClient(existing=existing)

    update_workout_service(client, 123, name="  Renamed run ")

    assert existing == EXISTING_RUNNING
    submitted = client.updates[0][1]
    assert submitted["workoutName"] == "Renamed run"
    assert submitted["description"] == EXISTING_RUNNING["description"]
    assert submitted["estimatedDuration"] == EXISTING_RUNNING["estimatedDuration"]
    assert submitted is not existing


def test_rename_prepares_the_copied_document_after_applying_name(monkeypatch):
    existing = deepcopy(EXISTING_RUNNING)
    client = RecordingClient(existing=existing)
    original_prepare = service.prepare_workout_for_upload
    prepared_inputs = []

    def record_prepare(document):
        prepared_inputs.append(document)
        return original_prepare(document)

    monkeypatch.setattr(service, "prepare_workout_for_upload", record_prepare)

    result = update_workout_service(client, 123, name="  Prepared rename ")

    assert result["status"] == "success"
    assert len(prepared_inputs) == 1
    assert prepared_inputs[0]["workoutName"] == "Prepared rename"
    assert prepared_inputs[0] is not existing
    assert existing == EXISTING_RUNNING


def test_update_exception_is_ambiguous_and_sanitized():
    client = RecordingClient()
    client.update_workout = lambda *_args: (_ for _ in ()).throw(RuntimeError("token=secret"))

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": UPDATE_FAILED_MESSAGE,
        "update_may_have_applied": True,
    }


@pytest.mark.parametrize("response", [None, [], {}, {"workoutId": 999}, {"workoutId": "not-an-id"}])
def test_untrusted_update_response_is_partial_success(response):
    client = RecordingClient(update_response=response)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "partial_success",
        "workout_id": 123,
        "name": "New name",
        "sport": "running",
        "schedules_preserved": True,
        "message": INVALID_UPDATE_RESPONSE_MESSAGE,
    }


def test_trimmed_ascii_decimal_update_response_id_confirms_success():
    client = RecordingClient(update_response={"workoutId": " 123 "})

    result = update_workout_service(client, 123, name="New name")

    assert result["status"] == "success"


def test_dict_subclass_update_response_is_partial_success_without_protocol_calls():
    class ExplodingResponse(dict):
        def __bool__(self):
            raise RuntimeError("secret: bool")

        def get(self, *_args, **_kwargs):
            raise RuntimeError("secret: get")

        def __getitem__(self, _key):
            raise RuntimeError("secret: item")

        def __iter__(self):
            raise RuntimeError("secret: iter")

    client = RecordingClient(update_response=ExplodingResponse({"workoutId": 123}))

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "partial_success",
        "workout_id": 123,
        "name": "New name",
        "sport": "running",
        "schedules_preserved": True,
        "message": INVALID_UPDATE_RESPONSE_MESSAGE,
    }
    assert "secret" not in str(result)


def test_public_contract_exports_stable_sport_mapping():
    assert RAW_TO_FRIENDLY_SPORT == {
        "running": "running",
        "cycling": "cycling",
        "walking": "walking",
        "strength_training": "strength",
    }
