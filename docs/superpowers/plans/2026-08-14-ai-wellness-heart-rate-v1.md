# AI Wellness Heart-Rate v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one bounded, read-only `get_wellness_heart_rate` tool that returns validated Garmin all-day heart-rate summaries, raw points, or local-time bins for one through seven dates without exposing raw DTOs or encouraging invalid duration/zone inferences.

**Architecture:** Keep the feature inside the existing fork-owned `ai_training` package. A one-call-per-date provider wrapper invokes only pinned `Garmin.get_heart_rates(date)`; a new `heart_rate.py` service validates arguments, normalizes exact built-in JSON containers, establishes time provenance, projects raw/daily/binned results, reports factual gaps, applies bounds, and assembles the stable multi-date envelope. The existing `get_training_context`, upstream-oriented `health_wellness` tools, authentication, and Garmin client remain unchanged.

**Tech Stack:** Python 3.12, `garminconnect==0.3.10`, FastMCP 1.x, Pydantic strict MCP annotations, standard-library `datetime`, `statistics`, and `json`, pytest/pytest-asyncio, uv.

---

## File map and fixed contracts

- Modify `src/garmin_mcp/ai_training/providers.py`: add the sole permitted daily wellness-HR provider seam.
- Create `src/garmin_mcp/ai_training/heart_rate.py`: own request validation, payload validation, time normalization, raw/daily/bin reduction, gap facts, caps, status, and stable envelopes.
- Modify `src/garmin_mcp/ai_training/tools.py` and `src/garmin_mcp/ai_training/__init__.py`: register and export the new high-level service beside `get_training_context` using the existing configured client.
- Modify `src/garmin_mcp/__init__.py`: atomically add one tool name to the `ai-coach` profile; do not alter filter precedence or startup ordering.
- Extend `tests/unit/ai_training/test_providers.py`; create `tests/unit/ai_training/test_heart_rate.py` and `tests/integration/test_ai_wellness_heart_rate_tools.py`; update startup/profile tests.
- Create `docs/ai-wellness-heart-rate.md`; update only current-facing README/setup/AI guides and their contract tests. Historical specs and plans remain immutable.

Use these exact public names throughout:

```python
# providers.py
def get_wellness_heart_rate_day(client: Any, date: str) -> ProviderResult: ...

# heart_rate.py
MAX_DAYS = 7
MAX_SOURCE_POINTS_PER_DAY = 10_000
MAX_RAW_POINTS = 1_000
MAX_RETURNED_BINS = 1_000
MAX_SERIALIZED_BYTES = 262_144
GAP_THRESHOLD_SECONDS = 300
RESOLUTIONS = ("daily", "raw", "5m", "15m", "30m", "60m")

def get_wellness_heart_rate_service(
    client: Any,
    start_date: Any,
    end_date: Any = None,
    resolution: Any = "raw",
    start_time: Any = None,
    end_time: Any = None,
) -> dict[str, Any]: ...
```

The service accepts `Any` intentionally so direct Python callers receive the same fixed error envelope as MCP callers. The FastMCP adapter uses `StrictStr` for every supplied string and a `Literal` for resolution so booleans/numbers are not coerced before the service.

The only allowed Garmin method in this path is `client.get_heart_rates(date)`. No task may call `get_rhr_day`, `connectapi`, an activity endpoint, a write method, or an authentication method.

### Task 1: Add the bounded one-date provider seam

**Files:**

- Modify: `src/garmin_mcp/ai_training/providers.py`
- Modify: `tests/unit/ai_training/test_providers.py`

- [ ] **Step 1: Write the provider RED tests.**

  Import `get_wellness_heart_rate_day` and add a recorder that exposes only the approved read:

  ```python
  class WellnessHeartRateClient:
      def __init__(self, payload: object = None, failure: Exception | None = None):
          self.payload = payload
          self.failure = failure
          self.calls: list[str] = []

      def get_heart_rates(self, date: str) -> object:
          self.calls.append(date)
          if self.failure is not None:
              raise self.failure
          return self.payload

      def __getattr__(self, name: str) -> object:
          raise AssertionError(f"forbidden Garmin access: {name}")

  def test_wellness_provider_calls_only_get_heart_rates_once() -> None:
      payload = {"calendarDate": "2026-08-14", "heartRateValues": []}
      client = WellnessHeartRateClient(payload)
      assert get_wellness_heart_rate_day(client, "2026-08-14") == ProviderResult(data=payload)
      assert client.calls == ["2026-08-14"]

  def test_wellness_provider_sanitizes_external_failure() -> None:
      client = WellnessHeartRateClient(failure=RuntimeError("token=private"))
      result = get_wellness_heart_rate_day(client, "2026-08-14")
      assert result == ProviderResult(
          data=None,
          failed=True,
          warnings=({
              "provider": "wellness_heart_rate",
              "code": "provider_unavailable",
              "message": "Wellness heart-rate data is unavailable for this date.",
          },),
      )
      assert "private" not in repr(result)
  ```

