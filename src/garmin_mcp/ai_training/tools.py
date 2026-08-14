"""MCP registration for the compact AI training-context tool."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import StrictStr

from .heart_rate import get_wellness_heart_rate_service
from .service import get_training_context_service


garmin_client: Any = None


def configure(client: Any) -> None:
    """Configure the Garmin client used by this package's MCP tool."""
    global garmin_client
    garmin_client = client


def register_tools(app: Any) -> Any:
    """Register compact, read-only AI training tools."""

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

    @app.tool()
    async def get_wellness_heart_rate(
        start_date: StrictStr,
        end_date: StrictStr | None = None,
        resolution: Literal["daily", "raw", "5m", "15m", "30m", "60m"] = "raw",
        start_time: StrictStr | None = None,
        end_time: StrictStr | None = None,
    ) -> str:
        """Return bounded read-only all-day wellness heart-rate evidence.

        This evidence is fetched explicitly when detailed evidence is needed. Requests
        cover at most seven dates. Raw mode is limited to one date and refuses
        results above 1,000 points rather than truncating them.
        Incomplete current-day local time uses Garmin's provisional start-bound
        offset only when it matches the MCP host's current local UTC offset;
        spring/fall transitions or a remote-host mismatch fail closed. This host
        check is conservative, not Garmin-authoritative. Never borrows yesterday's
        offset (the previous day's offset) and never interprets a requested local
        window as UTC. There is one Garmin
        heart-rate read per requested date; response caps and bin schema are
        unchanged. The provisional warning code is local_time_provisional.
        Every returned raw, bin, or gap timestamp includes UTC; local ISO is
        included only when unambiguous. Samples can be irregular or missing; sample
        count times cadence is not duration, and this does not establish time in
        zone. Wellness samples are distinct from FIT activity HR and cannot be
        assumed to use the same sensor, smoothing, samples, or zones. Gaps have
        no inferred cause. Bins summarize returned samples, not continuous
        coverage. Do not infer drift, recovery, stress, or coaching conclusions
        from this tool alone. Garmin, device, account, and sync availability can
        vary.
        """
        result = get_wellness_heart_rate_service(
            garmin_client,
            start_date,
            end_date,
            resolution,
            start_time,
            end_time,
        )
        return json.dumps(result, separators=(",", ":"), ensure_ascii=False)

    return app
