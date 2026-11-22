"""Mesh resources inside a decompressed Darksiders II asset payload.

Layout of one mesh resource (little endian)::

    u32  unknown
    u32  n                      number of parts
    u32  n, u32 index_count[n]
    u32  n, i32 vertex_count[n] positive: skinned part, negative: static part
    i32  -n
    n x (u32 extra, u32)        extra: entries in an optional 16-byte stream (static parts)
    n x part header
    n x part data

Part header::

    u8   skinned (1) / static (0)
    u32  vertex_count, u32 gpu_stride (64 skinned, 60 static)
    u32  offset of this part's index buffer, relative to the start of the data
    skinned: u32 sub_count, u32 bone_count     static: u32 (2), u32 sub_count
    6 x f32 bounding box (min xyz, max xyz)
    skinned only: bone_count x [name][16 x f32 bind matrix][u32 bone id]
    sub_count x [name][i32 id][u32 0][u32 vertex_count][u32 base_vertex]
                [u32 index_count][u32 first_index]

``name`` is ``0xFF, u16 length, ascii``; the sub-mesh name is its material.

Part data::

    u32 index_bytes, u32 index_size (2 or 4), indices
    skinned: vc x 20 (u, v, 0, 0, -1)   vc x 52 (u32, xyz, 1.0, normal, tangent)
             vc x 16 (weights)          vc x 4  (bone indices)
    static:  vc x 12 (xyz)              vc x 48 (normal, tangent, u, v, 0, 0, -1)
             extra x 16
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np


@dataclass
class SubMesh:
    material: str
    first_index: int
    index_count: int


@dataclass
class Bone:
    name: str
    bone_id: int
    matrix: tuple


@dataclass
class MeshPart:
    skinned: bool
    positions: np.ndarray  # (N, 3) float32
    normals: np.ndarray  # (N, 3) float32
    uvs: np.ndarray  # (N, 2) float32
    indices: np.ndarray  # (M,) uint32, triangle list
    submeshes: list[SubMesh]
    bones: list[Bone] = field(default_factory=list)
    bbox: tuple = ()
    joints: np.ndarray | None = None  # (N, 4) uint8, indices into ``bones`` (skinned)
    weights: np.ndarray | None = None  # (N, 4) float32 (skinned)
    attach_bone: str | None = None  # static parts: bone they are attached to
    attach_world: np.ndarray | None = None  # 4x4 bone->model matrix used to place it


@dataclass
class Mesh:
    offset: int
    end: int
    parts: list[MeshPart]
    name: str | None = None

    @property
    def materials(self) -> list[str]:
        seen: dict[str, None] = {}
        for p in self.parts:
            for s in p.submeshes:
                seen.setdefault(s.material, None)
        return list(seen)

    @property
    def vertex_count(self) -> int:
        return sum(len(p.positions) for p in self.parts)

    @property
    def triangle_count(self) -> int:
        return sum(len(p.indices) // 3 for p in self.parts)


class _Bad(Exception):
    pass


def _name(d: bytes, o: int) -> tuple[str, int]:
    if d[o] != 0xFF:
        raise _Bad
    n = d[o + 1] | (d[o + 2] << 8)
    if not 0 < n < 256:
        raise _Bad
    raw = d[o + 3 : o + 3 + n]
    if any(c < 32 or c > 126 for c in raw):
        raise _Bad
    return raw.decode("ascii"), o + 3 + n


def _parse_mesh(d: bytes, start: int) -> Mesh:
    o = start
    _unk, n, n2 = struct.unpack_from("<3I", d, o)
    o += 12
    if not 1 <= n <= 255 or n != n2:
        raise _Bad
    index_counts = struct.unpack_from(f"<{n}I", d, o)
    o += 4 * n
    if struct.unpack_from("<I", d, o)[0] != n:
        raise _Bad
    o += 4
    vertex_counts = struct.unpack_from(f"<{n}i", d, o)
    o += 4 * n
    if struct.unpack_from("<i", d, o)[0] != -n:
        raise _Bad
    o += 4
    # Per part: number of entries in an optional extra 16-byte vertex stream.
    extra_counts = struct.unpack_from(f"<{2 * n}I", d, o)[0::2]
    o += 8 * n

    headers = []
    for i in range(n):
        skinned = d[o]
        vc, _stride, data_off, a, b = struct.unpack_from("<5I", d, o + 1)
        o += 21
        if skinned > 1 or vc == 0 or vc != abs(vertex_counts[i]) or (vertex_counts[i] > 0) != bool(skinned):
            raise _Bad
        sub_count, bone_count = (a, b) if skinned else (b, 0)
        if sub_count > 512 or bone_count > 2048:
            raise _Bad
        bbox = struct.unpack_from("<6f", d, o)
        o += 24
        bones = []
        for _ in range(bone_count):
            name, o = _name(d, o)
            matrix = struct.unpack_from("<16f", d, o)
            bone_id = struct.unpack_from("<I", d, o + 64)[0]
            o += 68
            bones.append(Bone(name, bone_id, matrix))
        subs = []
        for _ in range(sub_count):
            name, o = _name(d, o)
            _sid, _z, _svc, _base, icount, first = struct.unpack_from("<iIIIII", d, o)
            o += 24
            subs.append(SubMesh(name, first, icount))
        if extra_counts[i] > 4 * vc:
            raise _Bad
        headers.append((bool(skinned), vc, data_off, bbox, bones, subs, index_counts[i], extra_counts[i]))

    base = o
    parts = []
    expected = 8
    for skinned, vc, data_off, bbox, bones, subs, icount, extra in headers:
        if data_off != expected:
            raise _Bad
        p = base + data_off - 8
        ibytes, isize = struct.unpack_from("<2I", d, p)
        if isize not in (2, 4) or ibytes != icount * isize or icount % 3:
            raise _Bad
        p += 8
        idx = np.frombuffer(d, dtype="<u2" if isize == 2 else "<u4", count=icount, offset=p)
        p += ibytes
        if skinned:
            uv = np.frombuffer(d, dtype="<f4", count=vc * 5, offset=p).reshape(vc, 5)[:, :2]
            p += vc * 20
            vb = np.frombuffer(d, dtype="<f4", count=vc * 13, offset=p).reshape(vc, 13)
            pos, nrm = vb[:, 1:4], vb[:, 5:8]
            p += vc * 52
            weights = np.frombuffer(d, dtype="<f4", count=vc * 4, offset=p).reshape(vc, 4)
            p += vc * 16
            joints = np.frombuffer(d, dtype=np.uint8, count=vc * 4, offset=p).reshape(vc, 4)
            p += vc * 4
        else:
            weights = joints = None
            pos = np.frombuffer(d, dtype="<f4", count=vc * 3, offset=p).reshape(vc, 3)
            p += vc * 12
            attr = np.frombuffer(d, dtype="<f4", count=vc * 12, offset=p).reshape(vc, 12)
            nrm, uv = attr[:, 0:3], attr[:, 7:9]
            p += vc * 48 + extra * 16
        if p > len(d):
            raise _Bad
        if icount and int(idx.max()) >= vc:
            raise _Bad
        if not np.isfinite(pos).all():
            raise _Bad
        expected = p - base + 8
        parts.append(
            MeshPart(
                skinned=skinned,
                positions=pos.astype(np.float32),
                normals=nrm.astype(np.float32),
                uvs=uv.astype(np.float32),
                indices=idx.astype(np.uint32),
                submeshes=subs,
                bones=bones,
                bbox=bbox,
                joints=None if joints is None else joints.copy(),
                weights=None if weights is None else weights.astype(np.float32),
            )
        )
    return Mesh(offset=start, end=base + expected - 8, parts=parts)


def _candidates(payload, chunk: int = 1 << 26) -> np.ndarray:
    """Offsets whose header prefix looks like a mesh (vectorized, releases the GIL).

    Prefix: u32 any, u32 n, u32 n, u32[n], u32 n, i32[n], i32 -n  (1 <= n <= 255).
    """
    a = np.frombuffer(payload, dtype=np.uint8)
    total = len(a)
    found = []
    for s in range(0, max(total - 32, 0), chunk):
        e = min(total - 16, s + chunk)
        k = e - s
        b = a[s : e + 16]
        n = b[4 : k + 4]
        m = n != 0
        for off in (5, 6, 7, 9, 10, 11):
            m &= b[off : k + off] == 0
        m &= b[8 : k + 8] == n
        found.append(np.nonzero(m)[0] + s)
    if not found:
        return np.zeros(0, dtype=np.int64)
    c = np.concatenate(found).astype(np.int64)
    n = a[c + 4].astype(np.int64)
    ok = c + 20 + 8 * n < total
    c, n = c[ok], n[ok]
    p = c + 12 + 4 * n
    ok = (a[p] == n) & (a[p + 1] == 0) & (a[p + 2] == 0) & (a[p + 3] == 0)
    q = c + 16 + 8 * n
    ok &= (a[q] == 256 - n) & (a[q + 1] == 255) & (a[q + 2] == 255) & (a[q + 3] == 255)
    return c[ok]


def find_meshes(payload) -> list[Mesh]:
    """Locate and decode every mesh resource in a decompressed payload."""
    meshes = []
    pos = 0
    for start in _candidates(payload).tolist():
        if start < pos:
            continue
        try:
            mesh = _parse_mesh(payload, start)
        except (_Bad, struct.error, ValueError, IndexError):
            continue
        meshes.append(mesh)
        pos = mesh.end
    return meshes


def _similarity(name: str, mesh: Mesh) -> float:
    from difflib import SequenceMatcher

    n = name.lower()
    return max((SequenceMatcher(None, n, m.lower()).ratio() for m in mesh.materials), default=0.0)


def assign_names(meshes: list[Mesh], resource_names: list[str]) -> None:
    """Meshes appear in the payload in resource-table order.

    If some table entries could not be decoded, align the decoded meshes to the
    names in order, maximizing name/material similarity.
    """
    m, n = len(meshes), len(resource_names)
    if m == n:
        for mesh, name in zip(meshes, resource_names):
            mesh.name = name
    elif 0 < m < n:
        neg = float("-inf")
        # best[i][j]: best score placing the first i meshes among the first j names
        best = [[neg] * (n + 1) for _ in range(m + 1)]
        take = [[False] * (n + 1) for _ in range(m + 1)]
        for j in range(n + 1):
            best[0][j] = 0.0
        for i in range(1, m + 1):
            for j in range(i, n + 1):
                skip = best[i][j - 1]
                use = best[i - 1][j - 1] + _similarity(resource_names[j - 1], meshes[i - 1])
                if use >= skip:
                    best[i][j], take[i][j] = use, True
                else:
                    best[i][j] = skip
        i, j = m, n
        while i > 0:
            if take[i][j]:
                meshes[i - 1].name = resource_names[j - 1]
                i -= 1
            j -= 1
    for i, mesh in enumerate(meshes):
        if not mesh.name:
            mats = mesh.materials
            mesh.name = mats[0] if mats else f"mesh_{i:03d}"
