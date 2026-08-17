# AI Sleep Trend V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact, read-only `get_sleep_trend(days=7)` MCP tool that returns recent normalized nightly sleep facts, visible gaps, and denominator-aware aggregates.

**Architecture:** Add a focused `ai_training.sleep` module for strict Garmin sleep normalization and bounded sequential aggregation. Reuse the existing `ai_training.providers.get_sleep` access path and adapt `get_training_context` to the shared normalizer without changing its public response. Register the new tool and the exact 16-tool `ai-coach` profile atomically, then pin the public contract in docs and offline tests.

**Tech Stack:** Python 3.12+, FastMCP, Pydantic strict types, pinned `garminconnect`, pytest, `uv`, GitHub Actions.

---

## File map

| File | Responsibility |
|---|---|
| `src/garmin_mcp/ai_training/sleep.py` | Strict single-night facts, stable projection, multi-night service, aggregation, errors/warnings |
| `src/garmin_mcp/ai_training/providers.py` | Narrow expected-Garmin-exception wrapper around the existing sleep read |
| `src/garmin_mcp/ai_training/service.py` | Preserve training-context sleep output through the shared normalizer |
| `src/garmin_mcp/ai_training/tools.py` | FastMCP adapter and AI-facing guardrail description |
| `src/garmin_mcp/ai_training/__init__.py` | Export sleep constants/service |
| `src/garmin_mcp/__init__.py` | Add the tool to `ai-coach` |
| `tests/unit/ai_training/test_sleep.py` | Strict normalization, service, aggregation, status, adversarial inputs |
| `tests/unit/ai_training/test_providers.py` | Sleep provider boundary and exception scope |
| `tests/unit/ai_training/test_service.py` | Training-context compatibility through shared normalization |
| `tests/integration/test_ai_sleep_trend_tools.py` | Real FastMCP shape and read-only client harness |
| `tests/unit/test_tool_filter.py` | Exact 16-tool profile |
| `tests/unit/test_server_startup.py` | Actual registration equality and filter behavior |
| `docs/ai-sleep-trend.md` | Public sleep-trend contract and workflow |
| `.gitignore` | Track the new public guide |
| `README.md` | High-level role, profile list, and docs link |
| `docs/ai-training.md` | Snapshot-versus-trend guidance |
| `tests/unit/test_ai_sleep_trend_docs.py` | Guide/schema/profile pinning |
| Existing `tests/unit/test_*docs.py` files | Update hard-coded profile membership/count from 15 to 16 |

### Task 1: Add the narrow sleep provider boundary

**Files:**
- Modify: `src/garmin_mcp/ai_training/providers.py`
- Modify: `tests/unit/ai_training/test_providers.py`

- [ ] **Step 1: Write failing provider tests**

Add imports for `GarminConnectAuthenticationError`,
`GarminConnectConnectionError`, and `GarminConnectTooManyRequestsError`, then
pin one successful result and the exact expected exception boundary:

```python
@pytest.mark.parametrize(
    "exception",
    [
        GarminConnectAuthenticationError("private auth detail"),
        GarminConnectConnectionError("private connection detail"),
        GarminConnectTooManyRequestsError("private rate detail"),
    ],
)
def test_get_sleep_night_normalizes_expected_garmin_failures(exception):
    client = Mock()
    client.get_sleep_data.side_effect = exception

    result = get_sleep_night(client, "2026-08-17")

    assert result == ProviderResult(data=None, failed=True)
    client.get_sleep_data.assert_called_once_with("2026-08-17")
    assert "private" not in repr(result)


def test_get_sleep_night_returns_raw_data_without_copying_or_interpreting():
    raw = {"dailySleepDTO": {"calendarDate": "2026-08-17"}}
    client = Mock()
    client.get_sleep_data.return_value = raw

    result = get_sleep_night(client, "2026-08-17")

    assert result == ProviderResult(data=raw)
    assert result.data is raw


def test_get_sleep_night_does_not_hide_internal_or_test_double_failures():
    client = Mock()
    client.get_sleep_data.side_effect = AssertionError("forbidden read")

    with pytest.raises(AssertionError, match="forbidden read"):
        get_sleep_night(client, "2026-08-17")
```

- [ ] **Step 2: Run the tests and prove RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/ai_training/test_providers.py -k get_sleep_night
```

Expected: collection failure because `get_sleep_night` does not exist.

- [ ] **Step 3: Implement the provider wrapper**

Add the exact expected exception imports and delegate through the existing
`get_sleep` function:

```python
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)


_SLEEP_PROVIDER_EXCEPTIONS = (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)


