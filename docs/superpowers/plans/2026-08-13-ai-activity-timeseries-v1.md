# AI Activity Time Series v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single read-only, one-download MCP tool that exposes up to 600 privacy-safe, paged FIT-record time-series bins for one Garmin activity.

**Architecture:** Keep the feature wholly inside the fork-owned `ai_activity` seam: the provider performs the sole bounded ORIGINAL download, `timeseries.py` preflights and streams one FIT member while retaining only numeric allowlisted facts, and `timeseries_service.py` validates requests and builds the stable envelope. The existing `activity_analysis.py`/`fitparse` path remains unchanged; FastMCP, the package initializer, the root profile, and current-facing guides only wire the new narrow service into the existing application.

**Tech Stack:** Python 3.12, `garminconnect==0.3.10`, `fitdecode==0.11.0`, existing `fitparse>=1.2.0`, FastMCP 1.x/Pydantic `StrictInt` and `StrictStr`, `zipfile`, pytest/pytest-asyncio, uv.

---

## File map and non-negotiable boundaries

- Modify `pyproject.toml` and `uv.lock`: pin `fitdecode==0.11.0` without changing the existing `fitparse>=1.2.0` requirement.
- Modify `src/garmin_mcp/ai_activity/providers.py`: add the only permitted original-FIT download seam; retain the existing activity-summary provider functions unchanged.
- Create `src/garmin_mcp/ai_activity/timeseries.py`: classic-ZIP preflight, `LimitedReader`, strict `fitdecode.FitReader` iteration, numeric FIT-field extraction, pure window reduction, and no Garmin/FastMCP imports.
- Create `src/garmin_mcp/ai_activity/timeseries_service.py`: strict direct-call validation, one provider call after validation, fixed error/warning vocabulary, and ordered stable envelopes.
- Modify `src/garmin_mcp/ai_activity/tools.py` and `src/garmin_mcp/ai_activity/__init__.py`: register/export the new service beside the existing activity summary tool using the existing configured client.
- Modify `src/garmin_mcp/__init__.py`: insert exactly `get_activity_timeseries` into `TOOL_PROFILES["ai-coach"]`; do not add a client global or alter filter precedence.
- Create focused offline tests under `tests/unit/ai_activity/` and `tests/integration/test_ai_activity_timeseries_tools.py`; extend only the existing dependency, profile, startup, and current-document contract tests.
- Create `docs/ai-activity-timeseries.md`; update `README.md`, `docs/setup.md`, `docs/ai-training.md`, `docs/ai-workouts.md`, and `docs/ai-activity.md`. Do not edit historical specifications or plans.

The implementation must never call `get_activity_fit_data`, a raw request method, a mutation, `move_workout`, an activity summary endpoint, or a second download. It must never select, retain, or serialize location/raw-FIT/developer-field values. All foreign-provider and decoder failures cross explicitly named safe boundaries; programming defects in local helpers must propagate to tests instead of being transformed into sanitized outcomes.

### Shared implementation contracts established in this plan

Use these names consistently in every task; they give later agents a small, stable hand-off surface:

| Path | Public name and exact type |
| --- | --- |
| `providers.py` | `OriginalFitDownload(archive: bytes | None, failure_code: str | None)` and `download_original_fit(client: Any, activity_id: int) -> OriginalFitDownload` |
| `timeseries.py` | `RecordFact(raw_timestamp_seconds: int, timestamp_utc: datetime, encounter_index: int, heart_rate_bpm: int | float | None, speed_mps: int | float | None, cadence_rpm: int | float | None, power_w: int | float | None, altitude_m: int | float | None, grade_pct: int | float | None)` |
| `timeseries.py` | `ParseResult` holds a tuple of zero or more `RecordFact` values, `malformed_record_count: int`, and `failure_code: str | None`; `WindowResult(sampling: dict[str, Any], availability: dict[str, bool], series: dict[str, Any], next_start_seconds: int | None)`; `parse_original_fit(archive: bytes) -> ParseResult`; and `reduce_records(records: Sequence[RecordFact], start_seconds: int, duration_seconds: int, resolution_seconds: int) -> WindowResult` |
| `timeseries_service.py` | `get_activity_timeseries_service(client: Any, activity_id: Any, start_seconds: Any = 0, duration_seconds: Any = 600, resolution_seconds: Any = 1) -> dict[str, Any]` |

Each task below supplies the concrete behavior, tests, paths, and commands for its implementation.

### Task 1: Pin `fitdecode` and add the one-call original-download seam

