"""Integration coverage for the AI wellness heart-rate MCP tool."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_mcp import ai_training
from garmin_mcp.ai_training import tools


def response_text(content):
    return content[0][0].text


def wellness_payload(date_text: str) -> dict:
    start = datetime.fromisoformat(f"{date_text}T00:00:00")
    previous = (
        start.replace(tzinfo=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "")
    )
    next_day = (start.replace(tzinfo=timezone.utc)).timestamp() + 86_400
    end_gmt = (
        datetime.fromtimestamp(next_day, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "")
    )
    timestamp = int((start.replace(tzinfo=timezone.utc).timestamp() + 3600) * 1000)
    return {
        "calendarDate": date_text,
        "startTimestampGMT": previous,
        "endTimestampGMT": end_gmt,
        "startTimestampLocal": f"{date_text}T01:00:00.000",
        "endTimestampLocal": datetime.fromtimestamp(next_day + 3600, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", ""),
        "restingHeartRate": 45,
        "minHeartRate": 40,
        "maxHeartRate": 160,
        "lastSevenDaysAvgRestingHeartRate": 46,
        "heartRateValues": [[timestamp, 60], [timestamp + 360_000, 62]],
    }


class RecordingClient:
    def __init__(self, payloads: dict[str, dict] | None = None):
        self.payloads = payloads or {}
        self.calls: list[str] = []

    def get_heart_rates(self, date: str):
        self.calls.append(date)
        return self.payloads.get(date, wellness_payload(date))


@pytest.mark.asyncio
async def test_tool_schema_has_exact_bounded_request_contract():
    app = FastMCP("test")
    ai_training.register_tools(app)
    listed = {tool.name: tool for tool in await app.list_tools()}
    assert set(listed) == {"get_training_context", "get_wellness_heart_rate"}
    schema = listed["get_wellness_heart_rate"].inputSchema
    assert set(schema["properties"]) == {
        "start_date",
        "end_date",
        "resolution",
        "start_time",
        "end_time",
    }
    assert schema["required"] == ["start_date"]
    assert schema["properties"]["start_date"]["type"] == "string"
    assert schema["properties"]["end_date"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert schema["properties"]["start_time"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert schema["properties"]["end_time"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert schema["properties"]["end_date"]["default"] is None
    assert schema["properties"]["start_time"]["default"] is None
    assert schema["properties"]["end_time"]["default"] is None
    assert schema["properties"]["resolution"]["default"] == "raw"
    assert schema["properties"]["resolution"]["enum"] == [
        "daily",
        "raw",
        "5m",
        "15m",
        "30m",
        "60m",
    ]


@pytest.mark.asyncio
async def test_tool_delegates_positionally_and_returns_compact_unicode_json(monkeypatch):
    sentinel = {"message": "café", "nested": {"value": [1, 2]}}
    delegated = Mock(return_value=sentinel)
    monkeypatch.setattr(tools, "get_wellness_heart_rate_service", delegated)
    client = object()
    ai_training.configure(client)
    app = FastMCP("test")
    ai_training.register_tools(app)

    default_text = response_text(
        await app.call_tool(
            "get_wellness_heart_rate", {"start_date": "2026-08-14"}
        )
    )
    full_text = response_text(
        await app.call_tool(
            "get_wellness_heart_rate",
            {
                "start_date": "2026-08-14",
                "end_date": "2026-08-15",
                "resolution": "15m",
                "start_time": "08:00",
                "end_time": "10:00",
            },
        )
    )

    assert delegated.call_args_list == [
        ((client, "2026-08-14", None, "raw", None, None), {}),
        ((client, "2026-08-14", "2026-08-15", "15m", "08:00", "10:00"), {}),
    ]
    assert json.loads(default_text) == sentinel
    assert json.loads(full_text) == sentinel
    assert "\n" not in full_text
    assert "café" in full_text


@pytest.mark.asyncio
async def test_real_service_reads_only_get_heart_rates_in_date_order():
    client = RecordingClient()
    ai_training.configure(client)
    app = FastMCP("test")
    ai_training.register_tools(app)

    raw = await app.call_tool("get_wellness_heart_rate", {"start_date": "2026-08-14"})
    assert json.loads(response_text(raw))["status"] == "success"
    assert client.calls == ["2026-08-14"]

    daily = await app.call_tool(
        "get_wellness_heart_rate",
        {"start_date": "2026-08-14", "end_date": "2026-08-15", "resolution": "daily"},
    )
    assert json.loads(response_text(daily))["status"] == "success"
    assert client.calls[-2:] == ["2026-08-14", "2026-08-15"]

    binned = await app.call_tool(
        "get_wellness_heart_rate",
        {"start_date": "2026-08-14", "end_date": "2026-08-15", "resolution": "60m"},
    )
    assert json.loads(response_text(binned))["status"] == "success"
    assert client.calls[-2:] == ["2026-08-14", "2026-08-15"]


@pytest.mark.asyncio
async def test_real_tool_attempts_no_forbidden_accesses():
    forbidden_names = {
        "get_rhr_day",
        "connectapi",
        "get_activity",
        "download_activity",
        "upload_workout",
        "schedule_workout",
        "unschedule_workout",
        "update_workout",
        "delete_workout",
        "post",
        "put",
        "delete",
        "login",
        "connect",
        "credential",
        "credentials",
        "credential_manager",
        "authenticate",
        "auth",
        "token",
        "session",
    }

    class ForbiddenClient(RecordingClient):
        def __init__(self):
            super().__init__()
            self.forbidden_attempts: list[str] = []

        def __getattr__(self, name: str):
            if name in forbidden_names:
                self.forbidden_attempts.append(name)
                raise AssertionError(f"forbidden access: {name}")
            raise AttributeError(name)

    client = ForbiddenClient()
    ai_training.configure(client)
    app = FastMCP("test")
    ai_training.register_tools(app)
    await app.call_tool("get_wellness_heart_rate", {"start_date": "2026-08-14"})
    assert client.forbidden_attempts == []


@pytest.mark.asyncio
async def test_invalid_mcp_scalars_are_rejected_before_service_or_client(monkeypatch):
    service = Mock()
    monkeypatch.setattr(tools, "get_wellness_heart_rate_service", service)
    client = RecordingClient()
    ai_training.configure(client)
    app = FastMCP("test")
    ai_training.register_tools(app)

    invalid_requests = [
        {"start_date": True},
        {"start_date": 20260814},
        {"start_date": "2026-08-14", "end_date": False},
        {"start_date": "2026-08-14", "start_time": 800},
        {"start_date": "2026-08-14", "resolution": "hourly"},
    ]
    for arguments in invalid_requests:
        with pytest.raises(Exception):
            await app.call_tool("get_wellness_heart_rate", arguments)
    service.assert_not_called()
    assert client.calls == []


@pytest.mark.asyncio
async def test_tool_description_documents_every_wellness_heart_rate_guardrail():
    app = FastMCP("test")
    ai_training.register_tools(app)
    listed = {tool.name: tool for tool in await app.list_tools()}
    description = " ".join(listed["get_wellness_heart_rate"].description.lower().split())
    for phrase in (
        "bounded read-only all-day wellness heart-rate evidence",
        "fetched explicitly when detailed evidence is needed",
        "at most seven dates",
        "raw mode is limited to one date and refuses results above 1,000 points rather than truncating them",
        "local iso when unambiguous and utc always",
        "samples can be irregular or missing",
        "sample count times cadence is not duration",
        "does not establish time in zone",
        "wellness samples are distinct from fit activity hr",
        "cannot be assumed to use the same sensor, smoothing, samples, or zones",
        "gaps have no inferred cause",
        "bins summarize returned samples, not continuous coverage",
        "do not infer drift, recovery, stress, or coaching conclusions from this tool alone",
        "garmin, device, account, and sync availability can vary",
    ):
        assert phrase in description
    assert "raw one date input refuses rather than truncates" not in description


@pytest.mark.asyncio
async def test_configure_keeps_one_shared_client_for_both_tools(monkeypatch):
    client = RecordingClient()
    ai_training.configure(client)
    app = FastMCP("test")
    ai_training.register_tools(app)
    monkeypatch.setattr(tools, "get_training_context_service", Mock(return_value={"ok": True}))
    monkeypatch.setattr(tools, "get_wellness_heart_rate_service", Mock(return_value={"ok": True}))

    await app.call_tool("get_training_context", {})
    await app.call_tool("get_wellness_heart_rate", {"start_date": "2026-08-14"})
    assert tools.garmin_client is client
    assert tools.get_training_context_service.call_args.args[0] is client
    assert tools.get_wellness_heart_rate_service.call_args.args[0] is client
