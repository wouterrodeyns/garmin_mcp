"""Archive boundary tests for the private FIT time-series parser seam."""

from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import zipfile
import zlib

import pytest

from tests.unit.ai_activity.timeseries_fakes import (
    CountingReadable,
    eocd_offset,
    make_zip,
    mutate_u16,
    mutate_u32,
)


def _central_offset(payload: bytes) -> int:
    return int.from_bytes(payload[eocd_offset(payload) + 16 : eocd_offset(payload) + 20], "little")


def _result(payload: bytes):
    from garmin_mcp.ai_activity.timeseries import parse_original_fit

    return parse_original_fit(payload)


def _central_record_offsets(payload: bytes) -> list[int]:
    offsets: list[int] = []
    cursor = _central_offset(payload)
    entries = int.from_bytes(payload[eocd_offset(payload) + 10 : eocd_offset(payload) + 12], "little")
    for _ in range(entries):
        offsets.append(cursor)
        name_size = int.from_bytes(payload[cursor + 28 : cursor + 30], "little")
        extra_size = int.from_bytes(payload[cursor + 30 : cursor + 32], "little")
        comment_size = int.from_bytes(payload[cursor + 32 : cursor + 34], "little")
        cursor += 46 + name_size + extra_size + comment_size
    return offsets


def _descriptor_archive(*, signature: bool, padding: bytes = b"", crc: int | None = None) -> bytes:
    payload = make_zip({"activity.fit": b"x"})
    central = _central_offset(payload)
    eocd = eocd_offset(payload)
    local_name_size = int.from_bytes(payload[26:28], "little")
    local_extra_size = int.from_bytes(payload[28:30], "little")
    data_end = 30 + local_name_size + local_extra_size + 1
    descriptor_crc = int.from_bytes(payload[14:18], "little") if crc is None else crc
    descriptor = (b"PK\x07\x08" if signature else b"") + descriptor_crc.to_bytes(4, "little") + payload[18:26]
    changed = bytearray(payload[:data_end] + descriptor + padding + payload[data_end:])
    changed = bytearray(mutate_u16(bytes(changed), 6, 8))
    changed = bytearray(mutate_u32(bytes(changed), 14, 0))
    changed = bytearray(mutate_u32(bytes(changed), 18, 0))
    changed = bytearray(mutate_u32(bytes(changed), 22, 0))
    central += len(descriptor) + len(padding)
    eocd += len(descriptor) + len(padding)
    changed = bytearray(mutate_u16(bytes(changed), central + 8, 8))
    changed = bytearray(mutate_u32(bytes(changed), central + 16, descriptor_crc))
    changed = bytearray(mutate_u32(bytes(changed), eocd + 16, central))
    return bytes(changed)


@pytest.mark.parametrize("payload", [b"", b"not-a-zip", b".FIT\x10\x00", b"\x1f\x8b\x08gzip"])
def test_non_classic_zip_payloads_are_invalid_fit_payload(payload: bytes):
    assert _result(payload).failure_code == "invalid_fit_payload"


def test_zip_without_fit_member_is_invalid_fit_payload():
    assert _result(make_zip({"notes.txt": b"safe"})).failure_code == "invalid_fit_payload"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: mutate_u16(payload, eocd_offset(payload) + 8, 0xFFFF),
        lambda payload: mutate_u32(payload, eocd_offset(payload) + 12, 0xFFFFFFFF),
    ],
)
def test_zip64_markers_and_sentinel_fields_are_unsafe(mutation):
    payload = make_zip({"activity.fit": b"x"})
    assert _result(mutation(payload)).failure_code == "unsafe_fit_archive"


@pytest.mark.parametrize("signature", [b"PK\x06\x06", b"PK\x06\x07"])
def test_zip64_eocd_and_locator_records_before_eocd_are_unsafe(signature: bytes):
    payload = make_zip({"activity.fit": b"x"})
    offset = eocd_offset(payload)
    assert _result(payload[:offset] + signature + payload[offset:]).failure_code == "unsafe_fit_archive"


@pytest.mark.parametrize("field_offset", [4, 6])
def test_multi_disk_eocd_is_unsafe(field_offset: int):
    payload = make_zip({"activity.fit": b"x"})
    assert _result(mutate_u16(payload, eocd_offset(payload) + field_offset, 1)).failure_code == "unsafe_fit_archive"