**Implementer scope:** Fresh Terra/Luna agent. Own only dependency metadata, the new provider result/function, and their contract tests. Do not create parser/service/tool files in this task.

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/garmin_mcp/ai_activity/providers.py`
- Modify: `src/garmin_mcp/ai_activity/__init__.py`
- Modify: `tests/unit/test_project_dependencies.py`
- Modify: `tests/unit/ai_activity/test_providers.py`

- [ ] **Step 1: Write dependency and provider RED tests.**

  Add the exact package/lock assertions and a client that fails on every unapproved operation. The `download_activity` recorder must receive an `int` and the actual `Garmin.ActivityDownloadFormat.ORIGINAL` enum, while provider failures must expose only a code.

  ```python
  from garminconnect import Garmin
  from garmin_mcp.ai_activity.providers import (
      MAX_ORIGINAL_DOWNLOAD_BYTES,
      OriginalFitDownload,
      download_original_fit,
  )

  class DownloadOnlyClient:
      def __init__(self, payload: object) -> None:
          self.payload = payload
          self.calls: list[tuple[int, object]] = []

      def download_activity(self, activity_id: int, *, dl_fmt: object) -> object:
          self.calls.append((activity_id, dl_fmt))
          return self.payload

      def __getattr__(self, name: str) -> object:
          raise AssertionError(f"unexpected Garmin operation: {name}")

  def test_download_original_fit_uses_only_original_format_once() -> None:
      client = DownloadOnlyClient(bytearray(b"PK\\x03\\x04"))
      result = download_original_fit(client, 42)
      assert result == OriginalFitDownload(b"PK\\x03\\x04", None)
      assert client.calls == [(42, Garmin.ActivityDownloadFormat.ORIGINAL)]

  @pytest.mark.parametrize("payload", [None, "zip", [], memoryview(b"xy")[::2]])
  def test_download_original_fit_rejects_unsupported_payload_without_copying(payload: object) -> None:
      result = download_original_fit(DownloadOnlyClient(payload), 42)
      assert result == OriginalFitDownload(None, "invalid_download_payload")

  def test_download_original_fit_rejects_before_copying_an_oversized_mutable_payload(monkeypatch: pytest.MonkeyPatch) -> None:
      monkeypatch.setattr(providers, "MAX_ORIGINAL_DOWNLOAD_BYTES", 3)
      payload = bytearray(b"1234")
      result = download_original_fit(DownloadOnlyClient(payload), 42)
      assert result == OriginalFitDownload(None, "fit_download_too_large")
  ```

  Add a separate exact production-bound assertion: `assert MAX_ORIGINAL_DOWNLOAD_BYTES == 25_000_000`. This keeps the over-cap test allocation small while pinning the real contract.

  In `tests/unit/test_project_dependencies.py`, add:

  ```python
  def test_project_pins_fitdecode_without_replacing_fitparse() -> None:
      dependencies = PYPROJECT["project"]["dependencies"]
      assert "fitdecode==0.11.0" in dependencies
      assert "fitparse>=1.2.0" in dependencies
      assert _locked_version("fitdecode") == "0.11.0"
  ```

- [ ] **Step 2: Run the focused tests and record RED.**

  Run: `uv run pytest tests/unit/test_project_dependencies.py tests/unit/ai_activity/test_providers.py -q`

  Expected: FAIL during collection because `MAX_ORIGINAL_DOWNLOAD_BYTES`, `OriginalFitDownload`, and `download_original_fit` do not yet exist, and the dependency assertion fails.

- [ ] **Step 3: Pin and lock the public decoder dependency.**

  Add this line directly after the existing `fitparse` requirement; do not loosen, remove, or import `fitparse` from the new code:

  ```toml
      "fitparse>=1.2.0",
      "fitdecode==0.11.0",
  ```

  Regenerate only the lock resolution with `uv lock`. Confirm `uv.lock` has one `fitdecode` package at `0.11.0` and that `fitparse` remains present. Do not hand-edit package hashes or dependency metadata.

- [ ] **Step 4: Implement the strict provider boundary.**

  Add these definitions to `providers.py`; import `Garmin` from `garminconnect` and retain the current `ProviderResult` behavior for summary reads.

  ```python
  MAX_ORIGINAL_DOWNLOAD_BYTES = 25_000_000

  @dataclass(frozen=True)
  class OriginalFitDownload:
      archive: bytes | None
      failure_code: str | None

  def _archive_bytes(payload: Any) -> bytes | None:
      if type(payload) is bytes:
          return payload
      if type(payload) is bytearray:
          return bytes(payload)
      if (
          type(payload) is memoryview
          and payload.contiguous
          and payload.itemsize == 1
      ):
          return payload.tobytes()
      return None

  def download_original_fit(client: Any, activity_id: int) -> OriginalFitDownload:
      try:
          payload = client.download_activity(
              activity_id,
              dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL,
          )
      except Exception:
          return OriginalFitDownload(None, "download_failed")
      if type(payload) is bytes:
          payload_size = len(payload)
      elif type(payload) is bytearray:
          payload_size = len(payload)
      elif type(payload) is memoryview and payload.contiguous and payload.itemsize == 1:
          payload_size = payload.nbytes
      else:
          return OriginalFitDownload(None, "invalid_download_payload")
      if payload_size == 0:
          return OriginalFitDownload(None, "invalid_download_payload")
      if payload_size > MAX_ORIGINAL_DOWNLOAD_BYTES:
          return OriginalFitDownload(None, "fit_download_too_large")
      archive = _archive_bytes(payload)
      if archive is None:
          return OriginalFitDownload(None, "invalid_download_payload")
      return OriginalFitDownload(archive, None)
  ```

  Export the new constant, result, and function from `ai_activity/__init__.py`. The broad `except Exception` is deliberately confined to the foreign Garmin call; type/size validation happens outside it and no exception text/payload is retained.

- [ ] **Step 5: Run GREEN and check the call/read-only budget.**

  Run: `uv run pytest tests/unit/test_project_dependencies.py tests/unit/ai_activity/test_providers.py -q`

  Expected: PASS. The test suite confirms one `download_activity` call using `ORIGINAL`, zero calls for none beyond that method, all accepted payload forms at or below 25,000,000 bytes, and safe codes for raised/empty/wrong/oversized values.

- [ ] **Step 6: Commit the independently reviewable seam.**

  ```bash
  git add pyproject.toml uv.lock src/garmin_mcp/ai_activity/providers.py src/garmin_mcp/ai_activity/__init__.py tests/unit/test_project_dependencies.py tests/unit/ai_activity/test_providers.py
  git commit -m "feat: bound original FIT downloads"
  ```

**Review checkpoint:** Verify the diff adds `fitdecode==0.11.0` exactly once, leaves `fitparse>=1.2.0` unchanged, and does not add any Garmin operation other than `download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)`.

### Task 2: Preflight a classic ZIP and stream only one bounded FIT member

**Implementer scope:** Fresh Terra/Luna agent. Own `timeseries.py` archive primitives and archive-only tests. Do not implement FIT-frame interpretation, aggregation, service, or MCP wiring here.

**Files:**

- Create: `src/garmin_mcp/ai_activity/timeseries.py`
- Create: `tests/unit/ai_activity/timeseries_fakes.py`
- Create: `tests/unit/ai_activity/test_timeseries_archive.py`

- [ ] **Step 1: Add reusable safe ZIP and limit test helpers.**

  Create `timeseries_fakes.py` with fixture builders that produce valid small classic archives in memory and mutate only bounded structural fields. The helper below is the sole normal ZIP writer used by later tests; each malformed case starts from its returned immutable bytes and changes an EOCD/central/local field at a known offset.

  ```python
  from __future__ import annotations

  from io import BytesIO
  from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

  def make_zip(entries: dict[str, bytes], compression: int = ZIP_STORED) -> bytes:
      buffer = BytesIO()
      with ZipFile(buffer, "w", compression=compression, allowZip64=False) as archive:
          for name, value in entries.items():
              archive.writestr(name, value)
      return buffer.getvalue()

  def mutate_u16(payload: bytes, offset: int, value: int) -> bytes:
      changed = bytearray(payload)
      changed[offset:offset + 2] = value.to_bytes(2, "little")
      return bytes(changed)

  def mutate_u32(payload: bytes, offset: int, value: int) -> bytes:
      changed = bytearray(payload)
      changed[offset:offset + 4] = value.to_bytes(4, "little")
      return bytes(changed)

  def eocd_offset(payload: bytes) -> int:
      offset = payload.rfind(b"PK\\x05\\x06")
      assert offset >= 0
      return offset
  ```

  Add `CountingReadable`, whose `read(size)` appends every requested `size`, returns at most the requested bytes, and tracks bytes supplied. Later member-limit tests set a module constant with `monkeypatch` to `9` and feed a 10-byte member instead of allocating 25,000,001 bytes; one provider test continues to pin the real production constant.

- [ ] **Step 2: Write archive preflight RED tests before `ZipFile` can be reached.**

  Add parameterized tests for: empty/non-ZIP/raw FIT/gzip data (`invalid_fit_payload`); no FIT member (`invalid_fit_payload`); ZIP64 EOCD/locator/extra sentinels; multi-disk EOCD fields; an EOCD comment not ending at EOF; central-directory size/entry count/range errors; malformed central/local headers; encrypted/unsupported compression; absolute/traversal/backslash names; symlink mode; too-large auxiliary entry; zero/two/directory-only FIT entries; oversize declared FIT size; and a `ZipInfo` cross-check mismatch (`unsafe_fit_archive`). Use a harmless `archive.txt` to prove auxiliary files are never opened.

  Include this ordering regression, which proves preflight happens before `zipfile.ZipFile` construction rather than merely testing the preflight helper in isolation:

  ```python
  def test_invalid_eocd_is_rejected_before_zipfile_construction(monkeypatch: pytest.MonkeyPatch) -> None:
      from garmin_mcp.ai_activity import timeseries

      constructed = False

      def fail_if_constructed(*args: object, **kwargs: object) -> object:
          nonlocal constructed
          constructed = True
          raise AssertionError("ZipFile was constructed before EOCD preflight")

      monkeypatch.setattr(timeseries.zipfile, "ZipFile", fail_if_constructed)
      result = timeseries.parse_original_fit(b"not-a-zip")
      assert result.failure_code == "invalid_fit_payload"
      assert constructed is False
  ```

  Add a real small ZIP integration test that uses `make_zip({"activity.fit": b"not-a-fit", "notes.txt": b"safe"})`, wraps `ZipFile.open` to record only `activity.fit`, and asserts `ZipFile.read` is never called. At this stage strict decoding may return `fit_parse_failed`; the asserted integration facts are the one selected stream and zero auxiliary/full reads.

- [ ] **Step 3: Run the archive tests and capture RED.**

  Run: `uv run pytest tests/unit/ai_activity/test_timeseries_archive.py -q`

  Expected: FAIL during collection because `garmin_mcp.ai_activity.timeseries` does not exist.

- [ ] **Step 4: Implement manual EOCD/central/local preflight and `LimitedReader`.**

  Define the following exact production limits in `timeseries.py` and use literal comparisons against them:

  ```python
  MAX_ARCHIVE_ENTRIES = 16
  MAX_CENTRAL_DIRECTORY_BYTES = 65_536
  MAX_AUXILIARY_ENTRY_BYTES = 65_536
  MAX_FIT_MEMBER_BYTES = 25_000_000
  FIT_STREAM_READ_CHUNK_BYTES = 65_536
  ZIP_EOCD_TAIL_BYTES = 65_557
  ```

  Implement `_preflight_classic_zip(archive: bytes) -> PreflightResult` by searching only `archive[-min(len(archive), ZIP_EOCD_TAIL_BYTES):]` for classic EOCD signatures, accepting exactly one whose comment length finishes at `len(archive)`. Reject missing/ambiguous EOCD, ZIP64 signatures and sentinel values, disk numbers other than zero, unequal disk/total entry counts, count above 16, directory size above 65,536, and every range that escapes the archive or overlaps past the central directory.

  Parse each central record with `struct.unpack_from` and validate its variable name/extra/comment lengths, start disk, encryption bit, `ZIP_STORED`/`ZIP_DEFLATED` compression only, no ZIP64 extra tag, safe ordinary path, and a matching local header/data range before the central directory. Select exactly one non-directory name ending case-insensitively in `.fit`; require its declared uncompressed size at most 25,000,000. Return only immutable, primitive selected-member metadata (name, flags, compression, compressed/uncompressed sizes, local offset); do not retain archive entry objects.

  Implement the streaming wrapper exactly as follows:

  ```python
  class _MemberLimitExceeded(Exception):
      pass

  class LimitedReader:
      def __init__(self, source: BinaryIO) -> None:
          self._source = source
          self.bytes_read = 0

      def read(self, size: int = -1) -> bytes:
          requested = FIT_STREAM_READ_CHUNK_BYTES if size is None or size < 0 else size
          chunk = self._source.read(min(requested, FIT_STREAM_READ_CHUNK_BYTES))
          self.bytes_read += len(chunk)
          if self.bytes_read > MAX_FIT_MEMBER_BYTES:
              raise _MemberLimitExceeded
          return chunk
  ```

  `_open_fit_member` must call `_preflight_classic_zip` first, construct `zipfile.ZipFile(BytesIO(archive))` only after success, cross-check `ZipInfo.filename`, `flag_bits`, `compress_type`, `file_size`, `compress_size`, and `header_offset` against the preflight primitives, then yield `LimitedReader(zf.open(info, "r"))` from a context manager. Never call `zf.read`, `extract`, `extractall`, or open an auxiliary member.

- [ ] **Step 5: Make the parser entry point return only safe archive outcomes.**

  Implement `parse_original_fit` now so archive/preflight/open failures map to a `ParseResult((), 0, code)` without exception data. Until Task 3 supplies the decoder loop, call a private `_decode_fit_stream(stream)` that returns `ParseResult((), 0, "fit_parse_failed")`; replace that private function in the next task. Do not catch errors raised by `_preflight_classic_zip` itself: it must report a code rather than throw.

- [ ] **Step 6: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/ai_activity/test_timeseries_archive.py -q`

  Expected: PASS. All malformed/unsafe structures fail before `ZipFile`; safe archives open only their single FIT member through a 65,536-byte bounded reader; test-level caps exercise the 25,000,001-byte abort path without large allocations.

  ```bash
  git add src/garmin_mcp/ai_activity/timeseries.py tests/unit/ai_activity/timeseries_fakes.py tests/unit/ai_activity/test_timeseries_archive.py
  git commit -m "feat: preflight bounded FIT archives"
  ```

