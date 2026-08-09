# AI Training Context v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact, read-only `get_training_context(days=14)` MCP tool that aggregates bounded Garmin activity, schedule, recovery, and fitness reads into the approved coaching schema.

**Architecture:** Add a fork-owned `ai_training` package. `providers.py` performs bounded reads against `garminconnect==0.3.2`; `service.py` validates, normalizes, aggregates, and applies the stable status contract; `tools.py` exposes one MCP tool. Existing Taxuspt modules remain unchanged except for package registration and the `ai-coach` allowlist entry.

**Tech Stack:** Python 3.10+, `garminconnect==0.3.2`, FastMCP 1.x, pytest/pytest-asyncio, `unittest.mock`, standard-library dataclasses/date/json/math.

---

## File map

- Create `src/garmin_mcp/ai_training/providers.py`: provider result types, activity paging, direct getters, GraphQL validation.
- Create `src/garmin_mcp/ai_training/service.py`: envelope, normalizers, aggregation, fallback dates, status orchestration.
- Create `src/garmin_mcp/ai_training/tools.py`: configured client and MCP registration.
- Create `src/garmin_mcp/ai_training/__init__.py`: lazy configure/register seam.
- Create `tests/unit/ai_training/test_providers.py` and `test_service.py`.
- Create `tests/integration/test_ai_training_tools.py`.
- Modify `src/garmin_mcp/__init__.py`, startup tests, and filter tests atomically.
- Create `docs/ai-training.md` and `tests/unit/test_ai_training_docs.py`.
- Modify `README.md`, `docs/ai-workouts.md`, and its doc tests.

### Task 1: Build bounded Garmin providers

**Files:**
- Create: `src/garmin_mcp/ai_training/providers.py`
- Create: `tests/unit/ai_training/test_providers.py`

- [ ] **Step 1: Write failing paging and GraphQL tests**

Create tests with a scripted `Mock` client. Include these exact assertions:

```python
import json
from unittest.mock import Mock

import pytest
from garminconnect import GarminConnectConnectionError

from garmin_mcp.ai_training.providers import (
    RUNNING_TYPE_KEYS,
    activity_cap,
    get_last_run,
    get_period_activities,
    get_scheduled_workouts,
)


@pytest.mark.parametrize(
    ("days", "expected"),
    [(1, 200), (14, 200), (25, 400), (30, 400), (90, 1000)],
)
def test_activity_cap(days, expected):
    assert activity_cap(days) == expected


def test_period_read_keeps_prior_pages_after_later_failure():
    client = Mock()
    client.garmin_connect_activities = "/activities"
    page = [{"activityType": {"typeKey": "cycling"}}] * 200
    client.connectapi.side_effect = [page, GarminConnectConnectionError("private")]

    result = get_period_activities(client, "2026-07-11", "2026-08-09", 30)

    assert len(result.data) == 200
    assert result.failed is True and result.truncated is True
    assert result.warnings == ({
        "provider": "activities",
        "code": "provider_unavailable",
        "message": "Activity history is incomplete because a later page was unavailable.",
    },)
    assert client.connectapi.call_args_list[0].kwargs["params"] == {
        "startDate": "2026-07-11", "endDate": "2026-08-09",
        "start": "0", "limit": "200", "sortOrder": "desc",
    }
    assert client.connectapi.call_args_list[1].kwargs["params"]["start"] == "200"


def test_last_run_pages_unfiltered_and_stops_at_first_match():
    client = Mock()
    client.garmin_connect_activities = "/activities"
    client.connectapi.side_effect = [
        [{"activityType": {"typeKey": "cycling"}}] * 200,
        [{"activityType": {"typeKey": "trail_running"}, "startTimeLocal": "2026-06-06 07:00:00"}],
    ]

    result = get_last_run(client)

    assert result.data["activityType"]["typeKey"] == "trail_running"
    assert client.connectapi.call_count == 2
    assert "activityType" not in client.connectapi.call_args_list[0].kwargs["params"]
    assert RUNNING_TYPE_KEYS == frozenset({"running", "trail_running", "treadmill_running"})


def test_graphql_null_is_empty_and_json_decode_is_invalid():
    client = Mock()
    client.query_garmin_graphql.side_effect = [
        {"data": {"workoutScheduleSummariesScalar": None}},
        json.JSONDecodeError("secret", "x", 0),
    ]
    empty = get_scheduled_workouts(client, "2026-08-09", "2026-08-15")
    invalid = get_scheduled_workouts(client, "2026-08-09", "2026-08-15")
    assert empty.data == () and empty.failed is False
    assert invalid.warnings == ({
        "provider": "scheduled_workouts",
        "code": "invalid_provider_response",
        "message": "Scheduled workouts returned an invalid response.",
    },)
```

