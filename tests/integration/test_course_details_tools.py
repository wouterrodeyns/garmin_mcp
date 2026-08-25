"""FastMCP integration coverage for the read-only course-details tool."""

import json
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from garmin_mcp import course_details


class RecordingProxy:
    def __init__(self, response=None, failure=None):
        self.response = response
        self.failure = failure
        self.calls = []

    def connectapi(self, path):
        self.calls.append(path)
        if self.failure is not None:
            raise self.failure
        return self.response

    def __getattr__(self, name):
        raise AssertionError(f"forbidden client access: {name}")


def _result_text(result):
    return result[0][0].text


def _registered_app(client):
    course_details.configure(client)
    return course_details.register_tools(FastMCP("Test Course Details"))


@pytest.mark.asyncio
async def test_get_course_details_is_registered_with_one_strict_argument():
    app = _registered_app(RecordingProxy())

    tools = {tool.name: tool for tool in await app.list_tools()}

    assert set(tools) == {"get_course_details"}
    schema = tools["get_course_details"].inputSchema
    assert set(schema["properties"]) == {"course_id"}
    assert schema["properties"]["course_id"]["anyOf"] == [
        {"type": "integer"},
        {"type": "string"},
    ]


@pytest.mark.asyncio
async def test_get_course_details_serializes_exact_success_envelope():
    app = _registered_app(
        RecordingProxy(
            {
                "courseId": 123,
                "courseName": "Å Loop",
                "activityTypePk": 1,
                "distanceMeter": 1234.5,
                "elevationGainMeter": 42,
                "elevationLossMeter": 40,
            }
        )
    )

    result = await app.call_tool("get_course_details", {"course_id": "123"})
    text = _result_text(result)
    payload = json.loads(text)

    assert list(payload) == ["status", "error", "course", "warnings"]
    assert list(payload["course"]) == [
        "course_id",
        "name",
        "activity",
        "distance_m",
        "elevation_gain_m",
        "elevation_loss_m",
    ]
    assert payload["course"]["course_id"] == 123
    assert text == json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    assert '" :"' not in text
    assert '": "' not in text
    assert "Å" in text


@pytest.mark.asyncio
async def test_get_course_details_delegates_to_service_and_returns_json(monkeypatch):
    client = object()
    app = _registered_app(client)
    service_result = {
        "status": "error",
        "error": {"code": "client_unavailable", "message": "safe"},
        "course": None,
        "warnings": [],
    }
    service_call = Mock(return_value=service_result)
    monkeypatch.setattr(course_details, "get_course_details_service", service_call)

    result = await app.call_tool("get_course_details", {"course_id": "123"})

    service_call.assert_called_once_with(client, "123")
    assert _result_text(result) == json.dumps(
        service_result, separators=(",", ":"), ensure_ascii=False
    )


@pytest.mark.asyncio
async def test_tool_makes_one_detail_read_and_no_mutation_or_nested_client_access():
    client = RecordingProxy({"courseId": 123})
    app = _registered_app(client)

    await app.call_tool("get_course_details", {"course_id": 123})

    assert client.calls == ["/course-service/course/123"]


@pytest.mark.asyncio
async def test_tool_suppresses_provider_exception_details():
    client = RecordingProxy(
        failure=RuntimeError("https://private/?token=sentinel request-id=secret")
    )
    app = _registered_app(client)

    result = await app.call_tool("get_course_details", {"course_id": 123})
    text = _result_text(result)

    payload = json.loads(text)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "course_unavailable"
    assert "sentinel" not in text
    assert "secret" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False, 123.0, None])
async def test_tool_rejects_non_strict_course_id_before_any_reads(value):
    client = RecordingProxy({"courseId": 123})
    app = _registered_app(client)

    with pytest.raises(ToolError, match="course_id"):
        await app.call_tool("get_course_details", {"course_id": value})

    assert client.calls == []
