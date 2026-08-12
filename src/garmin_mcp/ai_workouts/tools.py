"""MCP registration for the AI-friendly workout creation tool."""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import StrictInt, StrictStr

from .service import create_workout_service, update_workout_service


garmin_client: Any = None


def configure(client: Any) -> None:
    """Configure the Garmin client used by this package's MCP tool."""
    global garmin_client
    garmin_client = client


def register_tools(app: Any) -> Any:
    """Register the AI-friendly workout creation and update tools."""

    @app.tool()
    async def create_workout(
        name: str,
        sport: str,
        steps: list[dict],
        schedule_date: Optional[str] = None,
    ) -> str:
        """Create and optionally schedule a friendly Garmin workout.

        Supported sports are running, cycling, walking, and strength. Use
        actions warmup, cooldown, work, run, interval, recovery, or rest;
        repeat groups use ``repeat`` and nested ``steps``. One repeat level is
        supported, with 1-50 iterations; nested repeat groups are not
        supported. Each action has one end condition: duration, distance, reps
        (strength only), or lap_button.

        Use these exact friendly units: duration ``"15m"`` (minutes),
        ``"90s"``, or ``"1.5h"``; distance ``"800m"`` (metres) or
        ``"5km"``; running pace ``"4:20-4:30/km"``; custom heart rate
        ``"150-165bpm"``; cycling power ``"220-250W"``; and zones such as
        ``"Z3"``. Targets can be pace (running), heart_rate_zone or
        heart_rate, power_zone (cycling), or power (cycling). Omit
        ``schedule_date`` to create without scheduling, or use ``YYYY-MM-DD``.
        A successful upload that cannot be scheduled returns ``partial_success``
        with the created workout ID and scheduling error.
        """
        result = create_workout_service(
            garmin_client, name, sport, steps, schedule_date
        )
        return json.dumps(result, indent=2)

    @app.tool()
    async def update_workout(
        workout_id: StrictInt | StrictStr,
        name: Optional[StrictStr] = None,
        sport: Optional[StrictStr] = None,
        steps: Optional[list[dict]] = None,
    ) -> str:
        """Patch an existing regular Garmin workout in place.

        ``workout_id`` is the template workout ID returned by
        ``get_workouts``, ``get_workout_by_id``, or
        ``get_scheduled_workouts``; it is not scheduled_workout_id (the
        identifier used by ``unschedule_workout``). Supply ``name`` to rename,
        or supply
        friendly replacement ``steps`` (and optionally ``sport``) to replace
        the step structure. Supported sports are running, cycling, walking,
        and strength (Garmin's ``strength_training`` alias). Sport may be
        supplied only with steps. Use the same friendly grammar and units as
        ``create_workout``: actions warmup, cooldown, work, run, interval,
        recovery, rest, and repeat groups with one repeat level and 1-50
        iterations; durations such as ``"15m"``, distances such as ``"800m"``,
        pace such as ``"4:20-4:30/km"``, heart-rate targets such as
        ``"150-165bpm"`` or ``"Z3"``, and cycling power such as ``"220-250W"``.
        Each action has one end condition: duration, distance, reps (strength
        only), or lap_button. Targets can be pace (running), heart_rate_zone
        or heart_rate, power_zone (cycling), or power (cycling).

        The server fetches the complete workout and sends a whole-document
        in-place PUT using the same ID. Existing calendar schedules are
        preserved (schedules preserved); this tool never uploads a replacement,
        never mutates the calendar, and never schedules, unschedules, or
        deletes. If the update result is
        ambiguous or partial, read the workout before retrying. UUID-based
        Garmin Coach/adaptive-plan workouts and unsupported sports are not
        supported.
        """
        result = update_workout_service(
            garmin_client,
            workout_id,
            name=name,
            sport=sport,
            steps=steps,
        )
        return json.dumps(result, indent=2)

    return app
