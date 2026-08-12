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
_DEFAULT_UPDATE_ERROR = object()


class _RawClientTrap:
    def __init__(self, owner):
        self._owner = owner

    def post(self, *_args, **_kwargs):
        return self._owner._forbidden("post")

    def put(self, *_args, **_kwargs):
        return self._owner._forbidden("put")

    def delete(self, *_args, **_kwargs):
        return self._owner._forbidden("delete")


class RecordingClient:
    def __init__(
        self,
        existing=EXISTING_RUNNING,
        update_response=_DEFAULT_RESPONSE,
        update_error=_DEFAULT_UPDATE_ERROR,
    ):
        self.existing = existing
        self.update_response = (
            {"workoutId": 123} if update_response is _DEFAULT_RESPONSE else update_response
        )
        self.update_error = update_error
        self.calls = []
        self.forbidden = []
        self.read_ids = []
        self.updates = []
        self.client = _RawClientTrap(self)

    def _forbidden(self, name):
        self.forbidden.append(name)
        raise AssertionError(f"forbidden provider operation: {name}")

    def get_workout_by_id(self, workout_id):
        self.calls.append("get_workout_by_id")
        self.read_ids.append(workout_id)
        return self.existing

    def update_workout(self, workout_id, document):
        self.calls.append("update_workout")
        self.updates.append((workout_id, document))
        if self.update_error is not _DEFAULT_UPDATE_ERROR:
            raise self.update_error
        return self.update_response

    def upload_workout(self, *_args, **_kwargs):
        return self._forbidden("upload_workout")

    def schedule_workout(self, *_args, **_kwargs):
        return self._forbidden("schedule_workout")

    def unschedule_workout(self, *_args, **_kwargs):
        return self._forbidden("unschedule_workout")

    def delete_workout(self, *_args, **_kwargs):
        return self._forbidden("delete_workout")


@pytest.mark.parametrize(
    "forbidden_method",
    [
        "upload_workout",
        "schedule_workout",
        "unschedule_workout",
        "delete_workout",
    ],
)
def test_recording_client_traps_forbidden_public_operations(forbidden_method):
    client = RecordingClient()

    with pytest.raises(AssertionError, match="forbidden provider operation"):
        getattr(client, forbidden_method)()

    assert client.forbidden == [forbidden_method]


@pytest.mark.parametrize("raw_method", ["post", "put", "delete"])
def test_recording_client_traps_forbidden_raw_operations(raw_method):
    client = RecordingClient()

    with pytest.raises(AssertionError, match="forbidden provider operation"):
        getattr(client.client, raw_method)()

    assert client.forbidden == [raw_method]


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
    assert client.calls == ["get_workout_by_id", "update_workout"]
    assert client.updates[0][0] == 123
    expected_payload = deepcopy(EXISTING_RUNNING)
    expected_payload["workoutName"] = "New name"
    assert client.updates[0][1] == expected_payload
    assert client.updates[0][1] is not client.existing
    assert client.existing == EXISTING_RUNNING
    assert client.forbidden == []


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
    assert client.calls == []
    assert client.forbidden == []


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
    assert client.calls == []
    assert client.forbidden == []


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
    assert client.calls == ["get_workout_by_id"]
    assert client.forbidden == []


@pytest.mark.parametrize(
    "mutate_existing",
    [
        pytest.param(
            lambda existing: existing.update({"workoutSegments": ["bad"]}),
            id="non-dict-segment",
        ),
        pytest.param(
            lambda existing: existing["workoutSegments"][0].update({"workoutSteps": None}),
            id="none-segment-steps",
        ),
        pytest.param(
            lambda existing: existing["workoutSegments"][0].update({"workoutSteps": {}}),
            id="dict-segment-steps",
        ),
        pytest.param(
            lambda existing: existing["workoutSegments"][0].update({"workoutSteps": ["bad"]}),
            id="non-dict-step",
        ),
        pytest.param(
            lambda existing: existing["workoutSegments"][0].update(
                {"workoutSteps": [{"type": "RepeatGroupDTO", "workoutSteps": None}]}
            ),
            id="repeat-with-none-steps",
        ),
        pytest.param(
            lambda existing: existing["workoutSegments"][0].update(
                {"workoutSteps": [{"type": "RepeatGroupDTO", "workoutSteps": ["bad"]}]}
            ),
            id="repeat-with-non-dict-child",
        ),
    ],
)
def test_malformed_existing_step_tree_is_rejected_before_update(mutate_existing):
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
    assert client.calls == ["get_workout_by_id"]
    assert client.forbidden == []


