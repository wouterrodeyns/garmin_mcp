"""MCP registration for the compact AI training-context tool."""

from __future__ import annotations

import json
from typing import Any

from .service import get_training_context_service


garmin_client: Any = None


def configure(client: Any) -> None:
    """Configure the Garmin client used by this package's MCP tool."""
    global garmin_client
    garmin_client = client


def register_tools(app: Any) -> Any:
    """Register the compact, read-only training-context tool."""

    @app.tool()
    async def get_training_context(days: int = 14) -> str:
        """Return a compact read-only Garmin coaching snapshot.

        days applies only to the retrospective activity lookback (1 through 90).
        Latest run is searched independently across up to 1,000 activity records
        and may be older than the requested period.
        Scheduled workouts always cover today through the following six days.
        Daily recovery and fitness metrics query today. Sleep, HRV, and readiness
        query today and then yesterday only for a legitimately empty response.
        Garmin metric availability varies by device and account; optional
        metrics may be unavailable or null. A null optional metric with no warning
        means it was not available in this snapshot; it does not prove the account
        or device does not support it. Provider failures are reported in structured
        warnings.
        """
        result = get_training_context_service(garmin_client, days)
        return json.dumps(result, indent=2)

    return app