- [ ] **Step 2: Run the focused test and record RED.**

  Run: `uv run pytest tests/unit/ai_training/test_providers.py -q`

  Expected: collection fails because `get_wellness_heart_rate_day` is not defined.

- [ ] **Step 3: Implement the narrow external boundary.**

  Append this function to `providers.py`; do not validate or copy the raw response in the provider because `heart_rate.py` owns the untrusted-container boundary:

  ```python
  def get_wellness_heart_rate_day(client: Any, date: str) -> ProviderResult:
      """Fetch one daily wellness-HR DTO through the pinned read-only client."""
      try:
          data = client.get_heart_rates(date)
      except Exception:
          return ProviderResult(
              data=None,
              failed=True,
              warnings=_warning(
                  "wellness_heart_rate",
                  "provider_unavailable",
                  "Wellness heart-rate data is unavailable for this date.",
              ),
          )
      return ProviderResult(data=data)
  ```

- [ ] **Step 4: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/ai_training/test_providers.py -q`

  Expected: PASS, including the existing provider suite.

  ```bash
  git add src/garmin_mcp/ai_training/providers.py tests/unit/ai_training/test_providers.py
  git commit -m "feat(ai-training): add wellness heart-rate provider"
  ```

### Task 2: Establish strict arguments and the stable error envelope

**Files:**

- Create: `src/garmin_mcp/ai_training/heart_rate.py`
- Create: `tests/unit/ai_training/test_heart_rate.py`

- [ ] **Step 1: Write RED tests for constants, envelope keys, and zero-read argument rejection.**

  Use a client whose `get_heart_rates` records any attempted date. Pin the exact constants, top-level keys, strict date syntax, date ordering, inclusive 7-day range, raw single-date rule, all six resolution literals, paired `HH:MM` arguments, no cross-midnight window, daily/window incompatibility, and theoretical bin cap.

  ```python
  TOP_LEVEL_KEYS = {
      "status", "error", "period", "resolution", "availability", "days", "warnings"
  }

  class RecordingClient:
      def __init__(self, payloads: dict[str, object] | None = None):
          self.payloads = payloads or {}
          self.calls: list[str] = []

      def get_heart_rates(self, date: str) -> object:
          self.calls.append(date)
          return self.payloads.get(date, {"heartRateValues": []})

  @pytest.mark.parametrize(
      ("kwargs", "code"),
      [
          ({"start_date": 20260814}, "invalid_start_date"),
          ({"start_date": "2026-8-14"}, "invalid_start_date"),
          ({"start_date": "2026-02-30"}, "invalid_start_date"),
          ({"start_date": "2026-08-14", "end_date": 1}, "invalid_end_date"),
          ({"start_date": "2026-08-14", "end_date": "2026-08-13"}, "invalid_date_range"),
          ({"start_date": "2026-08-01", "end_date": "2026-08-08"}, "date_range_too_large"),
          ({"start_date": "2026-08-14", "resolution": "RAW"}, "invalid_resolution"),
          ({"start_date": "2026-08-13", "end_date": "2026-08-14"}, "raw_requires_single_date"),
          ({"start_date": "2026-08-14", "start_time": "08:00"}, "invalid_time_window"),
          ({"start_date": "2026-08-14", "start_time": "8:00", "end_time": "09:00"}, "invalid_time_window"),
          ({"start_date": "2026-08-14", "start_time": "22:00", "end_time": "06:00"}, "invalid_time_window"),
          ({"start_date": "2026-08-14", "resolution": "daily", "start_time": "08:00", "end_time": "09:00"}, "invalid_time_window"),
      ],
  )
  def test_invalid_arguments_return_stable_error_without_garmin_reads(kwargs, code):
      client = RecordingClient()
      result = get_wellness_heart_rate_service(client, **kwargs)
      assert set(result) == TOP_LEVEL_KEYS
      assert result["status"] == "error"
      assert result["error"]["code"] == code
      assert client.calls == []
  ```

  Add exact-bound tests asserting Aug 8–14 is accepted and Aug 7–14 is rejected, every resolution in `RESOLUTIONS` is accepted, and a multi-day 5-minute request projects at most 1,000 bins before reads. Use a monkeypatch of `MAX_RETURNED_BINS` to make the red request-size test small and assert `request_too_large` with zero calls.

- [ ] **Step 2: Run the new file and record RED.**

  Run: `uv run pytest tests/unit/ai_training/test_heart_rate.py -q`

  Expected: collection fails because `garmin_mcp.ai_training.heart_rate` does not exist.

- [ ] **Step 3: Implement request parsing and stable base/error builders.**

  Create `heart_rate.py` with the exact exported constants and these private contracts:

  ```python
  from datetime import date, datetime, time, timedelta
  import json
  from typing import Any

  from .providers import ProviderResult, get_wellness_heart_rate_day

  MAX_DAYS = 7
  MAX_SOURCE_POINTS_PER_DAY = 10_000
  MAX_RAW_POINTS = 1_000
  MAX_RETURNED_BINS = 1_000
  MAX_SERIALIZED_BYTES = 262_144
  GAP_THRESHOLD_SECONDS = 300
  RESOLUTIONS = ("daily", "raw", "5m", "15m", "30m", "60m")
  BIN_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "60m": 60}

  ERROR_MESSAGES = {
      "invalid_start_date": "start_date must be a real calendar date in YYYY-MM-DD format.",
      "invalid_end_date": "end_date must be null or a real calendar date in YYYY-MM-DD format.",
      "invalid_date_range": "start_date must be on or before end_date.",
      "date_range_too_large": "The inclusive date range must contain at most 7 dates.",
      "invalid_resolution": "resolution must be one of: daily, raw, 5m, 15m, 30m, 60m.",
      "raw_requires_single_date": "raw resolution requires a single calendar date.",
      "invalid_time_window": "start_time and end_time must be paired HH:MM values with start_time earlier than end_time; daily resolution does not accept a window.",
      "request_too_large": "The requested bin count exceeds 1000; shorten the date/time range or use a coarser resolution.",
      "client_unavailable": "The Garmin client is unavailable.",
      "wellness_heart_rate_unavailable": "Wellness heart-rate data is unavailable for every requested date.",
      "raw_response_too_large": "The raw result exceeds 1000 points; narrow the time window or choose a binned resolution.",
      "response_too_large": "The normalized result exceeds 262144 bytes; narrow the time window or choose a coarser resolution.",
  }

  def _strict_date(value: Any) -> date | None:
      if type(value) is not str or len(value) != 10:
          return None
      try:
          parsed = datetime.strptime(value, "%Y-%m-%d").date()
      except ValueError:
          return None
      return parsed if parsed.isoformat() == value else None

  def _strict_time(value: Any) -> time | None:
      if type(value) is not str or len(value) != 5:
          return None
      try:
          parsed = datetime.strptime(value, "%H:%M").time()
      except ValueError:
          return None
      return parsed if parsed.strftime("%H:%M") == value else None
  ```

  Add `_base_envelope(...)`, `_error(...)`, `_requested_dates(...)`, and `_validate_request(...)`. `_base_envelope` always emits the seven exact top-level keys and includes safely constructible raw input values only when they are exact strings; error messages come exclusively from `ERROR_MESSAGES`. Compute projected bins as `ceil(window_minutes / bin_minutes) * requested_days` and reject before `client is None` or any provider call.

- [ ] **Step 4: Add the minimal service loop needed for argument tests.**

  After validation, reject `client is None` with `client_unavailable`; otherwise call `get_wellness_heart_rate_day` once per requested date in order and return a temporary stable empty-day result. Do not add DTO parsing in this task. Keep provider-result failure handling sufficient for `wellness_heart_rate_unavailable`; Task 4 replaces the temporary day assembly with the complete reducer.

- [ ] **Step 5: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/ai_training/test_heart_rate.py tests/unit/ai_training/test_providers.py -q`

  Expected: PASS for the argument/envelope/provider contracts.

  ```bash
  git add src/garmin_mcp/ai_training/heart_rate.py tests/unit/ai_training/test_heart_rate.py
  git commit -m "feat(ai-training): validate wellness heart-rate requests"
  ```

