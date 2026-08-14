# Current-day Wellness Heart-rate Time Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local-window and binned wellness heart-rate reads work for Garmin's incomplete current-day bounds without guessing historical or UTC semantics.

**Architecture:** Keep the existing provider and one-read-per-date orchestration. Normalize complete and provisional time provenance inside `heart_rate.py`, derive the effective current date and MCP host offset from an internal keyword-only `now` seam, and expose a stable provenance basis plus a fixed warning. Preserve validated source counts when local provenance is still unavailable.

**Tech Stack:** Python 3.12+, `garminconnect==0.3.2`, FastMCP, pytest, existing `ai_training` provider/service/tool layers.

---

### Task 1: Normalize provisional current-day provenance

**Files:**
- Modify: `src/garmin_mcp/ai_training/heart_rate.py:42-70,262-370,512-579,596-698`
- Modify: `tests/unit/ai_training/test_heart_rate.py`

- [ ] **Step 1: Write failing service regressions**

Add this incomplete-current-day payload helper and regression:

```python
def incomplete_current_day_payload(*, calendar_date: str = "2026-08-14") -> dict[str, Any]:
    return canonical_payload(
        calendarDate=calendar_date,
        startTimestampGMT="2026-08-13T22:00:00.0",
        endTimestampGMT="2026-08-14T11:40:00.0",
        startTimestampLocal="2026-08-14T00:00:00.0",
        endTimestampLocal="2026-08-15T00:00:00.0",
        heart_rate_values=[
            [1786696200000, 60],  # 2026-08-14 10:30 +02:00
            [1786703400000, 70],  # 2026-08-14 12:30 +02:00
        ],
    )


def test_current_day_incomplete_bounds_use_provisional_start_offset_for_local_window():
    client = RecordingClient(
        payloads={"2026-08-14": incomplete_current_day_payload()}
    )

    result = get_wellness_heart_rate_service(
        client,
        "2026-08-14",
        resolution="raw",
        start_time="10:00",
        end_time="11:00",
        now=datetime(2026, 8, 14, 12, 0, tzinfo=timezone(timedelta(hours=2))),
    )

    assert result["status"] == "success"
    assert result["days"][0]["time_provenance"] == {
        "local_offset_minutes": 120,
        "local_time_available": True,
        "local_time_basis": "current_day_start_bound",
    }
    assert result["days"][0]["sampling"]["source_points"] == 2
    assert result["days"][0]["sampling"]["returned_points"] == 1
    assert result["days"][0]["points"][0]["time_local"] == "2026-08-14T10:30:00+02:00"
    assert result["warnings"] == [{
        "provider": "wellness_heart_rate",
        "date": "2026-08-14",
        "code": "local_time_provisional",
        "message": "Current-day local wellness heart-rate time uses Garmin's provisional start-bound offset.",
    }]
    assert client.calls == ["2026-08-14"]
```

Add these separate boundary tests:

```python
def test_current_day_incomplete_bounds_support_local_bins():
    result = get_wellness_heart_rate_service(
        RecordingClient(
            payloads={"2026-08-14": incomplete_current_day_payload()}
        ),
        "2026-08-14",
        resolution="5m",
        start_time="10:00",
        end_time="11:00",
        now=datetime(2026, 8, 14, 12, 0, tzinfo=timezone(timedelta(hours=2))),
    )

    assert result["status"] == "success"
    assert result["days"][0]["sampling"]["returned_points"] == 1
    assert result["days"][0]["points"][0] == {
        "start_time_local": "2026-08-14T10:30:00+02:00",
        "end_time_local": "2026-08-14T10:35:00+02:00",
        "start_time_utc": "2026-08-14T08:30:00Z",
        "end_time_utc": "2026-08-14T08:35:00Z",
        "min_bpm": 60,
        "mean_bpm": 60.0,
        "max_bpm": 60,
        "sample_count": 1,
    }


def test_incomplete_bounds_are_not_provisional_for_a_non_current_date():
    result = get_wellness_heart_rate_service(
        RecordingClient(
            payloads={"2026-08-14": incomplete_current_day_payload()}
        ),
        "2026-08-14",
        resolution="raw",
        start_time="10:00",
        end_time="11:00",
        now=datetime(2026, 8, 15, 12, 0, tzinfo=timezone(timedelta(hours=2))),
    )

    assert result["status"] == "error"
    assert result["days"][0]["time_provenance"] == {
        "local_offset_minutes": None,
        "local_time_available": False,
        "local_time_basis": None,
    }
    assert result["days"][0]["sampling"]["source_points"] == 2
    assert result["days"][0]["points"] == []
    assert [warning["code"] for warning in result["warnings"]] == [
        "local_time_unavailable"
    ]


def test_completed_current_day_bound_disagreement_stays_unavailable():
    payload = incomplete_current_day_payload()
    payload["endTimestampGMT"] = "2026-08-14T23:00:00.0"

    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={"2026-08-14": payload}),
        "2026-08-14",
        resolution="raw",
        start_time="10:00",
        end_time="11:00",
        now=datetime(2026, 8, 14, 12, 0, tzinfo=timezone(timedelta(hours=2))),
    )

    assert result["status"] == "error"
    assert result["days"][0]["sampling"]["source_points"] == 2
    assert [warning["code"] for warning in result["warnings"]] == [
        "local_time_unavailable"
    ]


def test_complete_bounds_publish_complete_basis():
    result = get_wellness_heart_rate_service(
        RecordingClient(
            payloads={"2026-08-14": canonical_payload(heart_rate_values=[])}
        ),
        "2026-08-14",
        resolution="daily",
        now=datetime(2026, 8, 14, 12, 0, tzinfo=timezone(timedelta(hours=2))),
    )

    assert result["days"][0]["time_provenance"] == {
        "local_offset_minutes": 120,
        "local_time_available": True,
        "local_time_basis": "complete_bounds",
    }


@pytest.mark.parametrize(
    ("calendar_date", "garmin_offset", "host_offset"),
    [
        ("2026-03-29", 60, 120),   # spring-forward: stale Garmin start offset
        ("2026-10-25", 120, 60),   # fall-back: stale Garmin start offset
    ],
)
def test_dst_start_offset_mismatch_fails_closed(
    calendar_date: str, garmin_offset: int, host_offset: int
):
    payload = incomplete_current_day_payload(calendar_date=calendar_date)
    # The fixture builder supplies the Garmin bounds; adjust them to the
    # transition's stale start offset while retaining an incomplete end pair.
    payload["startTimestampGMT"] = f"{calendar_date}T00:00:00.0"
    payload["startTimestampLocal"] = (
        datetime.fromisoformat(calendar_date)
        + timedelta(minutes=garmin_offset)
    ).isoformat(timespec="milliseconds")
    result = get_wellness_heart_rate_service(
        RecordingClient(payloads={calendar_date: payload}),
        calendar_date,
        resolution="raw",
        start_time="10:00",
        end_time="11:00",
        now=datetime.fromisoformat(calendar_date).replace(
            hour=12, tzinfo=timezone(timedelta(minutes=host_offset))
        ),
    )

    assert result["status"] == "error"
    assert result["days"][0]["time_provenance"]["local_time_available"] is False


def test_current_day_incomplete_bounds_require_matching_host_offset():
    result = get_wellness_heart_rate_service(
        RecordingClient(
            payloads={"2026-08-14": incomplete_current_day_payload()}
        ),
        "2026-08-14",
        resolution="raw",
        start_time="10:00",
        end_time="11:00",
        now=datetime(2026, 8, 14, 12, 0, tzinfo=timezone(timedelta(hours=2))),
    )

    assert result["status"] == "success"
    assert result["days"][0]["time_provenance"]["local_time_basis"] == (
        "current_day_start_bound"
    )


def test_complete_bounds_ignore_host_offset_when_bounds_agree():
    result = get_wellness_heart_rate_service(
        RecordingClient(
            payloads={"2026-08-14": canonical_payload(heart_rate_values=[])}
        ),
        "2026-08-14",
        resolution="daily",
        now=datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert result["days"][0]["time_provenance"] == {
        "local_offset_minutes": 120,
        "local_time_available": True,
        "local_time_basis": "complete_bounds",
    }


class SecondOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(seconds=30)


class DateTimeSubclass(datetime):
    pass


@pytest.mark.parametrize(
    "invalid_now",
    [
        datetime(2026, 8, 14, 12, 0),
        datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None),
        "2026-08-14T12:00:00+02:00",
        date(2026, 8, 14),
        datetime(2026, 8, 14, 12, 0, tzinfo=SecondOffset()),
        DateTimeSubclass(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
    ],
)
def test_invalid_now_inputs_raise_type_error(invalid_now: object):
    with pytest.raises(TypeError):
        get_wellness_heart_rate_service(
            RecordingClient(payloads={"2026-08-14": canonical_payload()}),
            "2026-08-14",
            now=invalid_now,
        )
```

