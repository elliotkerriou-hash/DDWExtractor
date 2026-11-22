"""Software renderer for model previews (numpy + Pillow, no GPU needed).

Two modes:

* :meth:`Scene.render` - fast flat-shaded preview (one color per triangle),
  used while rotating.
* :meth:`Scene.render_detailed` - "in-game" look: z-buffered, per-pixel
  textures, smooth shading, alpha cut-out, emissive glow and anti-aliasing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

BACKGROUND = (32, 33, 40)
DEFAULT_COLOR = (0.72, 0.70, 0.66)


@dataclass
class PreviewMesh:
    """Triangles ready to draw (Y-up).

    ``colors`` are per-triangle RGB 0..1 (fast mode). ``tex_ids`` index the
    scene texture list (-1 = untextured); ``emis_ids`` likewise for glow maps.
    """

    positions: np.ndarray
    triangles: np.ndarray
    colors: np.ndarray
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    tex_ids: np.ndarray | None = None
    emis_ids: np.ndarray | None = None


def game_to_y_up(p: np.ndarray) -> np.ndarray:
    return np.stack([p[:, 0], p[:, 2], -p[:, 1]], axis=1)


def triangle_colors(uvs: np.ndarray, tris: np.ndarray, image: Image.Image | None) -> np.ndarray:
    """Sample a texture at each triangle's UV centroid (cheap 'textured' look)."""
    if image is None:
        return np.tile(np.array(DEFAULT_COLOR, dtype=np.float32), (len(tris), 1))
    tex = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    h, w = tex.shape[:2]
    c = uvs[tris].mean(axis=1)
    u = np.mod(c[:, 0], 1.0)
    v = np.mod(c[:, 1], 1.0)
    x = np.clip((u * w).astype(np.int64), 0, w - 1)
    y = np.clip((v * h).astype(np.int64), 0, h - 1)
    return tex[y, x]


def texture_array(image: Image.Image) -> np.ndarray:
    """RGBA uint8 array for :class:`Scene` textures."""
    return np.asarray(image.convert("RGBA"), dtype=np.uint8)


