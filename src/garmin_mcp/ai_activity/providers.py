"""Bounded, read-only Garmin activity data provider seams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from garminconnect import Garmin


RUNNING_TYPE_KEYS = frozenset({"running", "trail_running", "treadmill_running"})
WALKING_TYPE_KEYS = frozenset({"walking", "treadmill_walking"})
CYCLING_TYPE_KEYS = frozenset(
    {"cycling", "indoor_cycling", "road_biking", "mountain_biking", "gravel_cycling"}
)
STRENGTH_TYPE_KEYS = frozenset({"strength_training"})
MAX_RETURNED_SPLITS = 100
MAX_ORIGINAL_DOWNLOAD_BYTES = 25_000_000


@dataclass(frozen=True)
class ProviderResult:
    """Raw provider data and a bounded failure flag without exception details."""

    data: Any
    failed: bool = False


@dataclass(frozen=True)
class OriginalFitDownload:
    """Bounded original FIT archive result with a safe failure code."""

    archive: bytes | None
    failure_code: str | None


def _archive_bytes(payload: Any) -> bytes | None:
    if type(payload) is bytes:
        return payload
    if type(payload) is bytearray:
        return bytes(payload)
    if type(payload) is memoryview:
        try:
            if payload.contiguous and payload.itemsize == 1:
                return payload.tobytes()
        except ValueError:
            return None
    return None


def _memoryview_size(payload: memoryview) -> int | None:
    try:
        if payload.contiguous and payload.itemsize == 1:
            return payload.nbytes
    except ValueError:
        return None
    return None


def download_original_fit(client: Any, activity_id: int) -> OriginalFitDownload:
    """Download one bounded original FIT archive through the Garmin client."""
    try:
        payload = client.download_activity(
            activity_id,
            dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL,
        )
    except Exception:
        return OriginalFitDownload(None, "download_failed")

    if type(payload) is bytes:
        payload_size = len(payload)
    elif type(payload) is bytearray:
        payload_size = len(payload)
    elif type(payload) is memoryview:
        payload_size = _memoryview_size(payload)
        if payload_size is None:
            return OriginalFitDownload(None, "invalid_download_payload")
    else:
        return OriginalFitDownload(None, "invalid_download_payload")

    if payload_size == 0:
        return OriginalFitDownload(None, "invalid_download_payload")
    if payload_size > MAX_ORIGINAL_DOWNLOAD_BYTES:
        return OriginalFitDownload(None, "fit_download_too_large")

    archive = _archive_bytes(payload)
    if archive is None:
        return OriginalFitDownload(None, "invalid_download_payload")
    return OriginalFitDownload(archive, None)


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
    "MAX_ORIGINAL_DOWNLOAD_BYTES",
    "MAX_RETURNED_SPLITS",
    "OriginalFitDownload",
    "RUNNING_TYPE_KEYS",
    "STRENGTH_TYPE_KEYS",
    "WALKING_TYPE_KEYS",
    "ProviderResult",
    "get_activity",
    "download_original_fit",
    "get_heart_rate_zones",
    "get_power_zones",
    "get_splits",
    "get_strength",
]
