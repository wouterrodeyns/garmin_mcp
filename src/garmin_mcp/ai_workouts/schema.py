"""Immutable normalized schema and validation for friendly workouts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias, Union

from .parsing import END_CONDITION_PARSERS, TARGET_PARSERS, parse_date


SPORTS = {"running", "cycling", "walking", "strength"}
SPORT_ALIASES = {"strength_training": "strength"}
ACTIONS = {"warmup", "cooldown", "work", "run", "interval", "recovery", "rest"}
_ACTION_METADATA = {"exercise", "category"}


@dataclass(frozen=True)
class EndCondition:
    kind: str
    value: float | None


@dataclass(frozen=True)
class Target:
    kind: str
    values: tuple[float, float] | None = None
    zone: int | None = None


@dataclass(frozen=True)
class ActionStep:
    action: str
    end_condition: EndCondition
    target: Target | None = None
    exercise: str | None = None
    category: str | None = None


WorkoutStep: TypeAlias = Union[ActionStep, "RepeatStep"]


@dataclass(frozen=True)
class RepeatStep:
    iterations: int
    steps: tuple[WorkoutStep, ...]


@dataclass(frozen=True)
class WorkoutDefinition:
    name: str
    sport: str
    steps: tuple[WorkoutStep, ...]
    schedule_date: str | None = None


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_sport(value: Any) -> str:
    sport = _require_nonempty_string(value, "sport").lower()
    sport = SPORT_ALIASES.get(sport, sport)
    if sport not in SPORTS:
        raise ValueError(f"unsupported sport: {value!r}")
    return sport


def _validate_repeat(raw_step: dict[str, Any], sport: str) -> RepeatStep:
    if set(raw_step) != {"repeat", "steps"}:
        raise ValueError("repeat groups must contain exactly repeat and steps")
    iterations = raw_step["repeat"]
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations <= 0:
        raise ValueError("repeat must be a positive integer")
    nested = raw_step["steps"]
    if not isinstance(nested, list) or not nested:
        raise ValueError("repeat steps must be a non-empty list")
    return RepeatStep(iterations, tuple(_validate_step(step, sport) for step in nested))


def _parse_end_condition(config: dict[str, Any]) -> EndCondition:
    end_keys = [key for key in config if key in END_CONDITION_PARSERS]
    if len(end_keys) != 1:
        raise ValueError("each action requires exactly one end condition")
    kind = end_keys[0]
    parsed = END_CONDITION_PARSERS[kind](config[kind])
    value = None if kind == "lap_button" else float(parsed)
    return EndCondition(kind, value)


def _parse_target(config: dict[str, Any], sport: str) -> Target | None:
    target_keys = [key for key in config if key in TARGET_PARSERS]
    if len(target_keys) > 1:
        raise ValueError("each action allows at most one target")
    if not target_keys:
        return None
    kind = target_keys[0]
    if kind == "pace" and sport != "running":
        raise ValueError("pace targets are supported only for running")
    if kind in {"power", "power_zone"} and sport != "cycling":
        raise ValueError("power targets are supported only for cycling")
    parsed = TARGET_PARSERS[kind](config[kind])
    if kind in {"heart_rate_zone", "power_zone"}:
        return Target(kind, zone=parsed)
    return Target(kind, values=tuple(float(part) for part in parsed))


def _parse_metadata(config: dict[str, Any], sport: str) -> tuple[str | None, str | None]:
    metadata = _ACTION_METADATA.intersection(config)
    if metadata and sport != "strength":
        field = sorted(metadata)[0]
        raise ValueError(f"{field} metadata is supported only for strength workouts")
    exercise = config.get("exercise")
    category = config.get("category")
    if exercise is not None:
        exercise = _require_nonempty_string(exercise, "exercise")
    if category is not None:
        category = _require_nonempty_string(category, "category")
    return exercise, category


def _validate_action(raw_step: dict[str, Any], action: str, sport: str) -> ActionStep:
    config = raw_step[action]
    if not isinstance(config, dict):
        raise ValueError(f"{action} action must contain a configuration object")
    allowed = set(END_CONDITION_PARSERS) | set(TARGET_PARSERS) | _ACTION_METADATA
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"unknown fields in {action} action: {sorted(unknown)!r}")
    end_condition = _parse_end_condition(config)
    target = _parse_target(config, sport)
    exercise, category = _parse_metadata(config, sport)
    return ActionStep(action, end_condition, target, exercise, category)


def _validate_step(raw_step: Any, sport: str) -> WorkoutStep:
    if not isinstance(raw_step, dict):
        raise ValueError("each step must be an object")
    unknown = set(raw_step) - (ACTIONS | {"repeat", "steps"})
    if unknown:
        raise ValueError(f"unknown step keys: {sorted(unknown)!r}")
    action_keys = [key for key in raw_step if key in ACTIONS]
    has_repeat = "repeat" in raw_step or "steps" in raw_step
    if has_repeat:
        if action_keys:
            raise ValueError("a step must contain exactly one action key or repeat and steps")
        if "repeat" not in raw_step or "steps" not in raw_step:
            raise ValueError("repeat groups must contain exactly repeat and steps")
        return _validate_repeat(raw_step, sport)
    if len(action_keys) != 1:
        raise ValueError("each step must contain exactly one action key")
    if len(raw_step) != 1:
        unknown = set(raw_step) - set(action_keys)
        raise ValueError(f"unknown or conflicting step keys: {sorted(unknown)!r}")
    return _validate_action(raw_step, action_keys[0], sport)


def validate_workout(
    name: Any,
    sport: Any,
    steps: Any,
    schedule_date: str | None = None,
) -> WorkoutDefinition:
    """Validate and normalize the friendly workout DSL."""

    normalized_name = _require_nonempty_string(name, "name")
    normalized_sport = _normalize_sport(sport)
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")
    normalized_steps = tuple(_validate_step(step, normalized_sport) for step in steps)
    normalized_date = None if schedule_date is None else parse_date(schedule_date).isoformat()
    return WorkoutDefinition(normalized_name, normalized_sport, normalized_steps, normalized_date)
