"""OBPK header: the per-asset resource table (names grouped by type)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

# Resource type: the index stored in each group record of the header.
TYPE_EFFECT = 0
TYPE_MODEL = 1
TYPE_MESH = 2
TYPE_MATERIAL = 5
TYPE_TEXTURE = 6
TYPE_ANIMATION = 8
TYPE_SOUND = 9
TYPE_CLOTH = 11
TYPE_SKELETON = 20

TYPE_NAMES = {
    TYPE_EFFECT: "effect",
    TYPE_MODEL: "model",
    TYPE_MESH: "mesh",
    TYPE_MATERIAL: "material",
    TYPE_TEXTURE: "texture",
    TYPE_ANIMATION: "animation",
    TYPE_SOUND: "sound",
    TYPE_CLOTH: "cloth",
    TYPE_SKELETON: "skeleton",
}


@dataclass
class ResourceGroup:
    type_id: int
    names: list[str]

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.type_id, f"type{self.type_id}")


def read_resource_table(header: bytes) -> list[ResourceGroup]:
    if header[:4] != b"OBPK":
        raise ValueError("not an OBPK header")
    a_off, a_size = struct.unpack_from("<2I", header, 9)
    p = a_off
    n_groups, _n_entries, blob_size, _ = struct.unpack_from("<4I", header, p)
    p += 16 + blob_size + 16
    raw_groups = []
    for _ in range(n_groups):
        type_id, count, _o1, _o2 = struct.unpack_from("<4I", header, p)
        p += 16 + count  # followed by one flag byte per entry
        raw_groups.append((count, type_id))
    groups = []
    has_names = header[p]
    p += 1
    if has_names:
        p += 4
    for count, type_id in raw_groups:
        names = []
        if has_names:
            for _ in range(count):
                n = struct.unpack_from("<I", header, p + 8)[0]
                names.append(header[p + 12 : p + 12 + n].decode("utf-8", "replace"))
                p += 12 + n
        groups.append(ResourceGroup(type_id, names))
    if p > a_off + a_size:
        raise ValueError("OBPK resource table overruns its section")
    return groups


def names_of(groups: list[ResourceGroup], type_id: int) -> list[str]:
    out: list[str] = []
    for g in groups:
        if g.type_id == type_id:
            out.extend(g.names)
    return out
