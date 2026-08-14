"""Compact, read-only Garmin training context for AI coaching."""

from .heart_rate import (
    GAP_THRESHOLD_SECONDS,
    MAX_DAYS,
    MAX_RAW_POINTS,
    MAX_RETURNED_BINS,
    MAX_SERIALIZED_BYTES,
    MAX_SOURCE_POINTS_PER_DAY,
    get_wellness_heart_rate_service,
)
from .service import get_training_context_service


def configure(client):
    """Configure the training-context MCP tool without importing it eagerly."""
    from .tools import configure as configure_tools

    configure_tools(client)


def register_tools(app):
    """Register training-context tools without creating package import cycles."""
    from .tools import register_tools as register_ai_training_tools

    return register_ai_training_tools(app)


__all__ = [
    "GAP_THRESHOLD_SECONDS",
    "MAX_DAYS",
    "MAX_RAW_POINTS",
    "MAX_RETURNED_BINS",
    "MAX_SERIALIZED_BYTES",
    "MAX_SOURCE_POINTS_PER_DAY",
    "configure",
    "get_training_context_service",
    "get_wellness_heart_rate_service",
    "register_tools",
]
