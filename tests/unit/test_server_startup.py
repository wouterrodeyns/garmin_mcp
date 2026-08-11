"""Startup smoke tests for the packaged MCP server."""

import asyncio
from unittest.mock import Mock

import garmin_mcp
import pytest
from mcp.server.fastmcp import FastMCP


def _clear_tool_filter_environment(monkeypatch):
    """Ensure each startup test supplies its own filter configuration."""
    for variable in (
        "GARMIN_TOOL_PROFILE",
        "GARMIN_ENABLED_TOOLS",
        "GARMIN_DISABLED_TOOLS",
    ):
        monkeypatch.delenv(variable, raising=False)


def test_main_registers_tools_and_starts_stdio(monkeypatch):
    """Run main() without real Garmin auth and stop before entering the server loop."""
    run_calls = []

    monkeypatch.delenv("GARMIN_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("GARMIN_MCP_HOST", raising=False)
    monkeypatch.delenv("GARMIN_MCP_PORT", raising=False)
    _clear_tool_filter_environment(monkeypatch)
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
    _clear_tool_filter_environment(monkeypatch)
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


def test_main_configures_and_registers_ai_training(monkeypatch):
    configured = []
    registered = []
    original_configure = garmin_mcp.ai_training.configure
    original_register_tools = garmin_mcp.ai_training.register_tools

    monkeypatch.delenv("GARMIN_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("GARMIN_MCP_HOST", raising=False)
    monkeypatch.delenv("GARMIN_MCP_PORT", raising=False)
    _clear_tool_filter_environment(monkeypatch)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())
    monkeypatch.setattr(
        garmin_mcp.ai_training,
        "configure",
        lambda client: (configured.append(client), original_configure(client))[1],
    )
    monkeypatch.setattr(
        garmin_mcp.ai_training,
        "register_tools",
        lambda app: (registered.append(app), original_register_tools(app))[1],
    )
    monkeypatch.setattr(FastMCP, "run", lambda self, **_kwargs: None)

    garmin_mcp.main()

    assert len(configured) == 1
    assert len(registered) == 1
    assert configured[0]._client is not None
    assert registered[0] is not None


def test_main_configures_and_registers_ai_activity_adjacent_to_ai_tools(monkeypatch):
    events = []
    original_activity_configure = garmin_mcp.ai_activity.configure
    original_activity_register_tools = garmin_mcp.ai_activity.register_tools
    original_training_configure = garmin_mcp.ai_training.configure
    original_training_register_tools = garmin_mcp.ai_training.register_tools

    monkeypatch.delenv("GARMIN_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("GARMIN_MCP_HOST", raising=False)
    monkeypatch.delenv("GARMIN_MCP_PORT", raising=False)
    _clear_tool_filter_environment(monkeypatch)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())
    monkeypatch.setattr(
        garmin_mcp.ai_training,
        "configure",
        lambda client: (events.append(("configure_training", client)), original_training_configure(client))[1],
    )
    monkeypatch.setattr(
        garmin_mcp.ai_activity,
        "configure",
        lambda client: (events.append(("configure_activity", client)), original_activity_configure(client))[1],
    )
    monkeypatch.setattr(
        garmin_mcp.ai_training,
        "register_tools",
        lambda app: (events.append(("register_training", app)), original_training_register_tools(app))[1],
    )
    monkeypatch.setattr(
        garmin_mcp.ai_activity,
        "register_tools",
        lambda app: (events.append(("register_activity", app)), original_activity_register_tools(app))[1],
    )
    monkeypatch.setattr(FastMCP, "run", lambda self, **_kwargs: None)

    garmin_mcp.main()

    names = [event[0] for event in events]
    assert names.index("configure_training") < names.index("configure_activity")
    assert names.index("register_training") < names.index("register_activity")
    assert events[names.index("configure_activity")][1]._client is not None


def test_main_rejects_unknown_profile_before_authentication(monkeypatch, capsys):
    authentication = Mock()
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "ai_coach")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", authentication)
    monkeypatch.setattr(FastMCP, "run", lambda self, **_kwargs: None)

    with pytest.raises(SystemExit) as error:
        garmin_mcp.main()

    assert error.value.code == 1
    assert "Unknown GARMIN_TOOL_PROFILE 'ai_coach'; valid profile(s): ai-coach" in capsys.readouterr().err
    authentication.assert_not_called()


def test_main_explicit_allowlist_overrides_unknown_profile(monkeypatch):
    run_calls = []
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "ai_coach")
    monkeypatch.setenv("GARMIN_ENABLED_TOOLS", "get_devices")
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append([tool.name for tool in asyncio.run(self.list_tools())])

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls == [["get_devices"]]


def test_main_registers_exact_ai_coach_profile(monkeypatch):
    run_calls = []
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "ai-coach")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append({tool.name for tool in asyncio.run(self.list_tools())})

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls == [garmin_mcp.TOOL_PROFILES["ai-coach"]]


def test_main_warns_for_unknown_tool_in_profile(monkeypatch, capsys):
    run_calls = []
    monkeypatch.setitem(
        garmin_mcp.TOOL_PROFILES,
        "ai-coach",
        {"no_such_profile_tool"},
    )
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "ai-coach")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append([tool.name for tool in asyncio.run(self.list_tools())])

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls == [[]]
    stderr = capsys.readouterr().err
    assert "name(s) not found and ignored: no_such_profile_tool" in stderr
    assert "active allowlist permits no tools" in stderr


def test_main_warns_when_active_allowlist_permits_no_tools(monkeypatch, capsys):
    run_calls = []
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "ai-coach")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.setenv(
        "GARMIN_DISABLED_TOOLS",
        ",".join(garmin_mcp.TOOL_PROFILES["ai-coach"]),
    )
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append([tool.name for tool in asyncio.run(self.list_tools())])

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls == [[]]
    stderr = capsys.readouterr().err
    assert "Tool filter: allowlist of 0 tool(s)." in stderr
    assert "active allowlist permits no tools" in stderr