def get_sleep_night(client: Any, date: str) -> ProviderResult:
    """Fetch one sleep DTO while preserving a narrow exception boundary."""
    try:
        return ProviderResult(data=get_sleep(client, date))
    except _SLEEP_PROVIDER_EXCEPTIONS:
        return ProviderResult(data=None, failed=True)
```

Do not catch `Exception`, `AssertionError`, normalizer failures, or local
programming defects.

- [ ] **Step 4: Run the focused provider suite**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/ai_training/test_providers.py
```

Expected: all provider tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/garmin_mcp/ai_training/providers.py tests/unit/ai_training/test_providers.py
git commit -m "feat(ai-training): add sleep provider boundary"
```

### Task 2: Build strict single-night normalization

**Files:**
- Create: `src/garmin_mcp/ai_training/sleep.py`
- Create: `tests/unit/ai_training/test_sleep.py`

- [ ] **Step 1: Add RED tests for the exact complete-night facts**

Create a canonical DTO fixture containing every supported field and assert the
raw normalized facts, not rounded public display values:

```python
from dataclasses import replace


def complete_sleep_payload(date_text="2026-08-17"):
    return {
        "dailySleepDTO": {
            "calendarDate": date_text,
            "sleepTimeSeconds": 26641,
            "napTimeSeconds": 900,
            "deepSleepSeconds": 5281,
            "lightSleepSeconds": 15061,
            "remSleepSeconds": 6301,
            "awakeSleepSeconds": 1201,
            "restingHeartRate": 44,
            "avgSleepStress": 14,
            "awakeCount": 3,
            "restlessMomentsCount": 12,
            "sleepScores": {
                "overall": {"value": 82, "qualifierKey": " GOOD "}
            },
        },
        "avgOvernightHrv": 94,
        "wellnessSpO2SleepSummaryDTO": {
            "calendarDate": date_text,
            "averageSpo2": 96,
            "lowestSpo2": 93,
        },
    }


def normalized_facts(**changes):
    facts = normalize_sleep_night(complete_sleep_payload(), "2026-08-17")
    assert facts is not None
    return replace(facts, **changes)


def test_normalize_sleep_night_copies_every_supported_raw_fact():
    facts = normalize_sleep_night(complete_sleep_payload(), "2026-08-17")

    assert facts == SleepNightFacts(
        date="2026-08-17",
        sleep_seconds=26641,
        nap_seconds=900,
        score=82,
        score_qualifier="GOOD",
        deep_seconds=5281,
        light_seconds=15061,
        rem_seconds=6301,
        awake_seconds=1201,
        resting_hr_bpm=44,
        overnight_hrv_ms=94,
        average_sleep_stress=14,
        awake_count=3,
        restless_moments_count=12,
        average_spo2_percent=96,
        lowest_spo2_percent=93,
    )
```

Also parametrize empty responses (`None`, exact `[]`, exact `{}`, absent/empty
supported subtrees) to return `None`.

- [ ] **Step 2: Add RED malformed/adversarial tests**

Pin all safety ranges at accepted and rejected boundaries. Include NaN and
infinity, Boolean numerics, numeric strings, mismatched calendar dates,
non-string dictionary keys, oversized qualifier text, and exact hostile
subclasses:

```python
class ExplodingDict(dict):
    def __bool__(self):
        raise RuntimeError("token=truthiness-private")

    def get(self, key, default=None):
        raise RuntimeError("token=get-private")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("dailySleepDTO", "sleepTimeSeconds"), float("nan")),
        (("dailySleepDTO", "sleepScores", "overall", "value"), True),
        (("dailySleepDTO", "restingHeartRate"), 301),
        (("dailySleepDTO", "awakeCount"), 1.5),
        (("avgOvernightHrv",), 1001),
        (("wellnessSpO2SleepSummaryDTO", "averageSpo2"), 101),
    ],
)
def test_normalize_sleep_night_rejects_unsafe_supported_values(path, value):
    payload = complete_sleep_payload()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(payload, "2026-08-17")


def test_normalize_sleep_night_rejects_hostile_container_without_protocol_calls():
    with pytest.raises(InvalidSleepResponse):
        normalize_sleep_night(ExplodingDict(), "2026-08-17")
```

- [ ] **Step 3: Run the normalizer tests and prove RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/ai_training/test_sleep.py -k normalize
```

Expected: import failure because `ai_training.sleep` does not exist.

- [ ] **Step 4: Implement immutable facts and strict scalar helpers**

Create `sleep.py` with these public constants/types and exact-type helpers:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math
from typing import Any

from .providers import get_sleep_night

DEFAULT_SLEEP_DAYS = 7
MAX_SLEEP_DAYS = 30
MAX_SLEEP_TEXT_LENGTH = 64


class InvalidSleepResponse(ValueError):
    """The external sleep DTO does not match the bounded v1 contract."""


