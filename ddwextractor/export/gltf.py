"""Binary glTF 2.0 (.glb) writer with skeleton and skin weights.

Opens in Blender (File > Import > glTF 2.0), so models can be posed.
"""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path
from typing import Callable

import numpy as np

from ..ds2.mesh import Mesh

# Game space is Z-up with row-vector matrices; glTF is Y-up.
# Row-vector conversion p' = p @ _C maps (x, y, z) -> (x, z, -y).
_C = np.eye(4)
_C[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
_C_INV = _C.T.copy()


def _convert_matrix(w: np.ndarray, scale: float) -> np.ndarray:
    m = _C_INV @ w @ _C
    m[3, :3] *= scale
    return m


class _Buffer:
    def __init__(self):
        self.data = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []

    def _view(self, raw: bytes, target: int | None = None) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        view = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(raw)}
        if target:
            view["target"] = target
        self.data += raw
        self.views.append(view)
        return len(self.views) - 1

    def accessor(self, arr: np.ndarray, kind: str, target: int | None = None, minmax: bool = False) -> int:
        ctype = {np.dtype(np.float32): 5126, np.dtype(np.uint32): 5125,
                 np.dtype(np.uint16): 5123, np.dtype(np.uint8): 5121}[arr.dtype]
        arr = np.ascontiguousarray(arr)
        acc = {
            "bufferView": self._view(arr.tobytes(), target),
            "componentType": ctype,
            "count": int(arr.shape[0]),
            "type": kind,
        }
        if minmax:
            acc["min"] = arr.min(axis=0).astype(float).tolist()
            acc["max"] = arr.max(axis=0).astype(float).tolist()
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def image_view(self, png: bytes) -> int:
        return self._view(png)


