"""Small binary fixtures for FIT archive boundary tests."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_STORED, ZipFile

import fitdecode


def make_zip(entries: dict[str, bytes], compression: int = ZIP_STORED) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=compression, allowZip64=False) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def mutate_u16(payload: bytes, offset: int, value: int) -> bytes:
    changed = bytearray(payload)
    changed[offset : offset + 2] = value.to_bytes(2, "little")
    return bytes(changed)


def mutate_u32(payload: bytes, offset: int, value: int) -> bytes:
    changed = bytearray(payload)
    changed[offset : offset + 4] = value.to_bytes(4, "little")
    return bytes(changed)


def eocd_offset(payload: bytes) -> int:
    offset = payload.rfind(b"PK\x05\x06")
    assert offset >= 0
    return offset


class CountingReadable:
    """Readable fixture that records requested and supplied byte counts."""

    def __init__(self, payload: bytes) -> None:
        self._buffer = BytesIO(payload)
        self.requested_sizes: list[int] = []
        self.supplied_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        chunk = self._buffer.read(size)
        self.supplied_sizes.append(len(chunk))
        return chunk


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


class FakeReader:
    """A public-attribute-shaped FitReader fake with observable lifecycle."""

    def __init__(self, frames, *, next_error: Exception | None = None, close_error: Exception | None = None):
        self._iterator = iter(frames)
        self._next_error = next_error
        self._close_error = close_error
        self.close_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        if self._next_error is not None:
            error = self._next_error
            self._next_error = None
            raise error
        return next(self._iterator)

    def close(self) -> None:
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


def fake_reader(frames, *, next_error: Exception | None = None, close_error: Exception | None = None) -> FakeReader:
    return FakeReader(frames, next_error=next_error, close_error=close_error)


def header():
    return SimpleNamespace(frame_type=fitdecode.FIT_FRAME_HEADER)


def crc():
    return SimpleNamespace(frame_type=fitdecode.FIT_FRAME_CRC)


def definition(field_defs=(), dev_field_defs=()):
    return SimpleNamespace(
        frame_type=fitdecode.FIT_FRAME_DEFINITION,
        field_defs=field_defs,
        dev_field_defs=dev_field_defs,
    )


def fake_record(fields, *, global_mesg_num=20, time_offset=None):
    return SimpleNamespace(
        frame_type=fitdecode.FIT_FRAME_DATA,
        global_mesg_num=global_mesg_num,
        fields=fields,
        time_offset=time_offset,
        name="not-a-record",
        mesg_type=SimpleNamespace(name="not-a-record"),
    )