def _existing_repeat_with(end_condition_value, number_of_iterations=None):
    existing = deepcopy(EXISTING_RUNNING)
    repeat = {
        "type": "RepeatGroupDTO",
        "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
        "endConditionValue": end_condition_value,
        "workoutSteps": existing["workoutSegments"][0]["workoutSteps"],
    }
    if number_of_iterations is not None:
        repeat["numberOfIterations"] = number_of_iterations
    existing["workoutSegments"][0]["workoutSteps"] = [repeat]
    return existing


@pytest.mark.parametrize(
    "existing",
    [
        pytest.param(
            {
                **deepcopy(EXISTING_RUNNING),
                "workoutSegments": [
                    {
                        **deepcopy(EXISTING_RUNNING["workoutSegments"][0]),
                        "workoutSteps": [
                            {
                                **deepcopy(EXISTING_RUNNING["workoutSegments"][0]["workoutSteps"][0]),
                                "targetType": {
                                    "workoutTargetTypeId": 4,
                                    "workoutTargetTypeKey": "heart.rate.zone",
                                },
                                "targetValueOne": "token=secret",
                            }
                        ],
                    }
                ],
            },
            id="string-heart-rate-bound",
        ),
        pytest.param(
            {
                **deepcopy(EXISTING_RUNNING),
                "workoutSegments": [
                    {
                        **deepcopy(EXISTING_RUNNING["workoutSegments"][0]),
                        "workoutSteps": [
                            {
                                **deepcopy(EXISTING_RUNNING["workoutSegments"][0]["workoutSteps"][0]),
                                "endCondition": {"conditionTypeKey": []},
                            }
                        ],
                    }
                ],
            },
            id="unhashable-condition-key",
        ),
        pytest.param(
            {
                **deepcopy(EXISTING_RUNNING),
                "workoutSegments": [
                    {
                        **deepcopy(EXISTING_RUNNING["workoutSegments"][0]),
                        "workoutSteps": [
                            {
                                **deepcopy(EXISTING_RUNNING["workoutSegments"][0]["workoutSteps"][0]),
                                "targetType": {"workoutTargetTypeKey": []},
                            }
                        ],
                    }
                ],
            },
            id="unhashable-target-key",
        ),
        pytest.param(
            {
                **deepcopy(EXISTING_RUNNING),
                "workoutSegments": [
                    {
                        **deepcopy(EXISTING_RUNNING["workoutSegments"][0]),
                        "workoutSteps": [
                            {
                                **deepcopy(EXISTING_RUNNING["workoutSegments"][0]["workoutSteps"][0]),
                                "zoneNumber": "not-a-number",
                            }
                        ],
                    }
                ],
            },
            id="nonnumeric-zone",
        ),
        pytest.param(
            {
                **deepcopy(EXISTING_RUNNING),
                "workoutSegments": [
                    {
                        **deepcopy(EXISTING_RUNNING["workoutSegments"][0]),
                        "workoutSteps": [
                            {
                                **deepcopy(EXISTING_RUNNING["workoutSegments"][0]["workoutSteps"][0]),
                                "targetValueOne": float("nan"),
                            }
                        ],
                    }
                ],
            },
            id="nan-bound",
        ),
        pytest.param(
            {
                **deepcopy(EXISTING_RUNNING),
                "workoutSegments": [
                    {
                        **deepcopy(EXISTING_RUNNING["workoutSegments"][0]),
                        "workoutSteps": [
                            {
                                **deepcopy(EXISTING_RUNNING["workoutSegments"][0]["workoutSteps"][0]),
                                "secondaryZoneNumber": float("inf"),
                            }
                        ],
                    }
                ],
            },
            id="infinite-secondary-zone",
        ),
        pytest.param(_existing_repeat_with("bad"), id="repeat-string-iterations"),
        pytest.param(_existing_repeat_with([]), id="repeat-list-iterations"),
        pytest.param(_existing_repeat_with(float("inf")), id="repeat-infinite-iterations"),
        pytest.param(_existing_repeat_with(1.5), id="repeat-fractional-iterations"),
    ],
)
def test_malformed_existing_step_scalars_are_rejected_before_update(existing):
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert "secret" not in str(result)
    assert client.updates == []


def test_valid_custom_heart_rate_bounds_are_accepted():
    existing = deepcopy(EXISTING_RUNNING)
    step = existing["workoutSegments"][0]["workoutSteps"][0]
    step["targetType"] = {
        "workoutTargetTypeId": 4,
        "workoutTargetTypeKey": "heart.rate.zone",
    }
    step["targetValueOne"] = 105.0
    step["targetValueTwo"] = 143.0
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, name="New name")

    assert result["status"] == "success"
    assert len(client.updates) == 1


def test_valid_repeat_group_with_numeric_iterations_is_accepted():
    client = RecordingClient(existing=_existing_repeat_with(2.0, number_of_iterations=2))

    result = update_workout_service(client, 123, name="New name")

    assert result["status"] == "success"
    assert len(client.updates) == 1


