"""Strict, bounded access to the sole FIT member in a classic ZIP archive."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
import ntpath
import stat
import struct
import sys
from typing import BinaryIO, Iterator
import zipfile
import zlib


MAX_ARCHIVE_ENTRIES = 16
MAX_CENTRAL_DIRECTORY_BYTES = 65_536
MAX_AUXILIARY_ENTRY_BYTES = 65_536
MAX_FIT_MEMBER_BYTES = 25_000_000
FIT_STREAM_READ_CHUNK_BYTES = 65_536
ZIP_EOCD_TAIL_BYTES = 65_557

_EOCD_SIGNATURE = b"PK\x05\x06"
_CENTRAL_SIGNATURE = b"PK\x01\x02"
_LOCAL_SIGNATURE = b"PK\x03\x04"
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_DATA_DESCRIPTOR_FLAG = 0x08
_ENCRYPTED_FLAG_MASK = 0x41
_UTF8_FLAG = 0x800
_ZIP64_EXTRA_TAG = 0x0001
_EOCD_STRUCT = struct.Struct("<4s4H2LH")
_CENTRAL_STRUCT = struct.Struct("<4s6H3L5H2L")
_LOCAL_STRUCT = struct.Struct("<4s5H3L2H")


@dataclass(frozen=True)
class ParseResult:
    """The later decoder's public result shape, without exception details."""

    records: tuple[object, ...]
    malformed_record_count: int
    failure_code: str | None


@dataclass(frozen=True)
class FitMemberMetadata:
    """Primitive central-directory facts used to open one checked member."""

    name: str
    flags: int
    compression: int
    compressed_size: int
    uncompressed_size: int
    local_offset: int


@dataclass(frozen=True)
class PreflightResult:
    """Preflight outcome that retains no ZipInfo or archive object."""

    selected: FitMemberMetadata | None
    failure_code: str | None


@dataclass(frozen=True)
class _ValidatedLocalEntry:
    metadata: FitMemberMetadata
    data_end: int
    crc: int
    has_data_descriptor: bool


class _ArchiveFailure(Exception):
    def __init__(self, failure_code: str) -> None:
        self.failure_code = failure_code


class _MemberLimitExceeded(Exception):
    pass


class LimitedReader:
    """Bound individual reads and total decompressed bytes from one member."""

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


def _unsafe() -> PreflightResult:
    return PreflightResult(None, "unsafe_fit_archive")


def _invalid() -> PreflightResult:
    return PreflightResult(None, "invalid_fit_payload")


def _in_bounds(start: int, size: int, limit: int) -> bool:
    return start >= 0 and size >= 0 and start <= limit and size <= limit - start


def _has_zip64_extra(extra: bytes) -> bool:
    offset = 0
    while offset < len(extra):
        if len(extra) - offset < 4:
            return True
        tag, size = struct.unpack_from("<HH", extra, offset)
        offset += 4
        if size > len(extra) - offset:
            return True
        if tag == _ZIP64_EXTRA_TAG:
            return True
        offset += size
    return False


def _decode_name(raw_name: bytes, flags: int) -> str | None:
    try:
        return raw_name.decode("utf-8" if flags & _UTF8_FLAG else "cp437")
    except UnicodeDecodeError:
        return None


