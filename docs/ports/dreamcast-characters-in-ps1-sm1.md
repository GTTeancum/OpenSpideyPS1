# Dreamcast characters in PS1 Spider-Man

This is the repeatable route for running the Dreamcast character assets in the
recompiled PS1 Spider-Man engine. It covers the v6-to-v4 container conversion,
the donor-preserving, Dreamcast-seam-fitted Enter Electro web-wing transfer, the all-character census, and
the visible in-game parity proof.

## Loose files are the runtime contract

Disc media is input to the one-time extract/import step only. Neither the
conversion tools nor the normal game command accepts or searches for Dreamcast
GDI tracks or PS1 BIN/CUE data. After extraction, the working inputs are:

- `dreamcast/extracted/*.PSX` and `dreamcast/decoded/textures/`;
- `spiderman/extracted/` for the loose SM1 filesystem and `wad/` entries;
- `spiderman2/extracted/wad/spidey.psx` as the loose wing donor.

The SM1 executable persists the loose directory in `settings.json`. A disc path
is accepted only when no loose import exists and is immediately imported by
`LooseDiscImporter`; subsequent launches use `recompone-disc.json`, `CD.HED`,
and the extracted files. `SPIDEY_ASSET_DIR` overlays files by WAD entry name, so
ports never rewrite `CD.WAD` and never rebuild disc images.

## Character container conversion

Dreamcast actor models are version-6 Neversoft PSX containers. SM1 expects the
version-4 layout. `spiderman/tools/port_dc_character.py` performs these changes:

1. Parse the v6 object table, mesh pointers, tagged metadata, mesh-name hashes,
   texture hashes, texture headers, and mesh extents.
2. Preserve every object, hierarchy tag, vertex, normal, face packet, material
   assignment, and attachment reference that does not require format relocation.
3. Convert textured face UVs from the v6 normalized 0..511 domain to byte-sized
   PS1 coordinates using the generated texture dimensions. The v4 face record is
   eight bytes shorter because each UV component becomes one byte.
4. Rewrite mesh pointers and face-normal indices after relocation.
5. Quantize decoded RGBA PNGs to indexed 8-bit PS1 textures. Palette index zero
   is the transparent magenta key; opaque colors begin at index one.
6. Divide Dreamcast texture dimensions by four. This retains the DC atlas while
   keeping the aggregate actor texture load near the original SM1 VRAM budget.
7. Emit a v4 container whose embedded texture section is self-contained.

The output remains one loose `.psx` file per WAD entry. For Spider-Man, a matching
loose `sp_tex00.psx` is also generated because the shell loads that companion
texture library independently.

Convert one ordinary actor with:

```powershell
python spiderman/tools/port_dc_character.py `
  --model dreamcast/extracted/BLACKCAT.PSX `
  --textures dreamcast/decoded/textures/BLACKCAT `
  --texture-scale 4 `
  --output-model dreamcast/converted/blackcat/blackcat.psx
```

## Donor-preserving, recipient-fitted web wings

`dreamcast/tools/build_winged_spidey.py` loads the native PS1 Enter Electro
`spidey.psx` and transfers its authored wing payload into the Dreamcast SM1
Spider-Man model. The seven donor faces remain byte-exact apart from relocation,
but donor-only topology is not a sufficient fit: its upper edge skips the denser
Dreamcast shoulder and leaves a triangular hole at each armpit.

The donor has seven wing face records:

- mesh 4, left upper arm: three faces using donor vertices 0, 8, 30, and 31;
- mesh 9, right upper arm: four faces using donor vertices 0, 8, 30, and 5;
- material hash `DC38D248`.

Neversoft's type-2 vertices are stitched references, not blended modern skin
weights. A type-2 corner points to a file-wide type-1 attachment source owned by
another body part. The runtime resolves that source and therefore gives the
corner that source part's rigid animation. Exact transfer requires more than
copying the visible triangles:

1. Read all seven donor face records, their four-corner UV bytes, packet flags,
   colors/modes, vertex normals, and face normals.
2. Collect every donor type-1 attachment source referenced by the wing corners.
3. Copy those five source records into the matching Dreamcast body parts with
   the donor positions and normals unchanged. Coincident Dreamcast vertices are
   not substituted because their high-detail shading normals differ.
4. Shift pre-existing Dreamcast type-2 indices whenever an insertion changes the
   file-wide attachment-source numbering.
5. Translate the donor wing type-2 indices to the newly copied sources while
   preserving donor mesh/bone ownership.
6. Append the donor wing vertices and faces to upper-arm meshes 4 and 9. Only
   relocation-dependent vertex, normal, and texture indices change.
