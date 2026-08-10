"""Stable, privacy-bounded activity summary normalization."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .providers import (
    CYCLING_TYPE_KEYS,
    RUNNING_TYPE_KEYS,
    STRENGTH_TYPE_KEYS,
    MAX_RETURNED_SPLITS,
    WALKING_TYPE_KEYS,
    ProviderResult,
    get_activity,
    get_heart_rate_zones,
    get_power_zones,
    get_splits,
    get_strength,
)


AVAILABILITY_KEYS = (
    "activity",
    "splits",
    "heart_rate_zones",
    "power_zones",
    "strength",
)

ERROR_MESSAGES = {
    "invalid_activity_id": "activity_id must be a positive integer or decimal string.",
    "client_unavailable": "Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.",
    "activity_unavailable": "Activity data is unavailable. Check the activity ID, re-run garmin-mcp-auth if the session expired, or retry later.",
    "activity_not_found": "No activity data was found for the requested activity ID.",
    "invalid_activity_response": "Activity data had an unexpected shape.",
}

PROVIDER_WARNING_MESSAGES = {
    "provider_unavailable": {
        "splits": "Activity splits are unavailable.",
        "heart_rate_zones": "Heart-rate zone data is unavailable.",
        "power_zones": "Power-zone data is unavailable.",
        "strength": "Strength exercise-set data is unavailable.",
    },
    "invalid_provider_response": {
        "splits": "Activity splits response had an unexpected shape.",
        "heart_rate_zones": "Heart-rate zone response had an unexpected shape.",
        "power_zones": "Power-zone response had an unexpected shape.",
        "strength": "Strength exercise-set response had an unexpected shape.",
    },
    "splits_truncated": {
        "splits": "Activity splits were limited to 100 laps; split comparisons are unavailable.",
    },
}


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


def _error(code: str) -> dict[str, Any]:
    result = _empty_envelope()
    result["error"] = {"code": code, "message": ERROR_MESSAGES[code]}
    return result


def _positive_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 and _number(value) is not None else None
    if isinstance(value, str):
        text = value.strip()
        if text and text.isascii() and text.isdecimal():
            try:
                parsed = int(text)
            except ValueError:
                return None
            return parsed if parsed > 0 and _number(parsed) is not None else None
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
    if _number(parsed) is None:
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


def _rounded_finite(value: int | float, digits: int) -> float | None:
    try:
        rounded = round(value, digits)
    except (OverflowError, ValueError):
        return None
    try:
        return float(rounded) if math.isfinite(rounded) else None
    except OverflowError:
        return None


def _minutes(value: Any) -> float | None:
    seconds = _number(value, minimum=0)
    if seconds is None:
        return None
    try:
        return _rounded_finite(seconds / 60, 1)
    except OverflowError:
        return None


def _kilometers(value: Any) -> float | None:
    meters = _number(value, minimum=0)
    if meters is None:
        return None
    try:
        return _rounded_finite(meters / 1000, 2)
    except OverflowError:
        return None


def _speed_kph(value: Any) -> float | None:
    speed = _number(value, minimum=0)
    if speed is None:
        return None
    try:
        return _rounded_finite(speed * 3.6, 1)
    except OverflowError:
        return None


def _elevation(value: Any) -> float | None:
    meters = _number(value)
    return _rounded_finite(meters, 1) if meters is not None else None


def _pace(sport_family: str, duration: Any, distance: Any) -> str | None:
    seconds = _number(duration, minimum=0)
    meters = _number(distance, minimum=0)
    if sport_family not in {"running", "walking"} or not seconds or not meters:
        return None
    try:
        kilometers = meters / 1000
        if not math.isfinite(kilometers) or kilometers <= 0:
            return None
        seconds_per_km = int(round(seconds / kilometers))
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    return f"{seconds_per_km // 60}:{seconds_per_km % 60:02d}/km"


def _warning(provider: str, code: str, message: str) -> dict[str, str]:
    return {"provider": provider, "code": code, "message": message}


def _fixed_warning(provider: str, code: str) -> dict[str, str]:
    return _warning(provider, code, PROVIDER_WARNING_MESSAGES[code][provider])


def _absent_provider_data(data: Any) -> bool:
    """Recognize only JSON-like absent values without invoking foreign equality."""
    return data is None or (isinstance(data, dict) and not data)


def _split_item(lap: Mapping[str, Any], sport_family: str) -> tuple[dict[str, Any], float | None]:
    """Normalize a Garmin lap and retain its raw pace for split comparisons."""
    duration = _number(lap.get("duration"), minimum=0)
    distance = _number(lap.get("distance"), minimum=0)
    item = {
        "lap_number": _integer_equivalent(lap.get("lapIndex"), positive=True),
        "start_time": _text(lap.get("startTimeGMT"), 100),
        "duration_minutes": _minutes(duration),
        "moving_duration_minutes": _minutes(lap.get("movingDuration")),
        "elapsed_duration_minutes": _minutes(lap.get("elapsedDuration")),
        "distance_km": _kilometers(distance),
        "average_speed_kph": _speed_kph(lap.get("averageSpeed")),
        "max_speed_kph": _speed_kph(lap.get("maxSpeed")),
        "pace": _pace(sport_family, duration, distance),
        "average_hr_bpm": _number(lap.get("averageHR"), minimum=1),
        "max_hr_bpm": _number(lap.get("maxHR"), minimum=1),
        "average_cadence_spm": _number(lap.get("averageRunCadence"), minimum=1),
        "average_power_watts": _number(lap.get("averagePower"), minimum=1),
        "calories": _number(lap.get("calories"), minimum=0),
        "elevation_gain_meters": _elevation(lap.get("elevationGain")),
        "elevation_loss_meters": _elevation(lap.get("elevationLoss")),
        "intensity_type": _text(lap.get("intensityType"), 100),
    }
    raw_pace: float | None = None
    if sport_family in {"running", "walking"} and duration and distance:
        try:
            kilometers = distance / 1000
            candidate = duration / kilometers
            if kilometers > 0 and math.isfinite(kilometers) and math.isfinite(candidate):
                raw_pace = float(candidate)
        except (OverflowError, ValueError, ZeroDivisionError):
            pass
    return item, raw_pace


def _split_derived(
    items_with_pace: list[tuple[dict[str, Any], float | None]], truncated: bool, sport_family: str
) -> dict[str, Any]:
    derived = _empty_envelope()["derived"]
    if truncated or sport_family not in {"running", "walking"}:
        return derived
    comparisons = [(index, item, pace) for index, (item, pace) in enumerate(items_with_pace) if pace is not None]
    if not comparisons:
        return derived
    fastest = min(comparisons, key=lambda value: value[2])
    slowest = max(comparisons, key=lambda value: value[2])
    try:
        pace_range = int(round(slowest[2] - fastest[2]))
    except (OverflowError, ValueError):
        return derived

    def split_number(comparison: tuple[int, dict[str, Any], float]) -> int:
        return comparison[1]["lap_number"] or comparison[0] + 1

    return {
        "scope": "all_returned_splits",
        "fastest_split_number": split_number(fastest),
        "fastest_pace": _pace(sport_family, fastest[2], 1000),
        "slowest_split_number": split_number(slowest),
        "slowest_pace": _pace(sport_family, slowest[2], 1000),
        "pace_range_seconds_per_km": pace_range,
    }


def _apply_splits(result: dict[str, Any], client: Any, activity_id: int, payload: Mapping[str, Any]) -> None:
    """Fetch and normalize eligible split data without exposing provider details."""
    family = result["activity"]["sport_family"]
    metadata = _mapping_value(payload, "metadataDTO")
    if family not in {"running", "walking", "cycling"} or metadata.get("hasSplits") is False:
        return
    try:
        provider_result = get_splits(client, activity_id)
    except Exception:
        provider_result = ProviderResult(None, failed=True)
    if not isinstance(provider_result, ProviderResult) or provider_result.failed:
        _provider_unavailable(result, "splits")
        return
    split_data = provider_result.data
    if _absent_provider_data(split_data):
        return
    if not isinstance(split_data, Mapping) or not isinstance(split_data.get("lapDTOs"), list):
        _provider_invalid(result, "splits")
        return

    laps = split_data["lapDTOs"]
    truncated = len(laps) > MAX_RETURNED_SPLITS
    if truncated:
        result["warnings"].append(_fixed_warning("splits", "splits_truncated"))
    items_with_pace: list[tuple[dict[str, Any], float | None]] = []
    malformed = False
    for lap in laps[:MAX_RETURNED_SPLITS]:
        if not isinstance(lap, Mapping):
            malformed = True
            continue
        item, raw_pace = _split_item(lap, family)
        if not any(value is not None for value in item.values()):
            malformed = True
            continue
        items_with_pace.append((item, raw_pace))
    if malformed:
        _provider_invalid(result, "splits")
    if not items_with_pace and laps:
        return
    result["availability"]["splits"] = True
    result["splits"] = {
        "total_count": len(laps),
        "returned_count": len(items_with_pace),
        "truncated": truncated,
        "items": [item for item, _pace_value in items_with_pace],
    }
    result["derived"] = _split_derived(items_with_pace, truncated, family)


def _provider_invalid(result: dict[str, Any], provider: str) -> None:
    result["status"] = "partial_success"
    result["warnings"].append(_fixed_warning(provider, "invalid_provider_response"))


def _provider_unavailable(result: dict[str, Any], provider: str) -> None:
    result["status"] = "partial_success"
    result["warnings"].append(_fixed_warning(provider, "provider_unavailable"))


def _signal_present(summary: Mapping[str, Any], *keys: str) -> bool:
    return any(
        (numeric := _number(summary.get(key))) is not None and numeric > 0
        for key in keys
    )


def _zone_list(data: Any) -> list[Any] | None | bool:
    """Return zones, None for an absent response, and False for a malformed root."""
    if _absent_provider_data(data):
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping) and isinstance(data.get("zones"), list):
        return data["zones"]
    return False


def _zone_item(value: Any, *, boundary_unit: str) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(value, Mapping):
        return None, True
    zone = _integer_equivalent(value.get("zoneNumber"), positive=True)
    duration_seconds = _number(value.get("timeInZone"), minimum=0)
    percentage = _number(value.get("percentageInZone"))
    if percentage is not None and not 0 <= percentage <= 100:
        percentage = None
    lower = _number(value.get("zoneLowBoundary"), minimum=0)
    upper = _number(value.get("zoneHighBoundary"), minimum=0)
    invalid = (
        ("zoneNumber" in value and zone is None)
        or ("timeInZone" in value and duration_seconds is None)
        or ("percentageInZone" in value and percentage is None)
        or ("zoneLowBoundary" in value and lower is None)
        or ("zoneHighBoundary" in value and upper is None)
    )
    item = {
        "zone": zone,
        "duration_seconds": duration_seconds,
        "duration_minutes": _minutes(duration_seconds),
        "percentage": _rounded_finite(percentage, 1) if percentage is not None else None,
        f"lower_{boundary_unit}": lower,
        f"upper_{boundary_unit}": upper,
    }
    if not any(value is not None for value in (zone, duration_seconds, percentage, lower, upper)):
        return None, True
    return item, invalid


def _apply_zones(
    result: dict[str, Any], client: Any, activity_id: int, *, provider: str, reader: Any,
    boundary_unit: str,
) -> None:
    try:
        provider_result = reader(client, activity_id)
    except Exception:
        provider_result = ProviderResult(None, failed=True)
    if not isinstance(provider_result, ProviderResult) or provider_result.failed:
        _provider_unavailable(result, provider)
        return
    zones = _zone_list(provider_result.data)
    if zones is None:
        return
    if zones is False:
        _provider_invalid(result, provider)
        return
    items: list[dict[str, Any]] = []
    malformed = False
    for value in zones:
        item, item_malformed = _zone_item(value, boundary_unit=boundary_unit)
        malformed = malformed or item_malformed
        if item is not None:
            items.append(item)
    if not items and zones:
        _provider_invalid(result, provider)
        return
    result["availability"][provider] = True
    result[provider] = {"items": items}
    if malformed:
        _provider_invalid(result, provider)


def _strength_root(data: Any) -> list[Any] | None | bool:
    if _absent_provider_data(data):
        return None
    if isinstance(data, Mapping) and isinstance(data.get("exercises"), list):
        return data["exercises"]
    return False


def _strength_exercise(value: Any) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(value, Mapping):
        return None, True
    name = _text(value.get("exerciseName"), 200)
    malformed = "exerciseName" in value and name is None
    sets = value.get("sets")
    if not isinstance(sets, list):
        return None, True
    normalized_sets: list[dict[str, int | None]] = []
    repetitions: int | None = None
    for raw_set in sets:
        if not isinstance(raw_set, Mapping):
            malformed = True
            continue
        set_number = _integer_equivalent(raw_set.get("setNumber"), positive=True)
        raw_repetitions = _integer_equivalent(raw_set.get("reps"), positive=False)
        reps = raw_repetitions if raw_repetitions is not None and raw_repetitions >= 0 else None
        set_malformed = (
            ("setNumber" in raw_set and set_number is None)
            or ("reps" in raw_set and reps is None)
        )
        if set_number is None and reps is None:
            malformed = True
            continue
        malformed = malformed or set_malformed
        normalized_sets.append({"set_number": set_number, "repetitions": reps})
        if reps is not None:
            repetitions = (repetitions or 0) + reps
    if name is None and not normalized_sets:
        return None, True
    return {
        "name": name,
        "set_count": len(normalized_sets),
        "repetition_count": repetitions,
        "sets": normalized_sets,
    }, malformed


def _apply_strength(result: dict[str, Any], client: Any, activity_id: int) -> None:
    provider = "strength"
    try:
        provider_result = get_strength(client, activity_id)
    except Exception:
        provider_result = ProviderResult(None, failed=True)
    if not isinstance(provider_result, ProviderResult) or provider_result.failed:
        _provider_unavailable(result, provider)
        return
    exercises = _strength_root(provider_result.data)
    if exercises is None:
        return
    if exercises is False:
        _provider_invalid(result, provider)
        return
    items: list[dict[str, Any]] = []
    malformed = False
    for value in exercises:
        item, item_malformed = _strength_exercise(value)
        malformed = malformed or item_malformed
        if item is not None:
            items.append(item)
    if not items and exercises:
        _provider_invalid(result, provider)
        return
    set_count = sum(item["set_count"] for item in items)
    known_repetitions = [item["repetition_count"] for item in items if item["repetition_count"] is not None]
    result["availability"][provider] = True
    result[provider] = {
        "exercise_count": len(items),
        "set_count": set_count,
        "repetition_count": sum(known_repetitions) if known_repetitions else None,
        "items": items,
    }
    if malformed:
        _provider_invalid(result, provider)


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
        return _error("invalid_activity_id")
    if client is None:
        return _error("client_unavailable")

    try:
        provider_result = get_activity(client, normalized_id)
    except Exception:
        return _error("activity_unavailable")
    if not isinstance(provider_result, ProviderResult) or provider_result.failed:
        return _error("activity_unavailable")
    if _absent_provider_data(provider_result.data):
        return _error("activity_not_found")
    if not isinstance(provider_result.data, Mapping):
        return _error("invalid_activity_response")
    response_id = _integer_equivalent(provider_result.data.get("activityId"), positive=True)
    if response_id != normalized_id:
        return _error("invalid_activity_response")

    result = _empty_envelope()
    result["status"] = "success"
    result["activity"] = _activity_summary(provider_result.data, normalized_id)
    result["availability"]["activity"] = True
    family = result["activity"]["sport_family"]
    if family == "strength":
        _apply_strength(result, client, normalized_id)
        return result

    _apply_splits(result, client, normalized_id, provider_result.data)
    summary = _mapping_value(provider_result.data, "summaryDTO")
    if family in {"running", "walking", "cycling"} and _signal_present(
        summary, "averageHR", "maxHR", "minHR"
    ):
        _apply_zones(
            result, client, normalized_id,
            provider="heart_rate_zones", reader=get_heart_rate_zones, boundary_unit="bpm",
        )
    if family == "cycling" and _signal_present(
        summary, "averagePower", "maxPower", "normalizedPower"
    ):
        _apply_zones(
            result, client, normalized_id,
            provider="power_zones", reader=get_power_zones, boundary_unit="watts",
        )
    return result


__all__ = ["AVAILABILITY_KEYS", "analyze_activity_service"]