### Task 3: Normalize Garmin summaries, timestamps, and raw points

**Files:**

- Modify: `src/garmin_mcp/ai_training/heart_rate.py`
- Modify: `tests/unit/ai_training/test_heart_rate.py`

- [ ] **Step 1: Add synthetic payload fixtures and RED tests.**

  Define a fixture with no real user data:

  ```python
  def wellness_payload(samples=None):
      return {
          "calendarDate": "2026-08-14",
          "startTimestampGMT": "2026-08-13T22:00:00.0",
          "endTimestampGMT": "2026-08-14T22:00:00.0",
          "startTimestampLocal": "2026-08-14T00:00:00.0",
          "endTimestampLocal": "2026-08-15T00:00:00.0",
          "restingHeartRate": 45,
          "minHeartRate": 41,
          "maxHeartRate": 166,
          "lastSevenDaysAvgRestingHeartRate": 46,
          "heartRateValues": samples if samples is not None else [
              [1786665600000, 48],
              [1786665720000, None],
              [1786665840000, 51],
          ],
      }
  ```

  Add tests for complete daily/raw results, null bpm retention, missing summary values staying null, deterministic timestamp sorting without mutating the source, local `+02:00` and exact UTC `Z`, daily mode not inspecting malformed entries, and daily `sampling` null fields. Add parameterized malformed-provider cases for root/list/sample exact-container subclasses, wrong tuple length, invalid timestamps, and bpm values `True`, `0`, `301`, `1.0`, and `"50"`. Assert one fixed `invalid_provider_response` warning and no raw payload text in serialized output.

  Add cap tests that monkeypatch `MAX_SOURCE_POINTS_PER_DAY` and `MAX_RAW_POINTS`: exact boundaries succeed, one above source cap becomes invalid provider response, and one above selected raw cap returns `raw_response_too_large` with no partial points.

