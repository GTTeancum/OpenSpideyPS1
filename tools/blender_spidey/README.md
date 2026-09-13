# OpenSpidey Character Tools for Blender

Import a native character as a rigged template, align your replacement over it,
transfer its weights, and export a native character package. The target can be
Spider-Man, an NPC, an enemy, or a boss. The target supplies its object layout
and animation data; the exporter does not assume Spider-Man's skeleton.

## Install

Build the add-on ZIP from this checkout:

```powershell
python tools/blender_spidey/build_zip.py --output OpenSpidey-Character-Tools.zip
```

Install that ZIP as a Blender add-on and enable **OpenSpidey Character Tools**.
Tested with Blender 4.5.8 LTS. In its preferences, configure:

1. This OpenSpideyPS1 repository directory.
2. A Python executable with Pillow installed. This is separate from Blender's Python.
3. The NeversoftMultitool executable used by the repository's actor converters.

The ZIP contains the Blender interface, not game models or the native conversion
backend. Keep the repository and Multitool available while using it.

## Artist workflow

1. Choose **Import Bundled Character Template** in the **Spidey** sidebar to
   select a character from the configured repository. Alternatively, import a
   **native v4** `.psx` using File > Import. Use the game's converted runtime
   actor, not a raw Dreamcast v6 file.
   The template's mesh, rigid joint groups, hierarchy, and seam ownership are
   imported. The template is a geometry/weight reference; original materials
   are not reconstructed for display. Its source container is embedded in the
   blend file for export, so keep one template per scene.
2. Keep the template object and armature object transforms unchanged. In Pose
   Mode, spread any touching arms, hands, legs, or accessories before transferring.
   This is especially important when hands touch hips: surface transfer cannot
   otherwise reliably distinguish those surfaces. Do not apply this pose as the
   template's rest pose or rename its `part_###` bones.
3. Import your new character using Blender's regular model importers. Align and
   pose it over the template. Join the replacement into one mesh and bake its
   materials into **one diffuse image atlas**. The mesh may have a source rig;
   the transfer step freezes its visible pose before replacing that rig.
4. Select the replacement mesh and choose **Transfer Template Weights to Active
   Mesh**. This replaces its vertex groups and modifiers, so save first or use
   Undo to return to the source rig. Weights transfer from the closest triangle
   on the posed template using barycentric interpolation. The tool reverses the
   template pose into bind coordinates and adds the native preview rig.
5. Inspect and adjust weights in Blender. Template pose changes preview the new
   mesh. Export uses the original rest coordinates and dominant rigid weights;
   Blender's blended preview is not an exact substitute for an in-game check.
6. Select the replacement and choose **Export Native Character Package**. Choose
   a fresh output path. The `.spidey` path is a **directory**, containing an
   `assets/<original-character-name>.psx` and its host texture pack under
   `assets/packs/`. The original template and edited mesh are not overwritten.
7. Test the package with `SPIDEY_ASSET_DIR` pointing to that `assets` directory.
   The runtime picks up the companion texture pack automatically. Use a separate
   test game directory. Clear the override to restore the original character;
   there is no disc rebuild, executable modification, or permanent installation.

## What export does

- Triangulates the replacement and partitions it by the strongest native joint
  assignment. Shared boundary vertices become native attachment references,
  keeping adjacent parts joined. It does not cut open a closed mesh and then
  add hidden caps. Holes already present in the source still need artist repair.
- Reduces a temporary mesh copy until every part, including attachment vertices,
  fits the 256-vertex limit. Disable automatic reduction if you prefer to simplify
  manually. Reduction changes topology and can affect texture detail; its report
  records iterations and any UV boundary clamps.
- Normalizes repeated whole atlas tiles. Polygons crossing tile boundaries must
  be split or baked before export. Normal/specular maps, alpha hair cards, multiple
  independent materials, and arbitrary shader graphs require baking/adaptation;
  this first release exports an opaque diffuse atlas.
- Produces a compact 64x64 indexed compatibility page plus the original-size host
  diffuse. It removes replaced body texture pages and preserves texture records
  not referenced by the original body, including player support textures.
- Preserves the target's object table and animation-tag bytes. Spider-Man's known
  alternate hand records receive the same custom hand pose in both slots.
