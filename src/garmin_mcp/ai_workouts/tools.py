"""MCP registration for the AI-friendly workout creation tool."""

from __future__ import annotations

import json
from typing import Any, Optional

from garmin_mcp import workouts

from .service import create_workout_service


garmin_client: Any = None


def configure(client: Any) -> None:
    """Configure the Garmin client used by this package's MCP tool."""
    global garmin_client
    garmin_client = client
    workouts.configure(client)


def register_tools(app: Any) -> Any:
    """Register the AI-friendly workout creation tool."""

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
        repeat groups use ``repeat`` and nested ``steps``. Each action has one
        end condition: duration, distance, reps, or lap_button. Targets can be
        pace (running), heart_rate_zone, heart_rate, power_zone (cycling), or
        power (cycling). A successful upload that cannot be scheduled returns
        ``partial_success`` with the created workout ID and scheduling error.
        """
        result = create_workout_service(
            garmin_client, name, sport, steps, schedule_date
        )
        return json.dumps(result, indent=2)

    return app
