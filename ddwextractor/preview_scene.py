"""Build preview scenes from loaded game meshes."""

from __future__ import annotations

import numpy as np

from .ds2.extract import LoadedAsset
from .ds2.mesh import Mesh
from .preview import PreviewMesh, Scene, game_to_y_up, texture_array, triangle_colors

_VFX_PREFIXES = ("vfx", "z_vfx", "gfx3d", "fx_")


def is_vfx(material: str) -> bool:
    return material.lower().startswith(_VFX_PREFIXES)


def build_scene(la: LoadedAsset, meshes: list[Mesh], hide_vfx: bool = True, tex_size: int = 1024) -> Scene:
    textures: list[np.ndarray] = []
    tex_slot: dict[str, int] = {}

    def slot(tex_name: str | None) -> int:
        if not tex_name:
            return -1
        key = tex_name.lower()
        if key not in tex_slot:
            img = la.texture_image(tex_name, tex_size)
            if img is None:
                tex_slot[key] = -1
            else:
                textures.append(texture_array(img))
                tex_slot[key] = len(textures) - 1
        return tex_slot[key]

    items = []
    for m in meshes:
        for part in m.parts:
            tris = part.indices.reshape(-1, 3)
            if len(tris) == 0:
                continue
            keep = np.ones(len(tris), dtype=bool)
            colors = triangle_colors(part.uvs, tris, None)
            tex_ids = np.full(len(tris), -1, np.int32)
            emis_ids = np.full(len(tris), -1, np.int32)
            for sub in part.submeshes:
                a, b = sub.first_index // 3, (sub.first_index + sub.index_count) // 3
                if a >= b:
                    continue
                if hide_vfx and is_vfx(sub.material):
                    keep[a:b] = False
                    continue
                maps = la.materials.get(sub.material.lower(), {})
                d = slot(maps.get("diffuse"))
                if d >= 0:
                    tex_ids[a:b] = d
                    colors[a:b] = triangle_colors(part.uvs, tris[a:b], _as_image(textures[d]))
                emis = maps.get("emissive")
                if emis and emis != maps.get("specular"):
                    emis_ids[a:b] = slot(emis)
            if keep.any():
                items.append(PreviewMesh(
                    positions=game_to_y_up(part.positions),
                    triangles=tris[keep],
                    colors=colors[keep],
                    normals=game_to_y_up(part.normals),
                    uvs=part.uvs,
                    tex_ids=tex_ids[keep],
                    emis_ids=emis_ids[keep],
                ))
    return Scene(items, textures)


def _as_image(arr: np.ndarray):
    from PIL import Image

    return Image.fromarray(arr)
