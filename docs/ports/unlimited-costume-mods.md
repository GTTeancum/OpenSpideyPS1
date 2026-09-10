# Spider-Man Unlimited costume mods

The offline converter emits ordinary `mods/suits/<id>` folders for SM1 and SM2.
Mangaverse and Last Stand include a custom native actor, full-resolution diffuse
PNG, and `suit.json`. Select them from the costume menu. No global asset override
is needed. Existing texture-only suits continue to work.

## Convert another costume

Place one exported FBX and its `*_D_rgb.tga` diffuse image in a source folder.
Use Blender 4.5 and Python with Pillow, then run from the repository root:

```powershell
python dreamcast/tools/build_unlimited_actor.py --source C:/Models/Mangaverse --output C:/Models/Converted/Mangaverse --id mangaverse-spiderman --name "Mangaverse Spidey" --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe"
```

Use a fresh output directory. Copy the generated `mods/suits/<id>` folder into
both games' `mods/suits` directories. Keep source assets outside the repository.
The conversion requires the Unlimited Clown001 rig; other rigs need an explicit
bone mapping. Anatomy determines orientation and scale. Coincident FBX seam
vertices are welded while retaining per-corner UVs. Dominant-bone attachments
become native shared vertices; the runtime does not implement blended skinning.
Both hand variants currently use fists. Review the actor in motion after every
conversion; structural validation alone does not establish visual quality.

## Manifest

```json
{
  "version": 1,
  "id": "mangaverse-spiderman",
  "name": "Mangaverse Spidey",
  "comments": "Spider-Man Unlimited",
  "model": "spiderman",
  "modelFile": "actor.psx",
  "abilities": { "profile": "spiderman" },
  "textures": { "AB76B463": "textures/diffuse.png" }
}
```

`modelFile` is relative to the suit folder, cannot traverse out or follow links,
and must name the converter's native v4 actor format: 18 parts, at most 256 vertices
per part, supported triangle records and valid attachment references, at most
1 MiB. FBX is not loaded at runtime. Material IDs come from the validated actor;
the converter assigns a private body material from the mod ID. Keep IDs unique.

`abilities.profile` remains independent of appearance. SM2 supports its nineteen
existing donor profiles; custom geometry adds no new powers or animations.
Normal and specular maps are not used by the native shader. A 128-square embedded
fallback texture reduces guest VRAM use; the mod uses the original diffuse PNG
through the host texture path. SM2 releases the previous private custom actor
when switching, retaining the shared stock actor binding.

Mangaverse retains all 2,896 source triangles, with a largest part of 242 vertices.
Last Stand reuses the previously fitted geometry and closed fists. The current
custom slot count is unchanged; expansion to 80 total remains separate work.
## Infinity War / Iron Spider Battle Mode

The extracted source is `ironspidernewwithtentackles`, not `ironspidernew`.
Its four mechanical arms are already rigidly weighted to Spine3. The untouched
source exceeds the native torso's 256-vertex budget. Prepare this costume first:

```powershell
& "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" --background --factory-startup --disable-autoexec -t 2 --python dreamcast/tools/prepare_unlimited_infinity_war.py -- --fbx C:/Programming/SMU-Costumes/costumes/ironspidernewwithtentackles/ironspidernewwithtentackles.fbx --output C:/Models/InfinityWarPrepared
```

Save `IronSpiderNewWithTentackles_D.png` as `InfinityWar_D_rgb.tga` in that prepared
folder, then use the normal converter with `--id infinity-war --name "Infinity War" --opaque-diffuse`.
The default preparation retains the body topology and four static arms, reduces
each arm to 22 vertices, and omits layered back decals and separate transparent
light cards. The final native torso uses 254 vertices. This preparation is specific
to this mesh and does not change the source FBX. Keep its preparation report with
the conversion record. The arms follow the torso but have no independent animation.

For Infinity War, `--opaque-diffuse` retains every RGB pixel but makes the body
opaque. The original alpha values are unsuitable for the native cutout path and
otherwise make almost the entire actor disappear. Do not force this option for
costumes that require actual transparent texture cutouts.

SM2's Infinity War smoke check also exposed its retail frame-command pool limit.
The port now reserves two fixed 256 KiB command pools from tracked expanded RAM,
updates the active native end pointer, and retains the original safety margin.
This prevents the observed omission of later body parts, shadows, and background
draws when the denser actor exceeds the old pool. It does not remove the per-mesh
256-vertex format limit. `SPIDEY_PACKET_TRACE=1` records crossing the old capacity;
SM2 suit regressions include pool allocation, bounds, and release checks.
