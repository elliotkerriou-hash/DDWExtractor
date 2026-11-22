"""Skeletons and placement of bone-attached ("static") mesh parts.

``Object3D`` BOD objects hold an optional ``Skeleton`` (a tree of ``Node3D``
with ``Position`` and ``Rotation``: Euler degrees applied X, then Y, then Z)
and a ``Visuals`` list. A ``StaticMeshVisual`` attaches part ``MeshID`` of
mesh ``MeshName`` to bone ``RefNode``; that part's vertices are in the bone's
local space. Matrices here use the row-vector convention (translation in the
last row), like the bind matrices stored in skinned mesh parts.
"""

from __future__ import annotations

import numpy as np

from .bod import BodObject, iter_bods
from .mesh import Mesh


def _rot(axis: int, deg: float) -> np.ndarray:
    t = np.radians(deg)
    c, s = np.cos(t), np.sin(t)
    if axis == 0:
        return np.array([[1, 0, 0], [0, c, s], [0, -s, c]])
    if axis == 1:
        return np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]])
    return np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])


def _vec3(v) -> list[float]:
    if isinstance(v, list) and len(v) >= 3 and all(isinstance(x, (int, float)) for x in v[:3]):
        return [float(x) for x in v[:3]]
    return [0.0, 0.0, 0.0]


class Skeleton:
    def __init__(self):
        self.parent: dict[str, str | None] = {}
        self.world: dict[str, np.ndarray] = {}

    @classmethod
    def from_bod(cls, root: BodObject) -> "Skeleton":
        sk = cls()
        stack = [(root, None, np.eye(4))]
        while stack:
            node, parent, parent_world = stack.pop()
            name = node.get("Name")
            rx, ry, rz = _vec3(node.get("Rotation"))
            local = np.eye(4)
            local[:3, :3] = _rot(0, rx) @ _rot(1, ry) @ _rot(2, rz)
            local[3, :3] = _vec3(node.get("Position"))
            world = local @ parent_world
            if isinstance(name, str):
                sk.parent.setdefault(name, parent)
                sk.world.setdefault(name, world)
            for child in node.get("Children") or []:
                if isinstance(child, BodObject):
                    stack.append((child, name if isinstance(name, str) else parent, world))
        return sk

    def merge(self, other: "Skeleton") -> None:
        for k, v in other.world.items():
            self.world.setdefault(k, v)
            self.parent.setdefault(k, other.parent.get(k))


def read_models(payload) -> tuple[Skeleton, list[tuple[str, int, str]]]:
    """Return (merged skeleton, [(mesh_name, part_index, bone)]) of an asset."""
    skeleton = Skeleton()
    attachments = []
    for _, obj in iter_bods(payload, "Object3D"):
        sk = obj.get("Skeleton")
        if isinstance(sk, BodObject):
            skeleton.merge(Skeleton.from_bod(sk))
        for vis in obj.get("Visuals") or []:
            if isinstance(vis, BodObject) and vis.cls == "StaticMeshVisual":
                mesh, mid, bone = vis.get("MeshName"), vis.get("MeshID"), vis.get("RefNode")
                if isinstance(mesh, str) and isinstance(mid, int) and isinstance(bone, str):
                    attachments.append((mesh.lower(), mid, bone))
    return skeleton, attachments


def place_static_parts(
    meshes: list[Mesh],
    skeleton: Skeleton,
    attachments: list[tuple[str, int, str]],
) -> int:
    """Move bone-attached static parts into model space. Returns parts moved."""
    # Bone -> model transforms known exactly from skinned parts' bind matrices.
    bind: dict[str, np.ndarray] = {}
    for m in meshes:
        for p in m.parts:
            for b in p.bones:
                if b.name not in bind:
                    try:
                        bind[b.name] = np.linalg.inv(np.array(b.matrix, dtype=np.float64).reshape(4, 4))
                    except np.linalg.LinAlgError:
                        pass

    def bone_world(bone: str) -> np.ndarray | None:
        if bone in bind:
            return bind[bone]
        if bone not in skeleton.world:
            return None
        # Nearest ancestor with a bind matrix anchors the skeleton offset.
        anc = skeleton.parent.get(bone)
        while anc is not None and anc not in bind:
            anc = skeleton.parent.get(anc)
        if anc is not None and anc in skeleton.world:
            rel = skeleton.world[bone] @ np.linalg.inv(skeleton.world[anc])
            return rel @ bind[anc]
        return skeleton.world[bone]

    by_name = {m.name.lower(): m for m in meshes if m.name}
    moved = 0
    for mesh_name, part_idx, bone in attachments:
        m = by_name.get(mesh_name)
        if m is None or not 0 <= part_idx < len(m.parts):
            continue
        part = m.parts[part_idx]
        if part.skinned or getattr(part, "_placed", False):
            continue
        w = bone_world(bone)
        if w is None:
            continue
        pos = part.positions.astype(np.float64)
        part.positions = (pos @ w[:3, :3] + w[3, :3]).astype(np.float32)
        part.normals = (part.normals.astype(np.float64) @ w[:3, :3]).astype(np.float32)
        part._placed = True
        part.attach_bone = bone
        part.attach_world = w
        moved += 1
    return moved
