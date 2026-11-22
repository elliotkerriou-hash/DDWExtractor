# DDWExtractor

A fan-made tool that extracts the **3D models and textures** from your own copy of
**Darksiders II Deathinitive Edition**, to use as reference for cosplay, figures,
3D printing and fan art.

*Versión en español: [README.es.md](README.es.md)*

> **Important:** this project **does not include any game files**. Everyone extracts the
> models from their own legal copy. Please **do not share the extracted files**: they belong
> to THQ Nordic. Share the tool, not the models.

## What it extracts

- **OBJ** models: static, open in any 3D program or slicer (Blender, ZBrush, Cura, PrusaSlicer…).
- **GLB** (glTF 2.0) models **with skeleton and skin weights**, so you can pose them in
  Blender (File > Import > glTF 2.0). Textures are embedded.
- **PNG** textures (color, normal, specular, emissive), linked from the OBJ `.mtl`.
- Characters, armor, weapons, enemies, bosses, NPCs and environments.

Useful assets for cosplay:

| Asset | Contents |
|---|---|
| `characters/death` | Death's head and mask, Reaper form and its scythe |
| `items/armor` | 205 pieces: base body and every armor set (body, gloves, boots, shoulders) |
| `items/weapons` | 197 weapons: scythes, double scythes, hammers, axes, gauntlets… |
| `characters/despair`, `characters/dust` | Death's horse and crow |
| `characters/vulgrim`, `characters/crow_father`, `characters/dark_war`… | NPCs, War and bosses |

All of Death's pieces share the same coordinate system: import the head, the base body and an
armor set and they fit together.

## Download (Windows, easiest)

1. Go to [Releases](https://github.com/elliotkerriou-hash/DDWExtractor/releases/latest) and
   download **`DDWExtractor.exe`**.
2. Double-click it. Nothing to install: no Python needed.

The exe is not code-signed, so Windows SmartScreen may say *"Windows protected your PC"*:
click **More info → Run anyway**. It takes a few seconds to open the first time.

## Install from source (any OS with Python)

1. Install [Python 3.10 or newer](https://www.python.org/downloads/) (tick "Add Python to PATH").
2. Download this project and, in its folder, run:

```
pip install -r requirements.txt
```

To build the exe yourself:

```
python -m venv build/venv
build\venv\Scripts\python -m pip install -r requirements.txt pyinstaller
build\venv\Scripts\python build_exe.py
```

The result is `dist/DDWExtractor.exe`.

## Using the window (recommended)

Double-click `DDWExtractor.exe` (from source: `DDWExtractor.pyw` or `python -m ddwextractor`).
Extracted files go to `Documents\DDWExtractor` by default.

1. The game is detected automatically. If not, click **Browse…** and pick its folder.
2. Click an asset (for example **Armor**) to open the **preview** with the list of its models
   and a search box.
3. Select one or more models (Ctrl/Shift + click) to see them together in 3D. Drag to
   rotate, use the mouse wheel to zoom and double-click to reset. Below the preview you get
   the size, in cm if you entered your height.
4. **In-game look** renders with full textures, smooth shading, transparency (hair, cloth)
   and glow. While you drag, a faster flat preview is used.
5. **Extract selected models** saves only what you are looking at; **Extract selected
   assets** saves whole assets. Choose the format: OBJ, GLB or both.

**Hide effects (VFX)** removes effect pieces (fire, auras, ghost forms) that are usually not
useful for cosplay.

## Command line

```
python -m ddwextractor list -m                       # assets that contain models
python -m ddwextractor list -m -v items/armor        # also list every model name
python -m ddwextractor extract characters/death
python -m ddwextractor extract items/armor --mesh "wanderer*,base_*" --format glb
python -m ddwextractor extract items/weapons --mesh "*scythe*" --height 180
python -m ddwextractor extract --all                 # everything (slow, several GB)
```

| `extract` option | What it does |
|---|---|
| `-o FOLDER` | Output folder (default `./extracted`) |
| `--mesh PATTERNS` | Only models whose name matches (`*` wildcard, comma separated) |
| `--format obj\|glb\|both` | Output format (default `both`) |
| `--height CM` | Scale so that Death is this tall (in cm) |
| `--all-textures` | Save every texture of the asset, not only the ones the models use |
| `--combine` | One file per asset instead of one per model |
| `--scale N` | Raw scale factor |
| `--game FOLDER` | (before the command) game folder, if it is not detected |

Files are written to `extracted/<asset>/models/` and `extracted/<asset>/textures/`.

### Scale for cosplay

In the game Death is about **64 units** tall, from the soles of his boots to the top of his
hair. `--height 180` (or the *Scale to my height* box) makes the models come out in
**centimeters for a 180 cm person** (OBJ). GLB files use meters, as glTF requires, so in
Blender the same model is 1.80 m tall. Most slicers read OBJ numbers as millimeters: choose
centimeters on import or scale by 10. Death has exaggerated proportions (huge arms and
shoulders), so adjust each piece to your real measurements.

### Posing in Blender

Import the `.glb` with *File > Import > glTF 2.0*, select the armature, switch to *Pose Mode*
and rotate bones. Armor pieces from the same set share the skeleton; weapon blades follow
their handle bones.

## Status

- **Darksiders II Deathinitive Edition:** models (skinned and static), skeletons and weights
  (GLB), textures and materials. Bone-attached pieces (e.g. double-scythe blades) are placed
  using the skeleton.
- **Darksiders Warmastered Edition (DS1):** in progress.

Technical notes on the file formats: [docs/format_ds2.md](docs/format_ds2.md).

## Credits

- Container and manifest format knowledge builds on public community research, especially
  Kierak1's [Darksiders 2 Modkit](https://github.com/Kierak1/Darksiders-2-Modkit) and the
  ZenHAX/ResHax threads. The code in this project is an independent implementation.
- Darksiders is a trademark of THQ Nordic. This project is not affiliated with THQ Nordic.

## License

The source code is released under the [MIT License](LICENSE). It covers the code only, not
the game files or anything extracted from them.
