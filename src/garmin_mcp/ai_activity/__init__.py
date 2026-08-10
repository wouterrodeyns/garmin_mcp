"""Read-only Garmin activity analysis provider seams."""

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


__all__ = [
    "CYCLING_TYPE_KEYS",
    "MAX_RETURNED_SPLITS",
    "RUNNING_TYPE_KEYS",
    "STRENGTH_TYPE_KEYS",
    "WALKING_TYPE_KEYS",
    "ProviderResult",
    "get_activity",
    "get_heart_rate_zones",
    "get_power_zones",
    "get_splits",
    "get_strength",
]
