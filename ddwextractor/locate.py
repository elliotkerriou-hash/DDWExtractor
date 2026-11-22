"""Find Darksiders installations (Steam, Epic, GOG) on Windows."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_DS2_DIRS = ("Darksiders II Deathinitive Edition", "Darksiders2", "Darksiders II")


def _steam_libraries() -> list[Path]:
    roots = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            roots.append(Path(base) / "Steam")
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            roots.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
    except OSError:
        pass
    libs = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore")):
                libs.append(Path(m.group(1).replace("\\\\", "\\")) / "steamapps" / "common")
        libs.append(root / "steamapps" / "common")
    return libs


def _epic_installs() -> list[Path]:
    out = []
    manifests = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if manifests.is_dir():
        for item in manifests.glob("*.item"):
            try:
                data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, ValueError):
                continue
            loc = data.get("InstallLocation")
            if loc:
                out.append(Path(loc))
    return out


def _gog_installs() -> list[Path]:
    out = []
    try:
        import winreg

        for hive_path in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, hive_path) as games:
                    for i in range(winreg.QueryInfoKey(games)[0]):
                        with winreg.OpenKey(games, winreg.EnumKey(games, i)) as g:
                            try:
                                out.append(Path(winreg.QueryValueEx(g, "path")[0]))
                            except OSError:
                                pass
            except OSError:
                continue
    except ImportError:
        pass
    return out


def find_darksiders2() -> Path | None:
    candidates: list[Path] = []
    for lib in _steam_libraries():
        candidates += [lib / d for d in _DS2_DIRS]
    candidates += _epic_installs() + _gog_installs()
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates += [Path(base) / "Epic Games" / d for d in _DS2_DIRS]
            candidates += [Path(base) / "GOG Galaxy" / "Games" / d for d in _DS2_DIRS]
    for c in candidates:
        if (c / "media" / "manifest.bin").exists() and (c / "media" / "media.upak").exists():
            return c
    return None
