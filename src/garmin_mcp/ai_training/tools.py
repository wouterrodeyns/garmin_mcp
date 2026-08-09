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

        days is an inclusive retrospective lookback from 1 through 90.
        Scheduled workouts always cover today through the following six days.
        Optional metrics may be null; isolated failures return warnings.
        """
        result = get_training_context_service(garmin_client, days)
        return json.dumps(result, indent=2)

    return app
