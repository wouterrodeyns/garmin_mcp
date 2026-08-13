"""Integration coverage for the read-only activity timeseries MCP tool."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from garmin_mcp import ai_activity
from garmin_mcp.ai_activity import tools


@pytest.fixture(autouse=True)
def isolate_configured_garmin_client():
    """Start each test unconfigured and restore the prior module-global client."""
    original_client = tools.garmin_client
    tools.garmin_client = None
    try:
        yield
    finally:
        tools.garmin_client = original_client


def response_text(response: object) -> str:
    return response[0][0].text  # type: ignore[index,union-attr]


def registered_app(client: object | None) -> FastMCP:
    app = FastMCP("AI Activity")
    ai_activity.configure(client)
    return ai_activity.register_tools(app)


def internal_error_envelope() -> dict[str, object]:
    return {
        "status": "error",
        "error": {
            "provider": "internal",
            "code": "internal_error",
            "message": "Activity time series is temporarily unavailable.",
        },
        "activity_id": None,
        "window": {
            "requested_start_seconds": None,
            "actual_end_seconds": None,
            "resolution_seconds": None,
        },
        "sampling": {
            "source_records": 0,
            "returned_points": 0,
            "observed_median_interval_seconds": None,
            "irregular": False,
        },
        "availability": {
            "heart_rate_bpm": False,
            "speed_mps": False,
            "pace_seconds_per_km": False,
            "cadence_rpm": False,
            "power_w": False,
            "altitude_m": False,
            "grade_pct": False,
        },
        "series": {
            "elapsed_seconds": [],
            "timestamp": [],
            "sample_count": [],
            "heart_rate_bpm": {"average": [], "minimum": [], "maximum": []},
            "speed_mps": {"average": []},
            "pace_seconds_per_km": {"average": [], "fastest": [], "slowest": []},
            "cadence_rpm": {"average": []},
            "power_w": {"average": []},
            "altitude_m": {"average": []},
            "grade_pct": {"average": []},
        },
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_get_activity_timeseries_schema_uses_strict_id_and_window_types():
    app = registered_app(object())

    tools_by_name = {tool.name: tool for tool in await app.list_tools()}

    assert set(tools_by_name) == {"analyze_activity", "get_activity_timeseries"}
    schema = tools_by_name["get_activity_timeseries"].inputSchema
    assert schema["required"] == ["activity_id"]
    assert schema["properties"]["activity_id"]["anyOf"] == [
        {"type": "integer"},
        {"type": "string"},
    ]
    assert schema["properties"]["start_seconds"]["default"] == 0
    assert schema["properties"]["duration_seconds"]["default"] == 600
    assert schema["properties"]["resolution_seconds"]["default"] == 1
    assert {
        name: schema["properties"][name]["type"]
        for name in ("start_seconds", "duration_seconds", "resolution_seconds")
    } == {
        "start_seconds": "integer",
        "duration_seconds": "integer",
        "resolution_seconds": "integer",
    }


@pytest.mark.asyncio
async def test_get_activity_timeseries_delegates_defaults_once_and_serializes_stably(
    monkeypatch: pytest.MonkeyPatch,
):
    client = object()
    app = registered_app(client)
    service_result = {"status": "success", "bins": [{"elapsed_seconds": 0}]}
    service = Mock(return_value=service_result)
    monkeypatch.setattr(tools, "get_activity_timeseries_service", service)

    response = await app.call_tool("get_activity_timeseries", {"activity_id": 42})

    service.assert_called_once_with(client, 42, 0, 600, 1)
    assert response_text(response) == json.dumps(service_result, indent=2)


@pytest.mark.asyncio
async def test_get_activity_timeseries_delegates_explicit_values_and_leaves_string_normalization_to_service(
    monkeypatch: pytest.MonkeyPatch,
):
    client = object()
    app = registered_app(client)
    service = Mock(return_value={"status": "success"})
    monkeypatch.setattr(tools, "get_activity_timeseries_service", service)

    await app.call_tool(
        "get_activity_timeseries",
        {
            "activity_id": " 42 ",
            "start_seconds": 7,
            "duration_seconds": 10,
            "resolution_seconds": 2,
        },
    )

    service.assert_called_once_with(client, " 42 ", 7, 10, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("activity_id", [True, 1.0, [], {}])
async def test_get_activity_timeseries_rejects_invalid_activity_id_types_before_service(
    monkeypatch: pytest.MonkeyPatch, activity_id: object
):
    app = registered_app(object())
    service = Mock()
    monkeypatch.setattr(tools, "get_activity_timeseries_service", service)

    with pytest.raises(ToolError, match="activity_id"):
        await app.call_tool("get_activity_timeseries", {"activity_id": activity_id})

    service.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("argument", ["start_seconds", "duration_seconds", "resolution_seconds"])
@pytest.mark.parametrize("value", [True, 1.0, "1", [], {}])
async def test_get_activity_timeseries_rejects_invalid_window_types_before_service(
    monkeypatch: pytest.MonkeyPatch, argument: str, value: object
):
    app = registered_app(object())
    service = Mock()
    monkeypatch.setattr(tools, "get_activity_timeseries_service", service)

    with pytest.raises(ToolError, match=argument):
        await app.call_tool(
            "get_activity_timeseries", {"activity_id": 42, argument: value}
        )

    service.assert_not_called()


@pytest.mark.asyncio
async def test_get_activity_timeseries_leaves_typed_out_of_range_values_to_service(
    monkeypatch: pytest.MonkeyPatch,
):
    client = object()
    app = registered_app(client)
    envelope = {"status": "error", "error": {"code": "invalid_window"}}
    service = Mock(return_value=envelope)
    monkeypatch.setattr(tools, "get_activity_timeseries_service", service)

    response = await app.call_tool(
        "get_activity_timeseries",
        {
            "activity_id": -42,
            "start_seconds": -1,
            "duration_seconds": 0,
            "resolution_seconds": -1,
        },
    )

    service.assert_called_once_with(client, -42, -1, 0, -1)
    assert json.loads(response_text(response)) == envelope


@pytest.mark.asyncio
async def test_get_activity_timeseries_ignores_undeclared_arguments(
    monkeypatch: pytest.MonkeyPatch,
):
    client = object()
    app = registered_app(client)
    service = Mock(return_value={"status": "success"})
    monkeypatch.setattr(tools, "get_activity_timeseries_service", service)

    await app.call_tool(
        "get_activity_timeseries", {"activity_id": 42, "ignored_argument": "ignored"}
    )

    service.assert_called_once_with(client, 42, 0, 600, 1)


@pytest.mark.asyncio
async def test_get_activity_timeseries_sanitizes_service_runtime_errors_at_the_public_boundary(
    monkeypatch: pytest.MonkeyPatch,
):
    client = object()
    app = registered_app(client)
    service = Mock(
        side_effect=RuntimeError(
            "token=private https://example.invalid Authorization request_id path"
        )
    )
    monkeypatch.setattr(tools, "get_activity_timeseries_service", service)

    response = await app.call_tool("get_activity_timeseries", {"activity_id": 42})
    expected = internal_error_envelope()
    text = response_text(response)

    service.assert_called_once_with(client, 42, 0, 600, 1)
    assert text == json.dumps(expected, indent=2)
    payload = json.loads(text)
    assert payload == expected

    def values(value: object):
        if type(value) is dict:
            for nested in value.values():
                yield from values(nested)
        elif type(value) is list:
            for nested in value:
                yield from values(nested)
        else:
            yield value

    rendered = " ".join(str(value).lower() for value in values(payload))
    for secret_fragment in (
        "token=private",
        "https://",
        "authorization",
        "request_id",
        "path",
        "runtimeerror",
    ):
        assert secret_fragment not in rendered


@pytest.mark.asyncio
async def test_get_activity_timeseries_documents_its_read_only_evidence_boundary():
    app = registered_app(object())
    tool = next(
        tool for tool in await app.list_tools() if tool.name == "get_activity_timeseries"
    )
    description = " ".join(tool.description.lower().split())

    for phrase in (
        "read-only",
        "one original fit download after valid input",
        "analyze_activity first",
        "short interval",
        "sparse",
        "gaps",
        "never imply one-hz sampling",
        "never include gps or raw fit data",
        "availability describes this returned window",
    ):
        assert phrase in description