- [ ] **Step 2: Run the normalization tests and record RED.**

  Run: `uv run pytest tests/unit/ai_training/test_heart_rate.py -q`

  Expected: failures show the temporary Task 2 day objects lack normalized summary, provenance, sampling, and raw points.

- [ ] **Step 3: Implement exact payload and scalar validation.**

  Add immutable internal facts:

  ```python
  from dataclasses import dataclass
  from math import isfinite
  from statistics import median

  @dataclass(frozen=True)
  class Sample:
      timestamp_ms: int
      bpm: int | None

  @dataclass(frozen=True)
  class DayFacts:
      date: str
      summary: dict[str, int | None]
      offset_minutes: int | None
      samples: tuple[Sample, ...]
      source_points: int
  ```

  Require `type(raw) is dict`. Treat an absent or explicit-null `heartRateValues` as an empty collection; otherwise require `type(heartRateValues) is list`. Check `len(values) <= MAX_SOURCE_POINTS_PER_DAY` before iterating. Summary fields accept only `type(value) is int` and `1 <= value <= 300`; absent/null maps to `None`, while any other supplied value invalidates the date. In `daily` mode record only the list length and never inspect its elements.

  In raw/binned modes require every item to be an exact list of length two; timestamp must be an exact non-boolean integer that converts through `datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)`; bpm must be `None` or exact int 1..300. Sort a fresh `Sample` list by `(timestamp_ms, source_index)` and never mutate Garmin's list.

- [ ] **Step 4: Implement time provenance and raw projection.**

  Parse all four Garmin bounds using `datetime.fromisoformat`. Treat GMT values as UTC and local values as naive wall time. Compute start and end offsets as `local.replace(tzinfo=UTC) - gmt`; accept only equal whole-minute offsets between -1,439 and +1,439 minutes. Otherwise use `None` and add one fixed `local_time_unavailable` warning.

  Project raw points with:

  ```python
  def _utc_iso(timestamp_ms: int) -> str:
      return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")

  def _local_iso(timestamp_ms: int, offset_minutes: int | None) -> str | None:
      if offset_minutes is None:
          return None
      zone = timezone(timedelta(minutes=offset_minutes))
      return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).astimezone(zone).isoformat()
  ```

  Window filtering uses local wall-clock minutes and is start-inclusive/end-exclusive. If a window is requested without valid local provenance, mark that date failed rather than filtering in UTC. Raw unwindowed mode retains UTC points with local null.

  Populate `sampling` exactly: source count, selected valid-bpm/null-bpm counts, raw returned count, median of adjacent positive selected timestamp intervals in seconds (or null), and literal `duration_from_sample_count_valid: false`.