**Review checkpoint:** Inspect that archive classification is exactly `invalid_fit_payload` for absent classic ZIP structure/no ordinary FIT member and `unsafe_fit_archive` for every safety/structure limit. Confirm neither preflight metadata nor the opened stream is serialized or retained after parsing.

### Task 3: Decode FIT frames as a strict numeric allowlist stream

**Implementer scope:** Fresh Terra/Luna agent. Replace only Task 2's private decoder stub and add frame-level tests. Preserve preflight/open behavior and do not add Garmin/service/FastMCP imports.

**Files:**

- Modify: `src/garmin_mcp/ai_activity/timeseries.py`
- Modify: `tests/unit/ai_activity/timeseries_fakes.py`
- Create: `tests/unit/ai_activity/test_timeseries_frames.py`

- [ ] **Step 1: Extend fakes with frame-shaped objects rather than binary FIT writers.**

  Use `types.SimpleNamespace` or frozen dataclasses exposing only public attributes read by the implementation. The fake data frames deliberately have misleading names so tests prove numeric identity is used.

  ```python
  @dataclass(frozen=True)
  class FakeBaseType:
      identifier: int

  @dataclass(frozen=True)
  class FakeFieldDef:
      def_num: int
      base_type: FakeBaseType
      size: int
      is_dev: bool = False

  @dataclass(frozen=True)
  class FakeFieldData:
      field_def: FakeFieldDef | None
      field: object
      parent_field: object | None
      is_expanded: bool
      raw_value: object
      value: object

  def fake_record(fields: list[FakeFieldData], *, global_mesg_num: int = 20, time_offset: int | None = None) -> object:
      return SimpleNamespace(
          frame_type=fitdecode.FIT_FRAME_DATA,
          global_mesg_num=global_mesg_num,
          fields=fields,
          time_offset=time_offset,
          name="not-a-record",
          mesg_type=SimpleNamespace(name="not-a-record"),
      )
  ```

  Provide `fake_reader(frames)` as a context manager with `__iter__`, `__next__`, and `close`; monkeypatch `timeseries.fitdecode.FitReader` to return it. This is a decoder boundary fake, not a tautological parser mock: the production extraction code receives objects shaped like real public `fitdecode` frames/fields and must evaluate every identity/range rule itself.

