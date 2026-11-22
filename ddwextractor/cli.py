"""Command line interface.

Examples::

    python -m ddwextractor                      # opens the graphical interface
    python -m ddwextractor list -m characters
    python -m ddwextractor extract characters/death items/armor
    python -m ddwextractor extract items/armor --mesh "wanderer*" --format glb --height 180
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
import time
from pathlib import Path

from .ds2.archive import Game
from .ds2.extract import extract_asset, model_assets
from .ds2.package import TYPE_MESH, TYPE_TEXTURE, names_of, read_resource_table
from .locate import find_darksiders2

DEATH_HEIGHT_UNITS = 64.0


def _game(args) -> Game:
    path = args.game or find_darksiders2()
    if not path:
        sys.exit(
            "Could not find Darksiders II automatically. "
            'Pass the install folder with --game "C:/path/to/Darksiders2"'
        )
    return Game(path)


def cmd_list(args) -> None:
    game = _game(args)
    pats = [p.lower() for p in args.filter] or ["*"]
    entries = [
        e
        for e in game.assets
        if e.pak in ("media", "maps") and any(fnmatch.fnmatch(e.path.lower(), p if "*" in p else f"*{p}*") for p in pats)
    ]
    for e in sorted(entries, key=lambda e: e.path):
        try:
            g = read_resource_table(game.read_header(e))
        except (ValueError, OSError):
            continue
        meshes, texs = names_of(g, TYPE_MESH), names_of(g, TYPE_TEXTURE)
        if args.models_only and not meshes:
            continue
        print(f"{e.path:60s} {len(meshes):4d} models {len(texs):5d} textures {e.size / 1e6:9.1f} MB")
        if args.verbose and meshes:
            for m in meshes:
                print(f"      {m}")


def cmd_extract(args) -> None:
    game = _game(args)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.all:
        targets = model_assets(game)
    else:
        targets = []
        for a in args.assets:
            if any(ch in a for ch in "*?"):
                targets += [e for e in game.assets if fnmatch.fnmatch(e.path.lower(), a.lower())]
            else:
                e = game.find(a)
                if e is None:
                    sys.exit(f"Unknown asset '{a}'. Use the 'list' command to see the names.")
                targets.append(e)
    if not targets:
        sys.exit("Nothing to extract.")
    scale = args.scale
    if args.height:
        scale = args.height / DEATH_HEIGHT_UNITS
    t0 = time.time()
    print(f"Extracting {len(targets)} asset(s) to {out}")
    for e in targets:
        try:
            extract_asset(
                game, e, out,
                mesh_filter=args.mesh,
                all_textures=args.all_textures,
                combine=args.combine,
                scale=scale,
                fmt=args.format,
            )
        except Exception as exc:  # keep going with the other assets
            print(f"  ERROR in {e.path}: {exc}")
    print(f"Done in {time.time() - t0:.0f} s")


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv == ["gui"]:
        from .gui import main as gui_main

        gui_main()
        return
    p = argparse.ArgumentParser(
        prog="ddwextractor",
        description="Extract 3D models and textures from your own copy of Darksiders II Deathinitive Edition.",
    )
    p.add_argument("--game", help="Darksiders II install folder (auto-detected when omitted)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list the game's assets")
    pl.add_argument("filter", nargs="*", help="text or pattern, e.g. characters or items/*")
    pl.add_argument("-m", "--models-only", action="store_true", help="only assets that contain models")
    pl.add_argument("-v", "--verbose", action="store_true", help="also print every model name")
    pl.set_defaults(func=cmd_list)

    pe = sub.add_parser("extract", help="extract models (OBJ/GLB) and textures (PNG)")
    pe.add_argument("assets", nargs="*", help="assets, e.g. characters/death items/armor 'characters/*'")
    pe.add_argument("--all", action="store_true", help="extract every asset that contains models")
    pe.add_argument("-o", "--out", default="extracted", help="output folder (default: ./extracted)")
    pe.add_argument("--mesh", help="only models whose name matches, e.g. 'wanderer*,base_*'")
    pe.add_argument("--format", choices=("obj", "glb", "both"), default="both",
                    help="obj = static (3D printing), glb = with skeleton for posing, both (default)")
    pe.add_argument("--all-textures", action="store_true", help="save every texture, not only the used ones")
    pe.add_argument("--combine", action="store_true", help="one file per asset instead of one per model")
    pe.add_argument("--height", type=float, help="scale models so Death is this tall, in cm (e.g. 180)")
    pe.add_argument("--scale", type=float, default=1.0, help="raw scale factor for vertex positions")
    pe.set_defaults(func=cmd_extract)

    args = p.parse_args(argv)
    if args.cmd == "extract" and not args.assets and not args.all:
        pe.error("give at least one asset or use --all")
    args.func(args)


if __name__ == "__main__":
    main()
