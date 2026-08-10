"""Bounded, read-only Garmin activity data provider seams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RUNNING_TYPE_KEYS = frozenset({"running", "trail_running", "treadmill_running"})
WALKING_TYPE_KEYS = frozenset({"walking", "treadmill_walking"})
CYCLING_TYPE_KEYS = frozenset(
    {"cycling", "indoor_cycling", "road_biking", "mountain_biking", "gravel_cycling"}
)
STRENGTH_TYPE_KEYS = frozenset({"strength_training"})
MAX_RETURNED_SPLITS = 100


@dataclass(frozen=True)
class ProviderResult:
    """Raw provider data and a bounded failure flag without exception details."""

    data: Any
    failed: bool = False


def get_activity(client: Any, activity_id: int) -> ProviderResult:
    """Read the activity summary through the pinned Garmin client method."""
    try:
        return ProviderResult(client.get_activity(activity_id))
    except Exception:
        return ProviderResult(None, failed=True)


def get_splits(client: Any, activity_id: int) -> ProviderResult:
    """Read activity splits through the pinned Garmin client method."""
    try:
        return ProviderResult(client.get_activity_splits(activity_id))
    except Exception:
        return ProviderResult(None, failed=True)


def get_heart_rate_zones(client: Any, activity_id: int) -> ProviderResult:
    """Read heart-rate zones through the pinned Garmin client method."""
    try:
        return ProviderResult(client.get_activity_hr_in_timezones(activity_id))
    except Exception:
        return ProviderResult(None, failed=True)


def get_power_zones(client: Any, activity_id: int) -> ProviderResult:
    """Read power zones through the pinned Garmin client method."""
    try:
        return ProviderResult(client.get_activity_power_in_timezones(activity_id))
    except Exception:
        return ProviderResult(None, failed=True)


def get_strength(client: Any, activity_id: int) -> ProviderResult:
    """Read strength exercise sets through the pinned Garmin client method."""
    try:
        return ProviderResult(client.get_activity_exercise_sets(activity_id))
    except Exception:
        return ProviderResult(None, failed=True)


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