- [ ] **Step 5: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/ai_training/test_heart_rate.py -q`

  Expected: PASS for daily/raw normalization, strict malformed-data handling, time provenance, windows, and both point caps.

  ```bash
  git add src/garmin_mcp/ai_training/heart_rate.py tests/unit/ai_training/test_heart_rate.py
  git commit -m "feat(ai-training): normalize wellness heart-rate samples"
  ```

### Task 4: Add binned statistics, factual gaps, and multi-date status

**Files:**

- Modify: `src/garmin_mcp/ai_training/heart_rate.py`
- Modify: `tests/unit/ai_training/test_heart_rate.py`

- [ ] **Step 1: Write RED tests for every bin size and reduction rule.**

  Parameterize `5m`, `15m`, `30m`, and `60m`. Assert bins align to Garmin-local midnight/wall-clock boundaries; contain exact local/UTC starts and ends; report min, raw-sum-then-round mean to one decimal, max, and exact sample count; exclude null samples and empty bins; and never expose `coverage`, zone seconds, or inferred durations.

  Use three values whose round-then-sum differs from sum-then-round. Assert a bin over `[101, 102, 102]` returns `101.7`, not an average of pre-rounded components.

- [ ] **Step 2: Write RED gap and status tests.**

  Pin intervals at 299, 300, and 301 seconds; only 300+ becomes a gap. Assert gaps use adjacent valid-bpm samples after window filtering, include local/UTC bounds and one-decimal elapsed minutes, and never invent leading/trailing gaps. Add date-ordered multi-day tests for:

  - all valid dates -> `success`;
  - one provider exception or malformed date followed by a valid date -> `partial_success` and continued sequential reads;
  - every provider date failed/malformed -> `error`/`wellness_heart_rate_unavailable`;
  - every date legitimately empty -> `success`, all availability false;
  - local-time warning in unwindowed raw/daily -> `success`;
  - missing local time for bins/window -> failed date, partial when another is useful, error when none is useful.

  Assert warning order follows date order, warning dictionaries contain only provider/date/code/message, and secret exception/payload sentinels are absent from `json.dumps(result)`.

- [ ] **Step 3: Implement bin and gap reducers as pure local helpers.**

  Use `BIN_MINUTES[resolution]`. Derive local wall-clock minutes from the exact offset, floor to the resolution boundary, and convert both boundaries back to UTC. Accumulate only valid bpm values. Build each bin dictionary with exactly:

  ```python
  {
      "start_time_local": ...,
      "end_time_local": ...,
      "start_time_utc": ...,
      "end_time_utc": ...,
      "min_bpm": min(values),
      "mean_bpm": round(sum(values) / len(values), 1),
      "max_bpm": max(values),
      "sample_count": len(values),
  }
  ```

  Require `len(bins) <= MAX_RETURNED_BINS` without truncation. Build gaps only from adjacent selected `Sample` values whose bpm is not null and whose timestamp delta is at least `GAP_THRESHOLD_SECONDS * 1000`.

- [ ] **Step 4: Replace the temporary service aggregation with the final status contract.**

  Iterate requested dates once, sequentially. Convert provider failures to a dated fixed warning. Convert exact-container/payload failures to:

  ```python
  {
      "provider": "wellness_heart_rate",
      "date": requested_date,
      "code": "invalid_provider_response",
      "message": "Wellness heart-rate data had an unexpected shape for this date.",
  }
  ```

  Include one stable day object for every requested date, even failed/unavailable dates. `availability[date]` must equal `day["available"]`. Determine availability according to the approved mode-specific rules, not from sample count alone. Only provider/malformed/local-required failures influence `partial_success`; legitimate empty days and local-time warnings with usable UTC do not.

- [ ] **Step 5: Enforce the final serialized-size boundary.**

  Compactly serialize a successful/partial envelope using `json.dumps(result, separators=(",", ":"), ensure_ascii=False)`. If UTF-8 length exceeds `MAX_SERIALIZED_BYTES`, replace it with the stable `response_too_large` error envelope and return no day samples. Do not catch serializer or reducer programming errors. Add exact-cap and one-byte-over tests by monkeypatching the constant to the measured synthetic-envelope size.

- [ ] **Step 6: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/ai_training/test_heart_rate.py tests/unit/ai_training/test_providers.py -q`

  Expected: PASS for all service/provider behavior.

  ```bash
  git add src/garmin_mcp/ai_training/heart_rate.py tests/unit/ai_training/test_heart_rate.py
  git commit -m "feat(ai-training): aggregate bounded wellness heart rate"
  ```

