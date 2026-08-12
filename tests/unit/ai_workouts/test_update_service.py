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


def test_replacement_discards_legacy_step_tree_that_rename_rejects():
    legacy = deepcopy(EXISTING_RUNNING)
    legacy_step = legacy["workoutSegments"][0]["workoutSteps"][0]
    legacy_step.update(
        {
            "stepId": 501,
            "workoutSteps": None,
            "providerMetadata": "legacy-tree-sentinel",
        }
    )

    rename_client = RecordingClient(existing=deepcopy(legacy))
    rename_result = update_workout_service(rename_client, 123, name="New name")

    assert rename_result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert rename_client.calls == ["get_workout_by_id"]
    assert rename_client.updates == []
    assert rename_client.forbidden == []

    replacement_client = RecordingClient(existing=deepcopy(legacy))
    replacement_result = update_workout_service(
        replacement_client,
        123,
        steps=[{"run": {"duration": "30m"}}],
    )

    assert replacement_result["status"] == "success"
    assert replacement_client.calls == ["get_workout_by_id", "update_workout"]
    payload = replacement_client.updates[0][1]
    assert "stepId" not in str(payload)
    assert "legacy-tree-sentinel" not in str(payload)
    assert payload["workoutSegments"][0]["workoutSteps"][0]["endConditionValue"] == 1800.0
    assert replacement_client.forbidden == []


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


def _rename_existing_with_step_end_condition(end_condition):
    existing = deepcopy(EXISTING_RUNNING)
    step = existing["workoutSegments"][0]["workoutSteps"][0]
    if end_condition is None:
        del step["endCondition"]
    else:
        step["endCondition"] = end_condition
    existing["providerSecret"] = "token=retained-end-condition-secret"
    return existing


def _rename_existing_with_repeat_end_condition(end_condition):
    existing = _existing_repeat_with(2.0, number_of_iterations=2)
    repeat = existing["workoutSegments"][0]["workoutSteps"][0]
    if end_condition is None:
        del repeat["endCondition"]
    else:
        repeat["endCondition"] = end_condition
    existing["providerSecret"] = "token=retained-end-condition-secret"
    return existing


@pytest.mark.parametrize(
    "step_type", [pytest.param([], id="list"), pytest.param({}, id="dict")]
)
def test_rename_sanitizes_unhashable_retained_step_type(step_type):
    existing = _rename_existing_with_step_end_condition(
        {"conditionTypeId": 2, "conditionTypeKey": "time"}
    )
    existing["workoutSegments"][0]["workoutSteps"][0]["type"] = step_type
    existing["providerSecret"] = "token=unhashable-step-type-secret"
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert "unhashable-step-type-secret" not in str(result)
    assert client.calls == ["get_workout_by_id"]
    assert client.updates == []
    assert client.forbidden == []


@pytest.mark.parametrize(
    "existing",
    [
        pytest.param(_rename_existing_with_step_end_condition(None), id="executable-absent"),
        pytest.param(
            _rename_existing_with_step_end_condition({"conditionTypeKey": "time"}),
            id="executable-missing-id",
        ),
        pytest.param(
            _rename_existing_with_step_end_condition({"conditionTypeId": 2}),
            id="executable-missing-key",
        ),
        pytest.param(
            _rename_existing_with_step_end_condition(
                {"conditionTypeId": 3, "conditionTypeKey": "time"}
            ),
            id="executable-mismatched-pair",
        ),
        pytest.param(_rename_existing_with_repeat_end_condition(None), id="repeat-absent"),
        pytest.param(
            _rename_existing_with_repeat_end_condition({"conditionTypeKey": "iterations"}),
            id="repeat-missing-id",
        ),
        pytest.param(
            _rename_existing_with_repeat_end_condition({"conditionTypeId": 7}),
            id="repeat-missing-key",
        ),
        pytest.param(
            _rename_existing_with_repeat_end_condition(
                {"conditionTypeId": 2, "conditionTypeKey": "time"}
            ),
            id="repeat-non-iterations-pair",
        ),
    ],
)
def test_rename_rejects_retained_steps_without_canonical_end_condition(existing):
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert "retained-end-condition-secret" not in str(result)
    assert client.calls == ["get_workout_by_id"]
    assert client.updates == []
    assert client.forbidden == []


@pytest.mark.parametrize(
    "end_condition",
    [
        pytest.param({"conditionTypeId": 1, "conditionTypeKey": "lap.button"}, id="lap"),
        pytest.param({"conditionTypeId": 2, "conditionTypeKey": "time"}, id="time"),
        pytest.param({"conditionTypeId": 3, "conditionTypeKey": "distance"}, id="distance"),
        pytest.param({"conditionTypeId": 10, "conditionTypeKey": "reps"}, id="reps"),
    ],
)
def test_rename_accepts_compiler_supported_executable_end_conditions(end_condition):
    client = RecordingClient(existing=_rename_existing_with_step_end_condition(end_condition))

    result = update_workout_service(client, 123, name="New name")

    assert result["status"] == "success"
    assert client.calls == ["get_workout_by_id", "update_workout"]
    assert len(client.updates) == 1
    assert client.forbidden == []