- [ ] **Step 2: Write frame-stream RED tests covering the exact decoder contract.**

  Add direct tests for all seven standard tuples, wrong base type/size rejection, data-frame/global-20 numeric gate, zero/multiple timestamp discard, duplicate optional candidates becoming null, finite/Boolean/NaN/infinite/out-of-range metrics becoming null, raw timestamp lower/upper/integer/sentinel boundaries, aware-UTC cross-check, stable encounter indices, and out-of-order/duplicate timestamp preservation. Include these privacy and identity tests:

  ```python
  def test_developer_speed_named_like_standard_cannot_cross_numeric_boundary(monkeypatch: pytest.MonkeyPatch, fit_archive: bytes) -> None:
      timestamp = direct_timestamp(0x10000000)
      developer_speed = FakeFieldData(
          field_def=FakeFieldDef(6, FakeBaseType(0x84), 2, is_dev=True),
          field=SimpleNamespace(name="speed"),
          parent_field=None,
          is_expanded=False,
          raw_value=12_345_678,
          value=12_345_678,
      )
      monkeypatch.setattr(timeseries.fitdecode, "FitReader", lambda *a, **k: fake_reader([header(), fake_record([timestamp, developer_speed])]))
      result = timeseries.parse_original_fit(fit_archive)
      assert result.failure_code is None
      assert result.records[0].speed_mps is None
      assert "12345678" not in repr(result.records[0])
  ```

  Test the sole compressed timestamp path with `frame.time_offset is not None`, `field_def is None`, `field is fitdecode.profile.FIELD_TYPE_TIMESTAMP`, and no parent; reject every other expanded/component field including standard-looking enhanced speed `73` and enhanced altitude `78`. Test GPS `position_lat`/`position_long` and a developer `altitude` carrying coordinate sentinels are not present in `RecordFact.__dataclass_fields__` or serialized reduction inputs.

  Add limit tests by monkeypatching `MAX_FIT_FRAMES = 2`, `MAX_RECORD_MESSAGES = 1`, and `MAX_FIELDS_PER_DEFINITION = 1`, then using generators/fake frames just above the reduced cap. Separately assert production constants exactly equal 200,000, 100,000, and 128. Test a second header discards already collected facts and produces `chained_fit_unsupported`.

- [ ] **Step 3: Run the frame tests and capture RED.**

  Run: `uv run pytest tests/unit/ai_activity/test_timeseries_frames.py -q`

  Expected: FAIL because Task 2's `_decode_fit_stream` always reports `fit_parse_failed` and no `RecordFact` objects are emitted.

- [ ] **Step 4: Implement a narrow external-decoder boundary and exact frame counters.**

  Replace the stub with a `FitReader` constructed exactly as follows:

  ```python
  reader = fitdecode.FitReader(
      stream,
      check_crc=fitdecode.CrcCheck.RAISE,
      error_handling=fitdecode.ErrorHandling.RAISE,
      keep_raw_chunks=False,
  )
  ```

  Construct/iterate the foreign reader at a narrow boundary: catch exceptions from construction and from `next(iterator)` only, mapping them to `fit_parse_failed`; call local `_consume_frame` outside that handler so local defects are visible. Catch `_MemberLimitExceeded` separately as `fit_member_too_large`. Close the reader/stream in `finally` without retaining raw chunks, frames, messages, or `FieldData` instances.

  Count every yielded `FIT_FRAME_HEADER`, `FIT_FRAME_DEFINITION`, `FIT_FRAME_DATA`, and `FIT_FRAME_CRC` before filtering; return `frame_limit_exceeded` at 200,001. Require exactly one header and return `chained_fit_unsupported` immediately on the second. On every definition frame, check `len(frame.field_defs) + len(frame.dev_field_defs)` before any data filtering and return `definition_field_limit_exceeded` above 128. Count every `FIT_FRAME_DATA` having `global_mesg_num == 20` before extraction and return `record_limit_exceeded` at 100,001.

- [ ] **Step 5: Implement the numeric extractor and minimal fact construction.**

  Keep this table as a module constant; matching requires the entire `(def_num, base_type.identifier, size)` tuple and no display name:

  ```python
  STANDARD_FIELDS = {
      (253, 0x86, 4): "timestamp",
      (3, 0x02, 1): "heart_rate_bpm",
      (6, 0x84, 2): "speed_mps",
      (4, 0x02, 1): "cadence_rpm",
      (7, 0x84, 2): "power_w",
      (2, 0x84, 2): "altitude_m",
      (9, 0x83, 2): "grade_pct",
  }
  ```

  Iterate `frame.fields` exactly. A direct candidate requires `field_def is not None`, `field_def.is_dev is False`, `is_expanded is False`, and `parent_field is None`; never call field/message name lookup APIs. The only non-direct candidate is a timestamp when `frame.time_offset is not None`, `field_def is None`, `field is fitdecode.profile.FIELD_TYPE_TIMESTAMP`, and `parent_field is None`.

  A timestamp is valid only when `type(raw_value) is int`, `0x10000000 <= raw_value <= 0xFFFFFFFE`, and `value` is an aware zero-offset `datetime` equal to `FIT_EPOCH + timedelta(seconds=raw_value)`, where `FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)`. Zero/multiple valid timestamp candidates make the complete record malformed. For each optional metric, zero/multiple candidates or a normalization failure produces `None`, not a malformed record. Normalize only non-Boolean finite `int`/`float` values within these inclusive ranges: heart rate 1–300, speed 0–100, cadence 0–300, power 0–3000, altitude -1000–10000, and grade -100–100.

  Build each fact with primitive normalized values only:

  ```python
  return RecordFact(
      raw_timestamp_seconds=raw_timestamp,
      timestamp_utc=timestamp_value,
      encounter_index=encounter_index,
      heart_rate_bpm=values["heart_rate_bpm"],
      speed_mps=values["speed_mps"],
      cadence_rpm=values["cadence_rpm"],
      power_w=values["power_w"],
      altitude_m=values["altitude_m"],
      grade_pct=values["grade_pct"],
  )
  ```

  On completion return `no_timestamped_records` when no valid fact remains; otherwise return the unsorted tuple plus the activity-global malformed count. Do not sort/reduce yet.