def test_eocd_comment_must_end_at_eof_and_candidates_must_not_be_ambiguous():
    payload = make_zip({"activity.fit": b"x"})
    assert _result(payload + b"trailing").failure_code == "unsafe_fit_archive"

    # The original EOCD's comment reaches the appended EOCD, so both end at EOF.
    original_eocd = eocd_offset(payload)
    duplicate = mutate_u16(payload, original_eocd + 20, 22) + payload[original_eocd :]
    assert _result(duplicate).failure_code == "unsafe_fit_archive"


def test_zip64_extra_field_is_unsafe():
    payload = make_zip({"activity.fit": b"x"})
    central = _central_offset(payload)
    name_size = int.from_bytes(payload[central + 28 : central + 30], "little")
    insertion = central + 46 + name_size
    changed = bytearray(payload)
    changed[insertion:insertion] = b"\x01\x00\x00\x00"
    changed = bytearray(mutate_u16(bytes(changed), central + 30, 4))
    new_eocd = eocd_offset(bytes(changed))
    changed = bytearray(mutate_u32(bytes(changed), new_eocd + 12, 50 + name_size))
    assert _result(bytes(changed)).failure_code == "unsafe_fit_archive"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: mutate_u16(payload, eocd_offset(payload) + 10, 2),
        lambda payload: mutate_u32(payload, eocd_offset(payload) + 12, 65_537),
        lambda payload: mutate_u32(payload, eocd_offset(payload) + 16, len(payload)),
        lambda payload: mutate_u32(payload, eocd_offset(payload) + 12, 1),
    ],
)
def test_central_directory_count_size_and_range_errors_are_unsafe(mutator):
    assert _result(mutator(make_zip({"activity.fit": b"x"}))).failure_code == "unsafe_fit_archive"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: mutate_u32(payload, _central_offset(payload), 0),
        lambda payload: mutate_u16(payload, _central_offset(payload) + 28, 50_000),
        lambda payload: mutate_u32(payload, 0, 0),
        lambda payload: mutate_u16(payload, 26, 50_000),
    ],
)
def test_malformed_or_truncated_central_and_local_headers_are_unsafe(mutator):
    assert _result(mutator(make_zip({"activity.fit": b"x"}))).failure_code == "unsafe_fit_archive"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: mutate_u16(payload, _central_offset(payload) + 8, 1),
        lambda payload: mutate_u16(payload, _central_offset(payload) + 10, zipfile.ZIP_BZIP2),
    ],
)
def test_encryption_and_unsupported_compression_are_unsafe(mutator):
    assert _result(mutator(make_zip({"activity.fit": b"x"}))).failure_code == "unsafe_fit_archive"


def test_strong_encryption_is_rejected_before_zipfile_construction(monkeypatch):
    from garmin_mcp.ai_activity import timeseries

    payload = make_zip({"activity.fit": b"x"})
    central = _central_offset(payload)
    payload = mutate_u16(payload, 6, 0x40)
    payload = mutate_u16(payload, central + 8, 0x40)
    constructed = False

    def fail_if_constructed(*args, **kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("ZipFile construction is forbidden for strong encryption")

    monkeypatch.setattr(timeseries.zipfile, "ZipFile", fail_if_constructed)
    assert timeseries.parse_original_fit(payload).failure_code == "unsafe_fit_archive"
    assert constructed is False


@pytest.mark.parametrize(
    "name",
    ["/activity.fit", "../activity.fit", "a/../activity.fit", "a\\activity.fit", "C:/activity.fit", "./activity.fit", "a//activity.fit"],
)
def test_unsafe_member_names_are_rejected(name: str):
    assert _result(make_zip({name: b"x"})).failure_code == "unsafe_fit_archive"


def test_nul_and_symlink_members_are_unsafe():
    nul_name = make_zip({"activity.fit": b"x"})
    central = _central_offset(nul_name)
    changed = bytearray(nul_name)
    changed[30] = 0
    changed[central + 46] = 0
    assert _result(bytes(changed)).failure_code == "unsafe_fit_archive"

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("activity.fit")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        archive.writestr(info, b"target")
    assert _result(buffer.getvalue()).failure_code == "unsafe_fit_archive"


def test_auxiliary_size_and_fit_member_count_limits():
    assert _result(make_zip({"activity.fit": b"x", "notes.txt": b"a" * 65_537})).failure_code == "unsafe_fit_archive"
    assert _result(make_zip({"one.fit": b"x", "two.FIT": b"y"})).failure_code == "unsafe_fit_archive"
    assert _result(make_zip({"dir.fit/": b""})).failure_code == "invalid_fit_payload"
    assert _result(make_zip({"activity.fit": b"x" * 25_000_001})).failure_code == "unsafe_fit_archive"


@pytest.mark.parametrize(
    "offset,value",
    [
        (16, 1),  # central local-header offset
        (8, 1),  # central flags
        (10, zipfile.ZIP_BZIP2),  # central method
        (20, 2),  # central uncompressed size
        (24, 2),  # central compressed size
    ],
)
def test_central_local_metadata_mismatches_are_unsafe(offset: int, value: int):
    payload = make_zip({"activity.fit": b"x"})
    central = _central_offset(payload)
    changed = mutate_u32(payload, central + offset, value) if offset >= 16 else mutate_u16(payload, central + offset, value)
    assert _result(changed).failure_code == "unsafe_fit_archive"


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_stored_and_deflated_fit_archives_reach_the_decoder_stub(compression: int):
    result = _result(make_zip({"activity.fit": b"not-a-fit"}, compression))
    assert result.failure_code == "fit_parse_failed"
    assert result.records == ()
    assert result.malformed_record_count == 0


def test_only_selected_fit_member_is_opened_and_zipfile_read_is_never_used(monkeypatch):
    from garmin_mcp.ai_activity import timeseries

    opened: list[str] = []
    original_open = zipfile.ZipFile.open
    payload = make_zip({"activity.fit": b"x", "notes.txt": b"safe"})

    def recording_open(self, name, mode="r", *args, **kwargs):
        opened.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
        return original_open(self, name, mode, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", recording_open)
    monkeypatch.setattr(zipfile.ZipFile, "read", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("read used")))
    monkeypatch.setattr(zipfile.ZipFile, "extract", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("extract used")))
    monkeypatch.setattr(zipfile.ZipFile, "extractall", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("extractall used")))
    assert timeseries.parse_original_fit(payload).failure_code == "fit_parse_failed"
    assert opened == ["activity.fit"]