Here `SecondOffset` is a `tzinfo` whose `utcoffset()` returns 30 seconds and
`DateTimeSubclass` subclasses `datetime`; both demonstrate that the seam
requires an exact built-in aware datetime with a supported whole-minute offset.

- [ ] **Step 2: Run the regressions and verify RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-current-day-fix-cache uv run pytest \
  tests/unit/ai_training/test_heart_rate.py -k \
  'current_day or incomplete_bounds or preserves_validated_source_points or complete_bounds_basis' -q
```

Expected: failures because the service has no `now` seam, rejects the incomplete current-day end pair, resets source counts, and omits `local_time_basis`.

- [ ] **Step 3: Implement exact provenance classification**

Add `local_time_basis: str | None` to `DayFacts`. Replace `_local_offset_minutes` with helpers following this exact policy:

```python
def _offset_minutes(local_bound: datetime, gmt_bound: datetime) -> int | None:
    delta = local_bound.replace(tzinfo=timezone.utc) - gmt_bound.replace(tzinfo=timezone.utc)
    microseconds = (
        (delta.days * 86_400 + delta.seconds) * 1_000_000
        + delta.microseconds
    )
    if microseconds % 60_000_000:
        return None
    minutes = microseconds // 60_000_000
    return minutes if -1439 <= minutes <= 1439 else None


def _supported_offset_minutes(value: datetime) -> int | None:
    offset = value.utcoffset()
    if offset is None or offset.microseconds or offset.seconds % 60:
        return None
    minutes = offset.days * 1_440 + offset.seconds // 60
    return minutes if -1439 <= minutes <= 1439 else None


def _local_time_provenance(
    raw: dict[Any, Any], date_text: str, now: datetime
) -> tuple[int | None, str | None]:
    start_gmt = _parse_naive_bound(raw, "startTimestampGMT")
    end_gmt = _parse_naive_bound(raw, "endTimestampGMT")
    start_local = _parse_naive_bound(raw, "startTimestampLocal")
    end_local = _parse_naive_bound(raw, "endTimestampLocal")
    if None in (start_gmt, end_gmt, start_local, end_local):
        return None, None

    assert start_gmt is not None and end_gmt is not None
    assert start_local is not None and end_local is not None
    start_offset = _offset_minutes(start_local, start_gmt)
    end_offset = _offset_minutes(end_local, end_gmt)
    if start_offset is not None and start_offset == end_offset:
        return start_offset, "complete_bounds"

    host_offset = _supported_offset_minutes(now)
    if (
        date_text != now.date().isoformat()
        or start_offset is None
        or host_offset is None
        or start_offset != host_offset
    ):
        return None, None
    if end_local - start_local != timedelta(days=1):
        return None, None
    implied_full_day_end_gmt = end_local - timedelta(minutes=start_offset)
    if not (start_gmt <= end_gmt < implied_full_day_end_gmt):
        return None, None
    return start_offset, "current_day_start_bound"