Also test list/`activityList`/`None` roots, invalid roots, first-page failure,
computed-cap truncation, a five-page no-run result with informational
`activities_truncated`, a short no-run result without warning, GraphQL `errors`,
non-dict `data`, scalar wrong type, and generic request failure sanitization.

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/ai_training/test_providers.py -q
```

Expected: `ModuleNotFoundError: No module named 'garmin_mcp.ai_training'`.

- [ ] **Step 3: Implement provider contracts**

Create these definitions and complete the three readers:

```python
from dataclasses import dataclass
import json
import math
from typing import Any

RUNNING_TYPE_KEYS = frozenset({"running", "trail_running", "treadmill_running"})
PAGE_SIZE = 200
MAX_ACTIVITY_RECORDS = 1000

@dataclass(frozen=True)
class ProviderResult:
    data: Any
    failed: bool = False
    truncated: bool = False
    warnings: tuple[dict[str, str], ...] = ()

def activity_cap(days: int) -> int:
    return min(1000, 200 * math.ceil(max(200, days * 10) / 200))

def _warning(provider: str, code: str, message: str) -> dict[str, str]:
    return {"provider": provider, "code": code, "message": message}

def _activity_items(raw: Any) -> tuple[dict[str, Any], ...]:
    if raw is None:
        return ()
    if isinstance(raw, dict):
        raw = raw.get("activityList")
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError("invalid activity collection")
    return tuple(raw)
```

`get_period_activities` pages with `client.connectapi(client.garmin_connect_activities,
params=...)`, `limit=200`, `sortOrder=desc`, and date bounds. Preserve earlier
pages on later failure. `get_last_run` uses the same endpoint without date/type
filters, pages up to 1,000, matches locally, and stops at the first match.
`get_scheduled_workouts` uses the exact `workoutScheduleSummariesScalar` query;
catch `json.JSONDecodeError` as invalid, all other exceptions as unavailable,
and never include exception text.

Add one-line raw delegates: `get_daily_stats`, `get_sleep`, `get_hrv`,
`get_training_readiness`, and `get_training_status`.

- [ ] **Step 4: Run GREEN**

Run the Task 1 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/garmin_mcp/ai_training/providers.py tests/unit/ai_training/test_providers.py
git commit -m "feat(ai-training): add bounded Garmin providers"
```

### Task 2: Add the stable envelope and activity aggregation

**Files:**
- Create: `src/garmin_mcp/ai_training/service.py`
- Create: `tests/unit/ai_training/test_service.py`

- [ ] **Step 1: Write failing envelope/aggregation tests**

