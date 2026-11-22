"""Darksiders II (Deathinitive Edition) archive access.

Layout of the game's ``media`` folder:

* ``manifest.bin`` - index of every asset: folder paths, the ``.upak`` file
  each asset lives in, and its byte offset inside that file.
* ``media.upak`` / ``maps.upak`` - concatenated OBPK containers, one per
  asset, each aligned to 0x800 bytes.

An OBPK container is a header (resource names, types, offsets) followed, at
the offset stored at byte 25 of the header, by the payload: one or more
``[u32 uncompressed_size][zlib stream]`` chunks. Concatenating the
decompressed chunks yields the asset's payload.
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------- hashing

_CRC64_POLY = 0x01A1561E0005800C
_CRC64_TABLE = [0] * 256
for _i in range(1, 256):
    _CRC64_TABLE[_i] = ((_CRC64_TABLE[_i >> 1] << 1) & 0xFFFFFFFFFFFFFFFF) ^ (
        _CRC64_POLY if _i & 1 else 0
    )


def name_hash(name: str | bytes) -> int:
    """64-bit name hash the engine uses for class, property and object names."""
    if isinstance(name, str):
        name = name.encode("utf-8")
    h = 0xFFFFFFFFFFFFFFFF
    for b in name:
        h = (h >> 8) ^ _CRC64_TABLE[(h ^ b) & 0xFF]
    return h ^ 0xFFFFFFFFFFFFFFFF


# ---------------------------------------------------------------- manifest


@dataclass
class AssetEntry:
    name: str
    folder: str
    pak: str
    package_id: int
    offset: int
    size: int = 0

    @property
    def path(self) -> str:
        return f"{self.folder}/{self.name}" if self.folder else self.name


class _Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise ValueError("manifest.bin is truncated or has an unknown layout")
        b = self.data[self.pos : self.pos + n]
        self.pos += n
        return b

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]


def read_manifest(media_dir: Path) -> list[AssetEntry]:
    data = (media_dir / "manifest.bin").read_bytes()
    r = _Reader(data)
    version = r.u32()
    r.take(40)

    folders = []
    n_folders = r.u32()
    r.take(4)  # unused
    for _ in range(n_folders):
        r.take(8)  # name hash
        folders.append(r.take(r.u32()).decode("utf-8", "replace").replace("\\", "/"))

    paks = []
    for _ in range(r.u32()):
        r.take(1)
        paks.append(r.take(r.u16()).decode("utf-8", "replace"))

    entries = []
    for _ in range(r.u32()):
        name = r.take(r.u8()).decode("utf-8", "replace")
        r.take(8)  # name hash
        package_id = r.u16()
        folder_idx = r.u16()
        align = r.u8()
        r.take(align * 2)
        r.u8()
        pak_idx = r.u8()
        r.take(2)
        offset = r.u64() if version >= 13 else r.u32()
        entries.append(
            AssetEntry(
                name=name,
                folder=folders[folder_idx] if folder_idx < len(folders) else "",
                pak=paks[pak_idx] if pak_idx < len(paks) else f"pak{pak_idx}",
                package_id=package_id,
                offset=offset,
            )
        )

    # Sizes: distance to the next asset in the same .upak (or to end of file).
    by_pak: dict[str, list[AssetEntry]] = {}
    for e in entries:
        by_pak.setdefault(e.pak, []).append(e)
    for pak, items in by_pak.items():
        pak_path = media_dir / f"{pak}.upak"
        pak_len = pak_path.stat().st_size if pak_path.exists() else 0
        items.sort(key=lambda e: e.offset)
        for a, b in zip(items, items[1:] + [None]):
            a.size = (b.offset if b else pak_len) - a.offset
    return entries


# ---------------------------------------------------------------- OBPK


class Game:
    """Opened Darksiders II installation."""

    def __init__(self, install_dir: str | os.PathLike):
        root = Path(install_dir)
        self.media = root / "media" if (root / "media").is_dir() else root
        if not (self.media / "manifest.bin").exists():
            raise FileNotFoundError(
                f"media/manifest.bin not found in {root}. "
                "Select the Darksiders II install folder."
            )
        self.assets = read_manifest(self.media)
        self._by_path = {a.path.lower(): a for a in self.assets}

    def find(self, path: str) -> AssetEntry | None:
        key = path.replace("\\", "/").lower()
        if key in self._by_path:
            return self._by_path[key]
        matches = [a for a in self.assets if a.name.lower() == key]
        return matches[0] if len(matches) == 1 else None

    def read_raw(self, entry: AssetEntry) -> bytes:
        with open(self.media / f"{entry.pak}.upak", "rb") as f:
            f.seek(entry.offset)
            return f.read(entry.size)

    def read_payload(self, entry: AssetEntry) -> tuple[bytes, bytes]:
        """Return (obpk_header, decompressed_payload) of an asset."""
        return unpack_obpk(self.read_raw(entry))

    def read_header(self, entry: AssetEntry) -> bytes:
        with open(self.media / f"{entry.pak}.upak", "rb") as f:
            f.seek(entry.offset)
            head = f.read(64)
            if head[:4] != b"OBPK":
                raise ValueError(f"{entry.path} is not an OBPK container")
            data_start = struct.unpack_from("<I", head, 25)[0]
            f.seek(entry.offset)
            return f.read(data_start)

    def payload_to_file(self, entry: AssetEntry, out_path: Path, progress=None) -> int:
        """Stream-decompress an asset's payload to ``out_path``; return its size.

        Uses bounded memory, so multi-GB assets (e.g. ``items/armor``) work.
        """
        header = self.read_header(entry)
        end = entry.offset + entry.size
        total = 0
        with open(self.media / f"{entry.pak}.upak", "rb") as f, open(out_path, "wb") as out:
            pos = entry.offset + len(header)
            while pos + 6 <= end:
                f.seek(pos)
                head = f.read(5)
                usize = struct.unpack_from("<I", head)[0]
                if usize == 0 or usize > (1 << 30) or head[4] != 0x78:
                    break
                window = f.read(min(usize + usize // 512 + 1024, end - pos - 4))
                d = zlib.decompressobj()
                chunk = d.decompress(head[4:] + window)
                if not d.eof or len(chunk) != usize:
                    raise ValueError(f"{entry.path}: bad chunk at {pos - entry.offset:#x}")
                out.write(chunk)
                total += usize
                pos += 4 + 1 + len(window) - len(d.unused_data)
                if progress:
                    progress(pos - entry.offset, entry.size)
        return total


def unpack_obpk(raw: bytes) -> tuple[bytes, bytes]:
    if raw[:4] != b"OBPK":
        raise ValueError("not an OBPK container")
    data_start = struct.unpack_from("<I", raw, 25)[0]
    header = raw[:data_start]
    view = memoryview(raw)
    out = bytearray()
    pos = data_start
    while pos + 6 <= len(raw):
        usize = struct.unpack_from("<I", raw, pos)[0]
        if usize == 0 or usize > (1 << 30) or raw[pos + 4] != 0x78:
            break
        # A zlib stream is never much larger than its output, so feed a
        # bounded window instead of the whole rest of the file.
        window = view[pos + 4 : pos + 4 + usize + usize // 512 + 1024]
        d = zlib.decompressobj()
        chunk = d.decompress(window)
        if not d.eof or len(chunk) != usize:
            raise ValueError(f"chunk at {pos:#x}: got {len(chunk)} bytes, expected {usize}")
        out += chunk
        pos += 4 + len(window) - len(d.unused_data)
    return header, bytes(out)
