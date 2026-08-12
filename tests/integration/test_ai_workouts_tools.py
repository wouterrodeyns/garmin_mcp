"""Integration coverage for the AI-friendly workout creation tool."""

import json
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from garmin_mcp import workouts
from garmin_mcp.ai_workouts import configure, create_workout_service, register_tools
from garmin_mcp.ai_workouts import service
from garmin_mcp.ai_workouts import tools


THRESHOLD_STEPS = [
    {"warmup": {"duration": "15m"}},
    {
        "repeat": 4,
        "steps": [
            {"run": {"duration": "6m", "pace": "4:20-4:30/km"}},
            {"recovery": {"duration": "2m"}},
        ],
    },
    {"cooldown": {"duration": "10m"}},
]


@pytest.fixture
def app_with_ai_workouts(mock_garmin_client):
    """FastMCP app configured with the AI workout creation tool."""
    mock_garmin_client.query_garmin_graphql.return_value = {
        "data": {"workoutScheduleSummariesScalar": []}
    }
    workouts.configure(mock_garmin_client)
    configure(mock_garmin_client)
    app = FastMCP("Test AI Workouts")
    return register_tools(app)


def test_create_only_returns_concise_success_payload(mock_garmin_client):
    mock_garmin_client.upload_workout.return_value = {
        "workoutId": 101,
        "workoutName": "Uploaded Easy Run",
    }

    result = create_workout_service(
        mock_garmin_client,
        "Easy Run",
        "running",
        [{"run": {"duration": "30m"}}],
    )

    assert result == {
        "status": "success",
        "workout_id": 101,
        "name": "Uploaded Easy Run",
    }
    mock_garmin_client.upload_workout.assert_called_once()


def test_create_threshold_uploads_prepared_repeat_and_schedules_once(
    mock_garmin_client,
):
    mock_garmin_client.upload_workout.return_value = {"workoutId": 102}
    mock_garmin_client.query_garmin_graphql.return_value = {
        "data": {"workoutScheduleSummariesScalar": []}
    }
    response = MagicMock(status_code=200)
    mock_garmin_client.client.post.return_value = response
    workouts.configure(mock_garmin_client)

    result = create_workout_service(
        mock_garmin_client,
        "Threshold 4x6",
        "running",
        THRESHOLD_STEPS,
        "2026-09-01",
    )

    assert result == {
        "status": "success",
        "workout_id": 102,
        "name": "Threshold 4x6",
        "scheduled_date": "2026-09-01",
    }
    uploaded = mock_garmin_client.upload_workout.call_args.args[0]
    assert uploaded["workoutSegments"][0]["workoutSteps"][1]["type"] == "RepeatGroupDTO"
    pace_step = uploaded["workoutSegments"][0]["workoutSteps"][1]["workoutSteps"][0]
    assert pace_step["targetValueOne"] == pytest.approx(1000 / 270)
    assert pace_step["targetValueTwo"] == pytest.approx(1000 / 260)
    mock_garmin_client.client.post.assert_called_once()


def test_scheduled_creation_uses_injected_client_for_upload_and_schedule():
    client_a = MagicMock()
    client_a.upload_workout.return_value = {"workoutId": 107}
    client_a.query_garmin_graphql.return_value = {
        "data": {"workoutScheduleSummariesScalar": []}
    }
    client_a.client.post.return_value = MagicMock(status_code=200)
    client_b = MagicMock()
    client_b.query_garmin_graphql.return_value = {
        "data": {"workoutScheduleSummariesScalar": []}
    }
    client_b.client.post.return_value = MagicMock(status_code=200)
    workouts.configure(client_b)

    result = create_workout_service(
        client_a,
        "Client Affinity",
        "running",
        [{"run": {"duration": "5m"}}],
        "2026-09-01",
    )

    assert result["status"] == "success"
    client_a.upload_workout.assert_called_once()
    client_a.query_garmin_graphql.assert_called_once()
    client_a.client.post.assert_called_once()
    client_b.query_garmin_graphql.assert_not_called()
    client_b.client.post.assert_not_called()


@pytest.mark.parametrize(
    ("schedule_date", "steps", "message"),
    [
        ("2026-02-30", [{"run": {"duration": "5m"}}], "date"),
        (None, [{"run": {"duration": "5m"}, "extra": {}}], "step"),
    ],
)
def test_invalid_input_returns_error_before_upload(
    mock_garmin_client, schedule_date, steps, message
):
    result = create_workout_service(
        mock_garmin_client, "Invalid", "running", steps, schedule_date
    )

    assert result["status"] == "error"
    assert result["name"] == "Invalid"
    assert message in result["message"].lower()
    mock_garmin_client.upload_workout.assert_not_called()