```python
from datetime import date
import pytest
from garmin_mcp.ai_training import providers
from garmin_mcp.ai_training.service import get_training_context_service

TODAY = date(2026, 8, 9)

@pytest.mark.parametrize("days", [True, False, 0, 91, 14.0, "14"])
def test_invalid_days_is_stable_and_read_free(days, monkeypatch):
    monkeypatch.setattr(providers, "get_period_activities", lambda *_a, **_k: pytest.fail("read called"))
    result = get_training_context_service(object(), days=days, today=TODAY)
    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_days"
    assert result["period"] == {"days": None, "start_date": None, "end_date": "2026-08-09"}
    assert result["schedule_period"] == {"start_date": "2026-08-09", "end_date": "2026-08-15"}
    assert all(value is False for value in result["availability"].values())

def test_raw_first_activity_aggregation(monkeypatch):
    activities = tuple({
        "activityType": {"typeKey": kind},
        "startTimeLocal": f"2026-08-0{day} 07:00:00",
        "duration": 1838, "distance": distance,
        "averageHR": 140, "maxHR": 160, "averageSpeed": 3.0,
    } for kind, day, distance in [
        ("running", 8, 5000), ("trail_running", 7, 6000),
        ("treadmill_running", 6, 0),
    ])
    monkeypatch.setattr(providers, "get_period_activities", lambda *_a, **_k: providers.ProviderResult(activities))
    monkeypatch.setattr(providers, "get_scheduled_workouts", lambda *_a, **_k: providers.ProviderResult(()))
    monkeypatch.setattr(providers, "get_last_run", lambda *_a, **_k: providers.ProviderResult(activities[0]))
    for name in ("get_daily_stats", "get_sleep", "get_hrv", "get_training_readiness", "get_training_status"):
        monkeypatch.setattr(providers, name, lambda *_a, **_k: {})
    result = get_training_context_service(object(), today=TODAY)
    assert result["training"]["total_training_minutes"] == 91.9
    assert result["training"]["running_sessions"] == 3
    assert result["training"]["running_distance_km"] == 11.0
    assert result["training"]["days_since_last_run"] == 1
    assert result["recent_activities"][0]["duration_minutes"] == 30.6
```

Add tests for days 1/90, empty activities, missing/zero running distance,
same-day/future/malformed last run, unknown sports, newest-first local sorting,
20-item reduction, schedule ID reduction, and warning propagation.

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/ai_training/test_service.py -q
```

- [ ] **Step 3: Implement envelope and activity helpers**

Define `AVAILABILITY_KEYS` exactly as the 13 spec keys. Implement
`_base_result(days, today)` with every top-level section and null/default shown
in the spec. Use this public signature:

```python
def get_training_context_service(
    client: Any, days: int = 14, today: date | None = None
) -> dict[str, Any]:
    resolved_today = today or date.today()
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90:
        result = _base_result(None, resolved_today)
        result.update(status="error", error={
            "code": "invalid_days",
            "message": "days must be an integer from 1 through 90",
        })
        return result
    return _build_context(client, days, resolved_today)
```

Implement `_finite_number`, `_activity_date`, `_normalize_activity`,
`_populate_activity_training`, and `_reduce_scheduled_workouts`. Sum raw seconds
and metres before rounding, classify only `RUNNING_TYPE_KEYS`, sort locally,
exclude activity IDs, and retain both scheduled/workout IDs.

- [ ] **Step 4: Run Task 1 and Task 2 tests**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/ai_training/test_providers.py tests/unit/ai_training/test_service.py -q
```

Expected: both modules pass.

- [ ] **Step 5: Commit**

```bash
git add src/garmin_mcp/ai_training/service.py tests/unit/ai_training/test_service.py
git commit -m "feat(ai-training): aggregate compact activity context"
```

### Task 3: Normalize recovery and fitness data

**Files:**
- Modify: `src/garmin_mcp/ai_training/service.py`
- Modify: `tests/unit/ai_training/test_service.py`

- [ ] **Step 1: Add failing exact-path tests**

Use these payloads and assert the exact outputs:

```python
SLEEP = {"dailySleepDTO": {"calendarDate": "2026-08-08", "sleepTimeSeconds": 27360, "sleepScores": {"overall": {"value": 82, "qualifierKey": "GOOD"}}}}
HRV = {"hrvSummary": {"calendarDate": "2026-08-08", "lastNightAvg": 54, "weeklyAvg": 52, "status": "BALANCED", "baseline": {"balancedLow": 46, "balancedUpper": 62}}}
READINESS = {"readinessScore": 72, "readinessLevel": "HIGH", "recoveryTime": 240}
STATUS = {
    "primaryTrainingDevice": "watch-2",
    "mostRecentTrainingStatus": {"latestTrainingStatusData": {
        "watch-1": {"trainingStatus": "RECOVERY"},
        "watch-2": {"calendarDate": "2026-08-09", "trainingStatus": "MAINTAINING", "trainingStatusFeedbackPhrase": "ON_TRACK", "fitnessTrend": "UP", "acuteTrainingLoadDTO": {"dailyTrainingLoadAcute": 247, "dailyTrainingLoadChronic": 193, "dailyAcuteChronicWorkloadRatio": 1.14, "acwrStatus": "OPTIMAL"}},
    }},
    "mostRecentTrainingLoadBalance": {"metricsTrainingLoadBalanceDTOMap": {
        "watch-2": {"monthlyLoadAerobicLow": 300, "monthlyLoadAerobicHigh": 210, "monthlyLoadAnaerobic": 90, "trainingBalanceFeedbackPhrase": "BALANCED"}
    }},
    "mostRecentVO2Max": {"generic": {"vo2MaxValue": 51}, "cycling": {"vo2MaxValue": 53}},
}

@pytest.fixture
def configured_core(monkeypatch):
    monkeypatch.setattr(providers, "get_period_activities", lambda *_a, **_k: providers.ProviderResult(()))
    monkeypatch.setattr(providers, "get_scheduled_workouts", lambda *_a, **_k: providers.ProviderResult(()))
    monkeypatch.setattr(providers, "get_last_run", lambda *_a, **_k: providers.ProviderResult(None))
    monkeypatch.setattr(providers, "get_daily_stats", lambda *_a, **_k: {})
    monkeypatch.setattr(providers, "get_sleep", lambda *_a, **_k: {})
    monkeypatch.setattr(providers, "get_hrv", lambda *_a, **_k: {})
    monkeypatch.setattr(providers, "get_training_readiness", lambda *_a, **_k: {})
    monkeypatch.setattr(providers, "get_training_status", lambda *_a, **_k: {})
```

Tests must prove: today-empty/yesterday-data fallback exactly once; Garmin date
or request-date provenance; nested sleep score/qualifier; HRV `balancedUpper`;
all readiness alias pairs; recovery minutes/60 only when present; independent
daily-stats HR/Body Battery dates and availability; primary-device selection;
separate load-focus map; generic/cycling VO2; and absent ACWR staying null even
when acute/chronic loads are present.

Include this concrete fallback assertion:

```python
def test_overnight_metrics_fallback_once(monkeypatch, configured_core):
    sleep = Mock(side_effect=[{}, SLEEP])
    hrv = Mock(side_effect=[None, HRV])
    readiness = Mock(side_effect=[[], READINESS])
    monkeypatch.setattr(providers, "get_sleep", sleep)
    monkeypatch.setattr(providers, "get_hrv", hrv)
    monkeypatch.setattr(providers, "get_training_readiness", readiness)
    result = get_training_context_service(object(), today=TODAY)
    assert result["sleep"] == {"date": "2026-08-08", "duration_hours": 7.6, "score": 82, "score_qualifier": "GOOD"}
    assert result["hrv"]["baseline_balanced_upper_ms"] == 62
    assert result["recovery"]["readiness_date"] == "2026-08-08"
    assert result["recovery"]["recovery_hours"] == 4.0
    assert sleep.call_count == hrv.call_count == readiness.call_count == 2
```

- [ ] **Step 2: Run new node IDs and confirm RED**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/ai_training/test_service.py -k "overnight or sleep or hrv or readiness or daily_stats or training_status or acwr" -q
```

Expected: assertions fail because recovery/fitness values are still null.

- [ ] **Step 3: Implement normalizers**

Add `_normalize_sleep`, `_normalize_hrv`, `_normalize_readiness`,
`_normalize_daily_stats`, `_select_device`, and `_normalize_training_status`.
Use this fallback helper only for sleep/HRV/readiness:

```python
def _read_overnight(getter, client: Any, today: date, is_empty):
    value = getter(client, today.isoformat())
    if not is_empty(value):
        return value, today
    previous = today - timedelta(days=1)
    return getter(client, previous.isoformat()), previous