- [ ] **Step 6: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/ai_activity/test_timeseries_archive.py tests/unit/ai_activity/test_timeseries_frames.py -q`

  Expected: PASS. Tests prove strict public `FitReader` configuration, per-call fresh reader state, exact numeric field identity, no GPS/developer/component retention, fatal cap behavior without truncation, and sanitized decoder failures.

  ```bash
  git add src/garmin_mcp/ai_activity/timeseries.py tests/unit/ai_activity/timeseries_fakes.py tests/unit/ai_activity/test_timeseries_frames.py
  git commit -m "feat: stream allowlisted FIT record facts"
  ```

**Review checkpoint:** Search `timeseries.py` for `get_value`, `get_raw_value`, `get_field`, `all_field_defs`, `position_`, `latitude`, and `longitude`; none may appear. Confirm the only retained per-record object is `RecordFact`, not a frame/message/field/raw chunk.

### Task 4: Deterministically sort, page, bin, and reduce pure record facts

**Implementer scope:** Fresh Terra/Luna agent. Work only in pure reduction code and its unit tests; take `RecordFact` fixtures as input and do not touch ZIP/decoder/service/tool code.

**Files:**

- Modify: `src/garmin_mcp/ai_activity/timeseries.py`
- Create: `tests/unit/ai_activity/test_timeseries_reduction.py`

- [ ] **Step 1: Write pure reduction RED tests with concrete facts.**

  Make a `fact(raw, index, **metrics)` helper using `FIT_EPOCH + timedelta(seconds=raw)`. Assert the default `[0, 600)` window, a coarse 5-second window, records at start/end boundaries, empty pauses, multiple records in a one-second bin, stable out-of-order sorting by `(raw_timestamp_seconds, encounter_index)`, duplicate timestamps, and all aligned array lengths.

  ```python
  def test_half_open_pages_neither_repeat_nor_skip_boundary_records() -> None:
      records = [fact(BASE + 599, 0), fact(BASE + 600, 1), fact(BASE + 1200, 2)]
      first = reduce_records(records, 0, 600, 1)
      second = reduce_records(records, 600, 600, 1)
      assert first.series["elapsed_seconds"] == [599]
      assert first.next_start_seconds == 600
      assert second.series["elapsed_seconds"] == [600]
      assert second.next_start_seconds == 1200
  ```

  Pin heart-rate average/minimum/maximum, speed average including zero, positive-speed-only pace average/fastest/slowest, zero-only speed bins, missing all-null arrays, `math.fsum` before rounding, decimal round-half-up, whole-int extrema/pace, source-record count, positive-delta median to three decimals, and irregular semantics. Add a max-cursor test using raw timestamps from `0x10000000` through `0xFFFFFFFE`: a cursor is emitted only when the globally valid later record proves `actual_end_seconds <= MAX_FIT_ELAPSED_SECONDS`; an end beyond that maximum has no cursor.

- [ ] **Step 2: Run the reduction tests and capture RED.**

  Run: `uv run pytest tests/unit/ai_activity/test_timeseries_reduction.py -q`

  Expected: FAIL because `reduce_records` is absent or returns no bins.

- [ ] **Step 3: Implement stable selection and pagination facts.**

  Start reduction with `sorted(records, key=lambda item: (item.raw_timestamp_seconds, item.encounter_index))`. Let `t0 = ordered[0].raw_timestamp_seconds`, calculate each whole-second elapsed value as `record.raw_timestamp_seconds - t0`, and select exactly `start_seconds <= elapsed < start_seconds + duration_seconds`. Use `bin_index = (elapsed - start_seconds) // resolution_seconds` and anchor `start_seconds + bin_index * resolution_seconds`; omit empty bins. Set `next_start_seconds` to the computed end only if a globally valid record has elapsed `>= actual_end_seconds`, otherwise `None`.

  Build timestamps only from the anchor, not source sample timing:

  ```python
  def _timestamp_text(t0_raw_seconds: int, anchor_seconds: int) -> str:
      instant = FIT_EPOCH + timedelta(seconds=t0_raw_seconds + anchor_seconds)
      return instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
  ```

- [ ] **Step 4: Implement all fixed output arrays and reductions.**

  Return `WindowResult` whose dictionaries contain exactly the following keys and no source/FIT extras:

  ```python
  sampling = {
      "source_records": len(selected),
      "returned_points": len(bins),
      "observed_median_interval_seconds": median_or_none,
      "irregular": irregular,
  }
  availability = {
      "heart_rate_bpm": False,
      "speed_mps": False,
      "pace_seconds_per_km": False,
      "cadence_rpm": False,
      "power_w": False,
      "altitude_m": False,
      "grade_pct": False,
  }
  series = {
      "elapsed_seconds": [], "timestamp": [], "sample_count": [],
      "heart_rate_bpm": {"average": [], "minimum": [], "maximum": []},
      "speed_mps": {"average": []},
      "pace_seconds_per_km": {"average": [], "fastest": [], "slowest": []},
      "cadence_rpm": {"average": []}, "power_w": {"average": []},
      "altitude_m": {"average": []}, "grade_pct": {"average": []},
  }
  ```

  Implement `_mean(values) = math.fsum(values) / len(values)` and quantize `Decimal(str(value))` with `ROUND_HALF_UP` for final display only. Round heart-rate/cadence/power/altitude/grade means to one decimal, speed mean to three decimals, heart-rate extrema and pace values to whole JSON `int`s. For each bin, derive pace from positive speeds only: mean `1000 / mean(positive_speeds)`, fastest `1000 / max(positive_speeds)`, slowest `1000 / min(positive_speeds)`. Set pace availability only when any positive speed exists; a recorded zero keeps speed availability true but pace arrays null.

- [ ] **Step 5: Run GREEN and check privacy-shaped output.**

  Run: `uv run pytest tests/unit/ai_activity/test_timeseries_reduction.py -q`

  Expected: PASS. Every listed series array has exactly `sampling["returned_points"]` values, no fabricated bins/values occur, equal-timestamp ordering is deterministic for a fixed archive encounter order, and all cursor/rounding facts match the contract.

- [ ] **Step 6: Commit the pure transformation.**

  ```bash
  git add src/garmin_mcp/ai_activity/timeseries.py tests/unit/ai_activity/test_timeseries_reduction.py
  git commit -m "feat: reduce FIT records into bounded series"
  ```

**Review checkpoint:** Inspect only the `WindowResult` serializer inputs. There must be no coordinate, field-definition, raw-value, request payload, or source-object key, including null placeholders. Verify the reducer has no side effects, client arguments, file handles, or logger.

### Task 5: Validate direct service calls and construct stable safe envelopes

**Implementer scope:** Fresh Terra/Luna agent. Own the new service and service tests, using the provider/parser/reducer contracts already committed. Do not modify FastMCP/root wiring in this task.

**Files:**

- Create: `src/garmin_mcp/ai_activity/timeseries_service.py`
- Create: `tests/unit/ai_activity/test_timeseries_service.py`
- Modify: `src/garmin_mcp/ai_activity/__init__.py`

- [ ] **Step 1: Write direct-service RED tests for validation precedence and envelope shape.**

  Monkeypatch `download_original_fit` and `parse_original_fit` with non-tautological `OriginalFitDownload`/`ParseResult` values, then assert invalid service inputs never call either seam. Cover Boolean, float, numeric string, list, object, signed/decimal/exponent/non-ASCII ID text, zero, both upper caps, zero duration/resolution, and a 601-bin request. Assert first failure ordering is ID, start, duration, resolution, point limit and that normalized fields accumulated before the failure remain while later fields are null.

  ```python
  def test_invalid_duration_keeps_only_safe_prefix_of_window(monkeypatch: pytest.MonkeyPatch) -> None:
      download = Mock()
      monkeypatch.setattr(service, "download_original_fit", download)
      result = get_activity_timeseries_service(object(), " 42 ", 7, 0, 1)
      assert result["error"] == {
          "provider": "input",
          "code": "invalid_duration_seconds",
          "message": "duration_seconds must be an integer from 1 through 86400.",
      }
      assert result["activity_id"] == 42
      assert result["window"] == {
          "requested_start_seconds": 7,
          "actual_end_seconds": None,
          "resolution_seconds": None,
      }
      download.assert_not_called()
  ```

  Add exact top-level-order, empty-series, availability, warning-array, client-unavailable, download-failure/payload/size, every parser failure code, no-globally-valid-record outcome, globally malformed-vs-window-empty status, and recursive sanitization tests. The recursive helper must reject keys/values containing `token=`, `https://`, `authorization`, `request_id`, `position`, `latitude`, `longitude`, `coordinate`, `polyline`, a fake raw exception, or a coordinate sentinel.

- [ ] **Step 2: Run service tests and capture RED.**

  Run: `uv run pytest tests/unit/ai_activity/test_timeseries_service.py -q`

  Expected: FAIL during collection because `timeseries_service.py` and `get_activity_timeseries_service` do not exist.