def test_deeply_nested_repeats_return_error_without_upload(mock_garmin_client):
    steps = [{"run": {"duration": "1s"}}]
    for _ in range(300):
        steps = [{"repeat": 1, "steps": steps}]

    result = create_workout_service(
        mock_garmin_client,
        "Deeply Nested",
        "running",
        steps,
    )

    assert result == {
        "status": "error",
        "name": "Deeply Nested",
        "message": "repeat nesting must not exceed 1",
    }
    mock_garmin_client.upload_workout.assert_not_called()


def test_upload_exception_returns_error_and_never_schedules(mock_garmin_client, monkeypatch):
    mock_garmin_client.upload_workout.side_effect = RuntimeError("upload unavailable")
    schedule = MagicMock()
    monkeypatch.setattr(service, "schedule_workout_for_date", schedule)

    result = create_workout_service(
        mock_garmin_client,
        "Upload failure",
        "running",
        [{"run": {"duration": "5m"}}],
        "2026-09-01",
    )

    assert result == {
        "status": "error",
        "name": "Upload failure",
        "message": "upload unavailable",
    }
    schedule.assert_not_called()


@pytest.mark.parametrize("upload_result", [None, [], {}, {"workoutName": "Missing ID"}])
def test_missing_upload_id_returns_error_and_skips_scheduling(
    mock_garmin_client, monkeypatch, upload_result
):
    mock_garmin_client.upload_workout.return_value = upload_result
    schedule = MagicMock()
    monkeypatch.setattr(service, "schedule_workout_for_date", schedule)

    result = create_workout_service(
        mock_garmin_client,
        "Missing ID",
        "running",
        [{"run": {"duration": "5m"}}],
        "2026-09-01",
    )

    assert result["status"] == "error"
    assert result["name"] == "Missing ID"
    assert "workout_id" in result["message"]
    schedule.assert_not_called()


def test_schedule_failure_preserves_uploaded_id_and_never_deletes(
    mock_garmin_client, monkeypatch
):
    mock_garmin_client.upload_workout.return_value = {"workoutId": 103}
    monkeypatch.setattr(
        service,
        "schedule_workout_for_date",
        lambda *_args, **_kwargs: {"status": "failed", "message": "calendar rejected"},
    )

    result = create_workout_service(
        mock_garmin_client,
        "Schedule failure",
        "running",
        [{"run": {"duration": "5m"}}],
        "2026-09-01",
    )

    assert result == {
        "status": "partial_success",
        "workout_id": 103,
        "name": "Schedule failure",
        "requested_date": "2026-09-01",
        "scheduling_error": "calendar rejected",
    }
    mock_garmin_client.delete_workout.assert_not_called()


def test_schedule_exception_preserves_uploaded_id_and_never_deletes(
    mock_garmin_client, monkeypatch
):
    mock_garmin_client.upload_workout.return_value = {"workoutId": 104}

    def raise_schedule(*_args, **_kwargs):
        raise RuntimeError("schedule offline")

    monkeypatch.setattr(service, "schedule_workout_for_date", raise_schedule)

    result = create_workout_service(
        mock_garmin_client,
        "Schedule exception",
        "running",
        [{"run": {"duration": "5m"}}],
        "2026-09-01",
    )

    assert result == {
        "status": "partial_success",
        "workout_id": 104,
        "name": "Schedule exception",
        "requested_date": "2026-09-01",
        "scheduling_error": "schedule offline",
    }
    mock_garmin_client.delete_workout.assert_not_called()


def test_internal_compiler_exception_is_not_reported_as_user_error(
    mock_garmin_client, monkeypatch
):
    def raise_internal_error(*_args, **_kwargs):
        raise RuntimeError("compiler invariant broken")

    monkeypatch.setattr(service, "compile_workout", raise_internal_error)

    with pytest.raises(RuntimeError, match="compiler invariant broken"):
        create_workout_service(
            mock_garmin_client,
            "Compiler failure",
            "running",
            [{"run": {"duration": "5m"}}],
        )

    mock_garmin_client.upload_workout.assert_not_called()


def test_ai_workouts_configure_does_not_rebind_upstream_workout_client():
    upstream_client = MagicMock(name="upstream_client")
    ai_client = MagicMock(name="ai_client")
    workouts.configure(upstream_client)

    configure(ai_client)

    assert workouts.garmin_client is upstream_client


@pytest.mark.asyncio
async def test_update_workout_has_patch_schema_with_optional_fields_and_strict_id():
    app = FastMCP("AI Workouts")
    configure(object())
    registered = register_tools(app)

    tools_by_name = {tool.name: tool for tool in await registered.list_tools()}

    assert "update_workout" in tools_by_name
    schema = tools_by_name["update_workout"].inputSchema
    assert schema["properties"]["workout_id"] == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
        "title": "Workout Id",
    }
    assert schema["required"] == ["workout_id"]
    assert set(schema["properties"]) == {"workout_id", "name", "sport", "steps"}


