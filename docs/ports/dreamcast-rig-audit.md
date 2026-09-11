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
