"""High-level loading and extraction of one Darksiders II asset (OBJ + PNG)."""

from __future__ import annotations

import fnmatch
import io
import mmap
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from ..export.gltf import write_glb
from ..export.obj import write_obj
from .archive import AssetEntry, Game
from .bod import iter_bods
from .mesh import Mesh, assign_names, find_meshes
from .package import TYPE_MESH, TYPE_TEXTURE, names_of, read_resource_table
from .skeleton import Skeleton, place_static_parts, read_models
from .texture import Texture, find_textures, save_texture

_TEX_SLOTS = {
    "DiffuseMap1": "diffuse",
    "NormalMap1": "normal",
    "SpecularMap1": "specular",
    "EmissiveMap1": "emissive",
}


@dataclass
class ExtractResult:
    asset: str
    meshes: list[str] = field(default_factory=list)
    textures: int = 0
    out_dir: Path | None = None


@contextmanager
def open_payload(game: Game, entry: AssetEntry, work_dir: Path | None = None, progress=None):
    """Decompress an asset to a temporary file and memory-map it."""
    fd, tmp = tempfile.mkstemp(suffix=".dec", dir=work_dir)
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        size = game.payload_to_file(entry, tmp_path, progress)
        if size == 0:
            yield b""
            return
        with open(tmp_path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            yield mm
    finally:
        tmp_path.unlink(missing_ok=True)


_SKELETON_CACHE: dict[tuple[int, str], Skeleton] = {}
# Weapons, armor and gear attach to the player's skeleton.
_PLAYER_ASSET = "characters/death"


def _fallback_skeleton(game: Game, entry: AssetEntry, work_dir: Path | None) -> Skeleton:
    key = (id(game), _PLAYER_ASSET)
    if key not in _SKELETON_CACHE:
        sk = Skeleton()
        player = game.find(_PLAYER_ASSET)
        if player is not None and player.path != entry.path:
            with open_payload(game, player, work_dir) as payload:
                sk = read_models(payload)[0]
        _SKELETON_CACHE[key] = sk
    return _SKELETON_CACHE[key]


def read_materials(payload) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for _, obj in iter_bods(payload, "Material"):
        name = obj.get("Name")
        if not isinstance(name, str):
            continue
        params = obj.get("Parameters") or {}
        maps = {}
        if isinstance(params, dict):
            for slot, key in _TEX_SLOTS.items():
                p = params.get(slot)
                value = p.get("Value") if hasattr(p, "get") else None
                if isinstance(value, str) and value:
                    maps[key] = value
        out[name.lower()] = maps
    return out


class LoadedAsset:
    """A decompressed asset with its meshes, materials and textures.

    Keeps the decompressed payload memory-mapped until :meth:`close`.
    """

    def __init__(self, game: Game, entry: AssetEntry, work_dir: Path | None = None, log=print):
        self.game = game
        self.entry = entry
        self.meshes: list[Mesh] = []
        self.materials: dict[str, dict[str, str]] = {}
        self.textures: list[Texture] = []
        self._images: dict[tuple[str, int], object] = {}
        self._file = None
        self.payload = b""

        groups = read_resource_table(game.read_header(entry))
        mesh_names = names_of(groups, TYPE_MESH)
        tex_names = names_of(groups, TYPE_TEXTURE)
        if not mesh_names and not tex_names:
            return

        fd, tmp = tempfile.mkstemp(suffix=".dec", dir=work_dir)
        os.close(fd)
        self._tmp = Path(tmp)
        log(f"  {entry.path}: decompressing {entry.size / 1e6:.1f} MB...")
        try:
            if game.payload_to_file(entry, self._tmp) == 0:
                return
            self._file = open(self._tmp, "rb")
            self.payload = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
            payload = self.payload

            if mesh_names:
                self.meshes = find_meshes(payload)
                assign_names(self.meshes, mesh_names)
                if len(self.meshes) != len(mesh_names):
                    log(f"  warning: expected {len(mesh_names)} meshes, decoded {len(self.meshes)}")
            self._work_dir = work_dir
            self._skeleton: Skeleton | None = None
            self._attachments: list = []
            if any(not p.skinned for m in self.meshes for p in m.parts):
                place_static_parts(self.meshes, self.skeleton, self._attachments)
            self.materials = read_materials(payload) if self.meshes else {}
            self.textures = find_textures(payload, tex_names) if tex_names else []
        except BaseException:
            self.close()
            raise
        self._tex_by_name = {t.name.lower(): t for t in self.textures}

    @property
    def skeleton(self) -> Skeleton:
        """Bone hierarchy of the asset (falls back to Death's for player items)."""
        if getattr(self, "_skeleton", None) is None:
            sk, self._attachments = read_models(self.payload) if self.payload else (Skeleton(), [])
            needed = {b.name for m in self.meshes for p in m.parts for b in p.bones}
            needed |= {bone for _, _, bone in self._attachments}
            if needed - set(sk.world):
                sk.merge(_fallback_skeleton(self.game, self.entry, getattr(self, "_work_dir", None)))
            self._skeleton = sk
        return self._skeleton

    def texture_png(self, name: str) -> bytes | None:
        img = self.texture_image(name, 8192)
        if img is None:
            return None
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    # ---------------------------------------------------------------- utils
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        if isinstance(self.payload, mmap.mmap):
            self.payload.close()
        self.payload = b""
        if self._file:
            self._file.close()
            self._file = None
        tmp = getattr(self, "_tmp", None)
        if tmp:
            tmp.unlink(missing_ok=True)
            self._tmp = None

    def select(self, patterns: str | None = None, names: list[str] | None = None) -> list[Mesh]:
        meshes = self.meshes
        if names is not None:
            wanted = {n.lower() for n in names}
            meshes = [m for m in meshes if m.name.lower() in wanted]
        if patterns:
            pats = [p.strip().lower() for p in patterns.split(",") if p.strip()]
            meshes = [m for m in meshes if any(fnmatch.fnmatch(m.name.lower(), p) for p in pats)]
        return meshes

    def texture_image(self, name: str, max_size: int = 512):
        """Decoded texture as a Pillow image (thumbnail), or None."""
        key = (name.lower(), max_size)
        if max_size > 1024:  # full-size decodes are not cached (memory)
            self._images.pop(key, None)
        if key not in self._images:
            img = None
            tex = getattr(self, "_tex_by_name", {}).get(name.lower())
            if tex is not None and self.payload:
                try:
                    from PIL import Image

                    raw = bytes(self.payload[tex.offset : tex.offset + tex.size])
                    img = Image.open(io.BytesIO(raw))
                    img.load()
                    img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
                    if max(img.size) > max_size:
                        img.thumbnail((max_size, max_size))
                except Exception:
                    img = None
            if max_size > 1024:
                return img
            self._images[key] = img
        return self._images[key]

    def diffuse_image(self, material: str, max_size: int = 512):
        tex = self.materials.get(material.lower(), {}).get("diffuse")
        return self.texture_image(tex, max_size) if tex else None

    # ---------------------------------------------------------------- export
    def export(
        self,
        out_root: Path,
        meshes: list[Mesh] | None = None,
        all_textures: bool = False,
        combine: bool = False,
        scale: float = 1.0,
        log=print,
        fmt: str = "both",
    ) -> ExtractResult:
        """Write textures (PNG) and models: ``fmt`` is "obj", "glb" or "both"."""
        entry = self.entry
        out_dir = out_root / entry.path
        result = ExtractResult(entry.path, out_dir=out_dir)
        meshes = self.meshes if meshes is None else meshes
        want_obj, want_glb = fmt in ("obj", "both"), fmt in ("glb", "both")

        wanted = None
        if not all_textures:
            wanted = set()
            for m in meshes:
                for mat in m.materials:
                    wanted.update(t.lower() for t in self.materials.get(mat.lower(), {}).values())
        tex_dir = out_dir / "textures"
        for t in self.textures:
            if wanted is not None and t.name.lower() not in wanted:
                continue
            tex_dir.mkdir(parents=True, exist_ok=True)
            save_texture(self.payload, t, tex_dir)
            result.textures += 1

        if meshes:
            model_dir = out_dir / "models"
            model_dir.mkdir(parents=True, exist_ok=True)
            groups_out: list[tuple[str, list[Mesh]]] = (
                [(entry.name, meshes)] if combine else [(m.name, [m]) for m in meshes]
            )
            used: set[str] = set()
            for name, group in groups_out:
                fname = name
                k = 2
                while fname.lower() in used:
                    fname = f"{name}_{k}"
                    k += 1
                used.add(fname.lower())
                if want_obj:
                    write_obj(group, model_dir / f"{fname}.obj", self.materials, tex_dir, scale)
                if want_glb:
                    # glTF is in meters: treat scaled units as centimeters.
                    write_glb(group, model_dir / f"{fname}.glb", self.materials,
                              lambda n: self._png_for(n, tex_dir), self.skeleton.parent, scale * 0.01)
                result.meshes.append(fname)
        log(f"  {entry.path}: {len(result.meshes)} models, {result.textures} textures -> {out_dir}")
        return result

    def _png_for(self, name: str, tex_dir: Path) -> bytes | None:
        f = tex_dir / f"{name}.png"
        if not f.exists():
            f = next((p for p in tex_dir.glob("*.png") if p.stem.lower() == name.lower()), None) \
                if tex_dir.is_dir() else None
        if f is not None and f.exists():
            return f.read_bytes()
        return self.texture_png(name)


def extract_asset(
    game: Game,
    asset: str | AssetEntry,
    out_root: Path,
    mesh_filter: str | None = None,
    all_textures: bool = False,
    combine: bool = False,
    scale: float = 1.0,
    log=print,
    fmt: str = "both",
) -> ExtractResult:
    entry = asset if isinstance(asset, AssetEntry) else game.find(asset)
    if entry is None:
        raise KeyError(f"Unknown asset '{asset}'. Use 'list' to see the names.")
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    with LoadedAsset(game, entry, out_root, log) as loaded:
        if not loaded.meshes and not loaded.textures:
            log(f"  {entry.path}: no models or textures, skipped")
            return ExtractResult(entry.path)
        return loaded.export(
            out_root, loaded.select(mesh_filter), all_textures=all_textures,
            combine=combine, scale=scale, log=log, fmt=fmt,
        )


def model_assets(game: Game) -> list[AssetEntry]:
    """Assets whose resource table lists at least one mesh."""
    out = []
    for e in game.assets:
        if e.pak not in ("media", "maps"):
            continue
        try:
            groups = read_resource_table(game.read_header(e))
        except (ValueError, OSError):
            continue
        if names_of(groups, TYPE_MESH):
            out.append(e)
    return out