def test_rename_accepts_repeat_group_with_canonical_iterations_end_condition():
    client = RecordingClient(
        existing=_rename_existing_with_repeat_end_condition(
            {"conditionTypeId": 7, "conditionTypeKey": "iterations"}
        )
    )

    result = update_workout_service(client, 123, name="New name")

    assert result["status"] == "success"
    assert client.calls == ["get_workout_by_id", "update_workout"]
    assert len(client.updates) == 1
    assert client.forbidden == []


def _rename_existing_with_repeat_counts(end_condition_value, number_of_iterations):
    existing = _existing_repeat_with(end_condition_value, number_of_iterations)
    existing["providerSecret"] = "token=retained-repeat-count-secret"
    return existing


@pytest.mark.parametrize(
    ("end_condition_value", "number_of_iterations"),
    [
        pytest.param(2, 3, id="mismatch"),
        pytest.param(0, 2, id="zero"),
        pytest.param(-1, 2, id="negative"),
        pytest.param(1.5, 2, id="fractional"),
        pytest.param(True, 2, id="bool"),
        pytest.param(float("inf"), 2, id="infinite"),
    ],
)
def test_rename_rejects_invalid_retained_repeat_counts(
    end_condition_value, number_of_iterations
):
    client = RecordingClient(
        existing=_rename_existing_with_repeat_counts(
            end_condition_value, number_of_iterations
        )
    )

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert "retained-repeat-count-secret" not in str(result)
    assert client.calls == ["get_workout_by_id"]
    assert client.updates == []
    assert client.forbidden == []


@pytest.mark.parametrize(
    "end_condition_value",
    [pytest.param(2, id="integer"), pytest.param(2.0, id="float")],
)
def test_rename_accepts_equal_retained_repeat_counts(end_condition_value):
    client = RecordingClient(existing=_existing_repeat_with(end_condition_value, 2))

    result = update_workout_service(client, 123, name="New name")

    assert result["status"] == "success"
    assert client.calls == ["get_workout_by_id", "update_workout"]
    assert len(client.updates) == 1
    assert client.forbidden == []


def test_rename_accepts_retained_repeat_end_condition_value_for_taxuspt_backfill():
    client = RecordingClient(existing=_existing_repeat_with(2.0))

    result = update_workout_service(client, 123, name="New name")

    assert result["status"] == "success"
    assert client.calls == ["get_workout_by_id", "update_workout"]
    repeat = client.updates[0][1]["workoutSegments"][0]["workoutSteps"][0]
    assert repeat["numberOfIterations"] == 2
    assert client.forbidden == []


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


def test_read_assertion_error_is_sanitized_without_update():
    class AssertionReadClient(RecordingClient):
        def get_workout_by_id(self, _workout_id):
            self.calls.append("get_workout_by_id")
            raise AssertionError("token=read-private")

    client = AssertionReadClient()

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": INVALID_EXISTING_WORKOUT_MESSAGE,
    }
    assert "token=read-private" not in str(result)
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


def test_update_assertion_error_is_ambiguous_and_sanitized_without_retry():
    client = RecordingClient(update_error=AssertionError("token=update-private"))

    result = update_workout_service(client, 123, name="New name")

    assert result == {
        "status": "error",
        "workout_id": 123,
        "message": UPDATE_FAILED_MESSAGE,
        "update_may_have_applied": True,
    }
    assert "token=update-private" not in str(result)
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


def test_steps_patch_inherits_name_and_sport_and_replaces_stale_document_fields():
    client = RecordingClient(existing=deepcopy(EXISTING_RUNNING))
    caller_steps = deepcopy(THRESHOLD_5X5)
    existing_before = deepcopy(client.existing)

    result = update_workout_service(client, 123, steps=caller_steps)

    assert result == {
        "status": "success",
        "workout_id": 123,
        "name": "Original aerobic run",
        "sport": "running",
        "schedules_preserved": True,
    }
    assert client.calls == ["get_workout_by_id", "update_workout"]
    _, payload = client.updates[0]
    assert payload["workoutName"] == "Original aerobic run"
    assert payload["description"] == "Keep this user-written note"
    assert payload["sportType"] == {"sportTypeId": 1, "sportTypeKey": "running"}
    repeat = payload["workoutSegments"][0]["workoutSteps"][1]
    assert repeat["numberOfIterations"] == 5
    pace = repeat["workoutSteps"][0]
    assert pace["targetValueOne"] == pytest.approx(1000 / 270)
    assert pace["targetValueTwo"] == pytest.approx(1000 / 260)
    for stale_field in (
        "estimatedDuration",
        "estimatedDistance",
        "createdDate",
        "updatedDate",
        "workoutProvider",
    ):
        assert stale_field not in payload
    assert "stepId" not in str(payload)
    assert caller_steps == THRESHOLD_5X5
    assert client.existing == existing_before
    assert client.forbidden == []


