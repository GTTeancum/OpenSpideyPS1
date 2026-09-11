# Dreamcast rig audit and civilian suit restoration

The Quick Change (red) and Ben Reilly (Street) builds had changed original
Dreamcast vertex ownership and then reshaped overlapping waist/cuff surfaces.
Those alterations are removed. Their builders now preserve the original object
table, every vertex/attachment record, and all original faces. Mod texture pixels
and author credits are unchanged.

The visible clothing defects also involved draw order. PS1 ordering-table buckets
can draw the shoe through its cuff or the trousers through the jacket even with
the original rig. The host renderer now uses a depth buffer for opaque suit
textures when all three vertices carry exact GTE depth. Scenery, HUD, effects,
and vertices without that provenance retain their existing ordering. The buffer
is allocated lazily per display target and cleared for each rendered frame.

## Audit scope

Run `python dreamcast/tools/audit_dc_rigs.py` from the repository root. Its JSON
report is written to `proof_render/dreamcast-rig-audit/rig-audit.json`.

- SM1: 72 bundled actors, including 61 named Dreamcast actors and 11 imported
  SM2 costume aliases using the Dreamcast Spider-Man body.
- SM2: five bundled Dreamcast-derived player actors.
- Both staged mod folders: the two civilian custom actors are compared directly;
  texture-only suits inherit the audited bundled rig. Android Unlimited meshes
  are identified separately because they are not Dreamcast conversions.

All bundled actors preserve the original full-detail vertex positions and their
resolved source owners. Raw equality is reported separately: added wing records,
extra distance-detail copies, and existing skeleton compatibility remapping are
not evidence that original vertex ownership changed. The Jameson, viewer,
Parker and Scorpion compatibility checks also pass
(`audit_sm1_skeleton_adaptations.py`).

## Animation decision

Decoded Dreamcast and PS1 Spider-Man banks each contain 300 slots with matching
frame counts: 193 decoded clips match exactly and 107 differ. The differences
include rotations, not just byte packing. The two restored civilian suits now
carry their own original Dreamcast compressed animation bank. The existing
runtime can decode it; no animation runtime changes are required.

This does not replace all bundled animation banks. NPC/viewer compatibility
adaptations and SM2-specific banks remain as documented in the original port.
SM2 has different frame counts in 35 player slots compared with SM1, so a global
bank replacement would require separate compatibility work. The civilian mods
already used SM1 player banks in both games; their source banks retain the same
SM1 slot/frame layout.

`restore_dc_animation_bank.py` refuses actors whose object table or hierarchy
differs from the source. The builder verifies original vertex streams before
restoration and verifies preserved full-detail ownership afterward.

## Verification

Native process-local scripted captures cover stance, crouch, jump and landing
in SM1, and gameplay movement in SM2. Captures are reviewed individually for the
reported waist and ankle defects. These checks establish the tested poses;
they are not an exhaustive playthrough of every level or animation.

The current proof folders are `proof_render/quick-change-red/depth-sm1`,
`depth-sm2`, and the corresponding folders under `proof_render/ben-reilly-street`.
RenderingRegression, Sm2RenderingRegression and CustomSuitModelRegression cover
projection/depth provenance, native actor validation and suit material mapping.

The shoulder follow-up inspected all 32 existing native Dreamcast reference
frames in order. The source jacket has the raised rounded shoulder pieces and
pronounced upper-arm joins seen in the restored suit. The reference comes from
https://www.youtube.com/watch?v=QDu_hYTLFHM; one retained frame is
`proof_render/dreamcast-rig-audit/native-dreamcast-shoulders.png`.
The live SM1 attachment audit checked 11,160 batches with zero native-coordinate
mismatches, zero projection mismatches and zero missing projections. This
supports preserving the original shoulder geometry rather than re-rigging it.

## Repeating the conversion process

Run these commands from the repository root, supplying the downloaded author
archives and fresh output folders. Each builder checks its expected archive MD5,
preserves the mod's decoded texture pixels, verifies the donor rig, and restores
the matching source animation bank:

```powershell
python dreamcast/tools/build_quick_change_red_suit.py --archive PATH_TO_QUICK_CHANGE_ZIP --output NEW_QUICK_CHANGE_FOLDER
python dreamcast/tools/build_ben_reilly_street_suit.py --archive PATH_TO_BEN_REILLY_ZIP --output NEW_BEN_REILLY_FOLDER
dotnet run --project tools/RecompOne/tests/CustomSuitModelRegression -c Release -- NEW_QUICK_CHANGE_FOLDER/actor.psx
dotnet run --project tools/RecompOne/tests/CustomSuitModelRegression -c Release -- NEW_BEN_REILLY_FOLDER/actor.psx
dotnet run --project tools/RecompOne/tests/RenderingRegression -c Release
dotnet run --project tools/RecompOne/tests/Sm2RenderingRegression -c Release
```

For future Dreamcast texture conversions, start with the original donor geometry
and attachment ownership. Diagnose overlap in the renderer before changing
weights or deleting concealed faces. Compare decoded animation data before
substituting banks; preserve each game's required slot layout and compatibility
adaptations. Android model conversions are a separate process.

Publish the two games sequentially because they share runtime build outputs.
Use private test runtimes and the games' native `SPIDEY_SCRIPT`, `SPIDEY_SHOTS`
and `SPIDEY_CAPTURE_PRESENTED` facilities. Never drive the desktop to obtain
proofs. Review each captured pose individually, including deep crouch, airborne,
landing and movement views that expose the jacket hem and ankle cuffs.

After verification, copy each suit folder's contents into its matching
`mods/suits/<id>` folder in both staged games and copy the published executables.
Verify the staged files against the tested files, preserve `selected-suit.txt`,
and confirm texture files remain unchanged. Rerun `audit_dc_rigs.py` against
the stage. Keep direct links to the current proof PNGs, the audit report and
staged hashes; remove discarded experimental packages and duplicate logs.

Distribute the shared customization guide with every installed suit:

```powershell
python dreamcast/tools/install_suit_instructions.py "proof_render/user-facing-stage/ready/Spider-Man/mods/suits" "proof_render/user-facing-stage/ready/Spider-Man 2/mods/suits"
```

The tracked source is `mods/suit-instructions.txt`. Magenta Man is an archived
example in `mods/inactive-suits` in the staged games and is no longer needed in
the active roster to provide these instructions.
