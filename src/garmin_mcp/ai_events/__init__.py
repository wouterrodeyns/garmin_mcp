"""Compact, read-only Garmin target-event evidence for AI coaching."""

from .service import (
    DEFAULT_LOOKAHEAD_DAYS,
    MAX_LOOKAHEAD_DAYS,
    get_target_events_service,
)


def configure(client):
    """Configure target-event tools without importing them eagerly."""
    from .tools import configure as configure_tools

    configure_tools(client)


def register_tools(app):
    """Register target-event tools without creating import cycles."""
    from .tools import register_tools as register_ai_events_tools

    return register_ai_events_tools(app)


__all__ = [
    "DEFAULT_LOOKAHEAD_DAYS",
    "MAX_LOOKAHEAD_DAYS",
    "configure",
    "get_target_events_service",
    "register_tools",
]