```

Change `_normalize_day_facts` to receive `now`, store both returned values, and validate local timestamp representability exactly as before. Complete-bound agreement is evaluated before the host-offset guard, so complete bounds remain valid even when their agreed offset differs from the host.

Add a keyword-only deterministic seam without changing the MCP call shape:

```python
def get_wellness_heart_rate_service(
    client: Any,
    start_date: Any,
    end_date: Any = None,
    resolution: Any = "raw",
    start_time: Any = None,
    end_time: Any = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = datetime.now().astimezone() if now is None else now
    if type(effective_now) is not datetime:
        raise TypeError("now must be an exact built-in aware datetime")
    if effective_now.tzinfo is None or effective_now.utcoffset() is None:
        raise TypeError("now must be an exact built-in aware datetime")
    if _supported_offset_minutes(effective_now) is None:
        raise TypeError("now must have a supported whole-minute UTC offset")
```

Keep trusted internal misuse visible; do not catch the `TypeError`.

Add the fixed warning:

```python
_LOCAL_TIME_PROVISIONAL_WARNING = (
    "Current-day local wellness heart-rate time uses Garmin's provisional start-bound offset."
)
```

Append it only when `facts.local_time_basis == "current_day_start_bound"`. A warning alone must not change status.

Change public provenance to exactly:

```python
"time_provenance": {
    "local_offset_minutes": facts.offset_minutes,
    "local_time_available": facts.offset_minutes is not None,
    "local_time_basis": facts.local_time_basis,
}
```

Change `_empty_day` to accept `source_points: int = 0`; pass `facts.source_points` only for the local-provenance-unavailable branch. Failed reads and invalid DTOs retain zero.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-current-day-fix-cache uv run pytest \
  tests/unit/ai_training/test_heart_rate.py -q
```

Expected: all heart-rate service tests pass.

- [ ] **Step 5: Commit the service fix**

```bash
git add src/garmin_mcp/ai_training/heart_rate.py tests/unit/ai_training/test_heart_rate.py
git commit -m "fix(ai-training): support current-day heart-rate windows"
```

### Task 2: Publish and pin provisional provenance

**Files:**
- Modify: `src/garmin_mcp/ai_training/tools.py:53-66`
- Modify: `docs/ai-wellness-heart-rate.md`
- Modify: `tests/integration/test_ai_wellness_heart_rate_tools.py:277-301`
- Modify: `tests/unit/test_ai_wellness_heart_rate_docs.py`

- [ ] **Step 1: Write failing metadata and documentation tests**

Update the stable schema assertion:

```python
PROVENANCE_KEYS = [
    "local_offset_minutes",
    "local_time_available",
    "local_time_basis",
]
```

Require every example to use only `"complete_bounds"`,
`"current_day_start_bound"`, or `null`. Add assertions that the guide and real
FastMCP tool description contain all of these phrases:

```text
current-day start-bound offset is provisional
never borrows the previous day's offset
never interprets a local window as UTC
local_time_provisional
```

- [ ] **Step 2: Run documentation tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-current-day-fix-cache uv run pytest \
  tests/integration/test_ai_wellness_heart_rate_tools.py \
  tests/unit/test_ai_wellness_heart_rate_docs.py -q
```

Expected: failures because examples and tool metadata lack the new basis and provisional warning contract.

- [ ] **Step 3: Update tool metadata and current-facing documentation**

Add this guardrail to the MCP docstring:

```text
For an incomplete current day, local time may use Garmin's start-bound offset
provisionally and reports local_time_provisional; it never borrows yesterday's
offset or interprets a local window as UTC.
```

Update `docs/ai-wellness-heart-rate.md` to define all three basis values, include
the fixed warning vocabulary, explain that the service uses one Garmin read per
requested date, and add `local_time_basis` to every JSON example without changing
the point/bin schemas or 262,144-byte cap.

- [ ] **Step 4: Run focused service, MCP, and documentation tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-current-day-fix-cache uv run pytest \
  tests/unit/ai_training/test_heart_rate.py \
  tests/integration/test_ai_wellness_heart_rate_tools.py \
  tests/unit/test_ai_wellness_heart_rate_docs.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit documentation and metadata**

```bash
git add src/garmin_mcp/ai_training/tools.py docs/ai-wellness-heart-rate.md \
  tests/integration/test_ai_wellness_heart_rate_tools.py \
  tests/unit/test_ai_wellness_heart_rate_docs.py
git commit -m "docs(ai-training): explain provisional wellness time"
```

### Task 3: Verify and publish the fix PR

**Files:**
- Verify all files changed by Tasks 1-2

- [ ] **Step 1: Run the complete offline suite**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-current-day-fix-cache uv run pytest -m "not e2e" -q
```

Expected: zero failures; only live-account E2E tests are deselected.

- [ ] **Step 2: Run syntax and diff verification**

```bash
UV_CACHE_DIR=/private/tmp/garmin-mcp-current-day-fix-cache uv run python -m py_compile \
  src/garmin_mcp/ai_training/heart_rate.py \
  src/garmin_mcp/ai_training/tools.py
git diff --check main...HEAD
git status --short
```

Expected: compilation and diff checks succeed; the worktree is clean.

- [ ] **Step 3: Push and open a ready-for-review PR**

```bash
git push -u origin fix/wellness-current-day-time
gh pr create --base main --head fix/wellness-current-day-time \
  --title "fix: support current-day wellness heart-rate windows" \
  --body-file /private/tmp/garmin-mcp-current-day-pr-body.md
```

The PR body must summarize the observed Garmin bound mismatch, provisional
start-bound policy, truthful source counts, unchanged response-size scope, and
fresh test evidence. Create it ready for review, not as a draft.
