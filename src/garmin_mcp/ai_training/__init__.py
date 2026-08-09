"""Compact, read-only Garmin training context for AI coaching."""

from .service import get_training_context_service


def configure(client):
    """Configure the training-context MCP tool without importing it eagerly."""
    from .tools import configure as configure_tools

    configure_tools(client)


def register_tools(app):
    """Register training-context tools without creating package import cycles."""
    from .tools import register_tools as register_ai_training_tools

    return register_ai_training_tools(app)


__all__ = ["configure", "get_training_context_service", "register_tools"]