### Task 5: Register the strict FastMCP tool and prove read-only behavior

**Files:**

- Modify: `src/garmin_mcp/ai_training/tools.py`
- Modify: `src/garmin_mcp/ai_training/__init__.py`
- Modify: `tests/integration/test_ai_training_tools.py`
- Create: `tests/integration/test_ai_wellness_heart_rate_tools.py`

- [ ] **Step 1: Add MCP RED tests for exact schema/defaults and delegation.**

  Register a real `FastMCP`, list tools, and assert the new schema has required `start_date`, optional nullable `end_date/start_time/end_time`, literal resolution enum, and default `raw`. Invoke an omitted-option call and a full seven-day binned/windowed call and compare the parsed JSON to a monkeypatched service return.

  Pin tool metadata in lowercase normalized text. It must contain all of these concepts: read-only; explicit evidence fetch; max seven dates; raw one date/max 1,000/no silent truncation; local ISO plus UTC; irregular/missing spacing; sample count is not duration; no time-in-zone; wellness is not FIT activity heart rate and may use different sensor/smoothing/zones; gaps have unknown cause; bins describe returned samples rather than continuous coverage; no drift/recovery/stress/coaching inference.

- [ ] **Step 2: Add an actively trapped read-only integration test.**

  The recording client must implement only `get_heart_rates`. Its `__getattr__` records forbidden names before returning a callable that records invocation and raises. Explicitly invoke traps for `get_rhr_day`, `connectapi`, `get_activity`, `download_activity`, `upload_workout`, `schedule_workout`, `unschedule_workout`, `update_workout`, `delete_workout`, `post`, `put`, `delete`, and credential/login methods in a separate harness test to prove traps cannot be swallowed. Then call the real FastMCP tool and assert its only production calls are date-ordered `get_heart_rates` reads and `forbidden_calls == []`.

- [ ] **Step 3: Run the integration tests and record RED.**

  Run: `uv run pytest tests/integration/test_ai_training_tools.py tests/integration/test_ai_wellness_heart_rate_tools.py -q`

  Expected: failures show only `get_training_context` is registered/exported.

- [ ] **Step 4: Implement the adapter and package export.**

  Import `Literal` and Pydantic `StrictStr`. Add beside `get_training_context`:

  ```python
  @app.tool()
  async def get_wellness_heart_rate(
      start_date: StrictStr,
      end_date: StrictStr | None = None,
      resolution: Literal["daily", "raw", "5m", "15m", "30m", "60m"] = "raw",
      start_time: StrictStr | None = None,
      end_time: StrictStr | None = None,
  ) -> str:
      """Return bounded read-only all-day wellness heart-rate evidence.

      Fetch explicitly when detailed daily evidence is needed. At most seven
      dates are allowed; raw is one date and at most 1,000 points, with refusal
      instead of truncation. Timestamps include local ISO time when Garmin gives
      unambiguous provenance and always include UTC.

      Samples can be irregular or missing: sample count times an assumed cadence
      is not duration and does not establish time in zone. Wellness samples are
      distinct from FIT activity heart rate and must not be assumed to use the
      same sensor, smoothing, samples, or zones. Gaps have no inferred cause;
      bins summarize returned samples only, not continuous coverage. Do not infer
      drift, recovery, stress, or coaching conclusions from this tool alone.
      """
      result = get_wellness_heart_rate_service(
          garmin_client, start_date, end_date, resolution, start_time, end_time
      )
      return json.dumps(result, indent=2)
  ```

  Export `get_wellness_heart_rate_service` and all six bounds constants from `ai_training/__init__.py`; keep configure/register lazy and retain one shared configured client.

