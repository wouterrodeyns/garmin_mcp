"""Direct service coverage for safe friendly-workout updates."""

from copy import deepcopy

import pytest

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
    [True, False, 0, -1, 1.0, "", "  ", "+1", "1.0", "1e2", "1_000", "１２３", [], {}],
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


def test_public_contract_exports_stable_sport_mapping():
    assert RAW_TO_FRIENDLY_SPORT == {
        "running": "running",
        "cycling": "cycling",
        "walking": "walking",
        "strength_training": "strength",
    }
