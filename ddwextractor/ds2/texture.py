"""Textures: complete DDS files embedded in the payload, in resource-table order."""

from __future__ import annotations

import io
import re
import struct
from dataclasses import dataclass
from pathlib import Path

_DDS = re.compile(rb"DDS \x7c\x00\x00\x00")

_BLOCK8 = {b"DXT1", b"BC1U", b"ATI1", b"BC4U", b"BC4S"}
_BLOCK16 = {b"DXT2", b"DXT3", b"DXT4", b"DXT5", b"BC2U", b"BC3U", b"ATI2", b"BC5U", b"BC5S"}
_DXGI_BLOCK8 = set(range(70, 73)) | set(range(79, 82))
_DXGI_BLOCK16 = set(range(73, 79)) | set(range(82, 85)) | set(range(94, 100))


@dataclass
class Texture:
    offset: int
    size: int
    width: int
    height: int
    fmt: str
    name: str | None = None


def _dds_size(d, o: int) -> tuple[int, int, int, str]:
    h, w = struct.unpack_from("<2I", d, o + 12)
    mips = max(1, struct.unpack_from("<I", d, o + 28)[0])
    caps2 = struct.unpack_from("<I", d, o + 112)[0]
    pf_flags = struct.unpack_from("<I", d, o + 80)[0]
    fourcc = bytes(d[o + 84 : o + 88])
    header = 128
    block = 0
    fmt = fourcc.decode("latin-1").strip("\x00") or "RGB"
    if pf_flags & 0x4:
        if fourcc == b"DX10":
            header += 20
            dxgi = struct.unpack_from("<I", d, o + 128)[0]
            fmt = f"DXGI{dxgi}"
            block = 8 if dxgi in _DXGI_BLOCK8 else 16 if dxgi in _DXGI_BLOCK16 else 0
        elif fourcc in _BLOCK8:
            block = 8
        elif fourcc in _BLOCK16:
            block = 16
    faces = 6 if caps2 & 0x200 else 1
    total = 0
    bpp = struct.unpack_from("<I", d, o + 88)[0] or 32
    for _ in range(faces):
        mw, mh = w, h
        for _ in range(mips):
            if block:
                total += max(1, (mw + 3) // 4) * max(1, (mh + 3) // 4) * block
            else:
                total += ((mw * bpp + 31) // 32) * 4 * mh
            mw, mh = max(1, mw // 2), max(1, mh // 2)
    return header + total, w, h, fmt


def find_textures(payload, names: list[str]) -> list[Texture]:
    out = []
    for m in _DDS.finditer(payload):
        try:
            size, w, h, fmt = _dds_size(payload, m.start())
        except struct.error:
            continue
        if not (0 < w <= 16384 and 0 < h <= 16384) or m.start() + size > len(payload):
            continue
        out.append(Texture(m.start(), size, w, h, fmt))
    if len(out) == len(names):
        for t, n in zip(out, names):
            t.name = n
    for i, t in enumerate(out):
        if not t.name:
            t.name = f"texture_{i:04d}"
    return out


def save_texture(payload, tex: Texture, out_dir: Path, keep_dds: bool = False) -> Path:
    """Write the texture as PNG (falls back to .dds if Pillow can't decode it)."""
    raw = bytes(payload[tex.offset : tex.offset + tex.size])
    png = out_dir / f"{tex.name}.png"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            if img.mode not in ("RGB", "RGBA", "L", "LA"):
                img = img.convert("RGBA")
            img.save(png)
        if keep_dds:
            (out_dir / f"{tex.name}.dds").write_bytes(raw)
        return png
    except Exception:
        dds = out_dir / f"{tex.name}.dds"
        dds.write_bytes(raw)
        return dds