```

Do not retry exceptions or malformed non-empty payloads. Never derive ACWR.

- [ ] **Step 4: Run all service tests and confirm GREEN**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/ai_training/test_service.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/garmin_mcp/ai_training/service.py tests/unit/ai_training/test_service.py
git commit -m "feat(ai-training): normalize recovery and fitness metrics"
```

### Task 4: Implement decision-table orchestration

**Files:**
- Modify: `src/garmin_mcp/ai_training/service.py`
- Modify: `tests/unit/ai_training/test_service.py`

- [ ] **Step 1: Add failing status/error tests**

```python
def test_both_core_failures_stop_optional_reads(monkeypatch):
    monkeypatch.setattr(providers, "get_period_activities", lambda *_a, **_k: providers.ProviderResult((), failed=True, warnings=({"provider": "activities", "code": "provider_unavailable", "message": "Activities are unavailable."},)))
    monkeypatch.setattr(providers, "get_scheduled_workouts", lambda *_a, **_k: providers.ProviderResult((), failed=True, warnings=({"provider": "scheduled_workouts", "code": "provider_unavailable", "message": "Scheduled workouts are unavailable."},)))
    optional = Mock(side_effect=AssertionError("optional read called"))
    monkeypatch.setattr(providers, "get_last_run", optional)
    monkeypatch.setattr(providers, "get_daily_stats", optional)
    result = get_training_context_service(object(), today=TODAY)
    assert result["status"] == "error"
    assert result["error"]["code"] == "context_unavailable"
    assert [warning["provider"] for warning in result["warnings"]] == ["activities", "scheduled_workouts"]
    optional.assert_not_called()

@pytest.mark.parametrize("exc_type", [GarminConnectAuthenticationError, GarminConnectConnectionError])
def test_daily_stats_failures_are_isolated(monkeypatch, configured_core, exc_type):
    monkeypatch.setattr(providers, "get_daily_stats", Mock(side_effect=exc_type("private")))
    result = get_training_context_service(object(), today=TODAY)
    assert result["status"] == "partial_success"
    assert result["warnings"][-1] == {"provider": "daily_stats", "code": "provider_unavailable", "message": "Daily statistics are unavailable."}
    assert "private" not in str(result)
```

Add every decision-table row: one/both core success, optional absence, optional
invalid response, informational truncation staying success, period partial pages
causing partial success, missing client, and stable sanitized errors.

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/ai_training/test_service.py -k "core or status or failure or unavailable or truncation" -q
```

- [ ] **Step 3: Implement exact execution order**

```python
period = providers.get_period_activities(client, start, end, days)
schedule = providers.get_scheduled_workouts(client, schedule_start, schedule_end)
_merge_core(result, period, schedule)
if period.failed and schedule.failed:
    result["status"] = "error"
    result["error"] = {
        "code": "context_unavailable",
        "message": "Core Garmin context is unavailable. Re-run garmin-mcp-auth if your session expired; otherwise retry later.",
    }
    return result
# Only now call last_run, daily_stats, sleep, hrv, readiness, training_status.
```

Track provider failures separately from informational `activities_truncated`.
Catch optional exceptions with stable provider messages; never use `str(exc)`.

- [ ] **Step 4: Run all `ai_training` unit tests**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/ai_training -q
```

- [ ] **Step 5: Commit**

```bash
git add src/garmin_mcp/ai_training/service.py tests/unit/ai_training/test_service.py
git commit -m "feat(ai-training): add partial context failure semantics"
```

### Task 5: Expose the MCP tool and prove read-only behavior

**Files:**
- Create: `src/garmin_mcp/ai_training/tools.py`
- Create: `src/garmin_mcp/ai_training/__init__.py`
- Create: `tests/integration/test_ai_training_tools.py`

- [ ] **Step 1: Write failing FastMCP tests**

Register the package on a real `FastMCP`, call with omitted `days` and with 30,
parse JSON text, and assert the compact keys. Use a strict client where
`upload_workout`, `schedule_workout`, `delete_workout`, `post`, `put`, and
`delete` are mocks that raise `AssertionError`; assert none are called.

