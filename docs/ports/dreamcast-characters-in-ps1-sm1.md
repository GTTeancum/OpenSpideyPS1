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
5. Build one deterministic 255-color compatibility palette across the actor's
   complete texture set. Palette index zero remains the transparent magenta key,
   while every ordinary material in that actor shares one stable model-scoped
   cache id. This avoids both cross-actor palette aliasing and exhaustion of
   SM1's 68 physical 8-bit CLUT slots.
6. Embed quarter-size indexed pages only as the emulated-VRAM fallback and as
   stable replacement keys. This compact representation is not the visible
   quality ceiling and does not constrain texture mods.
7. Copy every original Dreamcast RGBA image, at its original dimensions and
   pixels, to the host texture pack. The recomp renderer resolves the compact
   page/CLUT key and samples this full-color host image directly, bypassing PS1
   5-bit framebuffer quantization and dithering. The same host path accepts
   arbitrary replacement dimensions for future HD packs.
8. Emit a v4 container whose compatibility texture section is self-contained.

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

The generated actor pack contains 618 source-to-runtime mappings backed by 589
unique full-resolution PNGs. Audit every generated v4 record, shared palette,
runtime key, source image, and packed RGBA image without relying on the converter
reader:

```powershell
python dreamcast/tools/audit_character_texture_pack.py
```

The audit currently passes all 51 converted actors, all 618 mappings, all 589
unique keys, and all 589 exact host PNGs. Scorpion accounts for the additional
mapping/key: its runtime-only material-18 alias points to the same source-exact
Dreamcast RGBA artwork as hook material 0, but is keyed through the independent
64x64 compatibility page required by SM1's spline renderer. Its report is
`dreamcast/converted/all-characters/packs/dreamcast-sm1-actors/texture-audit.json`.

The entire output directory can be supplied as `SPIDEY_ASSET_DIR`. SM1 requests
only the names needed by the active level, so unrelated batch entries remain
dormant. Independent batch validation reconstructs all 65 GLBs, decodes 847
textures from the 65 actors plus ten costume texture companions, counts 65,541
triangles, and creates five views for every actor (325 renders):

```powershell
python dreamcast/tools/validate_all_characters.py `
  --multitool C:\path\to\NeversoftMultitool.exe
```

The process-local runtime matrix launches 18 minimal story levels, captures two
native frames per level, and verifies all 34 actors referenced by story triggers:

```powershell
python dreamcast/tools/validate_character_runtime.py --concurrency 1 --resume
```

The current reports pass 65/65 static actors and 18/18 runtime levels with
34/34 story-loaded actors covered. The ten playable models also pass the preferred
4x main-menu 3D proof, sequentially:

```powershell
python dreamcast/tools/validate_sm1_costume_models_runtime.py `
  --concurrency 1 --render-scale 4 --proof-mode menu
```

Quick Change remains blocked for the user's requested feet/jacket review. All 21
L1A1 gameplay frames and 32 consecutive native Dreamcast Character Viewer frames
from 109.5 through 117.5 seconds of the cited reference were inspected individually.
The native model has the same triangular upper-thigh silhouette in its deep crouch
and the same bulky segmented jacket/shoulder joins; its running and wide-stance
poses remain coherent. The current evidence therefore does not establish a
port-specific deformation. Neutral source renders are clean, and all 127 stitch
sources and 143 references parse correctly. Gameplay costume proofs require the
requested retail level L/O/G assets, a live gameplay HUD or active level frame, and
a fresh slot-2 player head-geometry audit before every capture. GAME OVER,
save-progress, FMV, menu, and later NPC geometry cannot satisfy those gates.

The complete selectable Character Viewer roster is also exercised in one game
process at 4x. SM1 exposes 26 entries, ending at Sub-Mariner; the extra J. James
Jewett record in `charbio.dat` is not selectable in the retail viewer.

```powershell
python dreamcast/tools/validate_character_viewer_runtime.py --render-scale 4
```

Together, the story, costume, and Character Viewer routes naturally exercise 52
of the 65 actor-batch entries. Of the thirteen entries outside those routes, only
`CLAW`, `HOSTAGEF`, and `SYMBIOTE` are names SM1 can actually request. `CLAW` is
byte-identical in PS1 SM1 and Dreamcast. The other ten are Dreamcast-only
supplemental components, so they remain in the exhaustive source census but are
not installed as invented SM1 resource aliases. This actor-only batch never
replaces level geometry, collision, lighting, or object archives.

