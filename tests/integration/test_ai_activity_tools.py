"""Integration coverage for the read-only AI activity analysis MCP tool."""

from __future__ import annotations

import json

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


class ReadOnlyActivityClient:
    """A client that permits only the one read required by this test."""

    def __init__(self) -> None:
        self.activity_ids: list[int] = []

    def get_activity(self, activity_id: int) -> dict[str, object]:
        self.activity_ids.append(activity_id)
        return {
            "activityId": activity_id,
            "activityName": "Completed activity",
            "activityTypeDTO": {"typeKey": "other"},
            "summaryDTO": {},
            "metadataDTO": {},
        }

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected client access: {name}")


def response_text(response: object) -> str:
    return response[0][0].text  # type: ignore[index,union-attr]


def registered_app(client: object | None) -> FastMCP:
    app = FastMCP("AI Activity")
    ai_activity.configure(client)
    return ai_activity.register_tools(app)


@pytest.mark.asyncio
async def test_analyze_activity_has_only_a_required_integer_or_string_activity_id():
    app = registered_app(ReadOnlyActivityClient())

    tools_by_name = {tool.name: tool for tool in await app.list_tools()}

    assert set(tools_by_name) == {"analyze_activity"}
    schema = tools_by_name["analyze_activity"].inputSchema
    assert schema["properties"] == {
        "activity_id": {
            "anyOf": [{"type": "integer"}, {"type": "string"}],
            "title": "Activity Id",
        }
    }
    assert schema["required"] == ["activity_id"]


@pytest.mark.asyncio
async def test_unconfigured_registration_after_a_configured_test_is_client_unavailable():
    app = FastMCP("AI Activity")
    ai_activity.register_tools(app)

    payload = json.loads(
        response_text(await app.call_tool("analyze_activity", {"activity_id": 42}))
    )

    assert payload["error"]["code"] == "client_unavailable"


@pytest.mark.asyncio
async def test_analyze_activity_delegates_the_exact_integer_and_serializes_stably(
    monkeypatch: pytest.MonkeyPatch,
):
    client = object()
    app = registered_app(client)
    observed: list[tuple[object, object]] = []
    service_result = {"status": "success", "activity": {"id": 42}}

    def fake_service(received_client: object, activity_id: object) -> dict[str, object]:
        observed.append((received_client, activity_id))
        return service_result

    monkeypatch.setattr(tools, "analyze_activity_service", fake_service)

    response = await app.call_tool("analyze_activity", {"activity_id": 42})

    assert observed == [(client, 42)]
    assert response_text(response) == json.dumps(service_result, indent=2)


@pytest.mark.asyncio
async def test_analyze_activity_accepts_a_trimmed_decimal_string_with_no_writes():
    client = ReadOnlyActivityClient()
    app = registered_app(client)

    payload = json.loads(
        response_text(await app.call_tool("analyze_activity", {"activity_id": " 42 "}))
    )

    assert payload["status"] == "success"
    assert payload["activity"]["id"] == 42
    assert list(payload) == [
        "status",
        "error",
        "activity",
        "availability",
        "splits",
        "heart_rate_zones",
        "power_zones",
        "strength",
        "derived",
        "warnings",
    ]
    assert client.activity_ids == [42]


@pytest.mark.asyncio
async def test_analyze_activity_missing_id_is_rejected_by_fastmcp_validation():
    app = registered_app(ReadOnlyActivityClient())

    with pytest.raises(ToolError, match="activity_id"):
        await app.call_tool("analyze_activity", {})


@pytest.mark.asyncio
async def test_analyze_activity_returns_the_stable_client_unavailable_envelope():
    app = registered_app(None)

    payload = json.loads(
        response_text(await app.call_tool("analyze_activity", {"activity_id": 42}))
    )

    assert payload["error"] == {
        "code": "client_unavailable",
        "message": "Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.",
    }


@pytest.mark.asyncio
async def test_analyze_activity_documents_the_ai_coach_boundary():
    app = registered_app(ReadOnlyActivityClient())
    tool = next(tool for tool in await app.list_tools() if tool.name == "analyze_activity")
    description = " ".join(tool.description.lower().split())

    for phrase in (
        "completed garmin activity",
        "read-only",
        "factual",
        "bounded",
        "sport-aware",
        "optional garmin detail",
        "null or unavailable",
        "activity, device, account, or sync",
        "mechanical facts",
        "not coaching advice",
        "ai interprets the evidence",
    ):
        assert phrase in description
