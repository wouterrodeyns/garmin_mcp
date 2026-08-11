"""Read-only Garmin activity analysis provider seams."""

from .service import analyze_activity_service
from .providers import (
    CYCLING_TYPE_KEYS,
    MAX_RETURNED_SPLITS,
    RUNNING_TYPE_KEYS,
    STRENGTH_TYPE_KEYS,
    WALKING_TYPE_KEYS,
    ProviderResult,
    get_activity,
    get_heart_rate_zones,
    get_power_zones,
    get_splits,
    get_strength,
)


def configure(client):
    """Configure the activity-analysis MCP tool without importing it eagerly."""
    from .tools import configure as configure_tools

    configure_tools(client)


def register_tools(app):
    """Register activity-analysis tools without creating package import cycles."""
    from .tools import register_tools as register_ai_activity_tools

    return register_ai_activity_tools(app)


__all__ = [
    "CYCLING_TYPE_KEYS",
    "MAX_RETURNED_SPLITS",
    "RUNNING_TYPE_KEYS",
    "STRENGTH_TYPE_KEYS",
    "WALKING_TYPE_KEYS",
    "ProviderResult",
    "analyze_activity_service",
    "configure",
    "get_activity",
    "get_heart_rate_zones",
    "get_power_zones",
    "get_splits",
    "get_strength",
    "register_tools",
]