@pytest.mark.asyncio
async def test_update_workout_delegates_omitted_and_explicit_patch_arguments(
    monkeypatch: pytest.MonkeyPatch,
):
    client = object()
    app = FastMCP("AI Workouts")
    configure(client)
    register_tools(app)
    observed: list[tuple[object, object, object, object, object]] = []
    service_result = {"status": "success", "workout_id": 42, "name": "Easy"}

    def fake_service(
        received_client: object,
        workout_id: object,
        name: object = None,
        sport: object = None,
        steps: object = None,
    ) -> dict[str, object]:
        observed.append((received_client, workout_id, name, sport, steps))
        return service_result

    monkeypatch.setattr(tools, "update_workout_service", fake_service)

    omitted = await app.call_tool("update_workout", {"workout_id": 42})
    explicit_steps = [{"run": {"duration": "30m"}}]
    explicit = await app.call_tool(
        "update_workout",
        {
            "workout_id": " 42 ",
            "name": "Easy",
            "sport": "running",
            "steps": explicit_steps,
        },
    )

    assert json.loads(omitted[0][0].text) == service_result
    assert json.loads(explicit[0][0].text) == service_result
    assert observed == [
        (client, 42, None, None, None),
        (client, " 42 ", "Easy", "running", explicit_steps),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("workout_id", [True, False, 1.0])
async def test_update_workout_rejects_json_boolean_and_float_ids_before_garmin_calls(
    workout_id: object,
):
    class NoCalls:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected Garmin call: {name}")

    client = NoCalls()
    app = FastMCP("AI Workouts")
    configure(client)
    register_tools(app)

    with pytest.raises(ToolError, match="workout_id"):
        await app.call_tool("update_workout", {"workout_id": workout_id, "name": "Easy"})


@pytest.mark.asyncio
async def test_update_workout_documents_patch_identity_safety_and_retry_boundary():
    app = FastMCP("AI Workouts")
    configure(object())
    register_tools(app)
    tool = next(tool for tool in await app.list_tools() if tool.name == "update_workout")
    description = " ".join(tool.description.lower().split())

    for phrase in (
        "template workout id",
        "not scheduled_workout_id",
        "patch",
        "rename",
        "supported sports",
        "friendly",
        "whole-document",
        "in-place",
        "same id",
        "schedules preserved",
        "never mutates the calendar",
        "read the workout before retrying",
        "uuid",
        "adaptive",
    ):
        assert phrase in description


def test_idempotent_schedule_marks_success_without_extra_details(
    mock_garmin_client, monkeypatch
):
    mock_garmin_client.upload_workout.return_value = {"workoutId": 105}
    monkeypatch.setattr(
        service,
        "schedule_workout_for_date",
        lambda *_args, **_kwargs: {"status": "success", "idempotent": True},
    )

    result = create_workout_service(
        mock_garmin_client,
        "Already Scheduled",
        "running",
        [{"run": {"duration": "5m"}}],
        "2026-09-01",
    )

    assert result == {
        "status": "success",
        "workout_id": 105,
        "name": "Already Scheduled",
        "scheduled_date": "2026-09-01",
        "idempotent": True,
    }


@pytest.mark.asyncio
async def test_mcp_tool_creates_threshold_workout_and_schedules_it(
    app_with_ai_workouts, mock_garmin_client
):
    mock_garmin_client.upload_workout.return_value = {"workoutId": 106}
    mock_garmin_client.client.post.return_value = MagicMock(status_code=200)

    result = await app_with_ai_workouts.call_tool(
        "create_workout",
        {
            "name": "Tool Threshold",
            "sport": "running",
            "steps": THRESHOLD_STEPS,
            "schedule_date": "2026-09-01",
        },
    )

    payload = json.loads(result[0][0].text)
    assert payload == {
        "status": "success",
        "workout_id": 106,
        "name": "Tool Threshold",
        "scheduled_date": "2026-09-01",
    }
    uploaded = mock_garmin_client.upload_workout.call_args.args[0]
    assert uploaded["workoutSegments"][0]["workoutSteps"][1]["type"] == "RepeatGroupDTO"
    mock_garmin_client.client.post.assert_called_once()


@pytest.mark.asyncio
async def test_mcp_tool_returns_bad_input_as_json_error(
    app_with_ai_workouts, mock_garmin_client
):
    result = await app_with_ai_workouts.call_tool(
        "create_workout",
        {
            "name": "Bad Tool Input",
            "sport": "running",
            "steps": [{"run": {"duration": "five"}}],
        },
    )

    payload = json.loads(result[0][0].text)
    assert payload["status"] == "error"
    mock_garmin_client.upload_workout.assert_not_called()
