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

from .sleep import InvalidSleepResponse, SleepNightFacts, normalize_sleep_night

AVAILABILITY_KEYS = (
    "activities",
    "last_run",
    "scheduled_workouts",
    "sleep",
    "hrv",
    "resting_heart_rate",
    "body_battery",
    "training_readiness",
    "recovery_time",
    "training_status",
    "training_load",
    "load_focus",
    "vo2max",
)

_PROVIDER_MESSAGES = {
    "activities": ("Activities are unavailable.", "Activities returned an invalid response."),
    "last_run": ("Latest run is unavailable.", "Latest run returned an invalid response."),
    "scheduled_workouts": (
        "Scheduled workouts are unavailable.",
        "Scheduled workouts returned an invalid response.",
    ),
    "daily_stats": (
        "Daily statistics are unavailable.",
        "Daily statistics returned an invalid response.",
    ),
    "sleep": ("Sleep is unavailable.", "Sleep returned an invalid response."),
    "hrv": ("HRV is unavailable.", "HRV returned an invalid response."),
    "training_readiness": (
        "Training readiness is unavailable.",
        "Training readiness returned an invalid response.",
    ),
    "training_status": (
        "Training status is unavailable.",
        "Training status returned an invalid response.",
    ),
}


def _warning(provider: str, code: str) -> dict[str, str]:
    message_index = 1 if code == "invalid_provider_response" else 0
    return {
        "provider": provider,
        "code": code,
        "message": _PROVIDER_MESSAGES[provider][message_index],
    }


def _append_failure_warning(result: dict[str, Any], provider: str, code: str) -> None:
    warning = _warning(provider, code)
    if warning not in result["warnings"]:
        result["warnings"].append(warning)


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


def _normalized_number(value: Any) -> int | float | None:
    numeric = _finite_number(value)
    if numeric is None:
        return None
    return int(numeric) if numeric.is_integer() else numeric


