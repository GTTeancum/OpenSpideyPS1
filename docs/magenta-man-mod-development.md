# Magenta Man — developer notes

Magenta-colored fabric, original Dreamcast geometry/UVs, black web detail and white
eyes. This is a reskin, not a debug color or missing-texture placeholder.

## Install and select

Copy `mods/samples/magenta-man` to `mods/suits/magenta-man` beside `SpiderMan.exe`, then restart.
Choose **SPECIAL → COSTUME VIEWER → MAGENTA MAN → SELECT**. It is an additional,
always-unlocked suit; none of the twenty built-in suits or their unlocks is replaced.
The loader logs `[suit-mod] registered magenta-man` when installation is valid.

The selector aligns both columns' frames and first text lines, with eleven visible
rows at the original 10-pixel pitch and scrolling for additional suits. Descriptions use the
original `charbio.dat` palette: heading RGB (105,105,0), body (68,68,100).

The model is fixed in the loader: the installed, approved **wingless SM1**
Dreamcast default Spider-Man actor. No JSON donor field is accepted.
No Dreamcast disc, additional PSX, or model rebuild is
needed. The loader does not accept custom model files or executable code here.
This example is currently for SM1, not SM2.

## Edit the JSON and PNGs

`suit.json` supports `//` comments. `name` (up to 18 printable ASCII characters)
and `comments` (up to 72, further bounded by the available wrapped lines) appear
in the selector. GAME POWERS uses the chosen profile's retail text. `id` must be unique and stable;
selection is remembered by that ID outside the retail save. Removing a selected
mod falls back to default Spider-Man instead of selecting a different catalogue slot.

`abilities.profile` accepts these **SM1 retail profiles**:

- `spiderman` — default, used by this sample.
- `2099` — Spider-Man 2099.
- `symbiote` — Symbiote Spider-Man, including its unlimited webbing behavior.
- `captain-universe` — Captain Universe.
- `unlimited` — Spider-Man Unlimited.
- `bagman` — Amazing Bag Man.
- `scarlet` — Scarlet Spider-Man.
- `ben-reilly` — Ben Reilly.
- `quick-change` — Quick Change Spider-Man.
- `peter-parker` — Peter Parker.

These select complete existing behavior profiles, not independently combinable
power switches. Both the construction configuration and the retail costume-dependent
behavior select that profile, while the visible model remains DC Spider-Man. They
do not add SM2 abilities, animations or ammunition and do not unlock the stock donor
costume. Change the profile and restart to reload the manifest.

The eight hexadecimal keys in `textures` are **material names**, not memory
addresses. Each maps to an external RGBA PNG. Edit or replace those PNGs while
preserving their UV layout and alpha. Omitted materials retain their stock art.
The invisible wing cutout is not paintable in this wingless donor.

`9D39C02B.png` is deliberately **2048×2048** to exercise the HD path. It is a nearest-
neighbor enlargement of the tinted source, not newly painted HD detail. The other
seven images use original Dreamcast dimensions. The sample's decoded pixels occupy
17,776,640 bytes (about 17 MiB) in host RAM, plus GPU texture storage. PNG file size
is not the same as decoded memory cost. The generator does not modify the donor PSX.
No provenance file is included in the user-facing mod folder.

`TEMPLATE` contains reference sheets at the paint textures' exact dimensions.
Blender imports the original decoded DC `SPIDEY.glb` and its official UV Layout
exporter exports each matching material to SVG; Sharp composites those outlines
over copies of the PNGs without changing any UV coordinates. Original Blender
SVGs are retained under `TEMPLATE/UV`. The game never loads this folder.
The generator does not re-unwrap, infer islands, or read UVs from compatibility
face packets. It requires Blender, Node.js and Sharp (`BLENDER`, `NODE_EXE` and
`SHARP_MODULE` can select local installations).

## Boundaries and failure behavior

PNGs are decoded in host memory and uploaded to host GPU textures; they are never
copied into the guest model/VRAM allocation. Runtime material bindings come from
the trusted, currently loaded player donor. Switching back to stock removes those
bindings and retires mod GPU textures at a safe presentation boundary.

The loader rejects unknown/duplicate fields and material IDs, unsupported profiles,
path traversal, absolute paths, linked mod directories/files, control characters,
non-PNG images, dimensions over 4096, PNG files over 32 MiB, and suits over 64 MiB
decoded RGBA. These are explicit host resource budgets, not PS1 texture limits.
Only the active suit is decoded. The current selector supports twelve added mod
entries (32 total); additional entries are rejected with a log message.

Invalid catalogue entries are omitted with a diagnostic. A PNG that fails decoding
at selection falls back to stock Spider-Man, without a partial texture activation.
This data-only path does **not** sandbox the separate, full-trust C# mod system or
claim that arbitrary external model binaries are safe.

## Reproduce

From the repository root:

```powershell
python dreamcast/tools/build_magenta_man_sample.py
dotnet run --project tools/RecompOne/tests/SuitModRegression -c Release -- C:/Programming/GitHub/OpenSpideyPS1
python dreamcast/tools/smoke_magenta_man.py --mode selection --output proof_render/magenta-man/new-selection-proof
python dreamcast/tools/smoke_magenta_man.py --mode gameplay --output proof_render/magenta-man/new-gameplay-proof
```

The asset generator needs the developer's decoded DC source files; a player or
reskin author only needs this folder and the game's installed donor. The smoke
test uses private saves/settings, one game process, internal scripted input, and
the game's native capture facility. It never sends desktop input.
