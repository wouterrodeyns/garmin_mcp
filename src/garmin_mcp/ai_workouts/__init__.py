"""Friendly, normalized workout definitions for AI-facing workout tools."""

from .compiler import END_CONDITION_COMPILERS, TARGET_COMPILERS, compile_workout
from .parsing import (
    END_CONDITION_PARSERS,
    TARGET_PARSERS,
    parse_date,
    parse_distance,
    parse_duration,
    parse_heart_rate,
    parse_lap_button,
    parse_pace,
    parse_power,
    parse_reps,
    parse_zone,
)
from .schema import (
    ActionStep,
    EndCondition,
    RepeatStep,
    Target,
    WorkoutDefinition,
    WorkoutStep,
    validate_workout,
)
from .service import (
    INVALID_EXISTING_WORKOUT_MESSAGE,
    INVALID_UPDATE_RESPONSE_MESSAGE,
    INVALID_WORKOUT_ID_MESSAGE,
    RAW_TO_FRIENDLY_SPORT,
    UPDATE_FAILED_MESSAGE,
    create_workout_service,
    update_workout_service,
)


def configure(client):
    """Configure the AI workout MCP tool without importing it eagerly."""
    from .tools import configure as configure_tools

    configure_tools(client)


def register_tools(app):
    """Register AI workout tools without creating package import cycles."""
    from .tools import register_tools as register_ai_workout_tools

    return register_ai_workout_tools(app)


__all__ = [
    "ActionStep",
    "END_CONDITION_COMPILERS",
    "END_CONDITION_PARSERS",
    "EndCondition",
    "RepeatStep",
    "TARGET_PARSERS",
    "Target",
    "WorkoutDefinition",
    "WorkoutStep",
    "TARGET_COMPILERS",
    "RAW_TO_FRIENDLY_SPORT",
    "INVALID_EXISTING_WORKOUT_MESSAGE",
    "INVALID_UPDATE_RESPONSE_MESSAGE",
    "INVALID_WORKOUT_ID_MESSAGE",
    "UPDATE_FAILED_MESSAGE",
    "compile_workout",
    "configure",
    "create_workout_service",
    "parse_date",
    "parse_distance",
    "parse_duration",
    "parse_heart_rate",
    "parse_lap_button",
    "parse_pace",
    "parse_power",
    "parse_reps",
    "parse_zone",
    "register_tools",
    "validate_workout",
    "update_workout_service",
]