- Gives unused joints one inert vertex/normal pair and no faces. The native
  lighting loop reads its first normal even for a zero-count mesh, so emitting
  a completely empty joint can cause an invalid memory read in the menu renderer.
- Emits one terminal mesh per object. This follows the existing SM1 conversion
  strategy for stitched actors: mixing old reduced tiers with new seam references
  is invalid. There is no distance simplification in this release, so keep enemy
  triangle counts modest, particularly when many can appear together.
- Re-parses the resulting actor and checks face counts, joint references, part
  budgets, hierarchy, and animation tags. Structural success still requires native
  visual review. It does not promise automatic good weighting for every shape.

Native v3 props (for example the bundled cop car) and raw v6 Dreamcast sources
must first be converted to v4. The character export path supports different part
counts; it does not invent extra animations or change NPC behavior.

## Verification

`test_blackcat.py` runs the actual add-on functions in background Blender. It
imports SM1 Black Cat's template, spreads her limbs, aligns Unlimited Black Cat,
transfers weights, checks the posed alignment round trip, and exports. Gameloft
owns the source model and texture; source data is kept outside this repository.
The native smoke route stops input before the opening wall climb so Black Cat's
entrance and conversation play without further button presses.

`test_templates.py` imports and exports the native v4 roster in `templates.json`,
including unusual boss hierarchies and multi-tier enemies. It uses each template's
own geometry and a neutral test atlas. This is structural roster coverage, not
a claim that every character was replaced by Black Cat or visually reviewed.

`test_level_blackcats.py` builds a temporary L1A1 set: the player, Black Cat,
and the henchman model all use Unlimited Black Cat geometry. It maps the reviewed
Black Cat weights onto these three known humanoid templates; this alignment fixture
is separate from the artist-facing nearest-surface transfer tool.

`compare_level_blackcats.py` runs stock and replacement assets sequentially and
records private/working-set memory, native allocation ranges, allocation padding,
unused expanded RAM, and the enemy linked list. `--crowd` requires a game built
with the opt-in `CharacterBaseline` diagnostic hook. Between frames 3450 and 4050,
the hook positions the four existing L1A1 thugs near the player for their draw call
and restores their positions immediately afterward. AI and animations continue;
there is no controller input after the opening wall climb. With the environment
switch absent, the hook does nothing. This is a bounded baseline, not an exhaustive
memory-safety or full-level gameplay certification.

`--full-roster` enables `SPIDEY_BASELINE_ROSTER=1`. The SM1 L1A1 trigger table
contains five henchman records (9, 10, 11, 16, 19) and four story Black Cat
records (100, 113, 121, 138). The harness observes normal activation, then calls
the native trigger parser for each remaining character record after the intro,
300 frames apart. It draws all five henchmen beside the player and runs to frame
7200. This exercises every authored character placement, including those normally
gated by progression, without changing their record data or replacing scenery.
The spawned actors exist only in the private test process. Closing it restores
normal play; the asset overlay and diagnostic switches are not installed globally.
This is roster stress coverage, not a playthrough of every level script.

Initial full-roster result (2026-09-13): stock passed all nine records through
frame 7200, peaking at 235,064 command bytes. The Black Cat replacements reached
five henchmen plus the player, then hit the 256 KiB command-pool guard at 261,788
bytes after story record 100 activated. The diagnostic stopped the run; replacement
records 113 and 138 were not reached in that run.

The repaired SM1 build uses two bounded 512 KiB command pools, adding 512 KiB
total compared with the previous allocation. Both stock and replacement runs now
pass all nine records through frame 7200. Peak usage was 234,924 bytes stock and
377,256 bytes with replacements, leaving 147,032 bytes of physical buffer space.
Allocation padding, packet safety margins, unused arena, and actor-list checks
passed at four snapshots. Allocator regressions also cover buffer switching,
adjacent model memory, rejection at the new limit, and freeing/coalescing pools.
The tested executable is staged; normal models, settings, and saves are unchanged.
This passes the bounded full-roster baseline, not every level or animation.

Example background test (set the executable paths for your system):

```powershell
blender --background --factory-startup --disable-autoexec --python tools/blender_spidey/test_templates.py -- --repo C:/Programming/GitHub/OpenSpideyPS1 --census tools/blender_spidey/templates.json --report template-results.json --python C:/Python/python.exe --multitool C:/Tools/NeversoftMultitool.exe
```