```python
@pytest.mark.asyncio
async def test_get_training_context_has_compact_read_only_shape(monkeypatch):
    client = complete_read_client()
    writes = {}
    for name in ("upload_workout", "schedule_workout", "delete_workout", "post", "put", "delete"):
        writes[name] = Mock(side_effect=AssertionError(f"write called: {name}"))
        setattr(client, name, writes[name])
    monkeypatch.setattr(service, "date", FixedDate)
    app = FastMCP("test")
    ai_training.configure(client)
    ai_training.register_tools(app)
    content = await app.call_tool("get_training_context", {"days": 14})
    payload = json.loads(content[0].text)
    assert payload["period"]["days"] == 14
    assert set(payload) == {"status", "error", "period", "schedule_period", "availability", "training", "recent_activities", "recovery", "sleep", "hrv", "heart_rate", "fitness", "scheduled_workouts", "warnings"}
    for write in writes.values():
        write.assert_not_called()
```

Define `FixedDate.today()` to return `date(2026, 8, 9)` and
`complete_read_client()` with only the eight documented read methods.

```python
class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 8, 9)

def complete_read_client():
    client = Mock()
    client.garmin_connect_activities = "/activities"
    client.connectapi.return_value = []
    client.query_garmin_graphql.return_value = {"data": {"workoutScheduleSummariesScalar": []}}
    client.get_stats.return_value = {}
    client.get_sleep_data.return_value = {}
    client.get_hrv_data.return_value = {}
    client.get_morning_training_readiness.return_value = {}
    client.get_training_status.return_value = {}
    return client
```

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/integration/test_ai_training_tools.py -q
```

Expected: import or registration fails because `tools.py`/`__init__.py` do not
exist yet.

- [ ] **Step 3: Implement tools and package seam**

```python
# tools.py
garmin_client: Any = None

def configure(client: Any) -> None:
    global garmin_client
    garmin_client = client

def register_tools(app: Any) -> Any:
    @app.tool()
    async def get_training_context(days: int = 14) -> str:
        """Return a compact read-only Garmin coaching snapshot.

        days is an inclusive retrospective lookback from 1 through 90.
        Scheduled workouts always cover today through the following six days.
        Optional metrics may be null; isolated failures return warnings.
        """
        return json.dumps(get_training_context_service(garmin_client, days), indent=2)
    return app
```

Make `__init__.py` lazily configure/register like `ai_workouts.__init__` and
export `get_training_context_service`.

- [ ] **Step 4: Run unit plus integration tests**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/ai_training tests/integration/test_ai_training_tools.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/garmin_mcp/ai_training tests/integration/test_ai_training_tools.py
git commit -m "feat(ai-training): expose compact training context tool"
```

### Task 6: Wire startup and `ai-coach` atomically

**Files:**
- Modify: `src/garmin_mcp/__init__.py`
- Modify: `tests/unit/test_server_startup.py`
- Modify: `tests/unit/test_tool_filter.py`

- [ ] **Step 1: Add failing tests**

Require `get_training_context` in `TOOL_PROFILES["ai-coach"]`. Add this startup
test and retain the exact-profile registration assertion:

```python
def test_main_configures_and_registers_ai_training(monkeypatch):
    configured, registered = [], []
    original_configure = garmin_mcp.ai_training.configure
    original_register = garmin_mcp.ai_training.register_tools
    monkeypatch.delenv("GARMIN_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("GARMIN_MCP_HOST", raising=False)
    monkeypatch.delenv("GARMIN_MCP_PORT", raising=False)
    _clear_tool_filter_environment(monkeypatch)
    monkeypatch.setattr(garmin_mcp, "init_api", lambda _email, _password: Mock())
    monkeypatch.setattr(garmin_mcp.ai_training, "configure", lambda client: (configured.append(client), original_configure(client))[1])
    monkeypatch.setattr(garmin_mcp.ai_training, "register_tools", lambda app: (registered.append(app), original_register(app))[1])
    monkeypatch.setattr(FastMCP, "run", lambda self, **_kwargs: None)
    garmin_mcp.main()
    assert len(configured) == len(registered) == 1
```

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/test_server_startup.py tests/unit/test_tool_filter.py -q
```

Expected: `ai_training` is not imported/registered and the profile assertion
does not contain `get_training_context`.

- [ ] **Step 3: Add all integration points in one edit**

Import `ai_training`; add `"get_training_context"` to the profile; configure it
immediately after `ai_workouts`; register it immediately after `ai_workouts`.
Do not change filter precedence or default full registration.

- [ ] **Step 4: Run GREEN**

Run the Step 2 command. Expected: all startup/filter tests pass.

- [ ] **Step 5: Commit atomically**

```bash
git add src/garmin_mcp/__init__.py tests/unit/test_server_startup.py tests/unit/test_tool_filter.py
git commit -m "feat(server): add training context to ai-coach profile"
```

### Task 7: Document and pin the contract

**Files:**
- Create: `docs/ai-training.md`
- Create: `tests/unit/test_ai_training_docs.py`
- Modify: `README.md`
- Modify: `docs/ai-workouts.md`
- Modify: `tests/unit/test_ai_workouts_docs.py`

- [ ] **Step 1: Write failing documentation tests**

```python
def test_docs_pin_bounds_windows_and_statuses():
    lower = DOCS.lower()
    for text in (
        "get_training_context", "1 through 90", "inclusive retrospective",
        "today through the following six days", "read-only", "partial_success",
        "provider_unavailable", "invalid_provider_response",
        "activities_truncated", "garminconnect==0.3.2",
    ):
        assert text in lower

def test_docs_pin_workflow_and_sport_translation():
    lower = DOCS.lower()
    assert "get_training_context" in lower and "create_workout" in lower
    assert "trail_running" in lower and "create_workout.sport" in lower
```

Also pin fallback dates, null/availability, fixed schedule window, request caps,
read-only behavior, 11 profile tools, and the conversational two-tool workflow.
Remove the old assertion that training context is deferred.

- [ ] **Step 2: Run RED**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/test_ai_training_docs.py tests/unit/test_ai_workouts_docs.py -q
```

Expected: the new documentation file is absent and the old profile/deferred
assertions fail.

- [ ] **Step 3: Write documentation**

Document every item pinned above plus metric groups and device/account
variability. Update README with both flagship tools. Update `docs/ai-workouts.md`
from 10 to 11 tools and link the shipped context docs; leave move/update deferred.

- [ ] **Step 4: Run documentation tests**

Run the Step 2 command. Expected: both documentation modules pass.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ai-training.md docs/ai-workouts.md tests/unit/test_ai_training_docs.py tests/unit/test_ai_workouts_docs.py
git commit -m "docs(ai-training): document coaching context workflow"
```

### Task 8: Verify and open the draft PR

**Files:**
- No planned source changes.

- [ ] **Step 1: Run focused tests**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest tests/unit/ai_training tests/integration/test_ai_training_tools.py tests/unit/test_server_startup.py tests/unit/test_tool_filter.py tests/unit/test_ai_training_docs.py tests/unit/test_ai_workouts_docs.py -q
```

- [ ] **Step 2: Run the complete offline suite**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-uv-cache uv run pytest -m "not e2e"
```

- [ ] **Step 3: Inspect branch quality/scope**

```bash
git diff --check main...HEAD
git status --short
git log --oneline main..HEAD
git diff --stat main...HEAD
```

Expected: clean checks/tree, no live Garmin requirement, and no upstream auth or
generic Garmin refactor.

- [ ] **Step 4: Run two-stage review**

Dispatch a fresh spec-compliance reviewer, then a fresh code-quality reviewer.
Apply only verified findings and rerun focused/full suites.

- [ ] **Step 5: Push and create the draft PR**

```bash
git push -u origin feat/ai-training-context-v1
gh pr create --draft --base main --head feat/ai-training-context-v1 --title "feat: add compact AI training context" --body "Adds a read-only get_training_context tool, bounded direct Garmin providers, compact coaching normalization, partial-provider failure semantics, ai-coach profile integration, and offline tests/docs."
```

Expected: a draft PR URL targeting `main`. Do not merge it.