def test_unexpected_prepare_type_error_propagates(monkeypatch):
    client = RecordingClient()

    def fail_prepare(_document):
        raise TypeError("internal normalization sentinel")

    monkeypatch.setattr(service, "prepare_workout_for_upload", fail_prepare)

    with pytest.raises(TypeError, match="internal normalization sentinel"):
        update_workout_service(client, 123, name="New name")

    assert client.updates == []
    assert client.calls == ["get_workout_by_id"]
    assert client.forbidden == []


def test_prepare_value_error_is_sanitized_without_update(monkeypatch):
    client = RecordingClient()

    def fail_prepare(_document):
        raise ValueError("token=private normalization failure")

    monkeypatch.setattr(service, "prepare_workout_for_upload", fail_prepare)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert "private" not in str(result)
    assert client.calls == ["get_workout_by_id"]
    assert client.updates == []
    assert client.forbidden == []


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


def test_wide_provider_tree_is_rejected_before_unbounded_pending_worklist():
    existing = deepcopy(EXISTING_RUNNING)
    existing["wide"] = [0] * (service._MAX_PROVIDER_JSON_NODES + 1)
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
    assert client.calls == ["get_workout_by_id"]
    assert client.forbidden == []


def test_read_exception_is_sanitized_without_update():
    class RaisingReadClient(RecordingClient):
        def get_workout_by_id(self, _workout_id):
            self.calls.append("get_workout_by_id")
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
    assert client.calls == ["get_workout_by_id"]
    assert client.forbidden == []


def test_read_assertion_error_propagates_without_update():
    class AssertionReadClient(RecordingClient):
        def get_workout_by_id(self, _workout_id):
            self.calls.append("get_workout_by_id")
            raise AssertionError("internal read invariant")

    client = AssertionReadClient()

    with pytest.raises(AssertionError, match="internal read invariant"):
        update_workout_service(client, 123, name="New name")

    assert client.calls == ["get_workout_by_id"]
    assert client.updates == []
    assert client.forbidden == []


def test_internal_existing_validation_error_propagates(monkeypatch):
    client = RecordingClient()

    def fail_validation(*_args):
        raise RuntimeError("internal validation sentinel")

    monkeypatch.setattr(service, "_validated_existing_workout", fail_validation)

    with pytest.raises(RuntimeError, match="internal validation sentinel"):
        update_workout_service(client, 123, name="New name")

    assert client.updates == []
    assert client.calls == ["get_workout_by_id"]
    assert client.forbidden == []


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
        prepared = original_prepare(document)
        prepared_inputs.append((document, prepared))
        return prepared

    monkeypatch.setattr(service, "prepare_workout_for_upload", record_prepare)

    result = update_workout_service(client, 123, name="  Prepared rename ")

    assert result["status"] == "success"
    assert len(prepared_inputs) == 1
    assert prepared_inputs[0][0]["workoutName"] == "Prepared rename"
    assert prepared_inputs[0][0] is not existing
    assert client.updates[0][1] is prepared_inputs[0][1]
    assert existing == EXISTING_RUNNING


def test_update_exception_is_ambiguous_and_sanitized():
    client = RecordingClient(update_error=RuntimeError("token=secret"))

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": UPDATE_FAILED_MESSAGE,
        "update_may_have_applied": True,
    }
    assert "secret" not in str(result)
    assert client.calls == ["get_workout_by_id", "update_workout"]
    assert len(client.updates) == 1
    assert client.forbidden == []


def test_update_assertion_error_propagates_without_retry():
    client = RecordingClient(update_error=AssertionError("internal update invariant"))

    with pytest.raises(AssertionError, match="internal update invariant"):
        update_workout_service(client, 123, name="New name")

    assert client.calls == ["get_workout_by_id", "update_workout"]
    assert len(client.updates) == 1
    assert client.forbidden == []


@pytest.mark.parametrize(
    "response",
    [None, False, 0, "", [], {}, {"workoutId": 999}, {"workoutId": "not-an-id"}],
)
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
    assert client.calls == ["get_workout_by_id", "update_workout"]
    assert len(client.updates) == 1
    assert client.forbidden == []


def test_trimmed_ascii_decimal_update_response_id_confirms_success():
    client = RecordingClient(update_response={"workoutId": " 123 "})

    result = update_workout_service(client, 123, name="New name")

    assert result["status"] == "success"
    assert client.calls == ["get_workout_by_id", "update_workout"]
    assert client.forbidden == []


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
    assert client.calls == ["get_workout_by_id", "update_workout"]
    assert len(client.updates) == 1
    assert client.forbidden == []


def test_public_contract_exports_stable_sport_mapping():
    assert RAW_TO_FRIENDLY_SPORT == {
        "running": "running",
        "cycling": "cycling",
        "walking": "walking",
        "strength_training": "strength",
    }