def test_invalid_eocd_is_rejected_before_zipfile_construction(monkeypatch):
    from garmin_mcp.ai_activity import timeseries

    constructed = False

    def fail_if_constructed(*args, **kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("ZipFile was constructed before EOCD preflight")

    monkeypatch.setattr(timeseries.zipfile, "ZipFile", fail_if_constructed)
    result = timeseries.parse_original_fit(b"not-a-zip")
    assert result.failure_code == "invalid_fit_payload"
    assert constructed is False


def test_limited_reader_caps_every_request_and_detects_reduced_limit(monkeypatch):
    from garmin_mcp.ai_activity import timeseries

    monkeypatch.setattr(timeseries, "MAX_FIT_MEMBER_BYTES", 9)
    source = CountingReadable(b"0123456789")
    reader = timeseries.LimitedReader(source)
    with pytest.raises(timeseries._MemberLimitExceeded):
        reader.read(1_000_000)
    assert source.requested_sizes == [65_536]
    assert source.supplied_sizes == [10]


def test_parse_maps_stream_overflow_to_fit_member_too_large(monkeypatch):
    from garmin_mcp.ai_activity import timeseries

    def consume(stream):
        monkeypatch.setattr(timeseries, "MAX_FIT_MEMBER_BYTES", 9)
        stream.read()
        return timeseries.ParseResult((), 0, None)

    monkeypatch.setattr(timeseries, "_decode_fit_stream", consume)
    assert _result(make_zip({"activity.fit": b"0123456789"})).failure_code == "fit_member_too_large"


def test_member_decompression_failure_is_unsafe(monkeypatch):
    from garmin_mcp.ai_activity import timeseries

    payload = make_zip({"activity.fit": b"valid-looking-content" * 20}, zipfile.ZIP_DEFLATED)
    name_size = int.from_bytes(payload[26:28], "little")
    extra_size = int.from_bytes(payload[28:30], "little")
    changed = bytearray(payload)
    changed[30 + name_size + extra_size] ^= 0xFF

    def consume(stream):
        stream.read()
        return timeseries.ParseResult((), 0, None)

    monkeypatch.setattr(timeseries, "_decode_fit_stream", consume)
    assert _result(bytes(changed)).failure_code == "unsafe_fit_archive"


def test_standard_data_descriptor_member_reaches_decoder_stub():
    payload = make_zip({"activity.fit": b"x"})
    central = _central_offset(payload)
    eocd = eocd_offset(payload)
    descriptor = b"PK\x07\x08" + payload[14:26]
    local_name_size = int.from_bytes(payload[26:28], "little")
    local_extra_size = int.from_bytes(payload[28:30], "little")
    data_start = 30 + local_name_size + local_extra_size
    changed = bytearray(payload[:data_start + 1] + descriptor + payload[data_start + 1 :])
    changed = bytearray(mutate_u16(bytes(changed), 6, 8))
    changed = bytearray(mutate_u32(bytes(changed), 14, 0))
    changed = bytearray(mutate_u32(bytes(changed), 18, 0))
    changed = bytearray(mutate_u32(bytes(changed), 22, 0))
    central += len(descriptor)
    eocd += len(descriptor)
    changed = bytearray(mutate_u16(bytes(changed), central + 8, 8))
    changed = bytearray(mutate_u32(bytes(changed), eocd + 16, central))
    assert _result(bytes(changed)).failure_code == "fit_parse_failed"


@pytest.mark.parametrize("signature", [False, True])
def test_exact_12_and_16_byte_data_descriptors_are_accepted(signature: bool):
    from garmin_mcp.ai_activity.timeseries import _preflight_classic_zip

    assert _preflight_classic_zip(_descriptor_archive(signature=signature)).failure_code is None


def test_unsigned_descriptor_whose_crc_starts_with_signature_is_not_misclassified():
    from garmin_mcp.ai_activity.timeseries import _preflight_classic_zip

    assert _preflight_classic_zip(
        _descriptor_archive(signature=False, crc=0x08074B50)
    ).failure_code is None


@pytest.mark.parametrize("padding", [b"\x00", b"unexpected"])
def test_data_descriptor_cannot_have_trailing_gap_before_central_directory(padding: bytes):
    from garmin_mcp.ai_activity.timeseries import _preflight_classic_zip

    assert _preflight_classic_zip(
        _descriptor_archive(signature=True, padding=padding)
    ).failure_code == "unsafe_fit_archive"


def test_truncated_data_descriptor_is_unsafe():
    from garmin_mcp.ai_activity.timeseries import _preflight_classic_zip

    payload = _descriptor_archive(signature=True)
    central = _central_offset(payload)
    assert _preflight_classic_zip(payload[:central - 1] + payload[central:]).failure_code == "unsafe_fit_archive"


def test_data_descriptor_can_end_exactly_at_an_adjacent_local_header():
    from garmin_mcp.ai_activity.timeseries import _preflight_classic_zip

    payload = make_zip({"activity.fit": b"x", "notes.txt": b"y"})
    first_central, second_central = _central_record_offsets(payload)
    eocd = eocd_offset(payload)
    second_local = int.from_bytes(payload[second_central + 42 : second_central + 46], "little")
    descriptor = b"PK\x07\x08" + payload[14:26]
    changed = payload[:second_local] + descriptor + payload[second_local:]
    first_central += len(descriptor)
    second_central += len(descriptor)
    eocd += len(descriptor)
    changed = mutate_u16(changed, 6, 8)
    changed = mutate_u32(changed, 14, 0)
    changed = mutate_u32(changed, 18, 0)
    changed = mutate_u32(changed, 22, 0)
    changed = mutate_u16(changed, first_central + 8, 8)
    changed = mutate_u32(changed, second_central + 42, second_local + len(descriptor))
    changed = mutate_u32(changed, eocd + 16, first_central)
    assert _preflight_classic_zip(changed).failure_code is None


def test_adjacent_local_entries_do_not_trigger_overlap_rejection():
    from garmin_mcp.ai_activity.timeseries import _preflight_classic_zip

    assert _preflight_classic_zip(make_zip({"activity.fit": b"x", "notes.txt": b"safe"})).failure_code is None


def test_exact_duplicate_local_ranges_are_rejected_before_missing_fit_classification():
    from garmin_mcp.ai_activity.timeseries import _preflight_classic_zip

    payload = make_zip({"notes.txt": b"safe"})
    central = _central_offset(payload)
    eocd = eocd_offset(payload)
    duplicated_record = payload[central:eocd]
    changed = payload[:eocd] + duplicated_record + payload[eocd:]
    new_eocd = eocd + len(duplicated_record)
    changed = mutate_u16(changed, new_eocd + 8, 2)
    changed = mutate_u16(changed, new_eocd + 10, 2)
    changed = mutate_u32(changed, new_eocd + 12, len(duplicated_record) * 2)
    assert _preflight_classic_zip(changed).failure_code == "unsafe_fit_archive"


def test_partially_overlapping_local_ranges_are_rejected_during_preflight():
    from garmin_mcp.ai_activity.timeseries import _preflight_classic_zip

    payload = make_zip({"activity.fit": b"A" * 100, "notes.txt": b"B"})
    first_central, second_central = _central_record_offsets(payload)
    second_local = int.from_bytes(payload[second_central + 42 : second_central + 46], "little")
    first_data_start = 30 + int.from_bytes(payload[26:28], "little") + int.from_bytes(payload[28:30], "little")
    overlap_offset = first_data_start + 20
    changed = bytearray(payload)
    changed[overlap_offset : overlap_offset + (first_central - second_local)] = payload[second_local:first_central]
    changed = bytearray(mutate_u32(bytes(changed), second_central + 42, overlap_offset))
    assert _preflight_classic_zip(bytes(changed)).failure_code == "unsafe_fit_archive"


@pytest.mark.parametrize("mode", [0o010000, 0o060000, 0o020000])
def test_unix_fifo_socket_and_device_members_are_unsafe(mode: int):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("activity.fit")
        info.create_system = 3
        info.external_attr = (mode | 0o644) << 16
        archive.writestr(info, b"x")
    assert _result(buffer.getvalue()).failure_code == "unsafe_fit_archive"


def test_unix_directory_mode_requires_a_trailing_slash():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("directory.fit")
        info.create_system = 3
        info.external_attr = 0o40755 << 16
        archive.writestr(info, b"")
    assert _result(buffer.getvalue()).failure_code == "unsafe_fit_archive"


def test_unix_regular_files_and_slash_marked_directories_are_allowed():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        fit = zipfile.ZipInfo("activity.fit")
        fit.create_system = 3
        fit.external_attr = 0o100644 << 16
        archive.writestr(fit, b"x")
        directory = zipfile.ZipInfo("data/")
        directory.create_system = 3
        directory.external_attr = 0o40755 << 16
        archive.writestr(directory, b"")
    assert _result(buffer.getvalue()).failure_code == "fit_parse_failed"


@pytest.mark.parametrize(
    "error_type",
    [RuntimeError, OSError, EOFError, NotImplementedError, zlib.error],
)
def test_decoder_defects_are_not_normalized_as_member_read_failures(monkeypatch, error_type):
    from garmin_mcp.ai_activity import timeseries

    def programmer_defect(_stream):
        raise error_type("programmer defect")

    monkeypatch.setattr(timeseries, "_decode_fit_stream", programmer_defect)
    with pytest.raises(error_type, match="programmer defect"):
        timeseries.parse_original_fit(make_zip({"activity.fit": b"x"}))


@pytest.mark.parametrize("error_type", [OSError, EOFError, NotImplementedError, zlib.error])
def test_member_read_failures_are_normalized_at_limited_reader_boundary(monkeypatch, error_type):
    from garmin_mcp.ai_activity import timeseries

    class FailingReadable:
        def read(self, _size=-1):
            raise error_type("foreign member read failure")

    with pytest.raises(timeseries._FitMemberReadFailed):
        timeseries.LimitedReader(FailingReadable()).read()

    @contextmanager
    def open_failing_member(_archive):
        yield timeseries.LimitedReader(FailingReadable())

    def consume(stream):
        stream.read()
        return timeseries.ParseResult((), 0, None)

    monkeypatch.setattr(timeseries, "_open_fit_member", open_failing_member)
    monkeypatch.setattr(timeseries, "_decode_fit_stream", consume)
    result = timeseries.parse_original_fit(b"already-preflighted-in-this-fixture")
    assert result == timeseries.ParseResult((), 0, "unsafe_fit_archive")


def test_zipinfo_mismatch_after_preflight_is_unsafe(monkeypatch):
    from garmin_mcp.ai_activity import timeseries

    payload = make_zip({"activity.fit": b"x"})
    real_zipfile = zipfile.ZipFile

    class TamperingZipFile(real_zipfile):
        def infolist(self):
            infos = super().infolist()
            infos[0].flag_bits ^= 1
            return infos

    monkeypatch.setattr(timeseries.zipfile, "ZipFile", TamperingZipFile)
    assert timeseries.parse_original_fit(payload).failure_code == "unsafe_fit_archive"


def test_production_archive_limits_are_pinned():
    from garmin_mcp.ai_activity import timeseries

    assert timeseries.MAX_ARCHIVE_ENTRIES == 16
    assert timeseries.MAX_CENTRAL_DIRECTORY_BYTES == 65_536
    assert timeseries.MAX_AUXILIARY_ENTRY_BYTES == 65_536
    assert timeseries.MAX_FIT_MEMBER_BYTES == 25_000_000
    assert timeseries.FIT_STREAM_READ_CHUNK_BYTES == 65_536
    assert timeseries.ZIP_EOCD_TAIL_BYTES == 65_557