def _is_safe_name(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        return False
    if ntpath.splitdrive(name)[0]:
        return False
    components = name.split("/")
    return all(component not in {"", ".", ".."} for component in components)


def _has_safe_unix_file_type(
    version_made_by: int, external_attributes: int, is_directory: bool
) -> bool:
    """Accept only ordinary Unix files/directories when a type is recorded."""
    if (version_made_by >> 8) != 3:
        return True
    file_type = stat.S_IFMT(external_attributes >> 16)
    if file_type == 0:
        return True
    if file_type == stat.S_IFREG:
        return not is_directory
    if file_type == stat.S_IFDIR:
        return is_directory
    return False


def _preflight_classic_zip(archive: bytes) -> PreflightResult:
    """Validate classic ZIP structure without constructing ``ZipFile`` first."""
    if type(archive) is not bytes:
        return _invalid()
    tail_start = max(0, len(archive) - ZIP_EOCD_TAIL_BYTES)
    candidates: list[int] = []
    position = archive.find(_EOCD_SIGNATURE, tail_start)
    while position != -1:
        if _in_bounds(position, _EOCD_STRUCT.size, len(archive)):
            comment_length = struct.unpack_from("<H", archive, position + 20)[0]
            if position + _EOCD_STRUCT.size + comment_length == len(archive):
                candidates.append(position)
        position = archive.find(_EOCD_SIGNATURE, position + 1)

    if not candidates:
        if _EOCD_SIGNATURE in archive[tail_start:]:
            return _unsafe()
        return _invalid()
    if len(candidates) != 1:
        return _unsafe()
    eocd = candidates[0]
    (
        _signature,
        disk_number,
        central_disk_number,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        _comment_length,
    ) = _EOCD_STRUCT.unpack_from(archive, eocd)
    if (
        disk_number != 0
        or central_disk_number != 0
        or disk_entries != total_entries
        or disk_entries == 0xFFFF
        or total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
    ):
        return _unsafe()
    if total_entries > MAX_ARCHIVE_ENTRIES or central_size > MAX_CENTRAL_DIRECTORY_BYTES:
        return _unsafe()
    if not _in_bounds(central_offset, central_size, eocd):
        return _unsafe()
    central_end = central_offset + central_size
    if (
        _ZIP64_EOCD_SIGNATURE in archive[central_end:eocd]
        or _ZIP64_LOCATOR_SIGNATURE in archive[central_end:eocd]
    ):
        return _unsafe()

    local_entries: list[_ValidatedLocalEntry] = []
    cursor = central_offset
    for _ in range(total_entries):
        if not _in_bounds(cursor, _CENTRAL_STRUCT.size, central_end):
            return _unsafe()
        (
            signature,
            version_made_by,
            _version_needed,
            flags,
            compression,
            _modified_time,
            _modified_date,
            crc,
            compressed_size,
            uncompressed_size,
            name_size,
            extra_size,
            comment_size,
            start_disk,
            _internal_attributes,
            external_attributes,
            local_offset,
        ) = _CENTRAL_STRUCT.unpack_from(archive, cursor)
        if signature != _CENTRAL_SIGNATURE:
            return _unsafe()
        variable_size = name_size + extra_size + comment_size
        if not _in_bounds(cursor + _CENTRAL_STRUCT.size, variable_size, central_end):
            return _unsafe()
        variable_start = cursor + _CENTRAL_STRUCT.size
        raw_name = archive[variable_start : variable_start + name_size]
        extra_start = variable_start + name_size
        extra = archive[extra_start : extra_start + extra_size]
        if _has_zip64_extra(extra):
            return _unsafe()
        name = _decode_name(raw_name, flags)
        is_directory = name is not None and name.endswith("/")
        safe_name = name[:-1] if is_directory else name
        if (
            name is None
            or not _is_safe_name(safe_name)
            or not _has_safe_unix_file_type(version_made_by, external_attributes, is_directory)
            or start_disk != 0
            or flags & _ENCRYPTED_FLAG_MASK
            or compression not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        ):
            return _unsafe()
        if not _in_bounds(local_offset, _LOCAL_STRUCT.size, central_offset):
            return _unsafe()
        (
            local_signature,
            _local_version_needed,
            local_flags,
            local_compression,
            _local_time,
            _local_date,
            local_crc,
            local_compressed_size,
            local_uncompressed_size,
            local_name_size,
            local_extra_size,
        ) = _LOCAL_STRUCT.unpack_from(archive, local_offset)
        if local_signature != _LOCAL_SIGNATURE or local_flags != flags or local_compression != compression:
            return _unsafe()
        local_variable = local_name_size + local_extra_size
        local_variable_start = local_offset + _LOCAL_STRUCT.size
        if not _in_bounds(local_variable_start, local_variable, central_offset):
            return _unsafe()
        local_name = archive[local_variable_start : local_variable_start + local_name_size]
        local_extra = archive[
            local_variable_start + local_name_size : local_variable_start + local_variable
        ]
        if local_name != raw_name or _has_zip64_extra(local_extra):
            return _unsafe()
        data_start = local_variable_start + local_variable
        if not _in_bounds(data_start, compressed_size, central_offset):
            return _unsafe()
        data_end = data_start + compressed_size
        if flags & _DATA_DESCRIPTOR_FLAG:
            if local_crc != 0 or local_compressed_size != 0 or local_uncompressed_size != 0:
                return _unsafe()
        elif (
            local_crc != crc
            or local_compressed_size != compressed_size
            or local_uncompressed_size != uncompressed_size
        ):
            return _unsafe()

        local_entries.append(
            _ValidatedLocalEntry(
                metadata=FitMemberMetadata(
                    name=name,
                    flags=flags,
                    compression=compression,
                    compressed_size=compressed_size,
                    uncompressed_size=uncompressed_size,
                    local_offset=local_offset,
                ),
                data_end=data_end,
                crc=crc,
                has_data_descriptor=bool(flags & _DATA_DESCRIPTOR_FLAG),
            )
        )
        cursor = variable_start + variable_size

    if cursor != central_end:
        return _unsafe()

    ordered_local_entries = sorted(local_entries, key=lambda entry: entry.metadata.local_offset)
    ranges: list[tuple[int, int]] = []
    for index, entry in enumerate(ordered_local_entries):
        next_local_offset = (
            ordered_local_entries[index + 1].metadata.local_offset
            if index + 1 < len(ordered_local_entries)
            else central_offset
        )
        if next_local_offset <= entry.metadata.local_offset or entry.data_end > next_local_offset:
            return _unsafe()
        local_end = entry.data_end
        if entry.has_data_descriptor:
            descriptor_size = next_local_offset - entry.data_end
            if descriptor_size not in {12, 16}:
                return _unsafe()
            descriptor_offset = entry.data_end
            if descriptor_size == 16:
                if archive[descriptor_offset : descriptor_offset + 4] != b"PK\x07\x08":
                    return _unsafe()
                descriptor_offset += 4
            descriptor_crc, descriptor_compressed, descriptor_uncompressed = struct.unpack_from(
                "<3L", archive, descriptor_offset
            )
            if (
                descriptor_crc != entry.crc
                or descriptor_compressed != entry.metadata.compressed_size
                or descriptor_uncompressed != entry.metadata.uncompressed_size
            ):
                return _unsafe()
            local_end = next_local_offset
        ranges.append((entry.metadata.local_offset, local_end))

    previous_end = -1
    for local_start, local_end in ranges:
        if local_start < previous_end:
            return _unsafe()
        previous_end = local_end

    entries = [entry.metadata for entry in local_entries]
    selected = [
        entry
        for entry in entries
        if not entry.name.endswith("/") and entry.name.lower().endswith(".fit")
    ]
    for entry in entries:
        if entry not in selected and entry.uncompressed_size > MAX_AUXILIARY_ENTRY_BYTES:
            return _unsafe()
    if not selected:
        return _invalid()
    if len(selected) != 1:
        return _unsafe()
    fit_member = selected[0]
    if fit_member.uncompressed_size > MAX_FIT_MEMBER_BYTES:
        return _unsafe()
    return PreflightResult(fit_member, None)


def _zip_info_matches(info: zipfile.ZipInfo, member: FitMemberMetadata) -> bool:
    return (
        info.filename == member.name
        and info.flag_bits == member.flags
        and info.compress_type == member.compression
        and info.file_size == member.uncompressed_size
        and info.compress_size == member.compressed_size
        and info.header_offset == member.local_offset
    )


@dataclass
class _OpenedFitMember:
    zip_archive: zipfile.ZipFile
    source: BinaryIO
    reader: LimitedReader

    def close(self) -> None:
        try:
            try:
                self.source.close()
            finally:
                self.zip_archive.close()
        except (
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
            OSError,
            RuntimeError,
            NotImplementedError,
            EOFError,
            zlib.error,
        ) as error:
            raise _ArchiveFailure("unsafe_fit_archive") from error


def _discard_open_member(zip_archive: zipfile.ZipFile | None, source: BinaryIO | None) -> None:
    try:
        try:
            if source is not None:
                source.close()
        finally:
            if zip_archive is not None:
                zip_archive.close()
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        OSError,
        RuntimeError,
        NotImplementedError,
        EOFError,
        zlib.error,
    ):
        pass