@dataclass(frozen=True, slots=True)
class SleepNightFacts:
    date: str
    sleep_seconds: int | float | None
    nap_seconds: int | float | None
    score: int | float | None
    score_qualifier: str | None
    deep_seconds: int | float | None
    light_seconds: int | float | None
    rem_seconds: int | float | None
    awake_seconds: int | float | None
    resting_hr_bpm: int | float | None
    overnight_hrv_ms: int | float | None
    average_sleep_stress: int | float | None
    awake_count: int | None
    restless_moments_count: int | None
    average_spo2_percent: int | float | None
    lowest_spo2_percent: int | float | None


def _object(value: Any, *, optional: bool = False) -> dict[str, Any]:
    if value is None and optional:
        return {}
    if type(value) is not dict:
        raise InvalidSleepResponse
    if any(type(key) is not str for key in value):
        raise InvalidSleepResponse
    return value


def _number(value: Any, low: float, high: float) -> int | float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise InvalidSleepResponse
    if not low <= value <= high:
        raise InvalidSleepResponse
    return value


def _count(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 10_000:
        raise InvalidSleepResponse
    return value


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if type(value) is not str or len(value) > MAX_SLEEP_TEXT_LENGTH:
        raise InvalidSleepResponse
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_SLEEP_TEXT_LENGTH:
        raise InvalidSleepResponse
    return normalized
```

Check raw string length before trimming so an attacker cannot send an unbounded
whitespace prefix.

- [ ] **Step 5: Implement the strict normalizer**

Implement `normalize_sleep_night(raw, requested_date)` using only exact built-in
containers. Its construction must match this field extraction:

```python
def normalize_sleep_night(
    raw: Any, requested_date: str | None
) -> SleepNightFacts | None:
    if raw is None:
        return None
    if type(raw) is list:
        if len(raw) == 0:
            return None
        raise InvalidSleepResponse
    if type(raw) is not dict:
        raise InvalidSleepResponse
    if len(raw) == 0:
        return None

    root = _object(raw)
    daily = _object(root.get("dailySleepDTO"), optional=True)
    scores = _object(daily.get("sleepScores"), optional=True)
    overall = _object(scores.get("overall"), optional=True)
    spo2 = _object(root.get("wellnessSpO2SleepSummaryDTO"), optional=True)

    source_dates = [
        value
        for value in (daily.get("calendarDate"), spo2.get("calendarDate"))
        if value is not None
    ]
    if any(type(value) is not str for value in source_dates):
        raise InvalidSleepResponse
    if requested_date is not None and any(value != requested_date for value in source_dates):
        raise InvalidSleepResponse
    effective_date = requested_date or (source_dates[0] if source_dates else None)
    if effective_date is None:
        raise InvalidSleepResponse

    facts = SleepNightFacts(
        date=effective_date,
        sleep_seconds=_number(daily.get("sleepTimeSeconds"), 0, 86_400),
        nap_seconds=_number(daily.get("napTimeSeconds"), 0, 86_400),
        score=_number(overall.get("value"), 0, 100),
        score_qualifier=_text(overall.get("qualifierKey")),
        deep_seconds=_number(daily.get("deepSleepSeconds"), 0, 86_400),
        light_seconds=_number(daily.get("lightSleepSeconds"), 0, 86_400),
        rem_seconds=_number(daily.get("remSleepSeconds"), 0, 86_400),
        awake_seconds=_number(daily.get("awakeSleepSeconds"), 0, 86_400),
        resting_hr_bpm=_number(daily.get("restingHeartRate"), 1, 300),
        overnight_hrv_ms=_number(root.get("avgOvernightHrv"), 1, 1000),
        average_sleep_stress=_number(daily.get("avgSleepStress"), 0, 100),
        awake_count=_count(daily.get("awakeCount")),
        restless_moments_count=_count(daily.get("restlessMomentsCount")),
        average_spo2_percent=_number(spo2.get("averageSpo2"), 0, 100),
        lowest_spo2_percent=_number(spo2.get("lowestSpo2"), 0, 100),
    )
    metric_values = tuple(getattr(facts, field) for field in facts.__dataclass_fields__ if field != "date")
    return facts if any(value is not None for value in metric_values) else None
```

Keep line wrapping project-compliant and add an explicit check that two present
source calendar dates agree even when `requested_date` is `None`.

- [ ] **Step 6: Run Task 2 tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/ai_training/test_sleep.py -k normalize
```

Expected: all normalizer tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/garmin_mcp/ai_training/sleep.py tests/unit/ai_training/test_sleep.py
git commit -m "feat(ai-training): normalize nightly sleep facts"
```

### Task 3: Add stable projection and multi-night aggregation

**Files:**
- Modify: `src/garmin_mcp/ai_training/sleep.py`
- Modify: `tests/unit/ai_training/test_sleep.py`

- [ ] **Step 1: Add RED input/envelope tests**

Pin exact direct-service validation and zero reads:

```python
@pytest.mark.parametrize("days", [True, False, "7", 0, -1, 31, 1.0, None])
def test_sleep_trend_rejects_invalid_days_before_provider_access(days):
    client = Mock()

    result = get_sleep_trend_service(client, days, today=date(2026, 8, 17))

    assert result["status"] == "error"
    assert result["error"] == {
        "code": "invalid_days",
        "message": "days must be an integer from 1 through 30.",
    }
    assert result["period"] == {"days": None, "start_date": None, "end_date": None}
    client.get_sleep_data.assert_not_called()


def test_default_period_reads_oldest_to_newest_once():
    client = RecordingSleepClient(default_payload=complete_sleep_payload())

    result = get_sleep_trend_service(client, today=date(2026, 8, 17))

    assert client.calls == [
        "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
        "2026-08-15", "2026-08-16", "2026-08-17",
    ]
    assert result["period"] == {
        "days": 7,
        "start_date": "2026-08-11",
        "end_date": "2026-08-17",
    }
```

Use a recording client whose payload factory writes the requested date into
both supported Garmin calendar-date fields. Define it explicitly in the test
module:

```python
class RecordingSleepClient:
    def __init__(self, payloads=None, payload_factory=complete_sleep_payload):
        self.payloads = {} if payloads is None else payloads
        self.payload_factory = payload_factory
        self.calls = []

    def get_sleep_data(self, date_text):
        self.calls.append(date_text)
        if date_text in self.payloads:
            value = self.payloads[date_text]
            if isinstance(value, BaseException):
                raise value
            return value
        return self.payload_factory(date_text)
```

- [ ] **Step 2: Add RED status and visible-gap tests**

Cover all success, partial, and error rows. The current empty night must not
trigger an eighth read:

```python
def test_empty_current_night_is_visible_and_does_not_shift_window():
    payloads = {
        day: complete_sleep_payload(day)
        for day in ("2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15", "2026-08-16")
    }
    payloads["2026-08-17"] = {}
    client = RecordingSleepClient(payloads=payloads)

    result = get_sleep_trend_service(client, today=date(2026, 8, 17))

    assert result["status"] == "partial_success"
    assert result["availability"]["2026-08-17"] is False
    assert result["nights"][-1] == empty_sleep_night("2026-08-17")
    assert result["warnings"][-1]["code"] == "sleep_data_unavailable"
    assert client.calls[0] == "2026-08-11"
    assert client.calls[-1] == "2026-08-17"
    assert len(client.calls) == 7
```

Add a mixed test with one expected provider failure and one malformed payload;
assert fixed warnings, no private exception/payload sentinel in
`json.dumps(result)`, and later reads continue. Add an all-unavailable test for
`sleep_trend_unavailable`.

- [ ] **Step 3: Add RED projection and aggregate tests**

Assert exact stable nightly key order and conversions. Use three source sleep
durations that distinguish raw-first averaging from average-of-rounded values:

```python
def test_averages_use_raw_values_and_per_metric_denominators():
    facts = [
        replace(normalized_facts(), sleep_seconds=30_601, score=80, overnight_hrv_ms=90),
        replace(normalized_facts(), sleep_seconds=30_601, score=None, overnight_hrv_ms=92),
        replace(normalized_facts(), sleep_seconds=30_601, score=83, overnight_hrv_ms=None),
    ]

    summary = aggregate_sleep_facts(facts, nights_requested=3)

    assert summary["averages"]["duration_hours"] == {"value": 8.5, "nights": 3}
    assert summary["averages"]["score"] == {"value": 81.5, "nights": 2}
    assert summary["averages"]["overnight_hrv_ms"] == {"value": 91.0, "nights": 2}
```

Include `{"value": None, "nights": 0}` for a metric absent from all facts.

- [ ] **Step 4: Run service tests and prove RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/ai_training/test_sleep.py -k "trend or average or projection"
```

Expected: failures because service/projection functions are absent.

- [ ] **Step 5: Implement stable constructors and aggregation**

Add fixed vocabularies and stable constructors:

```python
PUBLIC_SLEEP_ERRORS = {
    "invalid_days": "days must be an integer from 1 through 30.",
    "client_unavailable": "Garmin client is unavailable.",
    "sleep_trend_unavailable": "Sleep trend is unavailable for the requested period.",
}

SLEEP_WARNINGS = {
    "sleep_data_unavailable": "Sleep data is unavailable for this date.",
    "provider_unavailable": "Sleep data could not be retrieved for this date.",
    "invalid_provider_response": "Sleep data returned an invalid response for this date.",
}


def empty_sleep_night(date_text: str) -> dict[str, Any]:
    return {
        "date": date_text,
        "available": False,
        "duration_hours": None,
        "nap_minutes": None,
        "score": None,
        "score_qualifier": None,
        "stages": {
            "deep_minutes": None,
            "light_minutes": None,
            "rem_minutes": None,
            "awake_minutes": None,
        },
        "resting_hr_bpm": None,
        "overnight_hrv_ms": None,
        "average_sleep_stress": None,
        "awake_count": None,
        "restless_moments_count": None,
        "spo2": {"average_percent": None, "lowest_percent": None},
    }
```

Implement `project_sleep_night(facts)` using one-decimal duration conversions.
Keep whole integer values as integers where no unit conversion occurs.

Implement `aggregate_sleep_facts` with a helper that receives raw attributes and
an optional divisor. It must sum raw values first, divide by count/divisor, then
round once:

```python
def _average(
    facts: list[SleepNightFacts], attribute: str, divisor: float = 1.0
) -> dict[str, int | float | None]:
    values = [getattr(item, attribute) for item in facts]
    present = [value for value in values if value is not None]
    if not present:
        return {"value": None, "nights": 0}
    value = round(sum(present) / len(present) / divisor, 1)
    return {"value": value, "nights": len(present)}
```

Use `average_spo2_percent` for `spo2_percent`.

- [ ] **Step 6: Implement the bounded sequential service**

Implement the exact signature:

```python
def get_sleep_trend_service(
    client: Any,
    days: Any = DEFAULT_SLEEP_DAYS,
    *,
    today: date | None = None,
) -> dict[str, Any]:
```

Validate `days` before date arithmetic or provider access. Resolve `today` once;
require `type(today) is date` when injected. Construct the inclusive date list,
then:

1. call `get_sleep_night` exactly once per date;
2. append one stable night and one availability entry per date;
3. map `failed=True` to `provider_unavailable`;
4. map `None` facts to `sleep_data_unavailable`;
5. catch only `InvalidSleepResponse` around normalization and map it to
   `invalid_provider_response`;
6. retain successful facts for aggregates; and
7. set status from the exact available-night count decision table.

For a validated request with `client is None`, return `client_unavailable`
without reads, while still filling the known period, one `availability: false`
entry per date, one stable empty night per date, and a summary with the requested
count, zero available nights, and null/zero-denominator averages. Invalid
`days` has no resolvable period and therefore returns empty availability/nights
and `nights_requested: 0`.

Do not catch exceptions from projection, aggregation, JSON serialization, or
trusted local helpers.

- [ ] **Step 7: Run the complete sleep unit suite**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/ai_training/test_sleep.py tests/unit/ai_training/test_providers.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/garmin_mcp/ai_training/sleep.py tests/unit/ai_training/test_sleep.py
git commit -m "feat(ai-training): aggregate bounded sleep trends"
```

### Task 4: Reuse the strict normalizer in training context

**Files:**
- Modify: `src/garmin_mcp/ai_training/service.py:364-399`
- Modify: `tests/unit/ai_training/test_service.py`

- [ ] **Step 1: Add RED compatibility tests**

Keep the existing exact snapshot assertions and add a test that monkeypatches
the imported shared normalizer:

```python
def test_training_context_sleep_adapter_uses_shared_normalizer(monkeypatch, providers):
    facts = normalized_facts(date="2026-02-14", sleep_seconds=25_200, score=81)
    normalizer = Mock(return_value=facts)
    monkeypatch.setattr(service, "normalize_sleep_night", normalizer)

    result = get_training_context_service(Mock(), today=date(2026, 2, 14))

    normalizer.assert_called_once_with(providers["sleep"].return_value, None)
    assert result["sleep"] == {
        "date": "2026-02-14",
        "duration_hours": 7.0,
        "score": 81,
        "score_qualifier": facts.score_qualifier,
    }
```

Add empty and `InvalidSleepResponse` cases to prove the existing yesterday-only
fallback and invalid-response behavior remain unchanged.

- [ ] **Step 2: Run focused compatibility tests and prove RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/ai_training/test_service.py -k sleep
```

Expected: the shared-normalizer spy is not called.

- [ ] **Step 3: Replace `_sleep_metrics` internals with the shared adapter**

Import `InvalidSleepResponse` and `normalize_sleep_night`. Preserve the existing
return tuple and output keys:

```python
def _sleep_metrics(raw: Any) -> tuple[dict[str, Any] | None, bool]:
    if raw is None:
        return None, True
    if type(raw) is list:
        return (None, True) if len(raw) == 0 else (None, False)
    if type(raw) is not dict:
        return None, False
    if len(raw) == 0:
        return None, True
    if "dailySleepDTO" not in raw:
        return None, False
    dto = raw.get("dailySleepDTO")
    if dto is None:
        return None, True
    if type(dto) is not dict:
        return None, False
    if len(dto) == 0:
        return None, True
    try:
        facts = normalize_sleep_night(raw, None)
    except InvalidSleepResponse:
        return None, False
    if facts is None:
        return None, True
    return {
        "date": facts.date,
        "duration_hours": (
            round(facts.sleep_seconds / 3600, 1)
            if facts.sleep_seconds is not None
            else None
        ),
        "score": facts.score,
        "score_qualifier": facts.score_qualifier,
    }, False
```

Do not change `_read_with_previous_day_fallback`, `_populate_sleep`, the service
provider order, or the public training-context envelope.

- [ ] **Step 4: Run training-context and sleep tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/ai_training/test_service.py tests/unit/ai_training/test_sleep.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/garmin_mcp/ai_training/service.py tests/unit/ai_training/test_service.py
git commit -m "refactor(ai-training): share sleep normalization"
```

### Task 5: Add the FastMCP adapter and read-only integration harness

**Files:**
- Modify: `src/garmin_mcp/ai_training/__init__.py`
- Modify: `src/garmin_mcp/ai_training/tools.py`
- Create: `tests/integration/test_ai_sleep_trend_tools.py`

- [ ] **Step 1: Write RED real-FastMCP tests**

Register the package on a real `FastMCP` instance. Pin the exact tool name,
default/explicit calls, compact JSON, description, and strict Boolean rejection.
Use a recording allowlist client:

```python
class ReadOnlySleepClient:
    def __init__(self):
        self.calls = []
        self.forbidden_calls = []

    def get_sleep_data(self, date_text):
        self.calls.append(("get_sleep_data", date_text))
        return integration_sleep_payload(date_text)

    def __getattr__(self, name):
        self.forbidden_calls.append(name)
        raise AssertionError(f"forbidden client access: {name}")


def integration_sleep_payload(date_text):
    return {
        "dailySleepDTO": {
            "calendarDate": date_text,
            "sleepTimeSeconds": 25_200,
            "sleepScores": {
                "overall": {"value": 81, "qualifierKey": "GOOD"}
            },
        }
    }


@pytest.mark.asyncio
async def test_get_sleep_trend_default_call_uses_only_documented_reads():
    client = ReadOnlySleepClient()
    app = FastMCP("sleep-test")
    ai_training.configure(client)
    ai_training.register_tools(app)

    result = await app.call_tool("get_sleep_trend", {})
    payload = json.loads(result[0][0].text)

    assert payload["period"]["days"] == 7
    assert len(client.calls) == 7
    assert client.forbidden_calls == []
```

Actively invoke traps for representative writes and raw access
(`upload_workout`, `update_workout`, `schedule_workout`, `unschedule_workout`,
`delete_workout`, `connectapi`, `garth`, `session`, `post`, `put`, `delete`) and
assert the sleep path never records any of them.

- [ ] **Step 2: Run the integration test and prove RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/integration/test_ai_sleep_trend_tools.py
```

Expected: `get_sleep_trend` is not registered.

- [ ] **Step 3: Export and register the tool**

In `ai_training.__init__`, export `DEFAULT_SLEEP_DAYS`, `MAX_SLEEP_DAYS`, and
`get_sleep_trend_service`.

In `tools.py`, import `StrictInt` and add:

```python
@app.tool()
async def get_sleep_trend(days: StrictInt = 7) -> str:
    """Return a bounded read-only recent sleep trend for AI coaching.

    The fixed inclusive period ends today and covers 1 through 30 nights.
    Detailed sleep evidence is fetched explicitly with one sequential Garmin
    read per requested date. Missing dates remain visible and are never replaced;
    today's sleep can be unavailable until the watch synchronizes. Per-metric
    averages state the number of nights actually used. Garmin metric availability
    varies by device, account, and sync state. This evidence alone does not
    establish causation, readiness, recovery, or a training recommendation.
    """
    result = get_sleep_trend_service(garmin_client, days)
    return json.dumps(result, separators=(",", ":"), ensure_ascii=False)
```

Place the tool immediately after `get_training_context` so the high-level
training reads remain grouped.

- [ ] **Step 4: Run package integration and unit tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q \
  tests/integration/test_ai_sleep_trend_tools.py \
  tests/integration/test_ai_training_tools.py \
  tests/unit/ai_training
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 5**

```bash
git add \
  src/garmin_mcp/ai_training/__init__.py \
  src/garmin_mcp/ai_training/tools.py \
  tests/integration/test_ai_sleep_trend_tools.py
git commit -m "feat(ai-training): expose sleep trend tool"
```

### Task 6: Wire the exact 16-tool AI-coach profile

**Files:**
- Modify: `src/garmin_mcp/__init__.py:112-130`
- Modify: `tests/unit/test_tool_filter.py`
- Modify: `tests/unit/test_server_startup.py`

- [ ] **Step 1: Update profile tests first and prove RED**

Add `get_sleep_trend` to the hard-coded expected profile sets and change exact
counts from 15 to 16. Keep the startup assertion that actual registered names
equal `TOOL_PROFILES["ai-coach"]`.

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
```

Expected: profile membership failures because production still contains 15
names.

- [ ] **Step 2: Add the profile member atomically**

Insert `"get_sleep_trend"` immediately after `"get_training_context"` in
`TOOL_PROFILES["ai-coach"]`. Do not alter allowlist/denylist precedence,
startup diagnostics, default unfiltered registration, or module ordering.

- [ ] **Step 3: Run profile/startup/tool tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q \
  tests/unit/test_tool_filter.py \
  tests/unit/test_server_startup.py \
  tests/integration/test_ai_sleep_trend_tools.py
```

Expected: all selected tests pass.

- [ ] **Step 4: Commit Task 6**

```bash
git add src/garmin_mcp/__init__.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
git commit -m "feat(server): add sleep trend to ai-coach"
```

### Task 7: Document and pin the public contract

**Files:**
- Modify: `.gitignore`
- Create: `docs/ai-sleep-trend.md`
- Modify: `README.md`
- Modify: `docs/ai-training.md`
- Create: `tests/unit/test_ai_sleep_trend_docs.py`
- Modify: `tests/unit/test_ai_training_docs.py`
- Modify: `tests/unit/test_readme_docs.py`
- Modify: `tests/unit/test_ai_workouts_docs.py`
- Modify: `tests/unit/test_ai_activity_docs.py`
- Modify: `tests/unit/test_ai_wellness_heart_rate_docs.py`

- [ ] **Step 1: Write RED documentation tests**

Create `test_ai_sleep_trend_docs.py`. Parse every JSON block, pin exact top-level,
nightly, stage, SpO2, average, warning, and error keys, and assert the guide
contains:

```python
REQUIRED_PHRASES = (
    "get_sleep_trend(days=7)",
    "fixed inclusive period",
    "ends today",
    "one sequential garmin read per requested date",
    "maximum 30",
    "today's sleep may be unavailable until the watch synchronizes",
    "missing dates remain visible",
    "per-metric denominator",
    "does not establish causation, readiness, recovery",
    "read-only",
    "sleep timestamps are not returned",
)
```

Update every existing hard-coded profile set/count to include
`get_sleep_trend` and 16. Add a negative assertion excluding stale
`15-tool surface` and `exactly 15 tools` wording.

- [ ] **Step 2: Run documentation tests and prove RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q tests/unit/test_*docs.py
```

Expected: failures because the guide is absent and current docs still advertise
15 tools.

- [ ] **Step 3: Add the public guide and tracking rule**

Add `!docs/ai-sleep-trend.md` to `.gitignore`. Write the guide from the approved
spec with:

- purpose and workflow;
- exact call signature and bounds;
- complete response example with a visible unsynced date;
- supported metrics and null semantics;
- aggregate `{value, nights}` semantics;
- status/error/warning tables;
- request budget;
- timestamp omission/China caveat;
- read-only and privacy boundaries; and
- interpretation guardrails.

Do not copy the historical design or implementation-plan prose into the public
guide. Keep it consumer-focused.

- [ ] **Step 4: Update README and training-context guide**

In README:

- add `get_sleep_trend(days=7)` as explicit multi-night sleep evidence;
- add it to the profile list immediately after `get_training_context`;
- change `15-tool surface` to `16-tool surface`;
- link the new guide in Documentation and development; and
- keep the README within its existing 150-220 line contract.

In `docs/ai-training.md`, explain the two-step flow:

```text
get_training_context -> current snapshot
get_sleep_trend      -> explicit recent multi-night evidence
```

State that the current snapshot does not imply a multi-night pattern.

- [ ] **Step 5: Run documentation/profile tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q \
  tests/unit/test_*docs.py \
  tests/unit/test_readme_docs.py \
  tests/unit/test_tool_filter.py \
  tests/unit/test_server_startup.py
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 7**

Because `docs/*` is ignored by default, force-add only the approved guide:

```bash
git add .gitignore README.md docs/ai-training.md tests/unit
git add -f docs/ai-sleep-trend.md
git commit -m "docs(ai-training): document sleep trend evidence"
```

### Task 8: Add final adversarial and contract coverage

**Files:**
- Modify: `tests/unit/ai_training/test_sleep.py`
- Modify: `tests/integration/test_ai_sleep_trend_tools.py`
- Modify production files only if a new regression proves a defect

- [ ] **Step 1: Audit the implementation against the approved spec**

Create a checklist from every Testing item in the design spec and map it to an
exact test name. Add tests for any unmapped item before reviewing production.

- [ ] **Step 2: Prove no private data crosses any failure path**

Use unique sentinels in expected provider exceptions, malformed nested values,
oversized strings, and hostile container protocol methods. Serialize each
public result and assert none of these substrings occur:

```python
for sentinel in (
    "token=provider-private",
    "token=payload-private",
    "token=truthiness-private",
    "https://private.example",
):
    assert sentinel not in json.dumps(result)
```

- [ ] **Step 3: Prove internal defects remain visible**

Monkeypatch `normalize_sleep_night`, `project_sleep_night`, and
`aggregate_sleep_facts` separately to raise `RuntimeError("internal defect")`.
Assert each error propagates rather than becoming a provider warning or public
error envelope.

- [ ] **Step 4: Prove maximum-request behavior**

Call `days=30`, assert exactly 30 chronological reads, 30 stable nightly
objects, no retries, and no mutation/raw-access traps. Call `days=31` and assert
zero reads.

- [ ] **Step 5: Run all focused suites**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -q \
  tests/unit/ai_training \
  tests/integration/test_ai_training_tools.py \
  tests/integration/test_ai_sleep_trend_tools.py \
  tests/unit/test_tool_filter.py \
  tests/unit/test_server_startup.py \
  tests/unit/test_*docs.py \
  tests/unit/test_readme_docs.py
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit only if Task 8 adds coverage or a proven fix**

```bash
git add tests/unit/ai_training/test_sleep.py tests/integration/test_ai_sleep_trend_tools.py src/garmin_mcp/ai_training
git commit -m "test(ai-training): harden sleep trend contracts"
```

If no file changed, do not create an empty commit.

### Task 9: Complete verification and open a ready-for-review PR

**Files:**
- Verify the complete branch; do not change historical spec/plan files during fixes

- [ ] **Step 1: Run formatting and whitespace checks**

Run:

```bash
git diff --check origin/main...HEAD
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache uv run ruff check src tests
```

Expected: both commands exit zero. If `ruff` is not installed by the project,
record that exact fact and rely on the configured CI commands; do not silently
claim lint passed.

- [ ] **Step 2: Run the complete offline suite**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache \
uv run pytest -m "not e2e" -q
```

Expected: zero failures; live E2E tests are deselected.

- [ ] **Step 3: Build and inspect packages**

Run:

```bash
BUILD_DIR=$(mktemp -d /private/tmp/garmin-mcp-sleep-trend-build.XXXXXX)
UV_CACHE_DIR=/private/tmp/garmin-mcp-sleep-trend-cache uv build --out-dir "$BUILD_DIR"
unzip -l "$BUILD_DIR"/*.whl | rg 'garmin_mcp/ai_training/(sleep|tools|service|providers)\.py'
```

Expected: build succeeds and the wheel contains `sleep.py` plus the existing
AI-training modules.

- [ ] **Step 4: Verify branch scope and working tree**

Run:

```bash
git status --short
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
```

Expected: clean working tree; commits are limited to sleep-trend design,
implementation, tests, profile, and current documentation.

- [ ] **Step 5: Push and open a non-draft PR**

Run:

```bash
git push -u origin feat/ai-sleep-trend-v1
gh pr create \
  --base main \
  --head feat/ai-sleep-trend-v1 \
  --title "feat: add bounded multi-night sleep trends" \
  --body "$(cat <<'EOF'
## Summary
- add a strict, bounded `get_sleep_trend(days=7)` read-only coaching tool
- return visible nightly gaps and denominator-aware aggregates
- reuse one sleep normalizer for the trend and existing training snapshot
- expose the exact 16-tool `ai-coach` profile and document interpretation limits

## Verification
- `uv run pytest -m \"not e2e\" -q`
- package build and wheel-content inspection
- `git diff --check origin/main...HEAD`
EOF
)"
```

Expected: a ready-for-review pull request, not a draft.

## Implementation constraints

- Execute tasks in order and preserve RED/GREEN evidence for every production
  change.
- Do not cherry-pick upstream PR #256; use it only as product inspiration.
- Do not upgrade `garminconnect` or other dependencies.
- Do not expose the upstream `get_sleep_summary` or raw sleep payload to
  `ai-coach`.
- Do not add historical date arguments, retries, parallel calls, timestamps,
  derived coaching fields, or writes.
- Do not edit the approved design spec during implementation unless the user
  explicitly approves a contract revision.
- Keep every commit focused and preserve unrelated user changes.
