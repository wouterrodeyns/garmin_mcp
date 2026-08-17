# AI Sleep Trend Garmin Field Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate nightly resting heart rate and sleep SpO2 from both verified Garmin sleep-response shapes while retaining strict validation and denominator-aware null handling.

**Architecture:** Keep the existing one-`get_sleep_data(date)`-read contract. Add a strict numeric-alias coalescer inside the sleep normalizer, use it for the nested/root resting-HR variants and lowercase/all-caps SpO2 variants, and reject conflicting aliases rather than selecting silently.

**Tech Stack:** Python 3.12, pinned `garminconnect==0.3.10`, pytest.

---

## File map

| File | Responsibility |
|---|---|
| `src/garmin_mcp/ai_training/sleep.py` | Strictly coalesce the verified Garmin field aliases |
| `tests/unit/ai_training/test_sleep.py` | Pin observed Forerunner response shape, compatibility, conflicts, and null behavior |
| `docs/ai-sleep-trend.md` | Document compatible source shapes and unchanged one-read behavior |

### Task 1: Add RED compatibility and conflict tests

**Files:**
- Modify: `tests/unit/ai_training/test_sleep.py`

- [ ] **Step 1: Add an observed-shape regression test**

Create a payload based on the live, safely inspected Forerunner response: remove
the nested resting-HR value, add the root value, and use `averageSPO2` /
`lowestSPO2` in the sleep summary. Assert that the existing public facts become
`42`, `97.0`, and `86`.

```python
def test_normalize_accepts_observed_root_hr_and_uppercase_spo2_shape() -> None:
    payload = complete_sleep_payload()
    payload["dailySleepDTO"].pop("restingHeartRate")
    payload["restingHeartRate"] = 42
    payload["wellnessSpO2SleepSummaryDTO"] = {
        "averageSPO2": 97.0,
        "lowestSPO2": 86,
    }

    assert normalize_sleep_night(payload, "2026-08-17") == normalized_facts(
        resting_hr_bpm=42,
        average_spo2_percent=97.0,
        lowest_spo2_percent=86,
    )
```

- [ ] **Step 2: Add alias agreement and conflict tests**

Assert equal duplicate aliases are accepted. Parametrize root/nested resting HR
and both SpO2 aliases with unequal values and assert `InvalidSleepResponse`.
Also assert an invalid alternate alias is rejected even when the original alias
is valid, preserving strict handling of supported fields.

- [ ] **Step 3: Prove RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/unit/ai_training/test_sleep.py \
  -k 'observed_root_hr or compatible_alias or conflicting_alias'
```

Expected: the observed-shape and alias-safety assertions fail because only the
original paths are currently read.

### Task 2: Implement strict alias coalescing

**Files:**
- Modify: `src/garmin_mcp/ai_training/sleep.py`
- Test: `tests/unit/ai_training/test_sleep.py`

- [ ] **Step 1: Add the minimal helper**

Build on `_optional_number` so every supported alias is type/range validated.
Return the sole/equal value, `None` when all aliases are absent/null, and reject
conflicting non-null values.

```python
def _compatible_number(
    sources: tuple[tuple[dict[Any, Any], str], ...],
    minimum: int,
    maximum: int,
) -> int | float | None:
    values = [
        value
        for parent, key in sources
        if (value := _optional_number(parent, key, minimum, maximum)) is not None
    ]
    if not values:
        return None
    if any(value != values[0] for value in values[1:]):
        raise InvalidSleepResponse
    return values[0]
```

- [ ] **Step 2: Apply the verified aliases**

Use `_compatible_number` for:

```python
resting_hr_bpm = _compatible_number(
    ((daily, "restingHeartRate"), (raw, "restingHeartRate")), 1, 300
)
average_spo2_percent = _compatible_number(
    ((spo2, "averageSpo2"), (spo2, "averageSPO2")), 0, 100
)
lowest_spo2_percent = _compatible_number(
    ((spo2, "lowestSpo2"), (spo2, "lowestSPO2")), 0, 100
)
```

Do not call `get_heart_rates`, `get_spo2_data`, raw HTTP, or any additional MCP
tool. Keep the request count at exactly one sleep read per date.

- [ ] **Step 3: Prove GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/unit/ai_training/test_sleep.py \
  tests/unit/ai_training/test_providers.py
```

Expected: all focused tests pass.

### Task 3: Update public compatibility documentation and verify

**Files:**
- Modify: `docs/ai-sleep-trend.md`
- Test: `tests/unit/test_ai_sleep_trend_docs.py`

- [ ] **Step 1: Document the compatibility behavior**

State that the normalizer accepts the verified root/nested resting-HR and
lowercase/all-caps SpO2 sleep-summary shapes, rejects conflicting variants, and
still makes one sleep request per date.

- [ ] **Step 2: Pin the statement in the documentation test**

Add exact assertions for `restingHeartRate`, `averageSPO2`, and `lowestSPO2` so
the compatibility note cannot disappear unnoticed.

- [ ] **Step 3: Run focused and full verification**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/unit/ai_training/test_sleep.py \
  tests/unit/ai_training/test_providers.py \
  tests/unit/test_ai_sleep_trend_docs.py
ruff check .
ruff format --check .
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Expected: all commands pass. Then run one read-only three-night service check
against the configured Garmin token and print only the three public metrics;
do not store raw responses or credentials.

- [ ] **Step 4: Commit**

```bash
git add \
  src/garmin_mcp/ai_training/sleep.py \
  tests/unit/ai_training/test_sleep.py \
  docs/ai-sleep-trend.md \
  tests/unit/test_ai_sleep_trend_docs.py \
  docs/superpowers/specs/2026-08-17-ai-sleep-trend-v1-design.md \
  docs/superpowers/plans/2026-08-17-ai-sleep-trend-garmin-field-compatibility.md
git commit -m "fix(ai-training): map Garmin sleep health fields"
```
