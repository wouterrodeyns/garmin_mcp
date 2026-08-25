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


def _set_safe_stdio_transport_environment(monkeypatch):
    """Isolate startup tests from ambient HTTP transport configuration."""
    monkeypatch.setenv("GARMIN_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("GARMIN_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("GARMIN_MCP_PORT", "8000")
    monkeypatch.delenv("GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE", raising=False)


def _clear_transport_environment(monkeypatch):
    """Clear transport settings for tests that exercise their defaults."""
    for variable in (
        "GARMIN_MCP_TRANSPORT",
        "GARMIN_MCP_HOST",
        "GARMIN_MCP_PORT",
        "GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE",
    ):
        monkeypatch.delenv(variable, raising=False)


def _register_unfiltered_reference_tools():
    """Build the full maintained surface without applying any tool filter."""
    app = FastMCP("unfiltered-reference")
    for module in (
        garmin_mcp.activity_management,
        garmin_mcp.health_wellness,
        garmin_mcp.user_profile,
        garmin_mcp.devices,
        garmin_mcp.gear_management,
        garmin_mcp.weight_management,
        garmin_mcp.challenges,
        garmin_mcp.training,
        garmin_mcp.workouts,
        garmin_mcp.ai_workouts,
        garmin_mcp.ai_training,
        garmin_mcp.ai_events,
        garmin_mcp.ai_activity,
        garmin_mcp.data_management,
        garmin_mcp.womens_health,
        garmin_mcp.nutrition,
        garmin_mcp.workout_builders,
        garmin_mcp.courses,
        garmin_mcp.course_details,
        garmin_mcp.activity_analysis,
    ):
        app = module.register_tools(app)
    return {tool.name for tool in asyncio.run(app.list_tools())}


def test_main_defaults_to_exact_ai_coach_tool_profile(monkeypatch):
    """Run main() without real Garmin auth and stop before entering the server loop."""
    run_calls = []

    _clear_transport_environment(monkeypatch)
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
    assert run_calls[0]["tool_count"] == 17
    assert set(run_calls[0]["tool_names"]) == garmin_mcp.TOOL_PROFILES["ai-coach"]
    assert "get_target_events" in run_calls[0]["tool_names"]
    assert "get_devices" not in run_calls[0]["tool_names"]
    assert "get_course_details" not in run_calls[0]["tool_names"]


def test_main_registers_normalized_upstream_full_profile(monkeypatch, capsys):
    run_calls = []
    _set_safe_stdio_transport_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", " UpStReAm-FuLl ")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append({tool.name for tool in asyncio.run(self.list_tools())})

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls[0] == _register_unfiltered_reference_tools()
    assert "Tool filter: full upstream-compatible tool surface active." in capsys.readouterr().err


def test_main_rejects_empty_explicit_allowlist_before_authentication(monkeypatch, capsys):
    authentication = Mock()
    _set_safe_stdio_transport_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "upstream-full")
    monkeypatch.setenv("GARMIN_ENABLED_TOOLS", ",,  ,")
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", authentication)

    with pytest.raises(SystemExit) as error:
        garmin_mcp.main()

    assert error.value.code == 1
    assert (
        capsys.readouterr().err
        == "GARMIN_ENABLED_TOOLS must contain at least one tool name\n"
    )
    authentication.assert_not_called()


def test_main_configures_and_registers_ai_workouts(monkeypatch):
    configured = []
    registered = []
    original_configure = garmin_mcp.ai_workouts.configure
    original_register_tools = garmin_mcp.ai_workouts.register_tools

    _set_safe_stdio_transport_environment(monkeypatch)
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

    _set_safe_stdio_transport_environment(monkeypatch)
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


