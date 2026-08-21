"""Public package-boundary contracts for the AI target-events package."""

from __future__ import annotations

import importlib

from garmin_mcp import ai_events


def test_package_exports_only_lazy_runtime_entry_points() -> None:
    assert ai_events.__all__ == ["configure", "register_tools"]
    assert not hasattr(ai_events, "DEFAULT_LOOKAHEAD_DAYS")
    assert not hasattr(ai_events, "MAX_LOOKAHEAD_DAYS")
    assert not hasattr(ai_events, "get_target_events_service")


def test_package_keeps_submodule_import_usability() -> None:
    service = importlib.import_module("garmin_mcp.ai_events.service")
    providers = importlib.import_module("garmin_mcp.ai_events.providers")
    tools = importlib.import_module("garmin_mcp.ai_events.tools")

    assert service.__name__ == "garmin_mcp.ai_events.service"
    assert providers.__name__ == "garmin_mcp.ai_events.providers"
    assert tools.__name__ == "garmin_mcp.ai_events.tools"
