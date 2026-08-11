"""MCP registration for the factual AI activity-analysis tool."""

from __future__ import annotations

import json
from typing import Any

from pydantic import StrictInt, StrictStr

from .service import analyze_activity_service


garmin_client: Any = None


def configure(client: Any) -> None:
    """Configure the Garmin client used by this package's MCP tool."""
    global garmin_client
    garmin_client = client


def register_tools(app: Any) -> Any:
    """Register the bounded, read-only AI activity-analysis tool."""

    @app.tool()
    async def analyze_activity(activity_id: StrictInt | StrictStr) -> str:
        """Return factual, bounded, sport-aware evidence for one completed Garmin activity.

        This read-only tool reports mechanical facts, not coaching advice: AI
        interprets the evidence. Optional Garmin detail can be null or
        unavailable and can vary by activity, device, account, or sync.
        Returned zone durations are authoritative; never estimate time in zone
        from split-average heart rate. Split averages do not establish
        heart-rate drift or decoupling, so do not calculate or claim those
        metrics.
        """
        result = analyze_activity_service(garmin_client, activity_id)
        return json.dumps(result, indent=2)

    return app
