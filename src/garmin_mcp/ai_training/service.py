"""Assembly of a compact, stable AI training-context response."""

from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from numbers import Real
from typing import Any

from garmin_mcp.ai_training.providers import (
    RUNNING_TYPE_KEYS,
    ProviderResult,
    get_daily_stats,
    get_hrv,
    get_last_run,
    get_period_activities,
    get_scheduled_workouts,
    get_sleep,
    get_training_readiness,
    get_training_status,
)


def _iso_day(value: Any) -> str | None:
    """Return a canonical ISO date from a local Garmin timestamp."""
    if not isinstance(value, str):
        return None
    candidate = value[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _local_timestamp(value: Any) -> float | None:
    """Validate a local start timestamp and return a chronological sort key."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _activity_sport(activity: dict[str, Any]) -> str | None:
    activity_type = activity.get("activityType")
    type_key = activity_type.get("typeKey") if isinstance(activity_type, dict) else None
    return type_key if isinstance(type_key, str) and type_key else None


def _reduced_activity(activity: dict[str, Any]) -> tuple[dict[str, Any], float | None]:
    """Expose only compact, non-identifying activity fields."""
    item: dict[str, Any] = {}
    sport = _activity_sport(activity)
    if sport is not None:
        item["sport"] = sport
    activity_date = _iso_day(activity.get("startTimeLocal"))
    if activity_date is not None:
        item["date"] = activity_date

    duration = _finite_number(activity.get("duration"))
    if duration is not None:
        item["duration_minutes"] = round(duration / 60, 1)
    distance = _finite_number(activity.get("distance"))
    if distance is not None:
        item["distance_km"] = round(distance / 1000, 2)
    average_hr = _finite_number(activity.get("averageHR"))
    if average_hr is not None:
        item["average_hr"] = average_hr if average_hr % 1 else int(average_hr)
    max_hr = _finite_number(activity.get("maxHR"))
    if max_hr is not None:
        item["max_hr"] = max_hr if max_hr % 1 else int(max_hr)
    speed = _finite_number(activity.get("averageSpeed"))
    if speed is not None:
        item["average_speed_kmh"] = round(speed * 3.6, 1)
    return item, _local_timestamp(activity.get("startTimeLocal"))


def _base_result(today: date, days: int | None) -> dict[str, Any]:
    end = today.isoformat()
    start = (today.fromordinal(today.toordinal() - (days - 1))).isoformat() if days else None
    schedule_end = today.fromordinal(today.toordinal() + 6).isoformat()
    return {
        "status": "success",
        "error": None,
        "period": {"days": days, "start_date": start, "end_date": end},
        "schedule_period": {"start_date": end, "end_date": schedule_end},
        "availability": {
            "activities": False,
            "last_run": False,
            "scheduled_workouts": False,
            "sleep": False,
            "hrv": False,
            "resting_heart_rate": False,
            "body_battery": False,
            "training_readiness": False,
            "recovery_time": False,
            "training_status": False,
            "training_load": False,
            "load_focus": False,
            "vo2max": False,
        },
        "training": {
            "activity_count": 0,
            "running_sessions": 0,
            "sessions_by_sport": {},
            "total_training_minutes": None,
            "running_distance_km": None,
            "last_run_date": None,
            "days_since_last_run": None,
            "activities_truncated": False,
        },
        "recent_activities": [],
        "recovery": {
            "readiness_date": None,
            "training_readiness": None,
            "training_readiness_level": None,
            "recovery_hours": None,
            "body_battery": None,
            "body_battery_date": None,
        },
        "sleep": {"date": None, "duration_hours": None, "score": None, "score_qualifier": None},
        "hrv": {
            "date": None,
            "last_night_avg_ms": None,
            "weekly_avg_ms": None,
            "status": None,
            "baseline_balanced_low_ms": None,
            "baseline_balanced_upper_ms": None,
        },
        "heart_rate": {"date": None, "resting_hr": None, "resting_hr_7_day_avg": None},
        "fitness": {
            "training_status": None,
            "training_status_feedback": None,
            "fitness_trend": None,
            "acute_load": None,
            "chronic_load": None,
            "acute_chronic_ratio": None,
            "acwr_status": None,
            "vo2max_running": None,
            "vo2max_cycling": None,
            "load_focus": {"aerobic_low": None, "aerobic_high": None, "anaerobic": None, "feedback": None},
        },
        "scheduled_workouts": [],
        "warnings": [],
    }


def _append_warnings(result: dict[str, Any], provider_result: ProviderResult) -> None:
    result["warnings"].extend(provider_result.warnings)


def _populate_activities(result: dict[str, Any], provider_result: ProviderResult) -> None:
    """Populate aggregates and a bounded local activity summary."""
    _append_warnings(result, provider_result)
    result["availability"]["activities"] = not provider_result.failed
    result["training"]["activities_truncated"] = provider_result.truncated

    raw_items = provider_result.data if isinstance(provider_result.data, (tuple, list)) else ()
    activities = [item for item in raw_items if isinstance(item, dict)]
    result["training"]["activity_count"] = len(activities)

    sessions_by_sport: dict[str, int] = {}
    running_count = 0
    durations: list[float] = []
    running_distances: list[float] = []
    reduced: list[tuple[dict[str, Any], float | None]] = []
    for activity in activities:
        sport = _activity_sport(activity)
        if sport is not None:
            sessions_by_sport[sport] = sessions_by_sport.get(sport, 0) + 1
        is_running = sport in RUNNING_TYPE_KEYS
        if is_running:
            running_count += 1
        duration = _finite_number(activity.get("duration"))
        if duration is not None:
            durations.append(duration)
        distance = _finite_number(activity.get("distance"))
        if is_running and distance is not None:
            running_distances.append(distance)
        reduced.append(_reduced_activity(activity))

    result["training"]["sessions_by_sport"] = sessions_by_sport
    result["training"]["running_sessions"] = running_count
    if not activities:
        if not provider_result.failed:
            result["training"]["total_training_minutes"] = 0.0
            result["training"]["running_distance_km"] = 0.0
    else:
        result["training"]["total_training_minutes"] = round(sum(durations) / 60, 1) if durations else None
        if not running_count:
            result["training"]["running_distance_km"] = 0.0
        elif running_distances:
            result["training"]["running_distance_km"] = round(sum(running_distances) / 1000, 2)
        else:
            result["training"]["running_distance_km"] = None

    reduced.sort(key=lambda value: value[1] if value[1] is not None else float("-inf"), reverse=True)
    result["recent_activities"] = [item for item, _ in reduced[:20]]


def _populate_last_run(result: dict[str, Any], provider_result: ProviderResult, today: date) -> None:
    _append_warnings(result, provider_result)
    activity = provider_result.data
    if not isinstance(activity, dict) or _activity_sport(activity) not in RUNNING_TYPE_KEYS:
        return
    activity_day = _iso_day(activity.get("startTimeLocal"))
    if activity_day is None:
        return
    parsed_day = date.fromisoformat(activity_day)
    if parsed_day > today:
        return
    result["availability"]["last_run"] = True
    result["training"]["last_run_date"] = activity_day
    result["training"]["days_since_last_run"] = (today - parsed_day).days


def _scheduled_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    reduced: dict[str, Any] = {}
    fields = (
        ("scheduleDate", "date"),
        ("scheduledWorkoutId", "scheduled_workout_id"),
        ("workoutId", "workout_id"),
        ("workoutUuid", "workout_uuid"),
        ("workoutName", "name"),
        ("workoutType", "sport"),
    )
    for raw_key, public_key in fields:
        if item.get(raw_key) is not None:
            reduced[public_key] = item[raw_key]
    completed = item.get("associatedActivityId") is not None
    reduced["completed"] = completed
    if completed:
        reduced["activity_id"] = item["associatedActivityId"]
    return reduced


def _populate_scheduled_workouts(result: dict[str, Any], provider_result: ProviderResult) -> None:
    _append_warnings(result, provider_result)
    result["availability"]["scheduled_workouts"] = not provider_result.failed
    raw_items = provider_result.data if isinstance(provider_result.data, (tuple, list)) else ()
    invalid_item = False
    scheduled: list[dict[str, Any]] = []
    for item in raw_items:
        reduced = _scheduled_item(item)
        if reduced is None:
            invalid_item = True
        else:
            scheduled.append(reduced)
    result["scheduled_workouts"] = scheduled
    if invalid_item:
        result["warnings"].append(
            {
                "provider": "scheduled_workouts",
                "code": "invalid_provider_response",
                "message": "Scheduled workout response had an unexpected item.",
            }
        )


def _read_optional_sections(client: Any, day: str) -> None:
    """Keep the future optional-section reads bounded while their schema lands."""
    get_daily_stats(client, day)
    get_sleep(client, day)
    get_hrv(client, day)
    get_training_readiness(client, day)
    get_training_status(client, day)


def get_training_context_service(client: Any, days: int = 14, today: date | None = None) -> dict[str, Any]:
    """Return a compact training-context envelope with stable null sections."""
    effective_today = today or date.today()
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90:
        result = _base_result(effective_today, None)
        result["status"] = "error"
        result["error"] = {"code": "invalid_days", "message": "days must be an integer from 1 through 90"}
        return result

    result = _base_result(effective_today, days)
    start = result["period"]["start_date"]
    end = result["period"]["end_date"]
    schedule_end = result["schedule_period"]["end_date"]
    period_result = get_period_activities(client, start, end, days)
    schedule_result = get_scheduled_workouts(client, end, schedule_end)
    last_run_result = get_last_run(client)
    _populate_activities(result, period_result)
    _populate_scheduled_workouts(result, schedule_result)
    _populate_last_run(result, last_run_result, effective_today)
    _read_optional_sections(client, end)
    return result
