"""Unit tests for the env-var tool filter (_ToolFilter)."""

import pytest

from garmin_mcp import TOOL_PROFILES, _ToolFilter, _resolve_tool_filters


class FakeApp:
    """Minimal stand-in for FastMCP: records which tools get registered."""

    def __init__(self):
        self.registered = []

    def tool(self, *args, **kwargs):
        explicit = kwargs.get("name") or (
            args[0] if args and isinstance(args[0], str) else None
        )

        def decorator(fn):
            self.registered.append(explicit or fn.__name__)
            return fn

        return decorator

    def run(self):
        return "ran"


def _register(filt, names):
    """Register one no-op tool per name through the filter."""
    for n in names:
        def fn():
            return None

        fn.__name__ = n
        filt.tool()(fn)


def test_no_filter_registers_all():
    app = FakeApp()
    filt = _ToolFilter(app, set(), set())
    _register(filt, ["get_a", "get_b"])
    assert app.registered == ["get_a", "get_b"]


def test_allowlist_only_registers_listed():
    app = FakeApp()
    filt = _ToolFilter(app, {"get_a"}, set())
    _register(filt, ["get_a", "get_b"])
    assert app.registered == ["get_a"]


def test_denylist_skips_listed():
    app = FakeApp()
    filt = _ToolFilter(app, set(), {"get_b"})
    _register(filt, ["get_a", "get_b"])
    assert app.registered == ["get_a"]


def test_allowlist_takes_precedence_over_denylist():
    app = FakeApp()
    filt = _ToolFilter(app, {"get_a"}, {"get_a"})
    _register(filt, ["get_a", "get_b"])
    assert app.registered == ["get_a"]


def test_matching_is_case_insensitive():
    app = FakeApp()
    filt = _ToolFilter(app, {"get_a"}, set())
    _register(filt, ["GET_A"])
    assert app.registered == ["GET_A"]


def test_unknown_filter_names_flags_typos():
    app = FakeApp()
    filt = _ToolFilter(app, {"get_a", "get_typo"}, set())
    _register(filt, ["get_a"])
    assert filt.unknown_filter_names() == ["get_typo"]


def test_explicit_name_kwarg_used_for_matching():
    app = FakeApp()
    filt = _ToolFilter(app, {"real_name"}, set())

    def fn():
        return None

    fn.__name__ = "internal_fn"
    filt.tool(name="real_name")(fn)
    assert app.registered == ["real_name"]
    assert filt.unknown_filter_names() == []


def test_passthrough_to_wrapped_app():
    app = FakeApp()
    filt = _ToolFilter(app, set(), set())
    assert filt.run() == "ran"


def test_ai_coach_profile_registers_selected_workout_tools_only():
    enabled, disabled = _resolve_tool_filters(" ai-Coach ", None, None)

    assert enabled == TOOL_PROFILES["ai-coach"]
    assert disabled == set()
    assert enabled == {
        "get_training_context",
        "analyze_activity",
        "create_workout",
        "get_activities",
        "get_activities_by_date",
        "get_activity",
        "get_workouts",
        "get_workout_by_id",
        "get_scheduled_workouts",
        "schedule_workout",
        "unschedule_workout",
        "delete_workout",
    }
    assert not {
        "upload_workout",
        "upload_workouts",
        "delete_workouts",
        "create_manual_activity",
    } & enabled


def test_explicit_enabled_tools_override_profile_and_disabled_tools():
    enabled, disabled = _resolve_tool_filters(
        "ai-coach", " GET_DEVICES, get_workouts ", "get_workouts"
    )

    assert enabled == {"get_devices", "get_workouts"}
    assert disabled == set()


def test_ai_coach_profile_subtracts_disabled_tools():
    enabled, disabled = _resolve_tool_filters(
        "AI-COACH", None, " GET_WORKOUTS, analyze_activity "
    )

    assert enabled == TOOL_PROFILES["ai-coach"] - {"get_workouts", "analyze_activity"}
    assert disabled == set()


def test_ai_coach_profile_with_all_members_disabled_stays_restrictive():
    enabled, disabled = _resolve_tool_filters(
        "ai-coach",
        None,
        ",".join(TOOL_PROFILES["ai-coach"]),
    )
    app = FakeApp()
    filt = _ToolFilter(app, enabled, disabled, allowlist_active=True)
    _register(filt, ["get_workouts", "create_workout", "upload_workout"])

    assert app.registered == []


def test_profile_filter_warns_for_typo_in_disabled_tools_only():
    enabled, disabled = _resolve_tool_filters(
        "ai-coach", None, "get_workouts, create_workuout"
    )
    app = FakeApp()
    filt = _ToolFilter(
        app,
        enabled,
        disabled,
        allowlist_active=True,
        configured_names={"get_workouts", "create_workuout"},
    )
    _register(filt, ["get_workouts", "create_workout", "upload_workout"])

    assert filt.unknown_filter_names() == ["create_workuout"]


def test_empty_profile_preserves_denylist_behavior():
    enabled, disabled = _resolve_tool_filters(None, None, " GET_DEVICES, get_devices ")

    assert enabled == set()
    assert disabled == {"get_devices"}


def test_unknown_profile_names_are_rejected():
    with pytest.raises(ValueError, match=r"Unknown GARMIN_TOOL_PROFILE.*ai-coach"):
        _resolve_tool_filters("unknown", None, None)