def _normalized_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


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
        item["average_speed_kph"] = round(speed * 3.6, 1)
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
        "availability": dict.fromkeys(AVAILABILITY_KEYS, False),
        "training": {
            "activity_count": None,
            "running_sessions": None,
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
    result["training"]["activities_truncated"] = provider_result.truncated

    raw_items = provider_result.data if isinstance(provider_result.data, (tuple, list)) else ()
    activities = [item for item in raw_items if isinstance(item, dict)]
    result["availability"]["activities"] = not provider_result.failed or bool(activities)
    if not result["availability"]["activities"]:
        return
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


def _scheduled_item(item: Any) -> tuple[dict[str, Any], bool] | None:
    if not isinstance(item, dict):
        return None
    reduced: dict[str, Any] = {}
    invalid = False
    fields = (
        ("scheduleDate", "date", str),
        ("scheduledWorkoutId", "scheduled_workout_id", int),
        ("workoutId", "workout_id", int),
        ("workoutUuid", "workout_uuid", str),
        ("workoutName", "name", str),
        ("workoutType", "sport", str),
    )
    for raw_key, public_key, expected_type in fields:
        value = item.get(raw_key)
        if value is None:
            continue
        if isinstance(value, expected_type) and not isinstance(value, bool):
            reduced[public_key] = value
        else:
            invalid = True
    activity_id = item.get("associatedActivityId")
    completed = isinstance(activity_id, int) and not isinstance(activity_id, bool)
    if activity_id is not None and not completed:
        invalid = True
    if not reduced and not completed:
        return None
    reduced["completed"] = completed
    if completed:
        reduced["activity_id"] = activity_id
    return reduced, invalid


def _populate_scheduled_workouts(
    result: dict[str, Any], provider_result: ProviderResult
) -> bool:
    _append_warnings(result, provider_result)
    raw_items = provider_result.data if isinstance(provider_result.data, (tuple, list)) else ()
    invalid_item = False
    valid_item = False
    scheduled: list[dict[str, Any]] = []
    for item in raw_items:
        scheduled_item = _scheduled_item(item)
        if scheduled_item is None:
            invalid_item = True
        else:
            reduced, item_invalid = scheduled_item
            invalid_item = invalid_item or item_invalid
            valid_item = valid_item or not item_invalid
            scheduled.append(reduced)
    all_items_malformed = bool(raw_items) and not valid_item
    result["availability"]["scheduled_workouts"] = (
        not provider_result.failed and not all_items_malformed
    )
    result["scheduled_workouts"] = scheduled
    if invalid_item:
        result["warnings"].append(
            {
                "provider": "scheduled_workouts",
                "code": "invalid_provider_response",
                "message": "Scheduled workout response had an unexpected item.",
            }
        )
    return invalid_item


def _populate_daily_stats(result: dict[str, Any], raw: Any) -> None:
    if not isinstance(raw, dict):
        return
    source_date = _iso_day(raw.get("calendarDate"))
    resting_hr = _normalized_number(raw.get("restingHeartRate"))
    resting_average = _normalized_number(raw.get("lastSevenDaysAvgRestingHeartRate"))
    body_battery = _normalized_number(raw.get("bodyBatteryMostRecentValue"))
    if resting_hr is not None or resting_average is not None:
        result["availability"]["resting_heart_rate"] = True
        result["heart_rate"].update(
            date=source_date,
            resting_hr=resting_hr,
            resting_hr_7_day_avg=resting_average,
        )
    if body_battery is not None:
        result["availability"]["body_battery"] = True
        result["recovery"]["body_battery"] = body_battery
        result["recovery"]["body_battery_date"] = source_date


def _sleep_metrics(raw: Any, requested_date: str) -> tuple[dict[str, Any] | None, bool]:
    """Return normalized sleep values and whether a response is retryably empty."""
    if raw is None:
        return None, True
    if type(raw) is list:
        return None, len(raw) == 0
    if type(raw) is not dict:
        return None, False
    if len(raw) == 0:
        return None, True
    if "dailySleepDTO" not in raw:
        return None, False
    dto = raw.get("dailySleepDTO")
    if dto is None:
        return None, True
    if type(dto) is not dict:
        return None, False
    if len(dto) == 0:
        return None, True
    try:
        facts: SleepNightFacts | None = normalize_sleep_night(raw, requested_date)
    except InvalidSleepResponse:
        return None, False
    if facts is None:
        return None, True
    if facts.sleep_seconds is None and facts.score is None and facts.score_qualifier is None:
        return None, True
    return {
        # Preserve the legacy snapshot's Garmin-source provenance. The shared
        # normalizer uses the requested date to validate the response and to
        # key trend entries, but a missing Garmin calendarDate remains missing
        # in the compact training-context snapshot.
        "date": _iso_day(dto.get("calendarDate")),
        "duration_hours": (
            round(facts.sleep_seconds / 3600, 1)
            if facts.sleep_seconds is not None else None
        ),
        "score": facts.score,
        "score_qualifier": facts.score_qualifier,
    }, False


def _hrv_metrics(raw: Any) -> tuple[dict[str, Any] | None, bool]:
    if raw is None or raw == [] or raw == {}:
        return None, True
    if not isinstance(raw, dict) or "hrvSummary" not in raw:
        return None, False
    summary = raw.get("hrvSummary")
    if summary is None or summary == {}:
        return None, True
    if not isinstance(summary, dict):
        return None, False
    baseline = summary.get("baseline")
    malformed = baseline is not None and not isinstance(baseline, dict)
    baseline = baseline if isinstance(baseline, dict) else {}
    raw_last_night = summary.get("lastNightAvg")
    raw_weekly = summary.get("weeklyAvg")
    raw_status = summary.get("status")
    raw_low = baseline.get("balancedLow")
    raw_upper = baseline.get("balancedUpper")
    metrics = {
        "date": _iso_day(summary.get("calendarDate")),
        "last_night_avg_ms": _normalized_number(raw_last_night),
        "weekly_avg_ms": _normalized_number(raw_weekly),
        "status": _normalized_text(raw_status),
        "baseline_balanced_low_ms": _normalized_number(raw_low),
        "baseline_balanced_upper_ms": _normalized_number(raw_upper),
    }
    for raw_value, normalized in (
        (raw_last_night, metrics["last_night_avg_ms"]),
        (raw_weekly, metrics["weekly_avg_ms"]),
        (raw_low, metrics["baseline_balanced_low_ms"]),
        (raw_upper, metrics["baseline_balanced_upper_ms"]),
    ):
        if raw_value is not None and normalized is None:
            malformed = True
    if raw_status not in (None, "") and metrics["status"] is None:
        malformed = True
    if not any(value is not None for key, value in metrics.items() if key != "date"):
        return None, not malformed
    return metrics, False


def _readiness_metrics(raw: Any) -> tuple[dict[str, Any] | None, bool]:
    if raw is None or raw == [] or raw == {}:
        return None, True
    if not isinstance(raw, dict):
        return None, False
    recognized_keys = {
        "readinessScore", "score", "trainingReadinessLevel", "readinessLevel",
        "level", "trainingReadinessLevelKey", "recoveryTime",
    }
    recognized_shape = any(key in raw for key in recognized_keys) or set(raw) <= {"calendarDate"}
    malformed = False
    score = None
    for key in ("readinessScore", "score", "trainingReadinessLevel"):
        raw_score = raw.get(key)
        score = _normalized_number(raw_score)
        if score is not None:
            break
        if raw_score is not None:
            malformed = True
    level = None
    for key in ("readinessLevel", "level", "trainingReadinessLevelKey"):
        raw_level = raw.get(key)
        level = _normalized_text(raw_level)
        if level is not None:
            break
        if raw_level not in (None, ""):
            malformed = True
    raw_recovery = raw.get("recoveryTime")
    recovery_minutes = _finite_number(raw_recovery)
    if raw_recovery is not None and recovery_minutes is None:
        malformed = True
    if score is None and level is None and recovery_minutes is None:
        return None, recognized_shape and not malformed
    return {
        "date": _iso_day(raw.get("calendarDate")),
        "score": score,
        "level": level,
        "recovery_hours": round(recovery_minutes / 60, 1) if recovery_minutes is not None else None,
    }, False


def _read_with_previous_day_fallback(
    getter: Any, client: Any, today: date, normalizer: Any
) -> tuple[dict[str, Any] | None, str, bool]:
    today_text = today.isoformat()
    raw = getter(client, today_text)
    metrics, retry = normalizer(raw)
    source_date = today_text
    if retry:
        source_date = today.fromordinal(today.toordinal() - 1).isoformat()
        metrics, retry = normalizer(getter(client, source_date))
    return metrics, source_date, metrics is None and not retry


def _populate_sleep(result: dict[str, Any], client: Any, today: date) -> bool:
    today_text = today.isoformat()
    metrics, retry = _sleep_metrics(get_sleep(client, today_text), today_text)
    if retry:
        previous_text = today.fromordinal(today.toordinal() - 1).isoformat()
        metrics, retry = _sleep_metrics(get_sleep(client, previous_text), previous_text)
    if metrics is None:
        return not retry
    result["sleep"].update(metrics)
    result["availability"]["sleep"] = True
    return False


def _populate_hrv(result: dict[str, Any], client: Any, today: date) -> bool:
    metrics, source_date, invalid = _read_with_previous_day_fallback(
        get_hrv, client, today, _hrv_metrics
    )
    if metrics is None:
        return invalid
    metrics["date"] = metrics["date"] or source_date
    result["hrv"].update(metrics)
    result["availability"]["hrv"] = True
    return False


def _populate_readiness(result: dict[str, Any], client: Any, today: date) -> bool:
    metrics, source_date, invalid = _read_with_previous_day_fallback(
        get_training_readiness, client, today, _readiness_metrics
    )
    if metrics is None:
        return invalid
    result["recovery"]["readiness_date"] = metrics["date"] or source_date
    result["recovery"]["training_readiness"] = metrics["score"]
    result["recovery"]["training_readiness_level"] = metrics["level"]
    result["recovery"]["recovery_hours"] = metrics["recovery_hours"]
    result["availability"]["training_readiness"] = (
        metrics["score"] is not None or metrics["level"] is not None
    )
    result["availability"]["recovery_time"] = metrics["recovery_hours"] is not None
    return False


def _status_device_usable(candidate: dict[str, Any]) -> bool:
    if any(
        _normalized_text(candidate.get(key)) is not None
        for key in ("trainingStatus", "trainingStatusFeedbackPhrase", "fitnessTrend")
    ):
        return True
    load = candidate.get("acuteTrainingLoadDTO")
    if not isinstance(load, dict):
        return False
    return any(
        _normalized_number(load.get(key)) is not None
        for key in (
            "dailyTrainingLoadAcute", "dailyTrainingLoadChronic",
            "dailyAcuteChronicWorkloadRatio",
        )
    ) or _normalized_text(load.get("acwrStatus")) is not None


def _load_focus_device_usable(candidate: dict[str, Any]) -> bool:
    return any(
        _normalized_number(candidate.get(key)) is not None
        for key in ("monthlyLoadAerobicLow", "monthlyLoadAerobicHigh", "monthlyLoadAnaerobic")
    ) or _normalized_text(candidate.get("trainingBalanceFeedbackPhrase")) is not None


def _primary_device(device_map: Any, preferred_id: Any, usable: Any) -> dict[str, Any]:
    if not isinstance(device_map, dict):
        return {}
    if isinstance(preferred_id, str):
        preferred = device_map.get(preferred_id)
        if isinstance(preferred, dict) and usable(preferred):
            return preferred
    first: dict[str, Any] = {}
    for candidate in device_map.values():
        if not isinstance(candidate, dict) or not usable(candidate):
            continue
        if not first:
            first = candidate
        if candidate.get("primaryTrainingDevice") is True:
            return candidate
    return first


def _populate_training_status(result: dict[str, Any], raw: Any) -> None:
    if not isinstance(raw, dict):
        return
    recent = raw.get("mostRecentTrainingStatus")
    latest = recent.get("latestTrainingStatusData") if isinstance(recent, dict) else None
    primary_device_id = raw.get("primaryTrainingDevice")
    status = _primary_device(latest, primary_device_id, _status_device_usable)
    load = status.get("acuteTrainingLoadDTO")
    load = load if isinstance(load, dict) else {}

    status_values = {
        "training_status": _normalized_text(status.get("trainingStatus")),
        "training_status_feedback": _normalized_text(status.get("trainingStatusFeedbackPhrase")),
        "fitness_trend": _normalized_text(status.get("fitnessTrend")),
    }
    load_values = {
        "acute_load": _normalized_number(load.get("dailyTrainingLoadAcute")),
        "chronic_load": _normalized_number(load.get("dailyTrainingLoadChronic")),
        "acute_chronic_ratio": _normalized_number(load.get("dailyAcuteChronicWorkloadRatio")),
        "acwr_status": _normalized_text(load.get("acwrStatus")),
    }
    result["fitness"].update(status_values)
    result["fitness"].update(load_values)
    result["availability"]["training_status"] = any(value is not None for value in status_values.values())
    result["availability"]["training_load"] = any(value is not None for value in load_values.values())

    balance = raw.get("mostRecentTrainingLoadBalance")
    load_map = balance.get("metricsTrainingLoadBalanceDTOMap") if isinstance(balance, dict) else None
    focus = _primary_device(load_map, primary_device_id, _load_focus_device_usable)
    focus_values = {
        "aerobic_low": _normalized_number(focus.get("monthlyLoadAerobicLow")),
        "aerobic_high": _normalized_number(focus.get("monthlyLoadAerobicHigh")),
        "anaerobic": _normalized_number(focus.get("monthlyLoadAnaerobic")),
        "feedback": _normalized_text(focus.get("trainingBalanceFeedbackPhrase")),
    }
    result["fitness"]["load_focus"].update(focus_values)
    result["availability"]["load_focus"] = any(value is not None for value in focus_values.values())

    vo2 = raw.get("mostRecentVO2Max")
    generic = vo2.get("generic") if isinstance(vo2, dict) else None
    cycling = vo2.get("cycling") if isinstance(vo2, dict) else None
    running_vo2 = _normalized_number(generic.get("vo2MaxValue")) if isinstance(generic, dict) else None
    cycling_vo2 = _normalized_number(cycling.get("vo2MaxValue")) if isinstance(cycling, dict) else None
    result["fitness"]["vo2max_running"] = running_vo2
    result["fitness"]["vo2max_cycling"] = cycling_vo2
    result["availability"]["vo2max"] = running_vo2 is not None or cycling_vo2 is not None


def _failed_provider_result(provider: str) -> ProviderResult:
    return ProviderResult(data=(), failed=True, warnings=(_warning(provider, "provider_unavailable"),))


def _read_core(provider: str, getter: Any, *args: Any) -> ProviderResult:
    try:
        provider_result = getter(*args)
    except Exception:
        return _failed_provider_result(provider)
    if not isinstance(provider_result, ProviderResult):
        return ProviderResult(
            data=(), failed=True,
            warnings=(_warning(provider, "invalid_provider_response"),),
        )
    if provider_result.failed and not provider_result.warnings:
        return ProviderResult(
            data=provider_result.data,
            failed=True,
            truncated=provider_result.truncated,
            warnings=(_warning(provider, "provider_unavailable"),),
        )
    return provider_result


def _read_optional(
    result: dict[str, Any], provider: str, operation: Any
) -> tuple[Any, bool]:
    try:
        return operation(), False
    except Exception:
        _append_failure_warning(result, provider, "provider_unavailable")
        return None, True


def _daily_stats_shape_valid(raw: Any) -> bool:
    if raw is None or raw == {}:
        return True
    if not isinstance(raw, dict):
        return False
    metric_keys = (
        "restingHeartRate", "lastSevenDaysAvgRestingHeartRate",
        "bodyBatteryMostRecentValue",
    )
    if not ({"calendarDate", *metric_keys}.intersection(raw)):
        return False
    if raw.get("calendarDate") is not None and _iso_day(raw.get("calendarDate")) is None:
        return False
    return all(
        raw.get(key) is None or _finite_number(raw.get(key)) is not None
        for key in metric_keys
    )


def _training_status_shape_valid(raw: Any) -> bool:
    if raw is None or raw == {}:
        return True
    if not isinstance(raw, dict):
        return False
    recognized = {
        "primaryTrainingDevice", "mostRecentTrainingStatus",
        "mostRecentTrainingLoadBalance", "mostRecentVO2Max",
    }
    if not recognized.intersection(raw):
        return False
    for key in ("mostRecentTrainingStatus", "mostRecentTrainingLoadBalance", "mostRecentVO2Max"):
        value = raw.get(key)
        if value is not None and not isinstance(value, dict):
            return False
    recent = raw.get("mostRecentTrainingStatus")
    if isinstance(recent, dict):
        latest = recent.get("latestTrainingStatusData")
        if latest is not None and not isinstance(latest, dict):
            return False
    balance = raw.get("mostRecentTrainingLoadBalance")
    if isinstance(balance, dict):
        load_map = balance.get("metricsTrainingLoadBalanceDTOMap")
        if load_map is not None and not isinstance(load_map, dict):
            return False
    vo2 = raw.get("mostRecentVO2Max")
    if isinstance(vo2, dict):
        for key in ("generic", "cycling"):
            value = vo2.get(key)
            if value is not None and not isinstance(value, dict):
                return False
    return True


def get_training_context_service(client: Any, days: int = 14, today: date | None = None) -> dict[str, Any]:
    """Return a compact training-context envelope with stable null sections."""
    effective_today = today or date.today()
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90:
        result = _base_result(effective_today, None)
        result["status"] = "error"
        result["error"] = {"code": "invalid_days", "message": "days must be an integer from 1 through 90"}
        return result

    result = _base_result(effective_today, days)
    if client is None:
        result["status"] = "error"
        result["error"] = {
            "code": "client_unavailable",
            "message": "Garmin client is unavailable. Authenticate with garmin-mcp-auth and retry.",
        }
        return result

    start = result["period"]["start_date"]
    end = result["period"]["end_date"]
    schedule_end = result["schedule_period"]["end_date"]
    period_result = _read_core(
        "activities", get_period_activities, client, start, end, days
    )
    schedule_result = _read_core(
        "scheduled_workouts", get_scheduled_workouts, client, end, schedule_end
    )
    _populate_activities(result, period_result)
    schedule_invalid = _populate_scheduled_workouts(result, schedule_result)
    isolated_failure = period_result.failed or schedule_result.failed or schedule_invalid

    if not result["availability"]["activities"] and not result["availability"]["scheduled_workouts"]:
        if period_result.failed and not period_result.warnings:
            _append_failure_warning(result, "activities", "provider_unavailable")
        if schedule_result.failed and not schedule_result.warnings:
            _append_failure_warning(result, "scheduled_workouts", "provider_unavailable")
        result["status"] = "error"
        result["error"] = {
            "code": "context_unavailable",
            "message": (
                "Core Garmin context is unavailable. Re-run garmin-mcp-auth if your "
                "session expired; otherwise retry later."
            ),
        }
        return result

    last_run_result = _read_core("last_run", get_last_run, client)
    _populate_last_run(result, last_run_result, effective_today)
    isolated_failure = isolated_failure or last_run_result.failed

    daily_stats, failed = _read_optional(
        result, "daily_stats", lambda: get_daily_stats(client, end)
    )
    isolated_failure = isolated_failure or failed
    if not failed:
        if _daily_stats_shape_valid(daily_stats):
            _populate_daily_stats(result, daily_stats)
        else:
            _append_failure_warning(result, "daily_stats", "invalid_provider_response")
            isolated_failure = True

    for provider, populate in (
        ("sleep", _populate_sleep),
        ("hrv", _populate_hrv),
        ("training_readiness", _populate_readiness),
    ):
        invalid, failed = _read_optional(
            result, provider, lambda _populate=populate: _populate(result, client, effective_today)
        )
        isolated_failure = isolated_failure or failed
        if not failed and invalid:
            _append_failure_warning(result, provider, "invalid_provider_response")
            isolated_failure = True

    training_status, failed = _read_optional(
        result, "training_status", lambda: get_training_status(client, end)
    )
    isolated_failure = isolated_failure or failed
    if not failed:
        if _training_status_shape_valid(training_status):
            _populate_training_status(result, training_status)
        else:
            _append_failure_warning(result, "training_status", "invalid_provider_response")
            isolated_failure = True

    if isolated_failure:
        result["status"] = "partial_success"
    return result