def test_main_configures_and_registers_ai_events_with_garmin_proxy(monkeypatch):
    configured = []
    registered = []
    raw_client = Mock()
    original_configure = garmin_mcp.ai_events.configure
    original_register_tools = garmin_mcp.ai_events.register_tools

    _set_safe_stdio_transport_environment(monkeypatch)
    _clear_tool_filter_environment(monkeypatch)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: raw_client)
    monkeypatch.setattr(
        garmin_mcp.ai_events,
        "configure",
        lambda client: (configured.append(client), original_configure(client))[1],
    )
    monkeypatch.setattr(
        garmin_mcp.ai_events,
        "register_tools",
        lambda app: (registered.append(app), original_register_tools(app))[1],
    )
    monkeypatch.setattr(FastMCP, "run", lambda self, **_kwargs: None)

    garmin_mcp.main()

    assert len(configured) == 1
    assert len(registered) == 1
    assert configured[0]._client is raw_client
    assert registered[0] is not None


def test_main_configures_and_registers_ai_activity_adjacent_to_ai_tools(monkeypatch):
    events = []
    original_activity_configure = garmin_mcp.ai_activity.configure
    original_activity_register_tools = garmin_mcp.ai_activity.register_tools
    original_events_configure = garmin_mcp.ai_events.configure
    original_events_register_tools = garmin_mcp.ai_events.register_tools
    original_training_configure = garmin_mcp.ai_training.configure
    original_training_register_tools = garmin_mcp.ai_training.register_tools

    _set_safe_stdio_transport_environment(monkeypatch)
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
        garmin_mcp.ai_events,
        "configure",
        lambda client: (events.append(("configure_events", client)), original_events_configure(client))[1],
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
    monkeypatch.setattr(
        garmin_mcp.ai_events,
        "register_tools",
        lambda app: (events.append(("register_events", app)), original_events_register_tools(app))[1],
    )
    monkeypatch.setattr(FastMCP, "run", lambda self, **_kwargs: None)

    garmin_mcp.main()

    names = [event[0] for event in events]
    assert names.index("configure_training") < names.index("configure_events") < names.index("configure_activity")
    assert names.index("register_training") < names.index("register_events") < names.index("register_activity")
    assert events[names.index("configure_events")][1]._client is not None
    assert events[names.index("configure_activity")][1]._client is not None
    assert names.count("configure_events") == 1
    assert names.count("register_events") == 1
    assert names.count("configure_activity") == 1
    assert names.count("register_activity") == 1


def test_main_rejects_unknown_profile_before_authentication(monkeypatch, capsys):
    authentication = Mock()
    _set_safe_stdio_transport_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "TOP_SECRET_PROFILE")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", authentication)
    monkeypatch.setattr(FastMCP, "run", lambda self, **_kwargs: None)

    with pytest.raises(SystemExit) as error:
        garmin_mcp.main()

    assert error.value.code == 1
    assert capsys.readouterr().err == (
        "Unknown GARMIN_TOOL_PROFILE; valid profile(s): ai-coach, upstream-full\n"
    )
    authentication.assert_not_called()


@pytest.mark.parametrize("port", ("TOP_SECRET_PORT", "-1", "0", "65536", "70000"))
def test_main_rejects_invalid_port_before_authentication(monkeypatch, capsys, port):
    authentication = Mock()
    _clear_tool_filter_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("GARMIN_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("GARMIN_MCP_PORT", port)
    monkeypatch.delenv("GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", authentication)
    monkeypatch.setattr(FastMCP, "run", lambda self, **_kwargs: None)

    with pytest.raises(SystemExit) as error:
        garmin_mcp.main()

    assert error.value.code == 1
    assert capsys.readouterr().err == (
        "GARMIN_MCP_PORT must be an integer from 1 through 65535\n"
    )
    authentication.assert_not_called()


def test_main_rejects_remote_http_before_authentication(monkeypatch, capsys):
    authentication = Mock()
    monkeypatch.setenv("GARMIN_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("GARMIN_MCP_HOST", "192.168.1.2")
    monkeypatch.setenv("GARMIN_MCP_PORT", "8000")
    monkeypatch.delenv("GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE", raising=False)
    _clear_tool_filter_environment(monkeypatch)
    monkeypatch.setattr(garmin_mcp, "init_api", authentication)

    with pytest.raises(SystemExit) as error:
        garmin_mcp.main()

    assert error.value.code == 1
    assert capsys.readouterr().err == (
        "Refusing unauthenticated remote HTTP binding because this server does "
        "not provide HTTP authentication. Use an authenticating reverse proxy, "
        "or explicitly set GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE=true to "
        "accept this danger.\n"
    )
    authentication.assert_not_called()


def test_main_explicit_allowlist_overrides_unknown_profile(monkeypatch):
    run_calls = []
    _set_safe_stdio_transport_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "ai_coach")
    monkeypatch.setenv("GARMIN_ENABLED_TOOLS", "get_devices")
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append([tool.name for tool in asyncio.run(self.list_tools())])

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls == [["get_devices"]]


def test_main_explicit_allowlist_registers_only_course_details(monkeypatch):
    run_calls = []
    _set_safe_stdio_transport_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "ai-coach")
    monkeypatch.setenv("GARMIN_ENABLED_TOOLS", "get_course_details")
    monkeypatch.setenv("GARMIN_DISABLED_TOOLS", "get_course_details")
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append({tool.name for tool in asyncio.run(self.list_tools())})

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls == [{"get_course_details"}]


