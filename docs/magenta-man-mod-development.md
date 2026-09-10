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

The loader offers six fixed, bundled actors through `model`: `spiderman`,
`scarlet-spider`, `symbiote`, `quick-change`, `peter-parker`, and
`sm2-spiderman`. The last is default SM2 Spider-Man with web wings. Omitting
`model` selects SM1 Spider-Man in SM1 and SM2
Spider-Man in SM2 for backward compatibility. An optional `modelFile` selects a
validated native custom actor; see [Unlimited costume mods](ports/unlimited-costume-mods.md).
The JSON cannot supply guest addresses or executable code.
This folder is the SM1 example. SM2 has its own `mods/samples/magenta-man-sm2`
example, installed under `mods/suits/` beside `SpiderMan2.exe` and selected through
**SPECIAL → COSTUMES**. Its approved default DC body includes web wings and uses
the corrected fourteen-material SM2 texture layout. PNGs must match the selected
model base: SM1 reskins can also run in SM2 when they explicitly retain their SM1
model. The [SM2 sample README](../mods/samples/magenta-man-sm2/README.md) lists all
19 donor powersets and examples of choosing powers independently of appearance.

## SM2 implementation

The SM1 default model bundled for SM2 uses private material `57494E47` for its
transparent wing cutout. Keeping the original `DC38D248` ID collides with SM2's
visible wing page when both actors are resident. `build_sm2_mod_actor.py` packages
the SM1 actor with only that hash changed and refuses nontransparent donors. Run
it after rebuilding the base SM2 asset bundle and before publishing the EXE.


SM2 preserves its nineteen built-in records and adds up to twelve always-unlocked
reskins (31 total), with the same JSON fields, stock description palette, eleven
stock-spaced visible rows, external PNG validation and host-side texture lifetime.
`SuitRules.cs` owns the nineteen native power profiles. The shared parser owns the
six model names and their exact material allowlists; neither policy comes from JSON.

The native selector byte at `800B31F2` remains a valid 0..18 power-profile proxy.
The selected mod ID lives in the host-side selection file. The appearance loader
uses the selected fixed actor independently of the power profile. After the texture
load, the original one-based costume
identity at `GP+AA8` is restored for Insulated Suit's electrical-resistance logic.
The three power IDs and seven native flags are copied from the original selector's
behavior; the JSON cannot supply guest addresses or scripts.

Recompile SM2 through `spiderman2/tools/build.py`: it applies the checked selector
transform after generation. The transform relocates only the costume viewer table,
leaving other retail tables bounded to native profile indices.

Regression command: `dotnet run --project tools/RecompOne/tests/Sm2SuitModRegression -c Release -- <repo>`.
It checks all nineteen profiles against the original game's power decoder, matches
GAME POWERS text by original charbio key (not its differing storage order), confirms
write bounds and unchanged stock unlocks, and tests wrong-game/unsafe manifests.

Rebuild the SM2 sample with `build_sm2_magenta_sample.py --source <approved-spidey.glb>`.
Generate that GLB with Neversoft Multitool from the currently bundled approved
`spidey.psx`. The generator extracts the exported material PNGs without remapping,
recolors fabric, and uses Blender's UV Layout SVG exporter plus Sharp for templates.
The existing Blender compatibility helper removes only optional mixed-width `_PSX_*`
diagnostic attributes; geometry, standard colors, UVs, joints and weights are unchanged.

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
behavior select that profile independently from the fixed `model` choice. They
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

### Published player-layout smoke

`dreamcast/tools/smoke_player_reskin.py` tests a published single-file executable
outside the repository, using the real first-run installer and a dropped-in sample.
Run `--phase setup` with `--exe`, `--cue` and a fresh external `--install` directory,
then use that same directory for `--phase selection`, `--phase gameplay`, and
optionally `--phase stock` (which moves only the test mod into the proof folder).
No development asset/data paths, cheats, forced costume, copied saves or FMV-skip
override are supplied. The fresh-save menu route differs from the cheat-enabled
development harness: right from New Game, then one down to Special.

The 2026-09-04 published-working-tree smoke passed fresh install, normal selection,
restart persistence, opening-rooftop gameplay and missing-mod fallback. Logs,
launch environments and individually reviewed native captures are retained locally
under `proof_render/magenta-man/player-facing-smoke/`; `summary.md` records the
exact binary hash, the failed initial navigation attempt, and coverage limitations.
This is one default-profile mod's smoke pass, not a full playthrough or mod-count
stress test. No host desktop input is generated by this harness.

The equivalent SM2 run uses `--game sm2` and its published `SpiderMan2.exe`.
It passed real windowed extraction, **SPECIAL → COSTUMES** selection, restart
persistence, playable training-rooftop gameplay in 16:9, and selected-mod removal
fallback. Evidence and failed timing attempts are retained locally under
`proof_render/magenta-man/sm2-player-smoke/summary.md`. SM2 menu input is anchored
to `charlite.dat`, since `title.bmr` loads before its intro sequence. Both games
were run one at a time; neither smoke uses developer asset paths or forced suits.