- [ ] **Step 3: Implement strict normalizers and the ordered empty envelope.**

  Use `type(value) is int`, never `isinstance`, for all integer inputs. `_normalize_activity_id` accepts an `int` in `1..9007199254740991` or a `str` whose `strip()` result is nonempty ASCII decimal digits and within that range. `_normalize_start`, `_normalize_duration`, and `_normalize_resolution` accept only integer types in `0..4026531838`, `1..86400`, and `1..300`, respectively. Compute `actual_end_seconds = start + duration` only after both are valid, then reject `-(-duration // resolution) > 600`.

  Implement an empty result whose insertion order is fixed:

  ```python
  def _empty_envelope(
      activity_id: int | None = None,
      start_seconds: int | None = None,
      actual_end_seconds: int | None = None,
      resolution_seconds: int | None = None,
  ) -> dict[str, Any]:
      return {
          "status": "error",
          "error": None,
          "activity_id": activity_id,
          "window": {
              "requested_start_seconds": start_seconds,
              "actual_end_seconds": actual_end_seconds,
              "resolution_seconds": resolution_seconds,
          },
          "sampling": {"source_records": 0, "returned_points": 0, "observed_median_interval_seconds": None, "irregular": False},
          "availability": {"heart_rate_bpm": False, "speed_mps": False, "pace_seconds_per_km": False, "cadence_rpm": False, "power_w": False, "altitude_m": False, "grade_pct": False},
          "series": {"elapsed_seconds": [], "timestamp": [], "sample_count": [], "heart_rate_bpm": {"average": [], "minimum": [], "maximum": []}, "speed_mps": {"average": []}, "pace_seconds_per_km": {"average": [], "fastest": [], "slowest": []}, "cadence_rpm": {"average": []}, "power_w": {"average": []}, "altitude_m": {"average": []}, "grade_pct": {"average": []}},
          "warnings": [],
      }
  ```

- [ ] **Step 4: Map all safe outcomes and orchestrate exactly one read.**

  Keep this literal error mapping in one `ERRORS` dictionary and use it for every envelope/error assertion:

  | code | provider | message |
  | --- | --- | --- |
  | `invalid_activity_id` | `input` | `activity_id must be a positive integer or ASCII decimal string from 1 through 9007199254740991.` |
  | `invalid_start_seconds` | `input` | `start_seconds must be an integer from 0 through 4026531838.` |
  | `invalid_duration_seconds` | `input` | `duration_seconds must be an integer from 1 through 86400.` |
  | `invalid_resolution_seconds` | `input` | `resolution_seconds must be an integer from 1 through 300.` |
  | `point_limit_exceeded` | `input` | `ceil(duration_seconds / resolution_seconds) must not exceed 600.` |
  | `client_unavailable` | `client` | `Garmin client is unavailable. Authenticate with garmin-mcp-auth and restart the server.` |
  | `download_failed` | `garmin` | `Original FIT download is unavailable. Retry later or re-authenticate.` |
  | `invalid_download_payload` | `garmin` | `Original FIT download returned an invalid payload.` |
  | `fit_download_too_large` | `garmin` | `Original FIT download exceeds the 25 MB limit.` |
  | `invalid_fit_payload` | `fit` | `Original FIT data is invalid or unavailable.` |
  | `unsafe_fit_archive` | `fit` | `Original FIT archive violates safety limits.` |
  | `fit_member_too_large` | `fit` | `Original FIT member exceeds the 25 MB limit.` |
  | `fit_parse_failed` | `fit` | `Original FIT data could not be parsed.` |
  | `chained_fit_unsupported` | `fit` | `Chained FIT files are not supported.` |
  | `frame_limit_exceeded` | `fit` | `Original FIT data exceeds the 200000-frame limit.` |
  | `definition_field_limit_exceeded` | `fit` | `Original FIT data exceeds the 128-field definition limit.` |
  | `record_limit_exceeded` | `fit` | `Original FIT data exceeds the 100000-record limit.` |
  | `no_timestamped_records` | `fit` | `Original FIT data contains no usable timestamped record messages.` |

  After all successful validation, reject a missing client without a provider call; otherwise call `download_original_fit(client, normalized_id)` exactly once, call `parse_original_fit(download.archive)` exactly once only on a successful download, and call `reduce_records` only on a successful parse. Do not use a broad service `try/except`: the provider/parser return their expected safe codes and local programming errors propagate.

- [ ] **Step 5: Implement status, warning, and window projection rules.**

  On a good parse, copy only `WindowResult.sampling`, `availability`, and `series` into the empty envelope. Add `window["next_start_seconds"] = result.next_start_seconds` only when it is not `None`. If selected source records are zero, set `status` to `success` and leave warnings empty even when the parse's global malformed count is positive. If selected records exist and malformed count is positive, set `partial_success` and append exactly:

  ```python
  {
      "provider": "fit",
      "code": "malformed_records_discarded",
      "message": "Malformed FIT record messages were discarded.",
      "count": parsed.malformed_record_count,
  }
  ```

  Otherwise set `success`. Never return partial reductions after a fatal parser outcome. Export `get_activity_timeseries_service`, `MAX_ACTIVITY_ID`, and `MAX_FIT_ELAPSED_SECONDS` from `ai_activity/__init__.py`.

- [ ] **Step 6: Run GREEN and commit.**

  Run: `uv run pytest tests/unit/ai_activity/test_timeseries_service.py tests/unit/ai_activity/test_timeseries_reduction.py -q`

  Expected: PASS. Direct calls have stable typed envelopes for all input and safe error outcomes; valid calls have one permitted download, no cache, window-scoped facts, and activity-global malformed warning semantics.

  ```bash
  git add src/garmin_mcp/ai_activity/timeseries_service.py src/garmin_mcp/ai_activity/__init__.py tests/unit/ai_activity/test_timeseries_service.py
  git commit -m "feat: add bounded activity timeseries service"
  ```

**Review checkpoint:** Verify every non-success code is in the table with the exact provider/message, error envelopes have no partial series, and `next_start_seconds` is absent rather than null when unavailable. Search service output construction for raw provider/parser objects; none may be inserted.

### Task 6: Expose the exact FastMCP tool and integrate the 14-tool startup profile

**Implementer scope:** Fresh Terra/Luna agent. Own adapter/package/root profile changes and integration/startup tests. Do not revise parser or service semantics.

**Files:**

- Modify: `src/garmin_mcp/ai_activity/tools.py`
- Modify: `src/garmin_mcp/ai_activity/__init__.py`
- Modify: `src/garmin_mcp/__init__.py`
- Create: `tests/integration/test_ai_activity_timeseries_tools.py`
- Modify: `tests/unit/test_tool_filter.py`
- Modify: `tests/unit/test_server_startup.py`

- [ ] **Step 1: Write FastMCP and startup RED tests.**

  Register an app through `ai_activity.configure`/`register_tools` and assert the schema and defaults below, in addition to existing `analyze_activity` coverage:

  ```python
  assert tool.inputSchema["required"] == ["activity_id"]
  assert tool.inputSchema["properties"]["start_seconds"]["default"] == 0
  assert tool.inputSchema["properties"]["duration_seconds"]["default"] == 600
  assert tool.inputSchema["properties"]["resolution_seconds"]["default"] == 1

  @pytest.mark.parametrize("value", [True, 1.0, "1", [], {}])
  async def test_strict_window_shape_raises_toolerror_before_service(value: object) -> None:
      with pytest.raises(ToolError, match="start_seconds"):
          await app.call_tool("get_activity_timeseries", {"activity_id": 42, "start_seconds": value})
      fake_service.assert_not_called()
  ```

  Assert strict booleans/floats are rejected for all four declared fields before client/provider access, trimmed ASCII ID text reaches the service unchanged, direct service—not the adapter—handles range errors, and an undeclared `ignored_argument` is ignored by this pinned FastMCP call path and never supplied to the service. Assert `json.dumps(result, indent=2)` exact output, `ToolError` rather than an envelope for malformed declared arguments, and a privacy/read-only tool description.

  Update profile/startup tests to compare the exact ordered/set-equivalent fourteen names: `get_training_context`, `analyze_activity`, `get_activity_timeseries`, `create_workout`, `update_workout`, `get_activities`, `get_activities_by_date`, `get_activity`, `get_workouts`, `get_workout_by_id`, `get_scheduled_workouts`, `schedule_workout`, `unschedule_workout`, `delete_workout`. Explicitly assert neither `get_activity_fit_data` nor `move_workout` occurs, existing allowlist-over-profile and denylist-subtraction behavior remains, and root startup configures/registers `ai_activity` once.