- [ ] **Step 5: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/ai_training tests/integration/test_ai_training_tools.py tests/integration/test_ai_wellness_heart_rate_tools.py -q`

  Expected: PASS; the real MCP adapter exposes both `ai_training` tools and performs only the approved reads.

  ```bash
  git add src/garmin_mcp/ai_training/tools.py src/garmin_mcp/ai_training/__init__.py tests/integration/test_ai_training_tools.py tests/integration/test_ai_wellness_heart_rate_tools.py
  git commit -m "feat(ai-training): expose wellness heart-rate tool"
  ```

### Task 6: Add the tool atomically to the exact AI-coach profile

**Files:**

- Modify: `src/garmin_mcp/__init__.py`
- Modify: `tests/unit/test_tool_filter.py`
- Modify: `tests/unit/test_server_startup.py`

- [ ] **Step 1: Write profile/startup RED tests.**

  Update the expected literal profile set in both tests to contain exactly these 15 names:

  ```python
  {
      "get_training_context",
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
  }
  ```

  Retain the equality assertion between actual registered names and `TOOL_PROFILES["ai-coach"]`, explicit allowlist precedence, denylist subtraction, unknown-profile startup failure, and zero-tool warning tests.

- [ ] **Step 2: Run and record RED.**

  Run: `uv run pytest tests/unit/test_tool_filter.py tests/unit/test_server_startup.py -q`

  Expected: the profile/startup equality tests fail because the new registered tool is not yet allowlisted.

- [ ] **Step 3: Add exactly one profile member.**

  Insert `"get_wellness_heart_rate"` immediately after `"get_training_context"` in `TOOL_PROFILES["ai-coach"]`. Do not change `_resolve_tool_filters`, module registration order, or default broad registration.

- [ ] **Step 4: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/test_tool_filter.py tests/unit/test_server_startup.py tests/integration/test_ai_wellness_heart_rate_tools.py -q`

  Expected: PASS with exactly 15 registered profile tools.

  ```bash
  git add src/garmin_mcp/__init__.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
  git commit -m "feat(server): add wellness heart rate to ai-coach"
  ```

### Task 7: Document the explicit evidence read and pin current-facing claims

**Files:**

- Create: `docs/ai-wellness-heart-rate.md`
- Modify: `README.md`
- Modify: `docs/setup.md`
- Modify: `docs/ai-training.md`
- Modify: `docs/ai-activity.md`
- Modify: `docs/ai-activity-timeseries.md`
- Modify: `docs/ai-workouts.md`
- Create: `tests/unit/test_ai_wellness_heart_rate_docs.py`
- Modify existing current documentation contract tests only where literal profile lists/counts change.

- [ ] **Step 1: Write documentation RED tests.**

  Parse every JSON example in the new guide. Compare the documented 15-tool list as an exact set to `TOOL_PROFILES["ai-coach"]`. Assert current-facing docs contain no `14-tool`/`exactly 14` claim. Pin the full stable envelope and per-day key sets, all six resolutions/defaults/bounds, local/UTC rules, raw refusal, summary-only behavior, per-date partial semantics, read-only method allowlist, sync/device variability, and every interpretation guardrail.

  Add distinction assertions: `get_training_context` remains compact automatic context; `get_wellness_heart_rate` is explicit all-day evidence; `get_activity_timeseries` is activity FIT evidence. Assert docs never instruct the coach to calculate duration as sample count times cadence, coverage from bins, time in zone, or a gap cause.

- [ ] **Step 2: Run and record RED.**

  Run: `uv run pytest tests/unit/test_ai_wellness_heart_rate_docs.py tests/unit/test_readme_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_ai_activity_docs.py tests/unit/test_ai_activity_timeseries_docs.py tests/unit/test_ai_workouts_docs.py -q`

  Expected: the new guide is absent and existing current-facing tool lists still contain 14 tools.

- [ ] **Step 3: Write the feature guide and update current tool lists.**

  `docs/ai-wellness-heart-rate.md` must include:

  - purpose and explicit-fetch workflow;
  - the exact MCP signature and six-mode table;
  - the 1/7-day, 10,000-source, 1,000-raw, 1,000-bin, 256-KiB, and 300-second bounds labeled as product limits;
  - strict dates and same-day optional window behavior;
  - full stable response/error/warning schemas with synthetic daily/raw/bin/partial examples;
  - Garmin-local offset provenance plus UTC fallback;
  - null samples, mode-aware availability, factual internal gaps, and legitimate empty/sync behavior;
  - the complete interpretation guardrails from the tool description;
  - only `get_heart_rates(date)` is read, no raw DTO or write path;
  - device/account/sync variation and no live-account requirement for tests.

  Update README/setup and current AI guides to list exactly 15 tools and link the new guide. Describe the coaching flow as compact context -> optional explicit wellness/activity evidence -> recommendation -> confirmed workout write. Do not modify any file below `docs/superpowers/specs/` or `docs/superpowers/plans/`.

