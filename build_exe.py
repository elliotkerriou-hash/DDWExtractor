"""Build dist/DDWExtractor.exe (Windows, single file) with PyInstaller.

    python -m venv build/venv
    build/venv/Scripts/python -m pip install -r requirements.txt pyinstaller
    build/venv/Scripts/python build_exe.py
"""

from __future__ import annotations

from pathlib import Path

import PyInstaller.__main__

from ddwextractor import __version__

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
ICON = ROOT / "packaging" / "icon.ico"


def version_file() -> Path:
    nums = tuple(int(x) for x in __version__.split(".")) + (0,) * 4
    v = nums[:4]
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'DDWExtractor contributors'),
      StringStruct('FileDescription', 'DDWExtractor - Darksiders model extractor'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'DDWExtractor'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'DDWExtractor.exe'),
      StringStruct('ProductName', 'DDWExtractor'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    BUILD.mkdir(exist_ok=True)
    path = BUILD / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def main():
    PyInstaller.__main__.run(
        [
            str(ROOT / "DDWExtractor.pyw"),
            "--name=DDWExtractor",
            "--onefile",
            "--windowed",
            "--noconfirm",
            "--clean",
            f"--icon={ICON}",
            f"--add-data={ICON};.",
            f"--version-file={version_file()}",
            f"--distpath={ROOT / 'dist'}",
            f"--workpath={BUILD / 'pyinstaller'}",
            f"--specpath={BUILD}",
            # Not used by the app; keeps the exe smaller.
            "--exclude-module=matplotlib",
            "--exclude-module=scipy",
            "--exclude-module=pandas",
            "--exclude-module=pytest",
        ]
    )
    exe = ROOT / "dist" / "DDWExtractor.exe"
    print(f"\nBuilt {exe} ({exe.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