def test_steps_patch_can_replace_name_and_sport_with_cycling_power():
    client = RecordingClient()

    result = update_workout_service(
        client,
        123,
        name="Bike tempo",
        sport="cycling",
        steps=[{"work": {"duration": "20m", "power": "220-250W"}}],
    )

    assert result == {
        "status": "success",
        "workout_id": 123,
        "name": "Bike tempo",
        "sport": "cycling",
        "schedules_preserved": True,
    }
    _, payload = client.updates[0]
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
        ({"heart_rate_zone": "Z3"}, {"zoneNumber": 3}),
        (
            {"heart_rate": "150-165bpm"},
            {"targetValueOne": 150.0, "targetValueTwo": 165.0},
        ),
    ],
)
def test_steps_patch_compiles_named_and_custom_heart_rate_targets(target, expected):
    client = RecordingClient()
    step = {"duration": "20m"} | target

    result = update_workout_service(client, 123, steps=[{"run": step}])

    assert result["status"] == "success"
    compiled = client.updates[0][1]["workoutSegments"][0]["workoutSteps"][0]
    assert compiled["targetType"] == {
        "workoutTargetTypeId": 4,
        "workoutTargetTypeKey": "heart.rate.zone",
    }
    for field, value in expected.items():
        assert compiled[field] == value
    assert ("zoneNumber" in compiled) is ("zoneNumber" in expected)


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [{"run": {"duration": "broken"}}],
        [{"repeat": 51, "steps": [{"run": {"duration": "1m"}}]}],
    ],
)
def test_invalid_replacement_steps_read_once_but_never_write(steps):
    client = RecordingClient()

    result = update_workout_service(client, 123, steps=steps)

    assert result["status"] == "error"
    assert result["workout_id"] == 123
    assert client.calls == ["get_workout_by_id"]
    assert client.updates == []
    assert client.forbidden == []


def test_non_string_existing_description_is_not_copied_to_replacement():
    existing = deepcopy(EXISTING_RUNNING)
    existing["description"] = {"provider": "token=private"}
    client = RecordingClient(existing=existing)

    result = update_workout_service(client, 123, steps=[{"run": {"duration": "30m"}}])

    assert result["status"] == "success"
    payload = client.updates[0][1]
    assert "description" not in payload
    assert "token=private" not in str(payload)
    assert client.existing == existing


def test_steps_patch_prepares_the_compiled_document_before_updating(monkeypatch):
    client = RecordingClient()
    prepared_inputs = []

    def record_prepare(document):
        prepared_inputs.append(document)
        return document

    monkeypatch.setattr(service, "prepare_workout_for_upload", record_prepare)

    result = update_workout_service(client, 123, steps=[{"run": {"duration": "30m"}}])

    assert result["status"] == "success"
    assert len(prepared_inputs) == 1
    assert client.updates[0][1] is prepared_inputs[0]
    assert "estimatedDuration" not in prepared_inputs[0]


def test_replacement_compiler_value_error_propagates_without_update(monkeypatch):
    client = RecordingClient()

    def fail_compile(_definition):
        raise ValueError("compiler invariant sentinel")

    monkeypatch.setattr(service, "compile_workout", fail_compile)

    with pytest.raises(ValueError, match="compiler invariant sentinel"):
        update_workout_service(client, 123, steps=[{"run": {"duration": "30m"}}])

    assert client.calls == ["get_workout_by_id"]
    assert client.updates == []
    assert client.forbidden == []


def test_replacement_preparation_value_error_propagates_without_update(monkeypatch):
    client = RecordingClient()

    def fail_prepare(_document):
        raise ValueError("normalizer invariant sentinel")

    monkeypatch.setattr(service, "prepare_workout_for_upload", fail_prepare)

    with pytest.raises(ValueError, match="normalizer invariant sentinel"):
        update_workout_service(client, 123, steps=[{"run": {"duration": "30m"}}])

    assert client.calls == ["get_workout_by_id"]
    assert client.updates == []
    assert client.forbidden == []


@pytest.mark.parametrize(
    ("sport", "steps", "expected_sport_type"),
    [
        (
            "walking",
            [{"work": {"distance": "1km"}}],
            {"sportTypeId": 12, "sportTypeKey": "walking"},
        ),
        (
            "strength_training",
            [{"work": {"reps": 12, "exercise": "Squat", "category": "legs"}}],
            {"sportTypeId": 5, "sportTypeKey": "strength_training"},
        ),
    ],
)
def test_steps_patch_supports_other_friendly_compiler_sports(
    sport, steps, expected_sport_type
):
    client = RecordingClient()

    result = update_workout_service(client, 123, sport=sport, steps=steps)

    assert result["status"] == "success"
    assert client.updates[0][1]["sportType"] == expected_sport_type