The viewer validator's recorded probe mode covers complete converted actors that
SM1 owns but does not expose through its normal viewer/story proof routes. It
temporarily aliases the source through a real viewer slot, keeps the original
high-resolution texture pack active, records the true source model in the JSON
report, and removes the temporary alias after the one-process run:

```powershell
python dreamcast/tools/validate_character_viewer_runtime.py `
  --probe-model hostagef --probe-slot parker `
  --output dreamcast/converted/hostagef-viewer-probe --render-scale 4

python dreamcast/tools/validate_character_viewer_runtime.py `
  --probe-model symbiote --probe-slot symbi_02 `
  --output dreamcast/converted/symbiote-compatible-viewer-probe --render-scale 4
```

Both final probes pass their loads, loose overrides, native captures, and clean
exits. `SYMBIOTE` deliberately uses the compatible `symbi_02` slot; a diagnostic
Peter-Parker-slot run proved that a mismatched viewer animation can fold a valid
model and therefore must not be used as deformation evidence.

This route caught three conversion-specific metadata failures that ordinary load
tests could not: technicolor Jameson face lighting, Scorpion's detached tail
chain, and a collapsed viewer-only Peter Parker. Jameson/JJVIEWER, Scorpion, and
PARKER now keep their Dreamcast meshes, UVs, materials, and full-resolution
textures but use the matching retail SM1 object order, hierarchy, and animation
metadata by stable mesh name. Jameson also clears Dreamcast's indexed-RGB face
mode (`0x0800`), restores retail SM1's neutral face lighting, and omits the
incompatible animated `RGBs` channel. Scorpion preserves the seven retail-exact
controller cubes and adds the procedural renderer's missing material slot 18 as
a 64x64 compatibility alias to the source-exact 128x128 Dreamcast hook/tube
skin; the authored hook remains on Dreamcast material 0. `SPPARK` remains the
distinct playable Peter costume and continues to use the playable costume path.

An independent parser verifies all four adapted containers without importing the
converter. It checks donor-exact object tables, mesh order, tagged metadata,
source-exact Dreamcast vertices and normals, Jameson's neutral face-lighting
bytes plus cleared indexed-RGB flags, and all seven Scorpion tail meshes against
retail geometry. It also verifies Scorpion's material-18 spline alias and
64x64 compatibility page:

```powershell
python dreamcast/tools/audit_sm1_skeleton_adaptations.py
```

The current audit passes JAMESON (58 checks), JJVIEWER (58), PARKER (52), and
SCORPION (108). The one-process 4x L2A2 proof captures 11 consecutive gameplay
frames from 4200 through 4450; the complete sequence keeps Scorpion's tube
attached and blue/green-segmented throughout its swing. Jameson is partially
visible at the far right in frames 4275-4325 with a grey/blue shirt, red tie, and
beige trousers and no technicolor contamination; the unobstructed Character
Viewer capture remains the primary appearance proof.

## SM2 costume texture-mapping proofs

`map_sm2_dc_actors.py` first restricts the SM2 inventory to character actors—no
level/environment files or animated props—then compares each one against the DC
actor batch by object count, stable mesh-name hashes, hierarchy, animation tags,
and material hashes:

```powershell
python dreamcast/tools/map_sm2_dc_actors.py
```

The current census contains 30 SM2 character actors. Its structural audit finds
ten same-name DC candidates, one exact known alias (`HOSTAGE2` -> `HOSTAGE`), and
nineteen actors with no confirmed counterpart. Structural resemblance is kept as
evidence only: the current upgrade scope selects Spider-Man and records all 29
NPC/enemy actors as explicit fallbacks retaining their original SM2 models and
textures. Almost none of the structural candidates share material hashes, so a
same-name model is not treated as texture compatible.

Default (`sp_tex00`), Prodigy (`sp_tex02`), Dusk (`sp_tex03`), and Ricochet
(`sp_tex08`) retain static T-pose GLB audits of the texture transfer onto the
wing-capable high-detail Dreamcast body. Each output has five whole-model review
views and six tight wing views covering front, rear, underside, and both
obliques.

The original projection-bake prototype was rejected because Dreamcast's reused,
overlapping UV islands allowed unrelated target polygons to overwrite one
another, producing triangular color fragments. The production path transfers
each target polygon to one nearest SM2 source triangle, then barycentrically
maps all of that polygon's loops from the same material/UV domain. This keeps the
original SM2 texture pages intact and avoids cross-material seam contamination.
The four donor-exact wing polygons retain their authored UVs separately.