def test_main_upstream_full_includes_course_details(monkeypatch):
    run_calls = []
    _set_safe_stdio_transport_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "upstream-full")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append({tool.name for tool in asyncio.run(self.list_tools())})

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert "get_course_details" in run_calls[0]
    assert run_calls[0] == _register_unfiltered_reference_tools()


def test_upstream_full_denylist_removes_course_details(monkeypatch):
    run_calls = []
    _set_safe_stdio_transport_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "upstream-full")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.setenv("GARMIN_DISABLED_TOOLS", "get_course_details")
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append({tool.name for tool in asyncio.run(self.list_tools())})

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls == [
        _register_unfiltered_reference_tools() - {"get_course_details"}
    ]


def test_main_registers_exact_ai_coach_profile(monkeypatch):
    run_calls = []
    _set_safe_stdio_transport_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "ai-coach")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append({tool.name for tool in asyncio.run(self.list_tools())})

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls == [{
        "get_training_context",
        "get_target_events",
        "get_sleep_trend",
        "get_wellness_heart_rate",
        "analyze_activity",
        "get_activity_timeseries",
        "create_workout",
        "update_workout",
        "get_activities",
        "get_activities_by_date",
        "get_activity",
        "get_workouts",
        "get_workout_by_id",
        "get_scheduled_workouts",
        "schedule_workout",
        "unschedule_workout",
        "delete_workout",
    }]


def test_ai_coach_profile_equals_actual_registered_tool_names(monkeypatch):
    run_calls = []
    _set_safe_stdio_transport_environment(monkeypatch)
    monkeypatch.setenv("GARMIN_TOOL_PROFILE", "ai-coach")
    monkeypatch.delenv("GARMIN_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GARMIN_DISABLED_TOOLS", raising=False)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())

    def capture_run(self, **_kwargs):
        run_calls.append({tool.name for tool in asyncio.run(self.list_tools())})

    monkeypatch.setattr(FastMCP, "run", capture_run)

    garmin_mcp.main()

    assert run_calls == [{
        "get_training_context",
        "get_target_events",
        "get_sleep_trend",
        "get_wellness_heart_rate",
        "analyze_activity",
        "get_activity_timeseries",
        "create_workout",
        "update_workout",
        "get_activities",
        "get_activities_by_date",
        "get_activity",
        "get_workouts",
        "get_workout_by_id",
        "get_scheduled_workouts",
        "schedule_workout",
        "unschedule_workout",
        "delete_workout",
    }]
    assert len(run_calls[0]) == 17
    assert run_calls[0] == garmin_mcp.TOOL_PROFILES["ai-coach"]
    assert "get_target_events" in run_calls[0]
    assert "get_activity_fit_data" not in run_calls[0]
    assert "move_workout" not in run_calls[0]


def test_main_warns_for_unknown_tool_in_profile(monkeypatch, capsys):
    run_calls = []
    _set_safe_stdio_transport_environment(monkeypatch)
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
    _set_safe_stdio_transport_environment(monkeypatch)
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
