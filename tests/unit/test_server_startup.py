"""Startup smoke tests for the packaged MCP server."""

import asyncio
from unittest.mock import Mock

import garmin_mcp
from mcp.server.fastmcp import FastMCP


def test_main_registers_tools_and_starts_stdio(monkeypatch):
    """Run main() without real Garmin auth and stop before entering the server loop."""
    run_calls = []

    monkeypatch.delenv("GARMIN_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("GARMIN_MCP_HOST", raising=False)
    monkeypatch.delenv("GARMIN_MCP_PORT", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **kwargs):
        tools = asyncio.run(self.list_tools())
        run_calls.append(
            {
                "transport": kwargs.get("transport"),
                "tool_count": len(tools),
                "tool_names": [tool.name for tool in tools],
            }
        )

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls
    assert run_calls[0]["transport"] == "stdio"
    assert run_calls[0]["tool_count"] >= 10
    assert "get_devices" in run_calls[0]["tool_names"]
    assert "get_workouts" in run_calls[0]["tool_names"]
    assert "create_workout" in run_calls[0]["tool_names"]


def test_main_configures_and_registers_ai_workouts(monkeypatch):
    configured = []
    registered = []
    original_configure = garmin_mcp.ai_workouts.configure
    original_register_tools = garmin_mcp.ai_workouts.register_tools

    monkeypatch.delenv("GARMIN_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("GARMIN_MCP_HOST", raising=False)
    monkeypatch.delenv("GARMIN_MCP_PORT", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())
    monkeypatch.setattr(
        garmin_mcp.ai_workouts,
        "configure",
        lambda client: (configured.append(client), original_configure(client))[1],
    )
    monkeypatch.setattr(
        garmin_mcp.ai_workouts,
        "register_tools",
        lambda app: (registered.append(app), original_register_tools(app))[1],
    )

    monkeypatch.setattr(FastMCP, "run", lambda self, **_kwargs: None)

    garmin_mcp.main()

    assert len(configured) == 1
    assert len(registered) == 1
    assert configured[0]._client is not None
    assert registered[0] is not None
