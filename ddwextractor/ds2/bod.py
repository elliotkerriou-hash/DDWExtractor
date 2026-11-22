"""Reader for the engine's self-describing "BOD" object serialization.

A BOD blob starts with ``b"BOD\\xfd"``, four format bytes and two u32
counters, followed by one root object. Objects carry a class name and a list
of named properties; every value is prefixed with a one-byte type tag.

Names (class and property names, string references) are written inline the
first time they appear (flag 1: u64 hash, u16 length, bytes) and afterwards
referenced by their index in that per-blob list (flag 0: u32 index).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"BOD\xfd"
_MAX_DEPTH = 48


@dataclass
class BodObject:
    cls: str | None
    props: dict[str, object] = field(default_factory=dict)

    def get(self, *path: str, default=None):
        """Follow nested object/map keys, e.g. ``get("Parameters", "DiffuseMap1", "Value")``."""
        cur: object = self
        for key in path:
            if isinstance(cur, BodObject):
                if key not in cur.props:
                    return default
                cur = cur.props[key]
            elif isinstance(cur, dict):
                if key not in cur:
                    return default
                cur = cur[key]
            else:
                return default
        return cur


class BodError(ValueError):
    pass


class _Cursor:
    __slots__ = ("data", "pos", "names")

    def __init__(self, data: bytes, pos: int):
        self.data = data
        self.pos = pos
        self.names: list[str] = []

    def take(self, n: int) -> bytes:
        end = self.pos + n
        if end > len(self.data):
            raise BodError("truncated BOD data")
        b = self.data[self.pos : end]
        self.pos = end
        return b

    def u8(self) -> int:
        if self.pos >= len(self.data):
            raise BodError("truncated BOD data")
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def name_ref(self) -> str:
        if self.u8():
            self.take(8)  # crc64 of the name
            name = self.take(self.u16()).decode("utf-8", "replace")
            self.names.append(name)
            return name
        idx = self.u32()
        if idx >= len(self.names):
            raise BodError(f"name index {idx} out of range")
        return self.names[idx]


def _value(c: _Cursor, depth: int):
    if depth > _MAX_DEPTH:
        raise BodError("BOD nesting too deep")
    tag = c.u8()
    if tag == 0x00:
        return None
    if tag == 0x02:
        return struct.unpack("<i", c.take(4))[0]
    if tag == 0x03:
        return struct.unpack("<f", c.take(4))[0]
    if tag == 0x04:
        return c.u8() != 0
    if tag == 0x05:
        if c.u8() != 0xFF:
            raise BodError("unsupported string encoding")
        return c.take(c.u16()).decode("utf-8", "replace")
    if tag == 0x07:
        c.u32()
        return _object(c, depth + 1)
    if tag in (0x09, 0x0A):
        count = c.u32()
        if c.u8():
            out = {}
            for _ in range(count):
                k = _value(c, depth + 1)
                out[k if isinstance(k, (str, int, float)) else repr(k)] = _value(c, depth + 1)
            return out
        return [_value(c, depth + 1) for _ in range(count)]
    if tag == 0x0B:
        return [_value(c, depth + 1) for _ in range(c.u32())]
    if tag == 0x0D:
        return struct.unpack("<Q", c.take(8))[0]
    if tag == 0x0F:
        return c.name_ref()
    if tag == 0xFC:
        obj_id = c.u32()
        h = struct.unpack("<Q", c.take(8))[0]
        return f"obj:{obj_id}:{h:016X}"
    raise BodError(f"unknown value tag {tag:#x} at {c.pos - 1:#x}")


def _object(c: _Cursor, depth: int) -> BodObject | None:
    kind = c.u8()
    if kind == 0:
        return None
    if kind == 4:
        c.take(4)
    obj = BodObject(cls=c.name_ref())
    for _ in range(c.u32()):
        name = c.name_ref()
        obj.props[name] = _value(c, depth)
    return obj


def parse_bod(data: bytes, pos: int = 0) -> tuple[BodObject, int]:
    """Parse the BOD blob at ``pos``; return (root object, end offset)."""
    if data[pos : pos + 4] != MAGIC:
        raise BodError("not a BOD blob")
    c = _Cursor(data, pos + 4)
    if c.u8() < 3:
        raise BodError("unsupported BOD name mode")
    c.take(3)
    c.take(8)  # name slot count, longest name
    root = _object(c, 0)
    if root is None:
        raise BodError("empty BOD root")
    return root, c.pos


def iter_bods(data: bytes, cls: str | None = None):
    """Yield (offset, object) for every parseable BOD blob in ``data``."""
    pos = data.find(MAGIC)
    while pos != -1:
        try:
            obj, end = parse_bod(data, pos)
        except (BodError, struct.error):
            pos = data.find(MAGIC, pos + 4)
            continue
        if cls is None or obj.cls == cls:
            yield pos, obj
        pos = data.find(MAGIC, max(end, pos + 4))
