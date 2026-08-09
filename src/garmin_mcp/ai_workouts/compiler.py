"""Compile normalized friendly workouts into Garmin Connect workout JSON."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .schema import ActionStep, Target, WorkoutDefinition, WorkoutStep


SPORT_TYPES: Mapping[str, tuple[int, str]] = {
    "running": (1, "running"),
    "cycling": (2, "cycling"),
    "strength": (5, "strength_training"),
    "walking": (12, "walking"),
}

STEP_TYPES: Mapping[str, tuple[int, str]] = {
    "warmup": (1, "warmup"),
    "cooldown": (2, "cooldown"),
    "work": (3, "interval"),
    "run": (3, "interval"),
    "interval": (3, "interval"),
    "recovery": (4, "recovery"),
    "rest": (5, "rest"),
}

END_CONDITIONS: Mapping[str, tuple[int, str]] = {
    "lap_button": (1, "lap.button"),
    "duration": (2, "time"),
    "distance": (3, "distance"),
    "reps": (10, "reps"),
}


def _target_type(target_id: int, target_key: str) -> dict[str, Any]:
    return {"workoutTargetTypeId": target_id, "workoutTargetTypeKey": target_key}


def _no_target() -> dict[str, Any]:
    return {"targetType": _target_type(1, "no.target")}


def _bounds_target(target: Target, target_id: int, target_key: str) -> dict[str, Any]:
    if target.values is None:
        raise ValueError(f"target {target.kind!r} requires a value range")
    low, high = target.values
    return {
        "targetType": _target_type(target_id, target_key),
        "targetValueOne": low,
        "targetValueTwo": high,
    }


def _pace_target(target: Target) -> dict[str, Any]:
    return _bounds_target(target, 6, "pace.zone")


def _heart_rate_zone_target(target: Target) -> dict[str, Any]:
    if target.zone is None:
        raise ValueError("heart_rate_zone target requires a zone")
    return {"targetType": _target_type(4, "heart.rate.zone"), "zoneNumber": target.zone}


def _heart_rate_target(target: Target) -> dict[str, Any]:
    return _bounds_target(target, 4, "heart.rate.zone")


def _power_zone_target(target: Target) -> dict[str, Any]:
    if target.zone is None:
        raise ValueError("power_zone target requires a zone")
    return {"targetType": _target_type(2, "power.zone"), "zoneNumber": target.zone}


def _power_target(target: Target) -> dict[str, Any]:
    return _bounds_target(target, 6, "power.between")


TargetCompiler = Callable[[Target], dict[str, Any]]
TARGET_COMPILERS: dict[str, TargetCompiler] = {
    "pace": _pace_target,
    "heart_rate_zone": _heart_rate_zone_target,
    "heart_rate": _heart_rate_target,
    "power_zone": _power_zone_target,
    "power": _power_target,
}


def _step_type(action: str) -> dict[str, Any]:
    step_id, step_key = STEP_TYPES[action]
    return {"stepTypeId": step_id, "stepTypeKey": step_key}


def _end_condition(action: ActionStep) -> dict[str, Any]:
    condition_id, condition_key = END_CONDITIONS[action.end_condition.kind]
    return {"conditionTypeId": condition_id, "conditionTypeKey": condition_key}


def _compile_action(action: ActionStep, order: int) -> dict[str, Any]:
    compiled: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": _step_type(action.action),
        "endCondition": _end_condition(action),
    }
    compiled.update(
        _no_target()
        if action.target is None
        else TARGET_COMPILERS[action.target.kind](action.target)
    )
    if action.end_condition.value is not None:
        compiled["endConditionValue"] = action.end_condition.value
    if action.exercise is not None:
        compiled["exerciseName"] = action.exercise
    if action.category is not None:
        compiled["category"] = action.category
    return compiled


def _compile_steps(steps: tuple[WorkoutStep, ...]) -> list[dict[str, Any]]:
    compiled: list[dict[str, Any]] = []
    for order, step in enumerate(steps, start=1):
        if isinstance(step, ActionStep):
            compiled.append(_compile_action(step, order))
        else:
            compiled.append(
                {
                    "type": "RepeatGroupDTO",
                    "stepOrder": order,
                    "numberOfIterations": step.iterations,
                    "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
                    "endConditionValue": float(step.iterations),
                    "workoutSteps": _compile_steps(step.steps),
                }
            )
    return compiled


def compile_workout(definition: WorkoutDefinition) -> dict[str, Any]:
    """Compile an immutable normalized definition without mutating it."""

    sport_id, sport_key = SPORT_TYPES[definition.sport]
    sport_type = {"sportTypeId": sport_id, "sportTypeKey": sport_key}
    return {
        "workoutName": definition.name,
        "sportType": sport_type.copy(),
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": sport_type.copy(),
                "workoutSteps": _compile_steps(definition.steps),
            }
        ],
    }