def _construct_fit_member(archive: bytes) -> _OpenedFitMember:
    preflight = _preflight_classic_zip(archive)
    if preflight.failure_code is not None:
        raise _ArchiveFailure(preflight.failure_code)
    assert preflight.selected is not None
    zip_archive: zipfile.ZipFile | None = None
    source: BinaryIO | None = None
    try:
        zip_archive = zipfile.ZipFile(BytesIO(archive))
        matching = [
            info
            for info in zip_archive.infolist()
            if info.header_offset == preflight.selected.local_offset
        ]
        if len(matching) != 1 or not _zip_info_matches(matching[0], preflight.selected):
            raise _ArchiveFailure("unsafe_fit_archive")
        source = zip_archive.open(matching[0], "r")
        return _OpenedFitMember(zip_archive, source, LimitedReader(source))
    except _ArchiveFailure:
        _discard_open_member(zip_archive, source)
        raise
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        OSError,
        RuntimeError,
        NotImplementedError,
        EOFError,
        zlib.error,
    ) as error:
        _discard_open_member(zip_archive, source)
        raise _ArchiveFailure("unsafe_fit_archive") from error


@contextmanager
def _open_fit_member(archive: bytes) -> Iterator[LimitedReader]:
    opened = _construct_fit_member(archive)
    try:
        yield opened.reader
    finally:
        caller_failed = sys.exc_info()[0] is not None
        try:
            opened.close()
        except _ArchiveFailure:
            if not caller_failed:
                raise


def _decode_fit_stream(stream: LimitedReader) -> ParseResult:
    """Temporary decoder seam; FIT frame interpretation arrives in Task 3."""
    return ParseResult((), 0, "fit_parse_failed")


def parse_original_fit(archive: bytes) -> ParseResult:
    """Return a privacy-safe parsing failure/result without exception details."""
    try:
        with _open_fit_member(archive) as stream:
            return _decode_fit_stream(stream)
    except _MemberLimitExceeded:
        return ParseResult((), 0, "fit_member_too_large")
    except _ArchiveFailure as error:
        return ParseResult((), 0, error.failure_code)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, NotImplementedError, EOFError, zlib.error):
        return ParseResult((), 0, "unsafe_fit_archive")


__all__ = [
    "FIT_STREAM_READ_CHUNK_BYTES",
    "MAX_ARCHIVE_ENTRIES",
    "MAX_AUXILIARY_ENTRY_BYTES",
    "MAX_CENTRAL_DIRECTORY_BYTES",
    "MAX_FIT_MEMBER_BYTES",
    "ParseResult",
    "parse_original_fit",
]