class Scene:
    def __init__(self, meshes: list[PreviewMesh], textures: list[np.ndarray] | None = None):
        self.textures = textures or []
        self.cutout = [bool((t[:, :, 3] < 128).mean() > 0.02) for t in self.textures]
        pos, tris, cols, nrm, uvs, tid, eid = [], [], [], [], [], [], []
        base = 0
        for m in meshes:
            n, k = len(m.positions), len(m.triangles)
            if n == 0 or k == 0:
                continue
            pos.append(m.positions.astype(np.float32))
            tris.append(m.triangles.astype(np.int64) + base)
            cols.append(m.colors.astype(np.float32))
            nrm.append(m.normals.astype(np.float32) if m.normals is not None else np.zeros((n, 3), np.float32))
            uvs.append(m.uvs.astype(np.float32) if m.uvs is not None else np.zeros((n, 2), np.float32))
            tid.append(m.tex_ids.astype(np.int32) if m.tex_ids is not None else np.full(k, -1, np.int32))
            eid.append(m.emis_ids.astype(np.int32) if m.emis_ids is not None else np.full(k, -1, np.int32))
            base += n
        if pos:
            self.positions = np.concatenate(pos)
            self.triangles = np.concatenate(tris)
            self.colors = np.concatenate(cols)
            self.normals = np.concatenate(nrm)
            self.uvs = np.concatenate(uvs)
            self.tex_ids = np.concatenate(tid)
            self.emis_ids = np.concatenate(eid)
            lo, hi = self.positions.min(0), self.positions.max(0)
        else:
            self.positions = np.zeros((0, 3), np.float32)
            self.triangles = np.zeros((0, 3), np.int64)
            self.colors = np.zeros((0, 3), np.float32)
            self.normals = np.zeros((0, 3), np.float32)
            self.uvs = np.zeros((0, 2), np.float32)
            self.tex_ids = self.emis_ids = np.zeros(0, np.int32)
            lo = hi = np.zeros(3, np.float32)
        self.bbox_min, self.bbox_max = lo, hi
        self.center = (lo + hi) / 2
        if len(self.positions):
            self.radius = float(np.sqrt(((self.positions - self.center) ** 2).sum(1).max())) or 1.0
        else:
            self.radius = 1.0

    @property
    def size(self) -> np.ndarray:
        """Width, height, depth in game units (Y-up)."""
        return self.bbox_max - self.bbox_min

    # ------------------------------------------------------------------ common
    def _view(self, yaw: float, pitch: float) -> np.ndarray:
        cy, sy = np.cos(yaw), np.sin(yaw)
        cp, sp = np.cos(pitch), np.sin(pitch)
        ry = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]], dtype=np.float32)
        rx = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]], dtype=np.float32)
        return ry @ rx

    # ------------------------------------------------------------------ fast
    def render(self, width: int, height: int, yaw: float, pitch: float, zoom: float = 1.0,
               max_triangles: int | None = None) -> Image.Image:
        img = Image.new("RGB", (width, height), BACKGROUND)
        if len(self.triangles) == 0:
            return img
        v = (self.positions - self.center) @ self._view(yaw, pitch)
        tris, cols = self.triangles, self.colors
        if max_triangles and len(tris) > max_triangles:
            step = int(np.ceil(len(tris) / max_triangles))
            tris, cols = tris[::step], cols[::step]
        t = v[tris]
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        light = np.array([0.35, 0.55, 0.76], dtype=np.float32)
        shade = 0.30 + 0.70 * np.abs(n @ light)
        rgb = np.clip(cols * shade[:, None] * 255.0, 0, 255).astype(np.uint8)

        scale = min(width, height) * 0.46 / self.radius * zoom
        sx = width / 2 + t[:, :, 0] * scale
        sy_ = height / 2 - t[:, :, 1] * scale
        order = np.argsort(t[:, :, 2].mean(axis=1))  # far (negative z) first
        pts = np.stack([sx, sy_], axis=2)[order].reshape(-1, 6).tolist()
        fills = [tuple(c) for c in rgb[order].tolist()]
        draw = ImageDraw.Draw(img)
        poly = draw.polygon
        for p, c in zip(pts, fills):
            poly(p, fill=c)
        return img

    # ------------------------------------------------------------------ detailed
    def render_detailed(self, width: int, height: int, yaw: float, pitch: float,
                        zoom: float = 1.0, supersample: int = 2) -> Image.Image:
        W, H = width * supersample, height * supersample
        if len(self.triangles) == 0:
            return Image.new("RGB", (width, height), BACKGROUND)
        rot = self._view(yaw, pitch)
        v = (self.positions - self.center) @ rot
        nv = self.normals @ rot
        scale = min(W, H) * 0.46 / self.radius * zoom
        sx = W / 2 + v[:, 0] * scale
        sy = H / 2 - v[:, 1] * scale
        sz = v[:, 2]

        tri = self.triangles
        x0, x1, x2 = sx[tri[:, 0]], sx[tri[:, 1]], sx[tri[:, 2]]
        y0, y1, y2 = sy[tri[:, 0]], sy[tri[:, 1]], sy[tri[:, 2]]
        area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        xmin = np.floor(np.minimum(np.minimum(x0, x1), x2)).astype(np.int64)
        xmax = np.ceil(np.maximum(np.maximum(x0, x1), x2)).astype(np.int64)
        ymin = np.floor(np.minimum(np.minimum(y0, y1), y2)).astype(np.int64)
        ymax = np.ceil(np.maximum(np.maximum(y0, y1), y2)).astype(np.int64)
        ok = (np.abs(area) > 1e-9) & (xmax >= 0) & (ymax >= 0) & (xmin < W) & (ymin < H)
        xmin, ymin = np.maximum(xmin, 0), np.maximum(ymin, 0)
        xmax, ymax = np.minimum(xmax, W - 1), np.minimum(ymax, H - 1)
        extent = np.maximum(xmax - xmin, ymax - ymin) + 1

        S_pix, S_dep, S_tri, S_b1, S_b2 = [], [], [], [], []
        cut_tex = {i for i, c in enumerate(self.cutout) if c}
        prev = 0
        for k in (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096):
            sel = np.nonzero(ok & (extent > prev) & (extent <= k))[0]
            prev = k
            if len(sel) == 0:
                continue
            g = np.arange(k)
            batch = max(1, (1 << 22) // (k * k))
            for s in range(0, len(sel), batch):
                ids = sel[s : s + batch]
                px = xmin[ids][:, None, None] + g[None, None, :]
                py = ymin[ids][:, None, None] + g[None, :, None]
                cx, cy = px + 0.5, py + 0.5
                ax, ay = x0[ids][:, None, None], y0[ids][:, None, None]
                bx, by = x1[ids][:, None, None], y1[ids][:, None, None]
                qx, qy = x2[ids][:, None, None], y2[ids][:, None, None]
                ar = area[ids][:, None, None]
                w1 = ((cx - ax) * (qy - ay) - (cy - ay) * (qx - ax)) / ar
                w2 = ((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / ar
                w0 = 1.0 - w1 - w2
                inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
                inside &= (px <= xmax[ids][:, None, None]) & (py <= ymax[ids][:, None, None])
                ti, yy, xx = np.nonzero(inside)
                if len(ti) == 0:
                    continue
                b1, b2 = w1[ti, yy, xx], w2[ti, yy, xx]
                tg = ids[ti]
                pix = py[ti, yy, 0] * W + px[ti, 0, xx]
                t3 = tri[tg]
                dep = (1 - b1 - b2) * sz[t3[:, 0]] + b1 * sz[t3[:, 1]] + b2 * sz[t3[:, 2]]
                if cut_tex:
                    keep = self._alpha_keep(tg, t3, b1, b2, cut_tex)
                    pix, dep, tg, b1, b2 = pix[keep], dep[keep], tg[keep], b1[keep], b2[keep]
                S_pix.append(pix)
                S_dep.append(dep.astype(np.float32))
                S_tri.append(tg)
                S_b1.append(b1.astype(np.float32))
                S_b2.append(b2.astype(np.float32))

        out = np.empty((H * W, 3), np.float32)
        out[:] = np.array(BACKGROUND, np.float32) / 255.0
        if S_pix:
            pix = np.concatenate(S_pix)
            dep = np.concatenate(S_dep)
            order = np.lexsort((-dep, pix))  # per pixel: nearest (largest z) first
            pix_sorted = pix[order]
            first = np.ones(len(order), dtype=bool)
            first[1:] = pix_sorted[1:] != pix_sorted[:-1]
            win = order[first]
            P = pix[win]
            T = np.concatenate(S_tri)[win]
            B1 = np.concatenate(S_b1)[win]
            B2 = np.concatenate(S_b2)[win]
            out[P] = self._shade(T, B1, B2, nv)
        img = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8).reshape(H, W, 3))
        if supersample > 1:
            img = img.resize((width, height), Image.LANCZOS)
        return img

    def _uv_at(self, t3, b1, b2):
        b0 = 1 - b1 - b2
        return b0[:, None] * self.uvs[t3[:, 0]] + b1[:, None] * self.uvs[t3[:, 1]] + b2[:, None] * self.uvs[t3[:, 2]]

    def _sample(self, tex: np.ndarray, uv: np.ndarray) -> np.ndarray:
        h, w = tex.shape[:2]
        x = (np.mod(uv[:, 0], 1.0) * w).astype(np.int64) % w
        y = (np.mod(uv[:, 1], 1.0) * h).astype(np.int64) % h
        return tex[y, x]

    def _alpha_keep(self, tg, t3, b1, b2, cut_tex) -> np.ndarray:
        keep = np.ones(len(tg), dtype=bool)
        tids = self.tex_ids[tg]
        for t in cut_tex:
            m = tids == t
            if m.any():
                a = self._sample(self.textures[t], self._uv_at(t3[m], b1[m], b2[m]))[:, 3]
                keep[np.nonzero(m)[0][a < 128]] = False
        return keep

    def _shade(self, T, B1, B2, nv) -> np.ndarray:
        t3 = self.triangles[T]
        b0 = 1 - B1 - B2
        n = b0[:, None] * nv[t3[:, 0]] + B1[:, None] * nv[t3[:, 1]] + B2[:, None] * nv[t3[:, 2]]
        length = np.linalg.norm(n, axis=1, keepdims=True)
        n = np.where(length > 1e-6, n / np.maximum(length, 1e-6), np.array([0, 0, 1], np.float32))
        n *= np.where(n[:, 2:3] < 0, -1.0, 1.0)  # two-sided: face the viewer

        albedo = np.tile(np.array(DEFAULT_COLOR, np.float32), (len(T), 1))
        glow = np.zeros((len(T), 3), np.float32)
        uv = self._uv_at(t3, B1, B2)
        tids, eids = self.tex_ids[T], self.emis_ids[T]
        for t in np.unique(tids[tids >= 0]):
            m = tids == t
            albedo[m] = self._sample(self.textures[t], uv[m])[:, :3] / 255.0
        for t in np.unique(eids[eids >= 0]):
            m = eids == t
            glow[m] = self._sample(self.textures[t], uv[m])[:, :3] / 255.0

        key = np.array([-0.45, 0.55, 0.70], np.float32)
        key /= np.linalg.norm(key)
        fill = np.array([0.6, 0.2, 0.4], np.float32)
        fill /= np.linalg.norm(fill)
        diff = np.clip(n @ key, 0, None) * 0.95 + np.clip(n @ fill, 0, None) * 0.30
        half = key + np.array([0, 0, 1], np.float32)
        half /= np.linalg.norm(half)
        spec = np.clip(n @ half, 0, None) ** 32 * 0.18
        rim = (1 - np.clip(n[:, 2], 0, 1)) ** 3 * 0.25
        light = 0.28 + diff
        return albedo * light[:, None] + (spec + rim)[:, None] + glow
