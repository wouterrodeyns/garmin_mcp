"""Orchestration for creating and safely updating friendly workouts."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from garmin_mcp.workouts import prepare_workout_for_upload, schedule_workout_for_date

from .compiler import compile_workout
from .schema import validate_workout


RAW_TO_FRIENDLY_SPORT = {
    "running": "running",
    "cycling": "cycling",
    "walking": "walking",
    "strength_training": "strength",
}
INVALID_WORKOUT_ID_MESSAGE = "workout_id must be a positive integer or ASCII decimal string"
INVALID_EXISTING_WORKOUT_MESSAGE = "Could not retrieve a valid existing workout from Garmin."
UPDATE_FAILED_MESSAGE = (
    "Garmin could not confirm the workout update; read the workout before retrying."
)
INVALID_UPDATE_RESPONSE_MESSAGE = (
    "Garmin returned an unexpected update response; read the workout before retrying."
)

_MAX_PROVIDER_JSON_DEPTH = 20
_MAX_PROVIDER_JSON_NODES = 10_000


def _error(name: str, message: str) -> dict[str, Any]:
    return {"status": "error", "name": name, "message": message}


def create_workout_service(
    client: Any,
    name: str,
    sport: str,
    steps: list[dict[str, Any]],
    schedule_date: str | None = None,
) -> dict[str, Any]:
    """Validate, upload, and optionally schedule one friendly workout.

    Uploading and scheduling are deliberately non-transactional: after Garmin
    returns a workout ID, any scheduling problem is reported as a partial
    success so callers can retain and use the uploaded workout.
    """
    try:
        definition = validate_workout(name, sport, steps, schedule_date)
        compiled = compile_workout(definition)
        prepared = prepare_workout_for_upload(compiled)
    except ValueError as exc:
        return _error(name, str(exc))

    try:
        uploaded = client.upload_workout(prepared)
    except Exception as exc:
        return _error(name, str(exc))

    if not isinstance(uploaded, dict) or uploaded.get("workoutId") is None:
        return _error(name, "Upload response did not include workout_id")

    workout_id = uploaded["workoutId"]
    result: dict[str, Any] = {
        "status": "success",
        "workout_id": workout_id,
        "name": uploaded.get("workoutName") or name,
    }
    if definition.schedule_date is None:
        return result

    try:
        scheduling = schedule_workout_for_date(
            workout_id, definition.schedule_date, client=client
        )
    except Exception as exc:
        result.update(
            {
                "status": "partial_success",
                "requested_date": definition.schedule_date,
                "scheduling_error": str(exc),
            }
        )
        return result

    if not isinstance(scheduling, dict) or scheduling.get("status") != "success":
        scheduling_error = (
            scheduling.get("message")
            if isinstance(scheduling, dict)
            else None
        ) or "Scheduling did not return a success status"
        result.update(
            {
                "status": "partial_success",
                "requested_date": definition.schedule_date,
                "scheduling_error": scheduling_error,
            }
        )
        return result

    result["scheduled_date"] = definition.schedule_date
    if scheduling.get("idempotent") is True:
        result["idempotent"] = True
    return result


def _normalize_workout_id(workout_id: Any) -> int:
    """Return a strictly accepted numeric workout identifier."""
    if type(workout_id) is int:
        normalized = workout_id
    elif type(workout_id) is str:
        value = workout_id.strip()
        if not value or not value.isascii() or not value.isdecimal():
            raise ValueError(INVALID_WORKOUT_ID_MESSAGE)
        normalized = int(value)
    else:
        raise ValueError(INVALID_WORKOUT_ID_MESSAGE)

    if normalized <= 0:
        raise ValueError(INVALID_WORKOUT_ID_MESSAGE)
    return normalized


def _is_plain_bounded_json_tree(value: Any) -> bool:
    """Reject provider payloads before invoking methods on untrusted containers."""
    stack = [(value, 1)]
    node_count = 0
    while stack:
        current, depth = stack.pop()
        node_count += 1
        if node_count > _MAX_PROVIDER_JSON_NODES or depth > _MAX_PROVIDER_JSON_DEPTH:
            return False

        current_type = type(current)
        if current_type is dict:
            if len(current) > _MAX_PROVIDER_JSON_NODES - node_count - len(stack):
                return False
            for key, child in current.items():
                if type(key) is not str:
                    return False
                stack.append((child, depth + 1))
        elif current_type is list:
            if len(current) > _MAX_PROVIDER_JSON_NODES - node_count - len(stack):
                return False
            for child in current:
                stack.append((child, depth + 1))
        elif current_type is float:
            if not math.isfinite(current):
                return False
        elif current_type not in (str, int, bool, type(None)):
            return False
    return True


def _is_finite_number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _has_safe_workout_step_scalars(step: dict[str, Any]) -> bool:
    """Validate only scalar shapes consumed by Taxuspt normalization helpers."""
    end_condition = step.get("endCondition")
    if end_condition is not None:
        if type(end_condition) is not dict:
            return False
        condition_key = end_condition.get("conditionTypeKey")
        condition_id = end_condition.get("conditionTypeId")
        if condition_key is not None and type(condition_key) is not str:
            return False
        if condition_id is not None and type(condition_id) is not int:
            return False

    end_condition_value = step.get("endConditionValue")
    if end_condition_value is not None and not _is_finite_number(end_condition_value):
        return False

    target_layouts = (
        ("targetType", ("targetValueOne", "targetValueTwo", "zoneNumber")),
        (
            "secondaryTargetType",
            ("secondaryTargetValueOne", "secondaryTargetValueTwo", "secondaryZoneNumber"),
        ),
    )
    for target_field, scalar_fields in target_layouts:
        target = step.get(target_field)
        if target is not None:
            if type(target) is not dict:
                return False
            target_key = target.get("workoutTargetTypeKey")
            target_id = target.get("workoutTargetTypeId")
            if target_key is not None and type(target_key) is not str:
                return False
            if target_id is not None and type(target_id) is not int:
                return False
            for scalar_field in scalar_fields:
                nested_value = target.get(scalar_field)
                if nested_value is not None and not _is_finite_number(nested_value):
                    return False

    for scalar_field in (
        "targetValueOne",
        "targetValueTwo",
        "secondaryTargetValueOne",
        "secondaryTargetValueTwo",
        "zoneNumber",
        "secondaryZoneNumber",
    ):
        value = step.get(scalar_field)
        if value is not None and not _is_finite_number(value):
            return False

    if step.get("type") == "RepeatGroupDTO":
        if "numberOfIterations" in step:
            number_of_iterations = step["numberOfIterations"]
            if type(number_of_iterations) is not int or number_of_iterations <= 0:
                return False
        elif (
            not _is_finite_number(end_condition_value)
            or end_condition_value <= 0
            or (
                type(end_condition_value) is float
                and not end_condition_value.is_integer()
            )
        ):
            return False
    return True


def _has_safe_workout_step_tree(segments: list[Any]) -> bool:
    """Reject DTO shapes Taxuspt cannot traverse safely during a rename."""
    stack = [(segment, 3, True) for segment in segments]
    node_count = 0
    while stack:
        current, depth, is_segment = stack.pop()
        node_count += 1
        if node_count > _MAX_PROVIDER_JSON_NODES or depth > _MAX_PROVIDER_JSON_DEPTH:
            return False

        if type(current) is not dict:
            return False
        if not is_segment and not _has_safe_workout_step_scalars(current):
            return False
        if "workoutSteps" not in current:
            if is_segment:
                return False
            continue

        nested_steps = current["workoutSteps"]
        if type(nested_steps) is not list:
            return False
        if (is_segment or current.get("type") == "RepeatGroupDTO") and not nested_steps:
            return False
        if len(nested_steps) > _MAX_PROVIDER_JSON_NODES - node_count - len(stack):
            return False
        for nested_step in nested_steps:
            stack.append((nested_step, depth + 2, False))
    return True


def _validated_existing_workout(existing: Any, requested_id: int) -> tuple[dict[str, Any], str]:
    """Validate the minimum whole-document shape required for a safe rename."""
    if not _is_plain_bounded_json_tree(existing) or type(existing) is not dict:
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE)

    try:
        existing_id = _normalize_workout_id(existing["workoutId"])
        workout_name = existing["workoutName"]
        sport_type = existing["sportType"]
        segments = existing["workoutSegments"]
    except (KeyError, ValueError):
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE) from None

    if existing_id != requested_id or type(workout_name) is not str or not workout_name.strip():
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE)
    if type(sport_type) is not dict or type(segments) is not list or not segments:
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE)
    if not _has_safe_workout_step_tree(segments):
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE)

    sport_key = sport_type.get("sportTypeKey")
    if type(sport_key) is not str or sport_key not in RAW_TO_FRIENDLY_SPORT:
        raise ValueError(INVALID_EXISTING_WORKOUT_MESSAGE)
    return existing, RAW_TO_FRIENDLY_SPORT[sport_key]


def _update_result(status: str, workout_id: int, name: str, sport: str) -> dict[str, Any]:
    return {
        "status": status,
        "workout_id": workout_id,
        "name": name,
        "sport": sport,
        "schedules_preserved": True,
    }


def update_workout_service(
    client: Any,
    workout_id: Any,
    name: Any = None,
    sport: Any = None,
    steps: Any = None,
) -> dict[str, Any]:
    """Apply a safe rename patch to an existing workout.

    Replacement-step compilation remains outside this rename-only service;
    callers supplying steps receive the fixed pre-write error below.
    """
    try:
        normalized_id = _normalize_workout_id(workout_id)
    except ValueError:
        return {"status": "error", "message": INVALID_WORKOUT_ID_MESSAGE}

    if sport is not None and steps is None:
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": "sport can be supplied only when steps is supplied",
        }
    if name is None and steps is None:
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": "at least one of name or steps is required",
        }
    if name is not None and (type(name) is not str or not name.strip()):
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": "name must be a non-empty string",
        }

    if client is None:
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": INVALID_EXISTING_WORKOUT_MESSAGE,
        }

    try:
        existing = client.get_workout_by_id(normalized_id)
    except Exception:
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": INVALID_EXISTING_WORKOUT_MESSAGE,
        }

    try:
        existing, friendly_sport = _validated_existing_workout(existing, normalized_id)
    except ValueError:
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": INVALID_EXISTING_WORKOUT_MESSAGE,
        }

    # Replacement-step updates require a separate full-structure compiler.
    if steps is not None:
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": "Replacing workout steps is not available yet",
        }

    effective_name = name.strip()
    document = deepcopy(existing)
    document["workoutName"] = effective_name
    try:
        prepared = prepare_workout_for_upload(document)
    except ValueError:
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": INVALID_EXISTING_WORKOUT_MESSAGE,
        }

    try:
        updated = client.update_workout(normalized_id, prepared)
    except Exception:
        return {
            "status": "error",
            "workout_id": normalized_id,
            "message": UPDATE_FAILED_MESSAGE,
            "update_may_have_applied": True,
        }

    if type(updated) is not dict:
        result = _update_result("partial_success", normalized_id, effective_name, friendly_sport)
        result["message"] = INVALID_UPDATE_RESPONSE_MESSAGE
        return result
    try:
        response_id = _normalize_workout_id(updated["workoutId"])
    except (KeyError, ValueError):
        response_id = None
    if response_id != normalized_id:
        result = _update_result("partial_success", normalized_id, effective_name, friendly_sport)
        result["message"] = INVALID_UPDATE_RESPONSE_MESSAGE
        return result
    return _update_result("success", normalized_id, effective_name, friendly_sport)
