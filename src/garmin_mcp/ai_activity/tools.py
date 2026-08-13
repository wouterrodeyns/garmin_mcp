"""MCP registration for the factual AI activity-analysis tool."""

from __future__ import annotations

import json
from typing import Any

from pydantic import StrictInt, StrictStr

from .service import analyze_activity_service
from .timeseries_service import (
    _unexpected_error_envelope,
    get_activity_timeseries_service,
)


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

    @app.tool()
    async def get_activity_timeseries(
        activity_id: StrictInt | StrictStr,
        start_seconds: StrictInt = 0,
        duration_seconds: StrictInt = 600,
        resolution_seconds: StrictInt = 1,
    ) -> str:
        """Return short-window factual cadence, power, pace, speed, altitude, grade, and heart-rate evidence.

        This tool is read-only and makes one ORIGINAL FIT download after valid input.
        Use analyze_activity first for the normal completed-session overview; use this
        only for a concrete short interval question. Results are sparse, paged non-empty bins,
        can have gaps, never imply one-Hz sampling, and never include GPS or raw FIT data.
        Availability describes this returned window, not account or device capability.
        """
        try:
            result = get_activity_timeseries_service(
                garmin_client,
                activity_id,
                start_seconds,
                duration_seconds,
                resolution_seconds,
            )
        except Exception:
            result = _unexpected_error_envelope()
        return json.dumps(result, indent=2)

    return app
