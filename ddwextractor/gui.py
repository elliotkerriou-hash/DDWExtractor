"""Graphical interface (tkinter, bundled with Python) with a 3D model preview."""

from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

from .ds2.archive import Game
from .ds2.extract import LoadedAsset, extract_asset
from .ds2.mesh import Mesh
from .ds2.package import TYPE_MESH, TYPE_TEXTURE, names_of, read_resource_table
from .locate import find_darksiders2
from .preview_scene import build_scene, is_vfx

DEATH_HEIGHT_UNITS = 64.0
_DEFAULT_YAW = math.pi  # game models face -Y; show their front
_DEFAULT_PITCH = 0.12
_HINT = "Drag to rotate · mouse wheel to zoom · double-click to reset"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DDWExtractor - Darksiders II")
        self.geometry("1280x820")
        self.minsize(960, 640)
        self.game: Game | None = None
        self.rows: list[tuple[str, int, int, float]] = []
        self.events: queue.Queue = queue.Queue()
        self.busy = False

        # preview state
        self.loaded: LoadedAsset | None = None
        self.exporting: LoadedAsset | None = None
        self.load_gen = 0
        self.scene_gen = 0
        self.render_gen = 0
        self.scene = None
        self.yaw, self.pitch, self.zoom = _DEFAULT_YAW, _DEFAULT_PITCH, 1.0
        self._drag = None
        self._full_job = None
        self._photo = None

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        found = find_darksiders2()
        if found:
            self.game_var.set(str(found))
            self._load_game()

    # ------------------------------------------------------------- layout
    def _build(self):
        pad = {"padx": 6, "pady": 4}
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Game:").grid(row=0, column=0, sticky="w")
        self.game_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.game_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="Browse…", command=self._pick_game).grid(row=0, column=2)
        ttk.Label(top, text="Output:").grid(row=1, column=0, sticky="w")
        self.out_var = tk.StringVar(value=str(Path.home() / "Documents" / "DDWExtractor"))
        ttk.Entry(top, textvariable=self.out_var).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="Change…", command=self._pick_out).grid(row=1, column=2)
        top.columnconfigure(1, weight=1)

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, **pad)

        # --- left: asset list
        left = ttk.Frame(panes)
        bar = ttk.Frame(left)
        bar.pack(fill="x")
        ttk.Label(bar, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._refresh())
        ttk.Entry(bar, textvariable=self.filter_var).pack(side="left", fill="x", expand=True, padx=4)
        quick = ttk.Frame(left)
        quick.pack(fill="x", pady=(4, 0))
        for label, text in (("Death", "characters/death"), ("Armor", "items/armor"),
                            ("Weapons", "items/weapons"), ("Characters", "characters/"), ("All", "")):
            ttk.Button(quick, text=label, command=lambda t=text: self.filter_var.set(t)).pack(
                side="left", padx=1, fill="x", expand=True)
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True, pady=4)
        cols = ("asset", "models", "textures", "size")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="extended")
        for c, title, w, anchor in (("asset", "Asset", 300, "w"), ("models", "Models", 64, "e"),
                                    ("textures", "Textures", 64, "e"), ("size", "MB", 64, "e")):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c == "asset"))
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_asset_select)
        panes.add(left, weight=2)

        # --- right: preview
        right = ttk.LabelFrame(panes, text="Preview")
        head = ttk.Frame(right)
        head.pack(fill="x", padx=4, pady=2)
        self.preview_status = tk.StringVar(value="Click an asset to see its models.")
        ttk.Label(head, textvariable=self.preview_status).pack(side="left")
        self.game_look = tk.BooleanVar(value=True)
        ttk.Checkbutton(head, text="In-game look", variable=self.game_look,
                        command=lambda: self._render(full=True)).pack(side="right", padx=(8, 0))
        self.hide_vfx = tk.BooleanVar(value=True)
        ttk.Checkbutton(head, text="Hide effects (VFX)", variable=self.hide_vfx,
                        command=self._rebuild_scene).pack(side="right")

        body = ttk.Frame(right)
        body.pack(fill="both", expand=True, padx=4, pady=2)
        side = ttk.Frame(body)
        side.pack(side="left", fill="y")
        self.model_filter = tk.StringVar()
        self.model_filter.trace_add("write", lambda *_: self._fill_model_list())
        ttk.Entry(side, textvariable=self.model_filter).pack(fill="x", pady=(0, 4))
        lst = ttk.Frame(side)
        lst.pack(fill="both", expand=True)
        self.model_list = tk.Listbox(lst, selectmode="extended", width=30, exportselection=False,
                                     activestyle="none")
        self.visible: list[int] = []  # listbox row -> index in loaded.meshes
        lsb = ttk.Scrollbar(lst, orient="vertical", command=self.model_list.yview)
        self.model_list.configure(yscrollcommand=lsb.set)
        self.model_list.pack(side="left", fill="y", expand=True)
        lsb.pack(side="left", fill="y")
        self.model_list.bind("<<ListboxSelect>>", lambda e: self._rebuild_scene())

        self.canvas = tk.Canvas(body, background="#202128", highlightthickness=0, cursor="fleur")
        self.canvas.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.canvas.bind("<Configure>", lambda e: self._schedule_full())
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self._render(full=True))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Double-Button-1>", self._reset_view)

        foot = ttk.Frame(right)
        foot.pack(fill="x", padx=4, pady=4)
        self.preview_info = tk.StringVar(value=_HINT)
        ttk.Label(foot, textvariable=self.preview_info).pack(side="left")
        self.go_models = ttk.Button(foot, text="Extract selected models", command=self._extract_models)
        self.go_models.pack(side="right")
        panes.add(right, weight=3)

        # --- options + actions
        opts = ttk.LabelFrame(self, text="Options")
        opts.pack(fill="x", **pad)
        ttk.Label(opts, text="Only models matching:").grid(row=0, column=0, sticky="w", padx=4)
        self.mesh_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.mesh_var, width=28).grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text="(e.g. wanderer*,base_*)").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Label(opts, text="Scale to my height (cm):").grid(row=1, column=0, sticky="w", padx=4)
        self.height_var = tk.StringVar()
        self.height_var.trace_add("write", lambda *_: self._update_info())
        ttk.Entry(opts, textvariable=self.height_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(opts, text="empty = original game size").grid(row=1, column=2, sticky="w", padx=4)
        self.all_tex = tk.BooleanVar()
        self.combine = tk.BooleanVar()
        ttk.Checkbutton(opts, text="All textures", variable=self.all_tex).grid(row=0, column=3, sticky="w", padx=12)
        ttk.Checkbutton(opts, text="One file per asset", variable=self.combine).grid(row=1, column=3, sticky="w", padx=12)
        ttk.Label(opts, text="Format:").grid(row=0, column=4, sticky="w", padx=(12, 4))
        self.fmt = tk.StringVar(value="both")
        fmt_box = ttk.Frame(opts)
        fmt_box.grid(row=0, column=5, rowspan=2, sticky="w")
        for value, text in (("both", "OBJ + GLB"), ("obj", "OBJ (3D printing)"), ("glb", "GLB (with skeleton)")):
            ttk.Radiobutton(fmt_box, text=text, value=value, variable=self.fmt).pack(anchor="w")

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", **pad)
        self.go = ttk.Button(bottom, text="Extract selected assets", command=self._extract)
        self.go.pack(side="left")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(bottom, text="Open folder", command=self._open_out).pack(side="left")
        self.log = tk.Text(self, height=6, state="disabled", wrap="word")
        self.log.pack(fill="x", padx=6, pady=(0, 6))

    # ------------------------------------------------------------- helpers
    def _write(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _scale(self) -> float | None:
        h = self.height_var.get().strip().replace(",", ".")
        if not h:
            return 1.0
        try:
            v = float(h)
        except ValueError:
            return None
        return v / DEATH_HEIGHT_UNITS if v > 0 else None

    def _pick_game(self):
        d = filedialog.askdirectory(title="Darksiders II folder")
        if d:
            self.game_var.set(d)
            self._load_game()

    def _pick_out(self):
        d = filedialog.askdirectory(title="Output folder")
        if d:
            self.out_var.set(d)

    def _open_out(self):
        import os

        out = Path(self.out_var.get())
        out.mkdir(parents=True, exist_ok=True)
        os.startfile(out)  # type: ignore[attr-defined]

    def _on_close(self):
        self.load_gen += 1
        for la in {self.loaded, self.exporting}:
            if la is not None:
                la.close()
        self.destroy()

    # ------------------------------------------------------------- game / list
    def _load_game(self):
        try:
            self.game = Game(self.game_var.get())
        except Exception as exc:
            messagebox.showerror("DDWExtractor", str(exc))
            return
        self._write(f"Game: {self.game.media.parent}  ({len(self.game.assets)} assets). Reading index…")
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        rows = []
        for e in self.game.assets:
            if e.pak not in ("media", "maps"):
                continue
            try:
                g = read_resource_table(self.game.read_header(e))
            except (ValueError, OSError):
                continue
            n_mesh, n_tex = len(names_of(g, TYPE_MESH)), len(names_of(g, TYPE_TEXTURE))
            if n_mesh or n_tex:
                rows.append((e.path, n_mesh, n_tex, e.size / 1e6))
        rows.sort()
        self.events.put(("rows", rows))

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        f = self.filter_var.get().strip().lower()
        for path, nm, nt, mb in self.rows:
            if f and f not in path.lower():
                continue
            self.tree.insert("", "end", iid=path, values=(path, nm, nt, f"{mb:.1f}"))

    # ------------------------------------------------------------- preview: loading
    def _on_asset_select(self, _event=None):
        sel = self.tree.selection()
        if len(sel) != 1 or not self.game:
            return
        path = sel[0]
        if self.loaded is not None and self.loaded.entry.path == path:
            return
        row = next((r for r in self.rows if r[0] == path), None)
        if row is None or row[1] == 0:
            self.preview_status.set(f"{path}: no models (textures only).")
            return
        self.load_gen += 1
        gen = self.load_gen
        self.model_list.delete(0, "end")
        self.scene = None
        self._render(full=False)
        hint = " (large asset, this can take a moment)" if row[3] > 100 else ""
        self.preview_status.set(f"Loading {path}…{hint}")
        threading.Thread(target=self._load_asset, args=(gen, path), daemon=True).start()

    def _load_asset(self, gen: int, path: str):
        try:
            la = LoadedAsset(self.game, self.game.find(path), log=lambda m: None)
        except Exception as exc:
            self.events.put(("load_error", (gen, f"{path}: {exc}")))
            return
        self.events.put(("loaded", (gen, la)))

    def _on_loaded(self, gen: int, la: LoadedAsset):
        if gen != self.load_gen:  # user already picked another asset
            if la is not self.exporting:
                la.close()
            return
        old, self.loaded = self.loaded, la
        if old is not None and old is not self.exporting:
            old.close()
        n = len(la.meshes)
        self.preview_status.set(f"{la.entry.path}: {n} model{'s' if n != 1 else ''}")
        self.model_list.selection_clear(0, "end")
        self.visible = []
        self.model_filter.set("")  # triggers _fill_model_list
        first = next((row for row, i in enumerate(self.visible)
                      if not all(is_vfx(x) for x in la.meshes[i].materials)), 0 if self.visible else None)
        if first is not None:
            self.model_list.selection_set(first)
            self.model_list.see(first)
        self._reset_view(render=False)
        self._rebuild_scene()

    def _fill_model_list(self):
        selected = {self.visible[r] for r in self.model_list.curselection() if r < len(self.visible)}
        self.model_list.delete(0, "end")
        self.visible = []
        if self.loaded is None:
            return
        f = self.model_filter.get().strip().lower()
        order = sorted(range(len(self.loaded.meshes)), key=lambda i: self.loaded.meshes[i].name.lower())
        for i in order:
            m = self.loaded.meshes[i]
            if f and f not in m.name.lower():
                continue
            vfx = bool(m.materials) and all(is_vfx(mat) for mat in m.materials)
            self.model_list.insert("end", f"{m.name}{'  (vfx)' if vfx else ''}")
            if i in selected:
                self.model_list.selection_set(len(self.visible))
            self.visible.append(i)

    # ------------------------------------------------------------- preview: scene
    def _selected_meshes(self) -> list[Mesh]:
        if self.loaded is None:
            return []
        return [self.loaded.meshes[self.visible[r]] for r in self.model_list.curselection()
                if r < len(self.visible)]

    def _rebuild_scene(self):
        meshes = self._selected_meshes()
        self.scene_gen += 1
        gen = self.scene_gen
        if not meshes:
            self.scene = None
            self._render(full=False)
            self._update_info()
            return
        threading.Thread(target=self._build_scene, args=(gen, self.loaded, meshes, self.hide_vfx.get()),
                         daemon=True).start()

    def _build_scene(self, gen, la: LoadedAsset, meshes: list[Mesh], hide_vfx: bool):
        try:
            scene = build_scene(la, meshes, hide_vfx)
        except Exception as exc:  # e.g. asset closed because the user moved on
            if gen == self.scene_gen:
                self.events.put(("log", f"  preview: {exc}"))
            return
        self.events.put(("scene", (gen, scene)))

    # ------------------------------------------------------------- preview: view
    def _render(self, full: bool):
        """Fast flat preview now; if ``full`` and in-game look is on, a detailed
        render follows from a worker thread."""
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 10 or h < 10:
            return
        self.render_gen += 1
        if self.scene is None:
            self.canvas.delete("all")
            return
        if not (full and self.game_look.get()):
            img = self.scene.render(w, h, self.yaw, self.pitch, self.zoom,
                                    max_triangles=None if full else 12000)
            self._show(img)
            return
        if self._photo is None:  # nothing on screen yet: show the fast version first
            self._show(self.scene.render(w, h, self.yaw, self.pitch, self.zoom))
        args = (self.render_gen, self.scene, w, h, self.yaw, self.pitch, self.zoom)
        threading.Thread(target=self._detailed_worker, args=args, daemon=True).start()

    def _detailed_worker(self, gen, scene, w, h, yaw, pitch, zoom):
        try:
            img = scene.render_detailed(w, h, yaw, pitch, zoom)
        except Exception as exc:
            self.events.put(("log", f"  preview: {exc}"))
            return
        self.events.put(("detailed", (gen, img)))

    def _show(self, img):
        self.canvas.delete("all")
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)

    def _schedule_full(self):
        if self._full_job:
            self.after_cancel(self._full_job)
        self._full_job = self.after(200, lambda: self._render(full=True))

    def _drag_start(self, e):
        self._drag = (e.x, e.y, self.yaw, self.pitch)

    def _drag_move(self, e):
        if not self._drag:
            return
        x0, y0, yaw0, pitch0 = self._drag
        self.yaw = yaw0 + (e.x - x0) * 0.01
        self.pitch = max(-1.5, min(1.5, pitch0 + (e.y - y0) * 0.01))
        self._render(full=False)
        self._schedule_full()

    def _wheel(self, e):
        self.zoom = max(0.2, min(8.0, self.zoom * (1.12 if e.delta > 0 else 1 / 1.12)))
        self._render(full=False)
        self._schedule_full()

    def _reset_view(self, _e=None, render=True):
        self.yaw, self.pitch, self.zoom = _DEFAULT_YAW, _DEFAULT_PITCH, 1.0
        if render:
            self._render(full=True)

    def _update_info(self):
        if self.scene is None:
            self.preview_info.set(_HINT)
            return
        w, h, d = (float(x) for x in self.scene.size)
        tris = len(self.scene.triangles)
        scale = self._scale()
        if scale and self.height_var.get().strip():
            dims = f"{w * scale:.1f} × {h * scale:.1f} × {d * scale:.1f} cm (W × H × D)"
        else:
            dims = f"{w:.1f} × {h:.1f} × {d:.1f} game units (W × H × D)"
        self.preview_info.set(f"{tris:,} triangles · {dims}")

    # ------------------------------------------------------------- extraction
    def _check_scale(self) -> float | None:
        scale = self._scale()
        if scale is None:
            messagebox.showerror("DDWExtractor", "Height must be a number in centimeters.")
        return scale

    def _extract(self):
        if self.busy or not self.game:
            return
        sel = list(self.tree.selection())
        if not sel:
            messagebox.showinfo("DDWExtractor", "Select one or more assets in the list.")
            return
        scale = self._check_scale()
        if scale is None:
            return
        out = Path(self.out_var.get())
        out.mkdir(parents=True, exist_ok=True)
        self._set_busy(True, len(sel))
        args = (sel, out, self.mesh_var.get().strip() or None, self.all_tex.get(), self.combine.get(),
                scale, self.fmt.get())
        threading.Thread(target=self._run, args=args, daemon=True).start()

    def _extract_models(self):
        if self.busy or self.loaded is None:
            return
        meshes = self._selected_meshes()
        if not meshes:
            messagebox.showinfo("DDWExtractor", "Select one or more models in the preview list.")
            return
        scale = self._check_scale()
        if scale is None:
            return
        out = Path(self.out_var.get())
        out.mkdir(parents=True, exist_ok=True)
        self._set_busy(True, 1)
        self.exporting = self.loaded
        args = (self.loaded, meshes, out, self.all_tex.get(), self.combine.get(), scale, self.fmt.get())
        threading.Thread(target=self._run_models, args=args, daemon=True).start()

    def _set_busy(self, busy: bool, total: int = 1):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.go.configure(state=state)
        self.go_models.configure(state=state)
        if busy:
            self.progress.configure(maximum=total, value=0)

    def _run(self, assets, out, mesh_filter, all_textures, combine, scale, fmt):
        log = lambda m: self.events.put(("log", m))  # noqa: E731
        for i, a in enumerate(assets):
            try:
                if self.loaded is not None and self.loaded.entry.path == a:
                    la = self.loaded
                    self.exporting = la
                    la.export(out, la.select(mesh_filter), all_textures=all_textures,
                              combine=combine, scale=scale, log=log, fmt=fmt)
                else:
                    extract_asset(self.game, a, out, mesh_filter=mesh_filter, all_textures=all_textures,
                                  combine=combine, scale=scale, log=log, fmt=fmt)
            except Exception as exc:
                log(f"  ERROR in {a}: {exc}")
            self.events.put(("progress", i + 1))
        self.events.put(("done", out))

    def _run_models(self, la: LoadedAsset, meshes, out, all_textures, combine, scale, fmt):
        log = lambda m: self.events.put(("log", m))  # noqa: E731
        try:
            la.export(out, meshes, all_textures=all_textures, combine=combine, scale=scale, log=log, fmt=fmt)
        except Exception as exc:
            log(f"  ERROR in {la.entry.path}: {exc}")
        self.events.put(("progress", 1))
        self.events.put(("done", out))

    # ------------------------------------------------------------- event loop
    def _poll(self):
        try:
            while True:
                kind, val = self.events.get_nowait()
                if kind == "rows":
                    self.rows = val
                    self._refresh()
                    self._write(f"{len(val)} assets with models or textures. "
                                "Click one to preview it; select several to extract them.")
                elif kind == "log":
                    self._write(val)
                elif kind == "progress":
                    self.progress.configure(value=val)
                elif kind == "done":
                    finished = self.exporting
                    self.exporting = None
                    if finished is not None and finished is not self.loaded:
                        finished.close()
                    self._set_busy(False)
                    self._write(f"Done. Files in: {val}")
                elif kind == "loaded":
                    self._on_loaded(*val)
                elif kind == "load_error":
                    gen, msg = val
                    if gen == self.load_gen:
                        self.preview_status.set("Could not load this asset.")
                        self._write(f"  ERROR: {msg}")
                elif kind == "scene":
                    gen, scene = val
                    if gen == self.scene_gen:
                        self.scene = scene
                        self._photo = None
                        self._render(full=True)
                        self._update_info()
                elif kind == "detailed":
                    gen, img = val
                    if gen == self.render_gen:
                        self._show(img)
        except queue.Empty:
            pass
        self.after(50, self._poll)


def main():
    try:  # crisp text on scaled (high-DPI) Windows displays
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
