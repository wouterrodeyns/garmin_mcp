"""Compact, read-only Garmin target-event evidence for AI coaching."""

def configure(client):
    """Configure target-event tools without importing them eagerly."""
    from .tools import configure as configure_tools

    configure_tools(client)


def register_tools(app):
    """Register target-event tools without creating import cycles."""
    from .tools import register_tools as register_ai_events_tools

    return register_ai_events_tools(app)


__all__ = [
    "configure",
    "register_tools",
]