- [ ] **Step 2: Run adapter/profile tests and capture RED.**

  Run: `uv run pytest tests/integration/test_ai_activity_timeseries_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py -q`

  Expected: FAIL because the adapter has no `get_activity_timeseries` registration and the profile still has 13 members.

- [ ] **Step 3: Register the exact strict FastMCP signature.**

  Import `get_activity_timeseries_service` and place this function beside `analyze_activity` inside the existing `register_tools`; do not create a second `garmin_client` global.

  ```python
  @app.tool()
  async def get_activity_timeseries(
      activity_id: StrictInt | StrictStr,
      start_seconds: StrictInt = 0,
      duration_seconds: StrictInt = 600,
      resolution_seconds: StrictInt = 1,
  ) -> str:
      """Return short-window factual cadence, power, pace, speed, altitude, grade, and heart-rate evidence.

      This tool is read-only and makes one ORIGINAL FIT download after valid input.
      Use analyze_activity first for the normal completed-session overview; use this
      only for a concrete short interval question. Results are paged non-empty bins,
      can have gaps, never imply one-Hz sampling, and never include GPS or raw FIT data.
      Availability describes this returned window, not account or device capability.
      """
      result = get_activity_timeseries_service(
          garmin_client,
          activity_id,
          start_seconds,
          duration_seconds,
          resolution_seconds,
      )
      return json.dumps(result, indent=2)
  ```

- [ ] **Step 4: Export and make the profile atomic.**

  Add `get_activity_timeseries_service` to `ai_activity.__all__`. Insert the literal string `"get_activity_timeseries"` immediately after `"analyze_activity"` in the root `TOOL_PROFILES["ai-coach"]` set. Do not add root configure/register calls: `ai_activity.configure` and `ai_activity.register_tools` already run exactly once and now expose both package tools.

- [ ] **Step 5: Run GREEN against the real FastMCP integration.**

  Run: `uv run pytest tests/integration/test_ai_activity_tools.py tests/integration/test_ai_activity_timeseries_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py -q`

  Expected: PASS. Actual FastMCP type validation raises `ToolError` before the service for malformed declared values; valid/default calls delegate once; startup's filtered app has exactly fourteen curated names and no raw FIT/debug tool.

- [ ] **Step 6: Commit integration.**

  ```bash
  git add src/garmin_mcp/ai_activity/tools.py src/garmin_mcp/ai_activity/__init__.py src/garmin_mcp/__init__.py tests/integration/test_ai_activity_timeseries_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py
  git commit -m "feat: register activity timeseries tool"
  ```

**Review checkpoint:** Inspect `tools.py` for one service invocation and `json.dumps(result, indent=2)`. Confirm malformed adapter input cannot reach the service, service range errors still become envelopes, and the profile's current count is exactly 14 with unchanged precedence.

### Task 7: Publish current tool-selection guidance and pin it with document tests

**Implementer scope:** Fresh Terra/Luna agent. Own only current-facing documentation and documentation tests. Do not change historical records, runtime code, package metadata, or lockfile.

**Files:**

- Create: `docs/ai-activity-timeseries.md`
- Modify: `README.md`
- Modify: `docs/setup.md`
- Modify: `docs/ai-training.md`
- Modify: `docs/ai-workouts.md`
- Modify: `docs/ai-activity.md`
- Create: `tests/unit/test_ai_activity_timeseries_docs.py`
- Modify: `tests/unit/test_ai_activity_docs.py`
- Modify: `tests/unit/test_ai_training_docs.py`
- Modify: `tests/unit/test_ai_workouts_docs.py`
- Modify: `tests/unit/test_readme_docs.py`

- [ ] **Step 1: Write current-document RED tests before prose changes.**

  Define the one exact fourteen-name `PROFILE_TOOLS` fixture in each existing profile document test (or import one local constant from `test_readme_docs.py` only if it avoids test-package coupling), adding `get_activity_timeseries` after `analyze_activity`; change all live `13` claims to `14`. New tests must read only the six current documents above and assert historical `docs/superpowers/` files are not read.

  In `test_ai_activity_timeseries_docs.py`, parse a JSON response example with `json.loads` and assert top-level order and every fixed nested array key. Assert guide text contains these literal current contracts: `analyze_activity(activity_id)` first; concrete short interval evidence only; defaults `start_seconds=0`, `duration_seconds=600`, `resolution_seconds=1`; `600` non-empty bins; half-open pagination through `window.next_start_seconds`; stop when that key is absent; no one-Hz assumption/fill/interpolation; units/rounding; missing versus recorded zero; one ORIGINAL download; 25 MB archive/member, 16 entries, 65,536-byte directory/read chunk, 200,000 frames, 100,000 records, 128 definition fields; window-scoped availability; absolute GPS/location/raw-FIT exclusion; no coaching/comparison/recommendation/workout mutation.

- [ ] **Step 2: Run document tests and capture RED.**

  Run: `uv run pytest tests/unit/test_ai_activity_timeseries_docs.py tests/unit/test_ai_activity_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_ai_workouts_docs.py tests/unit/test_readme_docs.py -q`

  Expected: FAIL because the guide/link/profile count/tool name do not yet exist in current documentation.

- [ ] **Step 3: Write the standalone time-series guide with a parseable safe example.**

  Add sections named `Choosing the tool`, `Arguments and paging`, `Returned evidence`, `Privacy and safety`, and `Limits and exclusions`. Include a parseable populated response copied from the approved shape, with exactly these top-level keys in order: `status`, `error`, `activity_id`, `window`, `sampling`, `availability`, `series`, `warnings`. State that timestamps are canonical UTC `Z` bin anchors, not claims of an exact device sample; availability is returned-window-scoped; false metrics use null arrays and a recorded speed `0.000` is distinct from missing speed.

  Use this exact pagination example and no raw/GPS output example:

  ```text
  1. Call get_activity_timeseries(activity_id=123456, start_seconds=0, duration_seconds=600, resolution_seconds=1).
  2. If window.next_start_seconds is present, call the same tool with that integer as start_seconds.
  3. Stop when next_start_seconds is absent. Do not create missing seconds, carry values forward, or assume a one-Hz source stream.
  ```

- [ ] **Step 4: Update every current cross-reference and exact 14-tool list.**

  In `README.md`, link the new guide from Documentation and development, place the tool after `analyze_activity` in the profile list, and replace `13-tool surface` with `14-tool surface`. In setup/training/workout/activity-analysis guides, link to the new guide wherever high-level coaching roles or profile count are described; explain that it is the narrow follow-up evidence read, not a replacement for `analyze_activity`. Update profile lists/counts to the exact fourteen items and retain all existing write/read boundary text. Do not change specifications/plans or advertise raw/full FIT, GPS, coaching judgement, repeated downloads, or `move_workout`.

