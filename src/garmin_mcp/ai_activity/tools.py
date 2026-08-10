"""MCP registration for the factual AI activity-analysis tool."""

from __future__ import annotations

import json
from typing import Any

from .service import analyze_activity_service


garmin_client: Any = None


def configure(client: Any) -> None:
    """Configure the Garmin client used by this package's MCP tool."""
    global garmin_client
    garmin_client = client


def register_tools(app: Any) -> Any:
    """Register the bounded, read-only AI activity-analysis tool."""

    @app.tool()
    async def analyze_activity(activity_id: int | str) -> str:
        """Return factual, bounded, sport-aware evidence for one completed Garmin activity.

        This read-only tool reports mechanical facts, not coaching advice: AI
        interprets the evidence. Optional Garmin detail can be null or
        unavailable and can vary by activity, device, account, or sync.
        """
        result = analyze_activity_service(garmin_client, activity_id)
        return json.dumps(result, indent=2)

    return app
