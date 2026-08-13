"""Small binary fixtures for FIT archive boundary tests."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_STORED, ZipFile


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
