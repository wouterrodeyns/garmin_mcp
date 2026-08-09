"""Integration coverage for the compact AI training-context MCP tool."""

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_mcp import ai_training
from garmin_mcp.ai_training import service


COMPACT_KEYS = {
    "status",
    "error",
    "period",
    "schedule_period",
    "availability",
    "training",
    "recent_activities",
    "recovery",
    "sleep",
    "hrv",
    "heart_rate",
    "fitness",
    "scheduled_workouts",
    "warnings",
}


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 8, 9)


def complete_read_client():
    """Return a client limited to the read seams used by ai_training."""
    return SimpleNamespace(
        garmin_connect_activities="/activities",
        connectapi=Mock(return_value=[]),
        query_garmin_graphql=Mock(
            return_value={"data": {"workoutScheduleSummariesScalar": []}}
        ),
        get_stats=Mock(return_value={}),
        get_sleep_data=Mock(return_value={}),
        get_hrv_data=Mock(return_value={}),
        get_morning_training_readiness=Mock(return_value={}),
        get_training_status=Mock(return_value={}),
    )


def forbid_writes(client):
    writes = {}
    for name in (
        "upload_workout",
        "schedule_workout",
        "delete_workout",
        "post",
        "put",
        "delete",
    ):
        writes[name] = Mock(side_effect=AssertionError(f"write called: {name}"))
        setattr(client, name, writes[name])
    return writes


def response_payload(content):
    return json.loads(content[0][0].text)


@pytest.mark.asyncio
async def test_get_training_context_uses_default_days_and_is_read_only(monkeypatch):
    client = complete_read_client()
    writes = forbid_writes(client)
    monkeypatch.setattr(service, "date", FixedDate)
    app = FastMCP("test")
    ai_training.configure(client)
    ai_training.register_tools(app)

    payload = response_payload(await app.call_tool("get_training_context", {}))

    assert payload["period"] == {
        "days": 14,
        "start_date": "2026-07-27",
        "end_date": "2026-08-09",
    }
    assert payload["schedule_period"] == {
        "start_date": "2026-08-09",
        "end_date": "2026-08-15",
    }
    assert set(payload) == COMPACT_KEYS
    for write in writes.values():
        write.assert_not_called()


@pytest.mark.asyncio
async def test_get_training_context_accepts_explicit_days(monkeypatch):
    client = complete_read_client()
    writes = forbid_writes(client)
    monkeypatch.setattr(service, "date", FixedDate)
    app = FastMCP("test")
    ai_training.configure(client)
    ai_training.register_tools(app)

    payload = response_payload(
        await app.call_tool("get_training_context", {"days": 30})
    )

    assert payload["period"] == {
        "days": 30,
        "start_date": "2026-07-11",
        "end_date": "2026-08-09",
    }
    assert set(payload) == COMPACT_KEYS
    for write in writes.values():
        write.assert_not_called()
