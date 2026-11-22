# Darksiders II Deathinitive Edition (PC) file formats

Reverse-engineering notes used by DDWExtractor. All integers are little endian. Hashed
names use CRC64 (polynomial `0x01A1561E0005800C`, initial value and final XOR
`0xFFFFFFFFFFFFFFFF`, reflected table).

## `media` folder

| File | Contents |
|---|---|
| `manifest.bin` | Index of every asset |
| `media.upak`, `maps.upak` | Concatenated OBPK containers, 0x800 aligned |
| `anim_streams.upak` | Streamed animations (zlib) |
| `scripts.obsp` | Gameplay data (BOD objects) |

### manifest.bin (version 13)

```
u32 version
40 bytes
u32 n_folders, u32 (unused)
n_folders x { u64 hash, u32 len, char[len] path }
u32 n_paks
n_paks x { u8, u16 len, char[len] name }             "media", "maps"...
u32 n_assets
n_assets x {
    u8 len, char[len] name, u64 hash,
    u16 package_id, u16 folder_index,
    u8 align, align*2 bytes, u8, u8 pak_index, 2 bytes,
    u64 offset (u32 if version < 13)
}
```

An asset's size is the distance to the next asset in the same `.upak`.

## OBPK container

```
0x00  "OBPK"
0x04  u8   0 = little endian
0x05  u32  version (9)
0x09  u32  section A offset, 0x0D u32 section A size
0x11  u32  section B offset, 0x15 u32 section B size
0x19  u32  data start (multiple of 0x800)
```

Section A (resource table):

```
u32 n_groups, u32 n_entries, u32 blob_size, u32
blob[blob_size]                 per-entry hashes and u16 pairs
4 x u32
n_groups x { u32 type, u32 n, u32 hash_offset, u32 u16_offset, u8 flags[n] }
u8 has_names, u32 max_length
per group, n x { u64 hash, u32 len, char[len] }
```

Group types: 0 effects, 1 models (`Object3D`), 2 meshes, 5 materials, 6 textures,
8 animations, 9 sound, 11 cloth/physics, 20 skeleton.

Data: a sequence of `{ u32 uncompressed_size, zlib stream }` chunks. Concatenated they form
the *payload*. Resources appear in the payload in resource-table order.

## BOD objects

`"BOD\xFD"`, u8 mode (4), 3 bytes, u32, u32, then one root object.

Object: `u8 kind` (0 = null; 4 = 4 extra bytes), class name, `u32 n`, then n times
`property_name, value`.

Name: `u8 1, u64 hash, u16 len, char[len]` the first time (appended to a per-blob list) or
`u8 0, u32 index` afterwards.

Values (u8 tag): `00` null, `02` i32, `03` f32, `04` bool, `05 FF u16 len` string,
`07 u32` + object, `09`/`0A` `u32 n, u8 is_map` + items (or key/value pairs), `0B u32 n`
list, `0D` u64, `0F` name, `FC u32 id, u64 hash` reference.

Useful classes: `Material` (`Name`, `ShaderName`, `Parameters` → `DiffuseMap1`,
`NormalMap1`, `SpecularMap1`, `EmissiveMap1` → `Value` = texture name), `Object3D`
(`Skeleton`, `Visuals`), `Skeleton3D`/`Node3D` (`Name`, `Position`, `Rotation`,
`Children`), `SkinMeshVisual` / `StaticMeshVisual` (`MeshName`, `MeshID`, `RefNode`).

## Meshes

```
u32 unknown
u32 n_parts, u32 n_parts, u32 index_count[n]
u32 n_parts, i32 vertex_count[n]       >0 skinned, <0 static
i32 -n_parts
n x (u32 extra_count, u32)             entries of an optional 16-byte stream (static parts)
n x part_header
n x part_data
```

Part header:

```
u8  skinned
u32 vertex_count, u32 gpu_stride (64 / 60), u32 index_offset (relative to data start)
skinned: u32 n_submeshes, u32 n_bones          static: u32 (2), u32 n_submeshes
6 x f32 bounding box (min, max)
skinned: n_bones x { name, 16 x f32 inverse bind matrix, u32 bone id }
n_submeshes x { material_name, i32 id, u32 0, u32 vertex_count, u32 base_vertex,
                u32 index_count, u32 first_index }
```

(`name` = `FF, u16 len, ascii`.)

Part data:

```
u32 index_bytes, u32 index_size (2 or 4), indices (triangle list, part-global)
skinned:
    n x 20 B  { f32 u, f32 v, u32 0, u32 0, i32 -1 }
    n x 52 B  { u32 influence_count, f32 x y z, f32 1.0, f32 normal[3], f32 tangent[4], f32 sign }
    n x 16 B  weights (4 x f32, sum 1)
    n x  4 B  bone indices (4 x u8, into the part's bone list)
static:
    n x 12 B  f32 x y z
    n x 48 B  { normal[3], tangent[3], sign, f32 u, f32 v, u32 0, u32 0, i32 -1 }
    extra_count x 16 B
```

Matrices use the row-vector convention (translation in the last row). Game space is Z-up.
Death is about 64 units tall.

Static parts live in the local space of the `RefNode` bone of their `StaticMeshVisual`.
That bone's transform comes from its bind matrix (if a skinned part uses it) or from the
skeleton. `Node3D` rotations: degrees, applied X then Y then Z (`R = Rx·Ry·Rz`, row
vectors). Weapons, armor and gear use the skeleton in `characters/death`.

## Textures

Complete DDS files (`"DDS "`, DXT1/DXT5) inside the payload, in the same order as the
texture group of the resource table.