- [ ] **Step 4: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/test_ai_wellness_heart_rate_docs.py tests/unit/test_readme_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_ai_activity_docs.py tests/unit/test_ai_activity_timeseries_docs.py tests/unit/test_ai_workouts_docs.py -q`

  Expected: PASS; literal current-facing profile lists equal the runtime profile and example schemas parse.

  ```bash
  git add README.md docs/ai-wellness-heart-rate.md docs/setup.md docs/ai-training.md docs/ai-activity.md docs/ai-activity-timeseries.md docs/ai-workouts.md tests/unit/test_ai_wellness_heart_rate_docs.py tests/unit/test_readme_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_ai_activity_docs.py tests/unit/test_ai_activity_timeseries_docs.py tests/unit/test_ai_workouts_docs.py
  git commit -m "docs(ai-training): document wellness heart-rate evidence"
  ```

### Task 8: Whole-branch verification, independent review, and ready PR

**Files:**

- Verify all feature/source/test/docs files from Tasks 1–7.
- Modify only files implicated by concrete review findings.

- [ ] **Step 1: Run the focused matrix.**

  Run:

  ```bash
  uv run pytest tests/unit/ai_training tests/integration/test_ai_training_tools.py tests/integration/test_ai_wellness_heart_rate_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py tests/unit/test_ai_wellness_heart_rate_docs.py -q
  ```

  Expected: all focused tests pass; no test makes a live Garmin request.

- [ ] **Step 2: Run the complete offline and packaging gates.**

  Run each command separately and retain its output:

  ```bash
  uv run pytest -m "not e2e" -q
  uv lock --check
  uv build
  git diff --check main...HEAD
  git status --short
  ```

  Expected: offline suite passes with only e2e tests deselected; lock is current; wheel/sdist build; diff check is clean; worktree has no uncommitted files.

- [ ] **Step 3: Perform the security and contract audit.**

  Review the full branch diff against the approved design and specifically probe:

  - exact built-in containers and hostile dict/list subclasses;
  - source/raw/bin/serialized caps at and above boundaries;
  - timestamps at Python datetime limits and offset-transition payloads;
  - null bpm, duplicate/out-of-order timestamps, and nonuniform intervals;
  - provider exception isolation while monkeypatched local reducer defects propagate;
  - sequential partial-date reads and total-failure status;
  - fixed warnings/errors contain no exception/payload sentinel;
  - recording client proves only `get_heart_rates` is called;
  - tool metadata and docs prohibit invalid duration, zone, coverage, sensor-equivalence, gap-cause, drift, recovery, stress, and coaching conclusions.

  Convert every genuine finding into a failing regression test before changing production code, then rerun Steps 1–2.

- [ ] **Step 4: Commit verified review fixes, if any.**

  Use a narrowly scoped message matching the finding, for example:

  ```bash
  git add src/garmin_mcp/ai_training/heart_rate.py tests/unit/ai_training/test_heart_rate.py
  git commit -m "fix(ai-training): harden wellness heart-rate normalization"
  ```

  If the audit has no findings, create no empty commit.

- [ ] **Step 5: Push and open a ready-for-review PR.**

  ```bash
  git push -u origin feat/ai-wellness-heart-rate-v1
  gh pr create --base main --head feat/ai-wellness-heart-rate-v1 \
    --title "feat: add bounded wellness heart-rate context" \
    --body-file /tmp/garmin-mcp-wellness-heart-rate-pr.md
  ```

  The PR body must summarize the explicit-fetch product boundary, normalized modes, nonuniform-sampling guardrails, strict read-only seam, exact 15-tool profile change, offline test/build evidence, pinned Garmin 0.3.10 assumptions, and deferred cross-midnight/pagination/inference work. Create the PR as ready for review, not draft.

## Plan self-review checklist

- Every approved argument, output, availability, failure, cap, time-provenance, gap, security, and interpretation rule is assigned to Tasks 2–5.
- The provider/service/MCP/profile/docs boundaries match the approved design; neither `get_training_context` nor upstream-oriented modules are redesigned.
- All behavior changes begin with a failing test and end with a focused green run and commit.
- Current-facing docs change atomically with the 15-tool profile; historical specs/plans are not implementation targets.
- Normal acceptance is fully offline and includes lock/build/diff checks plus an independent adversarial review.
