"""Stable, privacy-bounded activity summary normalization."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .providers import (
    CYCLING_TYPE_KEYS,
    RUNNING_TYPE_KEYS,
    STRENGTH_TYPE_KEYS,
    WALKING_TYPE_KEYS,
    ProviderResult,
    get_activity,
)


AVAILABILITY_KEYS = (
    "activity",
    "splits",
    "heart_rate_zones",
    "power_zones",
    "strength",
)


def _empty_envelope() -> dict[str, Any]:
    return {
        "status": "error",
        "error": None,
        "activity": None,
        "availability": {key: False for key in AVAILABILITY_KEYS},
        "splits": None,
        "heart_rate_zones": None,
        "power_zones": None,
        "strength": None,
        "derived": {
            "scope": None,
            "fastest_split_number": None,
            "fastest_pace": None,
            "slowest_split_number": None,
            "slowest_pace": None,
            "pace_range_seconds_per_km": None,
        },
        "warnings": [],
    }


def _error(code: str, message: str) -> dict[str, Any]:
    result = _empty_envelope()
    result["error"] = {"code": code, "message": message}
    return result


def _positive_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text and text.isascii() and text.isdecimal():
            try:
                parsed = int(text)
            except ValueError:
                return None
            return parsed if parsed > 0 else None
    return None


def _integer_equivalent(value: Any, *, positive: bool = False) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text or not text.isascii() or not text.isdecimal():
            return None
        try:
            parsed = int(text)
        except ValueError:
            return None
    else:
        return None
    if positive and parsed <= 0:
        return None
    return parsed


def _number(value: Any, *, minimum: float | None = None) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        is_finite = math.isfinite(value)
    except OverflowError:
        return None
    if not is_finite:
        return None
    if minimum is not None and value < minimum:
        return None
    return value


def _text(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:maximum] or None


def _number_or_text(value: Any, maximum: int = 100) -> int | float | str | None:
    numeric = _number(value)
    return numeric if numeric is not None else _text(value, maximum)


def _mapping_value(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    candidate = payload.get(key)
    return candidate if isinstance(candidate, Mapping) else {}


def _type_key(payload: Mapping[str, Any], primary: str, fallback: str) -> str | None:
    value = _text(_mapping_value(payload, primary).get("typeKey"), 100)
    return value if value is not None else _text(_mapping_value(payload, fallback).get("typeKey"), 100)


def _sport_family(sport: str | None) -> str:
    if sport in RUNNING_TYPE_KEYS:
        return "running"
    if sport in WALKING_TYPE_KEYS:
        return "walking"
    if sport in CYCLING_TYPE_KEYS:
        return "cycling"
    if sport in STRENGTH_TYPE_KEYS:
        return "strength"
    return "generic"


def _minutes(value: Any) -> float | None:
    seconds = _number(value, minimum=0)
    return round(seconds / 60, 1) if seconds is not None else None


def _kilometers(value: Any) -> float | None:
    meters = _number(value, minimum=0)
    return round(meters / 1000, 2) if meters is not None else None


def _speed_kph(value: Any) -> float | None:
    speed = _number(value, minimum=0)
    return round(speed * 3.6, 1) if speed is not None else None


def _elevation(value: Any) -> float | None:
    meters = _number(value)
    return round(meters, 1) if meters is not None else None


def _pace(sport_family: str, duration: Any, distance: Any) -> str | None:
    seconds = _number(duration, minimum=0)
    meters = _number(distance, minimum=0)
    if sport_family not in {"running", "walking"} or not seconds or not meters:
        return None
    seconds_per_km = int(round(seconds / (meters / 1000)))
    return f"{seconds_per_km // 60}:{seconds_per_km % 60:02d}/km"


def _activity_summary(payload: Mapping[str, Any], activity_id: int) -> dict[str, Any]:
    summary = _mapping_value(payload, "summaryDTO")
    metadata = _mapping_value(payload, "metadataDTO")
    sport = _type_key(payload, "activityTypeDTO", "activityType")
    family = _sport_family(sport)
    duration = summary.get("duration")
    distance = summary.get("distance")
    return {
        "id": activity_id,
        "name": _text(payload.get("activityName"), 200),
        "description": _text(payload.get("description"), 500),
        "sport": sport,
        "sport_family": family,
        "event_type": _type_key(payload, "eventTypeDTO", "eventType"),
        "start_time_local": _text(summary.get("startTimeLocal"), 100),
        "duration_minutes": _minutes(duration),
        "moving_duration_minutes": _minutes(summary.get("movingDuration")),
        "elapsed_duration_minutes": _minutes(summary.get("elapsedDuration")),
        "distance_km": _kilometers(distance),
        "average_speed_kph": _speed_kph(summary.get("averageSpeed")),
        "max_speed_kph": _speed_kph(summary.get("maxSpeed")),
        "average_pace": _pace(family, duration, distance),
        "heart_rate": {
            "average_bpm": _number(summary.get("averageHR"), minimum=1),
            "max_bpm": _number(summary.get("maxHR"), minimum=1),
            "min_bpm": _number(summary.get("minHR"), minimum=1),
        },
        "power": {
            "average_watts": _number(summary.get("averagePower"), minimum=1),
            "max_watts": _number(summary.get("maxPower"), minimum=1),
            "normalized_watts": _number(summary.get("normalizedPower"), minimum=1),
        },
        "cadence": {
            "average_spm": _number(summary.get("averageRunCadence"), minimum=1),
            "max_spm": _number(summary.get("maxRunCadence"), minimum=1),
        },
        "elevation": {
            "gain_meters": _elevation(summary.get("elevationGain")),
            "loss_meters": _elevation(summary.get("elevationLoss")),
            "minimum_meters": _elevation(summary.get("minElevation")),
            "maximum_meters": _elevation(summary.get("maxElevation")),
        },
        "calories": _number(summary.get("calories"), minimum=0),
        "training_effect": {
            "aerobic": _number(summary.get("trainingEffect")),
            "anaerobic": _number(summary.get("anaerobicTrainingEffect")),
            "label": _text(summary.get("trainingEffectLabel"), 100),
            "load": _number(summary.get("activityTrainingLoad"), minimum=0),
        },
        "workout_feedback": {
            "rpe": _number(summary.get("directWorkoutRpe")),
            "feel": _number_or_text(summary.get("directWorkoutFeel")),
        },
        "recovery": {
            "heart_rate_bpm": _number(summary.get("recoveryHeartRate"), minimum=1),
            "body_battery_impact": _number(summary.get("differenceBodyBattery")),
        },
        "reported_lap_count": _integer_equivalent(metadata.get("lapCount"), positive=False),
    }


def analyze_activity_service(client: Any, activity_id: Any) -> dict[str, Any]:
    """Return a complete stable envelope for one normalized Garmin activity."""
    normalized_id = _positive_id(activity_id)
    if normalized_id is None:
        return _error(
            "invalid_activity_id", "activity_id must be a positive integer or decimal string."
        )
    if client is None:
        return _error(
            "client_unavailable",
            "Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.",
        )

    try:
        provider_result = get_activity(client, normalized_id)
    except Exception:
        return _error(
            "activity_unavailable",
            "Activity data is unavailable. Check the activity ID, re-run garmin-mcp-auth if the session expired, or retry later.",
        )
    if not isinstance(provider_result, ProviderResult) or provider_result.failed:
        return _error(
            "activity_unavailable",
            "Activity data is unavailable. Check the activity ID, re-run garmin-mcp-auth if the session expired, or retry later.",
        )
    if provider_result.data is None or provider_result.data == {}:
        return _error("activity_not_found", "No activity data was found for the requested activity ID.")
    if not isinstance(provider_result.data, Mapping):
        return _error("invalid_activity_response", "Activity data had an unexpected shape.")
    response_id = _integer_equivalent(provider_result.data.get("activityId"), positive=True)
    if response_id != normalized_id:
        return _error("invalid_activity_response", "Activity data had an unexpected shape.")

    result = _empty_envelope()
    result["status"] = "success"
    result["activity"] = _activity_summary(provider_result.data, normalized_id)
    result["availability"]["activity"] = True
    return result


__all__ = ["AVAILABILITY_KEYS", "analyze_activity_service"]