`audit_wing_glb.py` independently reads both source and output GLBs. It requires
exact wing UV coordinates, UV triangles, texture dimensions, and RGBA pixels,
four unique output triangles, and a two-sided output material. Dusk's 32x32
texture requires a 2x normalized-UV adjustment around Blender's `V=1` import
pivot; Prodigy's wing texture is intentionally fully transparent; Ricochet has
the visible black/white web treatment.

```powershell
python dreamcast/tools/validate_sm2_costumes.py
```

The report passes all four costumes, 20 T-pose views, and 24 wing close-ups.
These GLBs are independent texture-mapping proofs, not game inputs. SM1 and SM2
continue to load `.psx` containers at runtime.

The native runtime pack covers all nineteen retail Spider-Man texture slots:

```powershell
python dreamcast/tools/build_sm2_spider_man_costume_pack.py
```

Ordinary slots share a native SM2 `spidey.psx` containing Dreamcast geometry,
SM2's complete object table, hierarchy and animations, all alternate hand
meshes, and the authored wing seams. All nineteen `sp_tex00.psx` through
`sp_tex18.psx` libraries remain byte-exact retail SM2 inputs. Their compact PS1
pages identify textures only; the host renderer is not constrained to the PS1
page dimensions.

Bag-Man (slot 13) and Peter Parker (slot 17) change topology, so they cannot be
represented by the shared body plus the retail low-detail mesh-7 coordinate
morph. `build_sm2_special_dc_costumes.py` instead name-matches the complete
Dreamcast `SPBAGMAN` and `SPPARK` actors onto SM2's object order, skeleton and
animation metadata. The runtime keeps those converted actors resident under
private resource names. When the ordinary retail costume loader selects either
slot, it switches the shared Spider-Man resource's complete processed binding—
mesh table, texture table, tagged chunks, and container base—then refreshes the
three retail morph targets. This is the normal interactive selection path, not a
proof-only `spidey.psx` pre-load alias. Returning to any ordinary slot restores
the complete shared binding. Bag-Man additionally translates Dreamcast's nested
head/paper-bag depth relationship through the renderer's native per-face ordering
offset, guarded by the exact audited 179-face topology.

The special actors use compact emulated-VRAM identity pages plus 21
original-resolution Dreamcast host PNG mappings. No generic web wings are
invented for either dedicated actor.

Validate every slot against the actual live 3D main menu with:

```powershell
python dreamcast/tools/validate_sm2_spider_man_costumes_runtime.py --render-scale 4
```

The validator rejects the 320x240 title/FMV path, anchors all captures to
`charlite.dat`, and launches strictly one `SpiderMan2.exe` process at a time. It
records five 1280x960 frames for every slot: 95 frames total. All nineteen runtime
evidence sets pass, and all 95 frames have been manually reviewed. The review is
locked to the exact aggregate runtime-report SHA-256 in
`dreamcast/manifests/sm2-spider-man-costume-review.json`; any changed capture set
requires a new visual review before `map_sm2_dc_actors.py` promotes the mapping.

`capture_sm2_default_runtime.py` remains the separate 8x Default menu/gameplay
wing proof. Together these results prove that native `.psx` assets—not the audit
GLBs—render the mapped suits and connected wings. Every non-player structural
candidate remains an explicit retail-SM2 fallback under the player-only upgrade
policy.

## One-command pipeline

`run_port_pipeline.py` connects conversion, the complete host-texture audit,
exact wing parity, native in-game capture and close-crop authorship, all-character
reconstruction/rendering, 18-level runtime coverage, all ten SM1 menu costume
proofs, the complete 26-entry Character Viewer sweep, costume mapping, native SM2
Default packing and its menu/gameplay proof, the complete nineteen-slot SM2
Spider-Man pack and sequential 3D-menu proof, and final reports. Runtime
validation is restricted to one game process at a time:

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

The aggregate report is `dreamcast/converted/port-pipeline-report.json`. Its
final status is `technical-pass-user-review-required` while any actor in
`dreamcast/manifests/sm1-model-review.json` has `blocksClearance: true`; automated
conversion and runtime checks never silently clear user-reported visual failures.

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
3. Run `audit_character_texture_pack.py` to decode every compatibility palette
   and texture record and prove its full-resolution host mapping.
4. Reconstruct and render the whole model, not just its first mesh.
5. For stitched additions, run `verify_wing_parity.py` or an equivalent byte-level
   ownership/attachment audit.
6. Load the output through `SPIDEY_ASSET_DIR` in SM1.
7. Capture the actual GPU output in a level across multiple animated poses.
8. Keep proof/debug textures separate from production paint-out textures.
