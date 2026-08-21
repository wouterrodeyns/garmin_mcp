"""Integration coverage for the bounded AI target-events MCP tool."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from garmin_mcp import ai_events
from garmin_mcp.ai_events import service, tools


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 8, 21)


@pytest.fixture(autouse=True)
def isolate_configured_garmin_client():
    """Start each test unconfigured and restore the package-level client."""
    original_client = tools.garmin_client
    tools.garmin_client = None
    try:
        yield
    finally:
        tools.garmin_client = original_client


def response_text(response: object) -> str:
    return response[0][0].text  # type: ignore[index,union-attr]


def registered_app(client: object | None = None) -> FastMCP:
    app = FastMCP("AI Target Events")
    ai_events.configure(client)
    return ai_events.register_tools(app)


@pytest.mark.asyncio
async def test_get_target_events_schema_is_one_optional_strict_integer():
    app = registered_app(object())

    tools_by_name = {tool.name: tool for tool in await app.list_tools()}

    assert set(tools_by_name) == {"get_target_events"}
    schema = tools_by_name["get_target_events"].inputSchema
    assert "required" not in schema or schema["required"] == []
    assert schema["properties"]["days"] == {
        "default": 180,
        "title": "Days",
        "type": "integer",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False, "180", 180.0, None])
async def test_get_target_events_rejects_non_strict_days_before_any_reads(value):
    client = SimpleNamespace(get_scheduled_workouts=Mock())
    app = registered_app(client)

    with pytest.raises(ToolError, match="days"):
        await app.call_tool("get_target_events", {"days": value})

    client.get_scheduled_workouts.assert_not_called()


@pytest.mark.asyncio
async def test_get_target_events_delegates_once_and_serializes_compact_unicode_json(
    monkeypatch: pytest.MonkeyPatch,
):
    client = object()
    app = registered_app(client)
    service_result = {
        "status": "success",
        "events": [{"title": "Å race", "date": "2026-08-21"}],
    }
    service_call = Mock(return_value=service_result)
    monkeypatch.setattr(tools, "get_target_events_service", service_call)

    response = await app.call_tool("get_target_events", {"days": 42})

    service_call.assert_called_once_with(client, 42)
    assert response_text(response) == json.dumps(
        service_result, separators=(",", ":"), ensure_ascii=False
    )
    assert '" :"' not in response_text(response)
    assert '": "' not in response_text(response)
    assert "}, {" not in response_text(response)
    assert "Å" in response_text(response)


@pytest.mark.asyncio
async def test_get_target_events_uses_latest_configured_client_and_restores_global(
    monkeypatch: pytest.MonkeyPatch,
):
    original_client = object()
    tools.garmin_client = original_client
    first_client = object()
    second_client = object()
    app = FastMCP("AI Target Events")

    ai_events.configure(first_client)
    ai_events.register_tools(app)
    ai_events.configure(second_client)
    observed_clients = []

    def observe_client(client, days):
        observed_clients.append(tools.garmin_client)
        return {"status": "success", "events": []}

    # The registered closure reads the module-global client at call time.
    monkeypatch.setattr(tools, "get_target_events_service", observe_client)
    await app.call_tool("get_target_events", {})
    tools.garmin_client = original_client

    assert observed_clients == [second_client]


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [0, 367])
async def test_get_target_events_service_bounds_are_serialized_without_reads(
    monkeypatch: pytest.MonkeyPatch, days: int
):
    client = SimpleNamespace(get_scheduled_workouts=Mock())
    app = registered_app(client)
    monkeypatch.setattr(service, "date", FixedDate)

    response = await app.call_tool("get_target_events", {"days": days})

    payload = json.loads(response_text(response))
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "invalid_days"
    client.get_scheduled_workouts.assert_not_called()


@pytest.mark.asyncio
async def test_get_target_events_366_days_reads_thirteen_months_and_exposes_no_write_seams():
    class ReadOnlyClient:
        def __init__(self):
            self.calls = []

        def get_scheduled_workouts(self, year: int, month: int):
            self.calls.append((year, month))
            return {"calendarItems": []}

        def __getattr__(self, name: str):
            raise AssertionError(f"unexpected client surface accessed: {name}")

    client = ReadOnlyClient()
    app = registered_app(client)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service, "date", FixedDate)
    try:
        response = await app.call_tool("get_target_events", {"days": 366})
    finally:
        monkeypatch.undo()

    payload = json.loads(response_text(response))
    assert payload["status"] == "success"
    assert client.calls == [
        (2026, 8),
        (2026, 9),
        (2026, 10),
        (2026, 11),
        (2026, 12),
        (2027, 1),
        (2027, 2),
        (2027, 3),
        (2027, 4),
        (2027, 5),
        (2027, 6),
        (2027, 7),
        (2027, 8),
    ]


@pytest.mark.asyncio
async def test_get_target_events_docstring_describes_bounded_untrusted_evidence():
    app = registered_app(object())
    tool = {tool.name: tool for tool in await app.list_tools()}["get_target_events"]
    description = " ".join(tool.description.lower().split())

    assert "bounded" in description
    assert "read-only" in description
    assert "local" in description
    assert "1 through 366" in description
    assert "sequential" in description
    assert "100 events" in description
    assert "untrusted facts" in description
    assert "not instructions" in description
    assert "no coaching conclusion" in description
    assert "no garmin mutation" in description