- [ ] **Step 5: Run GREEN and validate examples.**

  Run: `uv run pytest tests/unit/test_ai_activity_timeseries_docs.py tests/unit/test_ai_activity_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_ai_workouts_docs.py tests/unit/test_readme_docs.py -q`

  Expected: PASS. All current documents agree on the exact 14-tool profile and the guide's JSON example parses with the safe stable shape.

  Run: `uv run python -c 'import json, re; from pathlib import Path; text = Path("docs/ai-activity-timeseries.md").read_text(); blocks = re.findall(r"```json\\n(.*?)\\n```", text, re.S); [json.loads(block) for block in blocks]; print(f"parsed {len(blocks)} JSON example(s)")'`

  Expected: `parsed 1 JSON example(s)` (or the intentionally documented exact count if the guide contains more than one parseable JSON block).

- [ ] **Step 6: Commit documentation contracts.**

  ```bash
  git add README.md docs/setup.md docs/ai-training.md docs/ai-workouts.md docs/ai-activity.md docs/ai-activity-timeseries.md tests/unit/test_ai_activity_timeseries_docs.py tests/unit/test_ai_activity_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_ai_workouts_docs.py tests/unit/test_readme_docs.py
  git commit -m "docs: document activity timeseries evidence"
  ```

**Review checkpoint:** Read only rendered/current docs and confirm a user can choose the overview tool first, page the evidence tool safely, interpret gaps/missing values correctly, and see the GPS/read-only/one-download boundary without reading an implementation file.

### Task 8: Run the full offline verification, build in a temporary directory, and audit the completed change

**Implementer scope:** Fresh Terra/Luna reviewer. Make no feature edits unless a failing assertion identifies a concrete mismatch; if an edit is necessary, return to the owning task's RED/GREEN sequence and commit that repair separately.

**Files:**

- Verify only: all files changed by Tasks 1–7

- [ ] **Step 1: Run the targeted feature matrix.**

  Run:

  ```bash
  uv run pytest tests/unit/test_project_dependencies.py tests/unit/ai_activity/test_providers.py tests/unit/ai_activity/test_timeseries_archive.py tests/unit/ai_activity/test_timeseries_frames.py tests/unit/ai_activity/test_timeseries_reduction.py tests/unit/ai_activity/test_timeseries_service.py tests/integration/test_ai_activity_tools.py tests/integration/test_ai_activity_timeseries_tools.py tests/unit/test_tool_filter.py tests/unit/test_server_startup.py tests/unit/test_ai_activity_timeseries_docs.py tests/unit/test_ai_activity_docs.py tests/unit/test_ai_training_docs.py tests/unit/test_ai_workouts_docs.py tests/unit/test_readme_docs.py -q
  ```

  Expected: PASS. This is the acceptance matrix for dependency pinning, provider one-call/read-only behavior, preflight-before-`ZipFile`, streaming caps, numeric field identity, privacy, reduction, validation, FastMCP `ToolError`, profile/startup, and current docs.

- [ ] **Step 2: Run the complete offline suite and package build without dirtying the repository.**

  Run: `uv run pytest -m "not e2e" -q`

  Expected: PASS with no network/authentication attempt.

  Run:

  ```bash
  timeseries_build_dir=$(mktemp -d /private/tmp/garmin-mcp-timeseries-build.XXXXXX)
  uv build --out-dir "$timeseries_build_dir"
  ```

  Expected: both source distribution and wheel are written below the temporary directory; no runtime artifact is added to the worktree.

- [ ] **Step 3: Audit spec coverage and privacy serialization.**

  Check this mapping against the approved design before claiming completion:

  | Approved requirement group | Implementing task(s) |
  | --- | --- |
  | Pinned ORIGINAL ZIP download, 25 MB cap, one read/no cache | 1, 5 |
  | EOCD/central/local safety, one streamed member, ZIP/member caps | 2, 3 |
  | Strict `fitdecode` setup, numeric allowlist, compressed timestamp, no GPS | 3 |
  | Stable sort, half-open windows/cursors, bin/metric aggregation/rounding | 4 |
  | Validation precedence, stable errors/envelope, warnings/status/sanitization | 5 |
  | Exact FastMCP types, ToolError/extras, root registration, 14 profile | 6 |
  | Current guide, workflow, limits, exact profile/document pins | 7 |

  Run the recursive output/privacy tests again and inspect the serializer sources:

  ```bash
  rg -n 'position_|latitude|longitude|coordinate|polyline|get_value|get_raw_value|get_field|all_field_defs' src/garmin_mcp/ai_activity/timeseries.py src/garmin_mcp/ai_activity/timeseries_service.py
  ```

  Expected: no matches. Any necessary `fitdecode.profile.FIELD_TYPE_TIMESTAMP` access is identity-only and is not a generic field lookup.

- [ ] **Step 4: Run the unfinished-language, formatting, and scope checks.**

  Run:

  ```bash
  rg -n -i 'T[O]DO|T[B]D|F[I]XME|similar[[:space:]]+to|implement[[:space:]]+later|appropriate[[:space:]]+error' src/garmin_mcp/ai_activity tests/unit/ai_activity tests/integration/test_ai_activity_timeseries_tools.py README.md docs/ai-activity-timeseries.md
  git diff --check HEAD~7..HEAD
  git status --short
  ```

  Expected: the marker scan has no matches; whitespace check has no output; status is clean after all planned commits. If the task count produced a different number of commits, replace `HEAD~7..HEAD` with the range beginning at the pre-Task-1 commit and retain the same no-output expectation.

- [ ] **Step 5: Record final review evidence without an extra empty commit.**

  In the handoff, report focused/full test commands, build result, current commit list, profile count, `git diff --check` result, and clean status. Do not alter `activity_analysis.py`, fitparse behavior, upstream modules, historical docs, or add `move_workout`.

**Review checkpoint:** A reviewer can trace every approved requirement to an executable assertion above, inspect a clean worktree, and find neither location/raw FIT data nor error/payload secrets in any serialized result.

## Plan self-review record

- [x] Read the approved design at `c31e15e` and mapped its provider, archive, decoder, reduction, service, adapter/profile, document, and verification requirements to Tasks 1–8.
- [x] Checked current architecture: the existing `ai_activity` package already supplies lazy `configure`/`register_tools`; root startup configures/registers it once; `TOOL_PROFILES["ai-coach"]` currently has 13 names; `activity_analysis.py` remains the separate `fitparse` path.
- [x] Checked existing tests and documentation locations so each task names exact owned paths and avoids parallel implementation overlap.
- [x] Included safe test construction: in-memory classic ZIPs plus targeted byte mutations, public-attribute FIT frame fakes, one real small ZIP/open integration check, monkeypatched small cap seams/generators, and a mutation-trapping Garmin client.
- [x] Checked names/types across tasks: `OriginalFitDownload`, `RecordFact`, `ParseResult`, `WindowResult`, `parse_original_fit`, `reduce_records`, and `get_activity_timeseries_service` are introduced before later tasks consume them.
- [x] Scanned this plan for unfinished-language markers and vague deferred implementation wording; each runtime/test step has an exact path, command, expected RED/GREEN result, concrete behavior, and commit boundary.
