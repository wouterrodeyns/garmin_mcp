"""Integration coverage for the explicit AI sleep-trend MCP tool."""

from __future__ import annotations

import json
from datetime import date

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from garmin_mcp import ai_training
from garmin_mcp.ai_training import sleep, tools


class FixedDate(date):
    """Keep integration period assertions deterministic."""

    @classmethod
    def today(cls) -> "FixedDate":
        return cls(2026, 8, 17)


class ReadOnlySleepClient:
    """Allow exactly one sleep read and record all forbidden access attempts."""

    _FORBIDDEN = (
        "create_workout",
        "upload_workout",
        "update_workout",
        "schedule_workout",
        "unschedule_workout",
        "delete_workout",
        "connectapi",
        "garth",
        "session",
        "post",
        "put",
        "delete",
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.forbidden_calls: list[str] = []

    def get_sleep_data(self, date_text: str) -> dict[str, object]:
        self.calls.append(("get_sleep_data", date_text))
        return integration_sleep_payload(date_text)

    def __getattr__(self, name: str) -> object:
        self.forbidden_calls.append(name)
        raise AssertionError(f"forbidden client access: {name}")


def integration_sleep_payload(date_text: str) -> dict[str, object]:
    return {
        "dailySleepDTO": {
            "calendarDate": date_text,
            "sleepTimeSeconds": 25_200,
            "sleepScores": {
                "overall": {"value": 81, "qualifierKey": "GOOD"}
            },
        }
    }


def response_text(response: object) -> str:
    return response[0][0].text  # type: ignore[index, union-attr]


def registered_app(client: object | None) -> FastMCP:
    app = FastMCP("AI Sleep Trend")
    ai_training.configure(client)
    return ai_training.register_tools(app)


@pytest.fixture(autouse=True)
def isolate_configured_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sleep, "date", FixedDate)
    original_client = tools.garmin_client
    tools.garmin_client = None
    yield
    tools.garmin_client = original_client


@pytest.mark.asyncio
async def test_get_sleep_trend_schema_is_strict_and_has_default_days():
    app = registered_app(ReadOnlySleepClient())

    tool = next(tool for tool in await app.list_tools() if tool.name == "get_sleep_trend")

    assert tool.inputSchema["properties"] == {
        "days": {"type": "integer", "default": 7, "title": "Days"}
    }
    assert "required" not in tool.inputSchema


@pytest.mark.asyncio
async def test_get_sleep_trend_default_call_reads_fixed_period_once_per_date():
    client = ReadOnlySleepClient()
    app = registered_app(client)

    payload = json.loads(response_text(await app.call_tool("get_sleep_trend", {})))

    assert payload["period"] == {
        "days": 7,
        "start_date": "2026-08-11",
        "end_date": "2026-08-17",
    }
    assert len(client.calls) == 7
    assert [date_text for _, date_text in client.calls] == [
        "2026-08-11",
        "2026-08-12",
        "2026-08-13",
        "2026-08-14",
        "2026-08-15",
        "2026-08-16",
        "2026-08-17",
    ]


@pytest.mark.asyncio
async def test_get_sleep_trend_explicit_days_delegates_to_service_once(
    monkeypatch: pytest.MonkeyPatch,
):
    client = object()
    app = registered_app(client)
    observed: list[tuple[object, object]] = []
    service_result = {"status": "success", "period": {"days": 3}}

    def fake_service(received_client: object, days: object) -> dict[str, object]:
        observed.append((received_client, days))
        return service_result

    monkeypatch.setattr(tools, "get_sleep_trend_service", fake_service)

    response = await app.call_tool("get_sleep_trend", {"days": 3})

    assert observed == [(client, 3)]
    assert response_text(response) == json.dumps(
        service_result, separators=(",", ":"), ensure_ascii=False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [True, False])
async def test_get_sleep_trend_rejects_json_booleans_before_garmin_reads(
    days: bool,
):
    client = ReadOnlySleepClient()
    app = registered_app(client)

    with pytest.raises(ToolError, match="days"):
        await app.call_tool("get_sleep_trend", {"days": days})

    assert client.calls == []


@pytest.mark.asyncio
async def test_get_sleep_trend_description_states_period_cost_and_interpretation_limits():
    app = registered_app(None)
    tool = next(tool for tool in await app.list_tools() if tool.name == "get_sleep_trend")
    description = " ".join(tool.description.lower().split())

    for phrase in (
        "fixed inclusive period ending today",
        "1 through 30 nights",
        "detailed sleep evidence is fetched explicitly",
        "one sequential garmin read per requested date",
        "missing dates remain visible and are not replaced",
        "current/today data may be unavailable until the watch synchronizes",
        "per-metric averages include their actual denominator (nights used)",
        "varies by device, account, and sync state",
        "do not infer causation, readiness, recovery, or make recommendations solely from sleep data",
    ):
        assert phrase in description


@pytest.mark.asyncio
async def test_get_sleep_trend_never_accesses_forbidden_client_methods():
    client = ReadOnlySleepClient()
    app = registered_app(client)

    for name in ReadOnlySleepClient._FORBIDDEN:
        with pytest.raises(AssertionError, match=f"forbidden client access: {name}"):
            getattr(client, name)

    assert client.forbidden_calls == list(ReadOnlySleepClient._FORBIDDEN)
    client.forbidden_calls.clear()

    await app.call_tool("get_sleep_trend", {"days": 1})

    assert client.forbidden_calls == []
    assert set(ReadOnlySleepClient._FORBIDDEN) == {
        "create_workout",
        "upload_workout",
        "update_workout",
        "schedule_workout",
        "unschedule_workout",
        "delete_workout",
        "connectapi",
        "garth",
        "session",
        "post",
        "put",
        "delete",
    }
