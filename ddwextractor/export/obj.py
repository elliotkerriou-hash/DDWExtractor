"""Wavefront OBJ/MTL writer (opens in Blender, 3ds Max, Maya, slicers...)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..ds2.mesh import Mesh


def _to_y_up(v: np.ndarray) -> np.ndarray:
    """Game space is Z-up; OBJ convention is Y-up."""
    return np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def write_obj(
    meshes: list[Mesh],
    obj_path: Path,
    materials: dict[str, dict[str, str]] | None = None,
    texture_dir: Path | None = None,
    scale: float = 1.0,
) -> None:
    """Write one or more meshes into a single OBJ (one object per mesh part).

    ``materials`` maps material name -> {"diffuse": tex, "normal": tex, ...};
    texture names are resolved to ``texture_dir/<name>.png`` (case-insensitive).
    """
    materials = materials or {}
    tex_files: dict[str, Path] = {}
    if texture_dir and texture_dir.is_dir():
        for f in texture_dir.iterdir():
            tex_files.setdefault(f.stem.lower(), f)

    mtl_path = obj_path.with_suffix(".mtl")
    used_mats: dict[str, None] = {}
    lines = [f"# DDWExtractor\nmtllib {mtl_path.name}\n"]
    base = 1
    for mesh in meshes:
        for pi, part in enumerate(mesh.parts):
            n = len(part.positions)
            if n == 0:
                continue
            label = part.submeshes[0].material if part.submeshes else "part"
            lines.append(f"o {_safe(mesh.name or 'mesh')}_{pi:02d}_{_safe(label)}\n")
            pos = _to_y_up(part.positions.astype(np.float64)) * scale
            nrm = _to_y_up(part.normals.astype(np.float64))
            lines.append("".join(f"v {x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in pos))
            lines.append("".join(f"vt {u:.6f} {1.0 - v:.6f}\n" for u, v in part.uvs))
            lines.append("".join(f"vn {x:.5f} {y:.5f} {z:.5f}\n" for x, y, z in nrm))
            tris = part.indices.reshape(-1, 3).astype(np.int64) + base
            covered = np.zeros(len(tris), dtype=bool)
            for sub in part.submeshes:
                a, b = sub.first_index // 3, (sub.first_index + sub.index_count) // 3
                if a >= b:
                    continue
                used_mats.setdefault(sub.material, None)
                lines.append(f"usemtl {_safe(sub.material)}\n")
                lines.append(_faces(tris[a:b]))
                covered[a:b] = True
            if not covered.all():
                lines.append(_faces(tris[~covered]))
            base += n
    obj_path.write_text("".join(lines), encoding="utf-8")

    mtl = ["# DDWExtractor\n"]
    for mat in used_mats:
        mtl.append(f"\nnewmtl {_safe(mat)}\nKa 0 0 0\nKd 0.8 0.8 0.8\nKs 0.1 0.1 0.1\nNs 20\nd 1\nillum 2\n")
        maps = materials.get(mat.lower(), {})
        for key, slot in (("diffuse", "map_Kd"), ("specular", "map_Ks"), ("normal", "map_Bump"), ("emissive", "map_Ke")):
            tex = maps.get(key)
            f = tex_files.get(tex.lower()) if tex else None
            if f:
                rel = Path("..", f.parent.name, f.name).as_posix() if f.parent != obj_path.parent else f.name
                mtl.append(f"{slot} {rel}\n")
    mtl_path.write_text("".join(mtl), encoding="utf-8")


def _faces(t: np.ndarray) -> str:
    return "".join(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n" for a, b, c in t)