def write_glb(
    meshes: list[Mesh],
    path: Path,
    materials: dict[str, dict[str, str]],
    texture_png: Callable[[str], bytes | None],
    bone_parent: dict[str, str | None],
    scale: float = 1.0,
) -> None:
    """``texture_png(name)`` returns PNG bytes of a texture (or None);
    ``bone_parent`` maps bone name -> parent bone name (skeleton hierarchy)."""
    buf = _Buffer()
    gl: dict = {
        "asset": {"version": "2.0", "generator": "DDWExtractor"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "materials": [],
        "textures": [],
        "images": [],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
        "buffers": [],
        "bufferViews": buf.views,
        "accessors": buf.accessors,
    }

    # ---------------------------------------------------------------- joints
    world: dict[str, np.ndarray] = {}
    for m in meshes:
        for part in m.parts:
            for b in part.bones:
                if b.name not in world:
                    try:
                        world[b.name] = np.linalg.inv(np.array(b.matrix, dtype=np.float64).reshape(4, 4))
                    except np.linalg.LinAlgError:
                        continue
            if not part.skinned and part.attach_bone and part.attach_world is not None:
                world.setdefault(part.attach_bone, np.asarray(part.attach_world, dtype=np.float64))
    joint_names = list(world)
    joint_index = {n: i for i, n in enumerate(joint_names)}
    conv = {n: _convert_matrix(w, scale) for n, w in world.items()}

    def joint_parent(name: str) -> str | None:
        p = bone_parent.get(name)
        seen = set()
        while p is not None and p not in joint_index and p not in seen:
            seen.add(p)
            p = bone_parent.get(p)
        return p if p in joint_index else None

    skin_root = None
    if joint_names:
        skin_root = len(gl["nodes"])
        gl["nodes"].append({"name": "Armature", "children": []})
        gl["scenes"][0]["nodes"].append(skin_root)
        first_joint = len(gl["nodes"])
        for name in joint_names:
            gl["nodes"].append({"name": name})
        for name in joint_names:
            node = gl["nodes"][first_joint + joint_index[name]]
            parent = joint_parent(name)
            if parent is None:
                local = conv[name]
                gl["nodes"][skin_root]["children"].append(first_joint + joint_index[name])
            else:
                local = conv[name] @ np.linalg.inv(conv[parent])
                gl["nodes"][first_joint + joint_index[parent]].setdefault("children", []).append(
                    first_joint + joint_index[name])
            if not np.allclose(local, np.eye(4), atol=1e-6):
                node["matrix"] = local.reshape(-1).tolist()
        ibm = np.stack([np.linalg.inv(conv[n]) for n in joint_names]).astype(np.float32)
        gl["skins"] = [{
            "name": "Skeleton",
            "skeleton": skin_root,
            "joints": [first_joint + i for i in range(len(joint_names))],
            "inverseBindMatrices": buf.accessor(ibm.reshape(len(joint_names), 16), "MAT4"),
        }]

    # ---------------------------------------------------------------- materials
    mat_index: dict[str, int] = {}
    tex_index: dict[str, int | None] = {}

    def texture(name: str | None) -> tuple[int | None, bool]:
        if not name:
            return None, False
        key = name.lower()
        if key not in tex_index:
            png = texture_png(name)
            if png is None:
                tex_index[key] = None
            else:
                gl["images"].append({"name": name, "mimeType": "image/png", "bufferView": buf.image_view(png)})
                gl["textures"].append({"source": len(gl["images"]) - 1, "sampler": 0})
                tex_index[key] = len(gl["textures"]) - 1
                tex_index[key + "#alpha"] = _has_cutout_alpha(png)
        return tex_index[key], bool(tex_index.get(key + "#alpha"))

    def material(name: str) -> int:
        if name not in mat_index:
            maps = materials.get(name.lower(), {})
            base, alpha = texture(maps.get("diffuse"))
            mat: dict = {
                "name": name,
                "doubleSided": True,
                "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.8},
            }
            if base is not None:
                mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": base}
            if alpha:
                mat["alphaMode"] = "MASK"
                mat["alphaCutoff"] = 0.5
            emis, _ = texture(maps.get("emissive")) if maps.get("emissive") != maps.get("specular") else (None, False)
            if emis is not None:
                mat["emissiveTexture"] = {"index": emis}
                mat["emissiveFactor"] = [1.0, 1.0, 1.0]
            gl["materials"].append(mat)
            mat_index[name] = len(gl["materials"]) - 1
        return mat_index[name]

    # ---------------------------------------------------------------- meshes
    for m in meshes:
        for pi, part in enumerate(m.parts):
            n = len(part.positions)
            if n == 0 or len(part.indices) == 0:
                continue
            p = part.positions.astype(np.float64)
            pos = (np.stack([p[:, 0], p[:, 2], -p[:, 1]], axis=1) * scale).astype(np.float32)
            nr = part.normals.astype(np.float64)
            nrm = np.stack([nr[:, 0], nr[:, 2], -nr[:, 1]], axis=1)
            nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
            attrs = {
                "POSITION": buf.accessor(pos, "VEC3", 34962, minmax=True),
                "NORMAL": buf.accessor(nrm.astype(np.float32), "VEC3", 34962),
                "TEXCOORD_0": buf.accessor(part.uvs.astype(np.float32), "VEC2", 34962),
            }
            skinned = False
            if skin_root is not None:
                if part.skinned and part.joints is not None and part.bones:
                    lut = np.array([joint_index.get(b.name, 0) for b in part.bones], dtype=np.uint16)
                    j = lut[np.minimum(part.joints, len(lut) - 1)]
                    w = part.weights.astype(np.float32).copy()
                    w[w < 0] = 0
                    s = w.sum(axis=1, keepdims=True)
                    w = np.where(s > 0, w / np.maximum(s, 1e-12), np.array([1, 0, 0, 0], np.float32))
                    skinned = True
                elif part.attach_bone in joint_index:
                    j = np.zeros((n, 4), np.uint16)
                    j[:, 0] = joint_index[part.attach_bone]
                    w = np.zeros((n, 4), np.float32)
                    w[:, 0] = 1.0
                    skinned = True
                if skinned:
                    attrs["JOINTS_0"] = buf.accessor(j.astype(np.uint16), "VEC4", 34962)
                    attrs["WEIGHTS_0"] = buf.accessor(w.astype(np.float32), "VEC4", 34962)

            tris = part.indices.astype(np.uint32)
            prims = []
            covered = np.zeros(len(tris), dtype=bool)
            for sub in part.submeshes:
                a, b = sub.first_index, sub.first_index + sub.index_count
                if a >= b or b > len(tris):
                    continue
                covered[a:b] = True
                prims.append({"attributes": attrs, "mode": 4, "material": material(sub.material),
                              "indices": buf.accessor(tris[a:b], "SCALAR", 34963)})
            if not covered.all():
                prims.append({"attributes": attrs, "mode": 4, "indices": buf.accessor(tris[~covered], "SCALAR", 34963)})
            label = part.submeshes[0].material if part.submeshes else "part"
            gl["meshes"].append({"name": f"{m.name}_{pi:02d}_{label}", "primitives": prims})
            node = {"name": f"{m.name}_{pi:02d}_{label}", "mesh": len(gl["meshes"]) - 1}
            if skinned:
                node["skin"] = 0
            gl["nodes"].append(node)
            gl["scenes"][0]["nodes"].append(len(gl["nodes"]) - 1)

    for key in ("materials", "textures", "images", "meshes"):
        if not gl[key]:
            del gl[key]
    if "textures" not in gl:
        del gl["samplers"]
    while len(buf.data) % 4:
        buf.data.append(0)
    gl["buffers"] = [{"byteLength": len(buf.data)}]

    js = json.dumps(gl, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(buf.data)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(js), b"JSON"))
        f.write(js)
        f.write(struct.pack("<I4s", len(buf.data), b"BIN\x00"))
        f.write(buf.data)


def _has_cutout_alpha(png: bytes) -> bool:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(png)) as img:
            if "A" not in img.getbands():
                return False
            alpha = np.asarray(img.getchannel("A"))
            return bool((alpha < 128).mean() > 0.02)
    except Exception:
        return False
