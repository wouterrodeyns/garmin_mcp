"""Orchestration for creating and optionally scheduling friendly workouts."""

from __future__ import annotations

from typing import Any

from garmin_mcp.workouts import prepare_workout_for_upload, schedule_workout_for_date

from .compiler import compile_workout
from .schema import validate_workout


def _error(name: str, message: str) -> dict[str, Any]:
    return {"status": "error", "name": name, "message": message}


def create_workout_service(
    client: Any,
    name: str,
    sport: str,
    steps: list[dict[str, Any]],
    schedule_date: str | None = None,
) -> dict[str, Any]:
    """Validate, upload, and optionally schedule one friendly workout.

    Uploading and scheduling are deliberately non-transactional: after Garmin
    returns a workout ID, any scheduling problem is reported as a partial
    success so callers can retain and use the uploaded workout.
    """
    try:
        definition = validate_workout(name, sport, steps, schedule_date)
        compiled = compile_workout(definition)
        prepared = prepare_workout_for_upload(compiled)
        uploaded = client.upload_workout(prepared)
    except Exception as exc:
        return _error(name, str(exc))

    if not isinstance(uploaded, dict) or uploaded.get("workoutId") is None:
        return _error(name, "Upload response did not include workout_id")

    workout_id = uploaded["workoutId"]
    result: dict[str, Any] = {
        "status": "success",
        "workout_id": workout_id,
        "name": uploaded.get("workoutName") or name,
    }
    if definition.schedule_date is None:
        return result

    try:
        scheduling = schedule_workout_for_date(
            workout_id, definition.schedule_date, client=client
        )
    except Exception as exc:
        result.update(
            {
                "status": "partial_success",
                "scheduled_date": definition.schedule_date,
                "scheduling_error": str(exc),
            }
        )
        return result

    if not isinstance(scheduling, dict) or scheduling.get("status") != "success":
        scheduling_error = (
            scheduling.get("message")
            if isinstance(scheduling, dict)
            else None
        ) or "Scheduling did not return a success status"
        result.update(
            {
                "status": "partial_success",
                "scheduled_date": definition.schedule_date,
                "scheduling_error": scheduling_error,
            }
        )
        return result

    result["scheduled_date"] = definition.schedule_date
    if scheduling.get("idempotent") is True:
        result["idempotent"] = True
    return result