7. Add one two-sided seam cap per side from the donor torso/mid-bicep edge to
   recipient upper-arm surface vertex 55. The cap UV shares the authored edge
   coordinates and extends into the opaque black/white web region; no body face
   or donor wing face is moved or replaced.
8. Add `DC38D248` as the ninth material. The production texture is a 64x64
   magenta/transparent paint-out so SM1 remains wingless by default, while the
   diagnostic build copies the retail SM2 `DC38D248` black/white wing texture.

Build the production asset from loose inputs:

```powershell
python dreamcast/tools/build_winged_spidey.py `
  --output-model dreamcast/converted/sm1-winged-production/spidey.psx `
  --output-textures dreamcast/converted/sm1-winged-production/sp_tex00.psx
python dreamcast/tools/verify_wing_parity.py `
  --ported dreamcast/converted/sm1-winged-production/spidey.psx
```

The verifier asserts all authored data rather than relying on a render:

```text
PASS: 7 donor wing faces exact plus 4 DC armpit seam faces; donor UV/packet
payloads and normals exact; all stitched
vertices preserve donor source geometry and bone ownership; 129 output
attachment sources; 0 unresolved stitches
```

Current production hashes:

| loose output | bytes | SHA-256 |
|---|---:|---|
| `dreamcast/converted/sm1-winged-production/spidey.psx` | 379,424 | `810956C00F7361103DC8509B1F364EB1A277BAFCD80DA37C736FFAC54A45F93F` |
| `dreamcast/converted/sm1-winged-production/sp_tex00.psx` | 28,740 | `FDD45FC5E22B7E0E6CD48546D317EE3F4AE5A414979503421ECC085C92C2C375` |

The generated PSX files remain excluded from Git because they contain
retail-derived game data. `dreamcast/manifests/winged-spidey-lock.json` safely
preserves the exact build instead: it records every private input hash, both
visible and production output hashes, seam parameters, proof requirements, and
the rebuild commands. Verify a local reconstruction byte-for-byte with:

```powershell
python dreamcast/tools/verify_wing_build_lock.py
```

## Visible SM1 runtime parity proof

Structural verification is necessary but is not sufficient to lock wing parity.
The same binary must be rendered by SM1 with the wings visible while the native
animation system moves their owner parts.

Generate the proof variant with `--visible-wing-proof`. This changes only the
normally painted-out wing texture: the converter reads SM2's 4-bit PS1 texture,
expands its packed nibbles, and writes the retail black/white artwork through the
same texture-library conversion used by the game. It does not change geometry,
UV bytes, normals, stitches, or ownership:

```powershell
python dreamcast/tools/build_winged_spidey.py `
  --visible-wing-proof `
  --output-model dreamcast/converted/sm1-winged-runtime/spidey.psx `
  --output-textures dreamcast/converted/sm1-winged-runtime/sp_tex00.psx

python dreamcast/tools/verify_wing_parity.py `
  --ported dreamcast/converted/sm1-winged-runtime/spidey.psx
```

Independent decoding confirms the rebuilt `DC38D248` PNG is pixel-for-pixel
identical to the donor: 64x64 pixels and zero mismatches. Proof hashes:

| loose output | SHA-256 |
|---|---|
| `sm1-winged-runtime/spidey.psx` | `208B3017C0DF7EB234380DB9FD66575888E883DCA9CD3D89AD67D77AEE85B083` |
| `sm1-winged-runtime/sp_tex00.psx` | `4C528ED5998B39FF08C79558F7C3BEF3F9C4E1BAFBCB760E0E453E5389501C02` |

`validate_wing_textures.py` asserts that visible payload against the retail
donor and separately requires the production wing to be a 64x64 all-magenta
palette with all-zero indices. It also reopens the four production in-game
paint-out captures at 2560x1920.

Run the actual SM1 new-game route and author the close crops with the dedicated
capture harness. `SPIDEY_SCRIPT` feeds controller state inside the game process;
it does not generate host OS input. GPU capture is native to the recompilation:

```powershell
python dreamcast/tools/capture_wing_runtime.py
```

The qualifying captures are under
`dreamcast/converted/sm1-winged-runtime/runtime-wing-seam-proof/`:

- 13 full native frames at 2560x1920, covering frames 4000 through 5000;
- `proof_front_wings.png`, exact crop of frame 4100;
- `proof_rear_wings.png`, exact crop of frame 4150;
- `proof_side_wings.png`, exact crop of frame 4800;
- all 13 frames were inspected sequentially; front, rear, both faces, turns,
  crouches, and asymmetric poses remain attached with no armpit holes or
  winding dropouts and use a continuous, clearly defined black/white web pattern.

`wing-runtime-proof.json` records every source frame, crop rectangle, size, and
SHA-256. The runtime log records loose override loads, L1A1 archive loads, actor
spawns, capture paths, and the clean scripted exit. These in-game frames are the
parity lock; T-pose and structural renders are supporting evidence only.

## Exhaustive Dreamcast actor batch

`dreamcast/tools/port_all_characters.py` discovers v6 actors by structure rather
than a hand-maintained name list. A v6 file is an actor when it contains an
animation tag (`0x2A` or `0x2C`) and the `HIER`/`0x52454948` hierarchy tag. Three
structural matches are deliberately excluded after audit: `CONTROL` is the menu
controller, `FIRE` is an effect, and `VMU` is the memory-card model.

Fourteen dedicated entity files already ship as native v3/v4 PS1 containers on
Dreamcast and are copied without conversion. This includes chopper, claw,
cop-car, turret, soft-spot components, and Dreamcast-only alternate components.

```powershell
python dreamcast/tools/port_all_characters.py
```

The current manifest is
`dreamcast/converted/all-characters/manifest.json`:

- 65 actor models total;
- 51 v6 actors converted to v4;
- 14 native v3/v4 actor/entity components copied;
- zero scan errors and zero conversion failures;
- Spider-Man uses the donor-preserving, DC-seam-fitted wing transfer and the
  default magenta paint-out.

The entire output directory can be supplied as `SPIDEY_ASSET_DIR`. SM1 requests
only the names needed by the active level, so unrelated batch entries remain
dormant. Independent batch validation reconstructs all 65 GLBs, decodes 763
textures, counts 65,537 triangles, and creates five views for every actor (325
renders):

```powershell
python dreamcast/tools/validate_all_characters.py `
  --multitool C:\path\to\NeversoftMultitool.exe
```

The process-local runtime matrix launches 18 minimal story levels, captures two
native frames per level, and verifies all 34 actors referenced by story triggers:

```powershell
python dreamcast/tools/validate_character_runtime.py --concurrency 3 --resume
```

The current reports pass 65/65 static actors and 18/18 runtime levels with
34/34 story-loaded actors covered.

## SM2-exclusive costume proofs

The selected SM2 costumes are baked onto the wing-capable high-detail Dreamcast
body and exported as static T-pose GLBs. The current set is Prodigy (`sp_tex02`),
Dusk (`sp_tex03`), and Ricochet (`sp_tex08`). Each output has five whole-model
review views and six tight wing views covering front, rear, underside, and both
obliques.

`audit_wing_glb.py` independently reads both source and output GLBs. It requires
exact wing UV coordinates, UV triangles, texture dimensions, and RGBA pixels,
four unique output triangles, and a two-sided output material. Dusk's 32x32
texture requires a 2x normalized-UV adjustment around Blender's `V=1` import
pivot; Prodigy's wing texture is intentionally fully transparent; Ricochet has
the visible black/white web treatment.

```powershell
python dreamcast/tools/validate_sm2_costumes.py
```

The report passes all three costumes, 15 T-pose views, and 18 wing close-ups.

## One-command pipeline

`run_port_pipeline.py` connects conversion, exact wing parity, native in-game
capture and close-crop authorship, all-character reconstruction/rendering,
18-level runtime coverage, costume baking, and final reports:

```powershell
python dreamcast/tools/run_port_pipeline.py `
  --multitool C:\path\to\NeversoftMultitool.exe `
  --blender "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" `
  --resume-runtime
```

For a fast integrity rerun against existing generated artifacts:

```powershell
python dreamcast/tools/run_port_pipeline.py `
  --skip-build --skip-costume-build --skip-static-tools `
  --resume-runtime --reuse-wing-captures
```

The aggregate report is `dreamcast/converted/port-pipeline-report.json`.

## Runtime allocation required by high-detail overrides

Original WAD loads allocate fixed sector-sized slots on the game's two-megabyte
heap. High-detail DC actors can be larger than those retail slots and several can
be resident together. `LooseWadOverrides` therefore allocates external override
payloads from the reclaimable `0x80300000..0x80780000` region using first-fit and
coalescing. Only loose external WAD overrides use this arena; the retail game heap
and ordinary WAD entries are unchanged.

The arena exists solely in the recompiled port's eight-megabyte address space.
It is why a whole converted cast can be tested without truncating models or
mutating the original loose extraction.

## Validation checklist

Before calling a new port complete:

1. Run the converter only against loose extracted files.
2. Parse the output with an independent PSX container reader.
3. Decode every palette and texture record.
4. Reconstruct and render the whole model, not just its first mesh.
5. For stitched additions, run `verify_wing_parity.py` or an equivalent byte-level
   ownership/attachment audit.
6. Load the output through `SPIDEY_ASSET_DIR` in SM1.
7. Capture the actual GPU output in a level across multiple animated poses.
8. Keep proof/debug textures separate from production paint-out textures.
