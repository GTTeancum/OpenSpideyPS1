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
selector supports 60 total costumes: 20 stock plus 40 mods in SM1, and 19 stock
plus 41 mods in SM2. The eleven-row scrolling viewport is unchanged. Extra
installed mods beyond the limit are rejected with a diagnostic; selected mod IDs
remain stable across restarts.
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
## Spider-Punk

Use the extracted `punk/punk.fbx` and `SpidermanPunk_D.png`. The original head
batch uses 270 native vertices, including borrowed attachment vertices, exceeding
the 256-vertex format limit. Prepare only the connected head surface first:

```powershell
& "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" --background --factory-startup --disable-autoexec -t 2 --python dreamcast/tools/prepare_unlimited_spider_punk.py -- --fbx C:/Programming/SMU-Costumes/costumes/punk/punk.fbx --output C:/Models/SpiderPunkPrepared
```

Save the diffuse PNG as `SpiderPunk_D_rgb.tga` in that prepared folder. Use the
normal converter with `--id spider-punk --name "Spider-Punk" --opaque-diffuse`.
The extracted alpha hides the pants and parts of the arms in the native cutout
path, so the body needs opaque alpha while retaining its original RGB colors.
Head reduction retains bone weights and face-corner
UVs; all separate mohawk and shoulder spikes and the body topology remain intact.
The preparation also binds the 104 source vertices of the lower coat band and
its folded inner edge to Spine1. Their original nearly tied Spine1/Spine2 weights
made adjacent hem vertices choose different native joints, kinking the waist in
animation. The band now follows one joint consistently; upper vest and limb
weights remain unchanged. This selection is specific to the original `punk.fbx`
coordinates and checked vertex count, so changed source geometry needs review.
The resulting actor has 2,942 source triangles and a maximum 247 vertices per part.

## Noir

Use the original `noir/noir.fbx` and `SpidermanNoir_D.png` (the collection also has
a separate `noirnew` variant). The original head needs 362 native vertices.
Prepare the head/collar surface with:

```powershell
& "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" --background --factory-startup --disable-autoexec -t 2 --python dreamcast/tools/prepare_unlimited_noir.py -- --fbx C:/Programming/SMU-Costumes/costumes/noir/noir.fbx --output C:/Models/NoirPrepared
```

Save the diffuse as `Noir_D_rgb.tga` in that directory, then run the normal
converter with `--id noir --name Noir --opaque-diffuse`. The head/collar surface
is reduced from 356 welded vertices to 217; body topology and weights remain
unchanged. Both hand variants use fists. Diffuse RGB is preserved, with opaque
alpha for the native material. Original source files remain unchanged.

## 2211

Use `2211/2211.fbx` with `Spiderman2211_D.png`. Run
`prepare_unlimited_2211.py` in Blender with `--fbx` and a fresh `--output`
directory, then save the diffuse there as `2211_D_rgb.tga`. Build with
`--id spiderman-2211 --name 2211 --opaque-diffuse`.

The helmet is reduced from 309 welded vertices to 174. The sixteen pieces of
the compact back attachments are lightly reduced and assigned rigidly to their
lower-waist or upper-middle-torso group, preserving the source arrangement.
This avoids per-vertex joint changes within the mechanical pieces. The main
body and limb topology/weights remain unchanged; both hand variants use fists.
The final actor has 3,384 source triangles and a largest native part of 245
vertices. No new attachment animation or powers are added.

## Pavitr Prabhakar

Pavitr is a one-off conversion. Use `prepare_unlimited_pavitr.py`, then
`build_pavitr_actor.py`, which calls `fit_pavitr_actor.py` and
`pack_pavitr_actor.py`. These corrections are not part of the shared Unlimited
fitter or packer and should not be applied to other costumes.

Use `india/india.fbx` with `SpidermanInida_D.png` (original spelling). Run the
preparation in Blender with `--fbx` and a fresh `--output` directory. Save the
diffuse as `India_D_rgb.tga` there. Run the dedicated builder with `--source`,
a fresh `--output`, `--blender`, and `--opaque-diffuse`; its default name and ID
are Pavitr Prabhakar and pavitr-prabhakar.

The source's 3,524 triangles remain. The fitting gives the trousers coherent
knee ownership and keeps the chest on the torso. The chest/abdomen envelope
follows default Spider-Man's dimensions; the shoulder transition is smoothed
to remove pointed upper-arm flaps. Native joint pivots remain unchanged.
Shoes are about 39% shorter, with a fuller instep and raised arch. The approved
foot and leg coordinates are preserved by the torso revision.

The packer adds 824 reversed trouser triangles as an inward-facing lining for
folds exposed by rigid hip/knee animation. It reuses the vertices and UVs and
preserves the original outward smooth normals. The complete actor contains
5,104 triangles including alternate hands, takes 544,580 bytes, and remains
within the 256-vertex-per-part limit. This is a targeted cloth treatment, not
a change to renderer culling or every costume's geometry.

Both hand variants use fists and standard Spider-Man donor powers/animations.
The diffuse keeps its original RGB with opaque alpha.

## Original SM1 Spider-Man in SM2

Run `python dreamcast/tools/build_sm1_spidey_sm2_suit.py --output <fresh-folder>`
to produce the `spiderman-sm1` suit, displayed as **Spider-Man (SM1)**. Copy that
folder into SM2's `mods/suits`. It selects the already bundled wingless SM1
actor through `model: spiderman` and copies the eight original SM1 body PNGs
without recoloring or resizing. Standard SM2 Spider-Man supplies the powers
and animations. The original SM2 Spider-Man remains a separate stock costume.
This builder needs the existing SM1 runtime bundle and converted texture manifest.

## Steve Ditko (SM1 and SM2)

Dat Mental Gamer's [Steve Ditko Costume](https://gamebanana.com/mods/249029)
uses the default wingless SM1 model. Download `steve_ditko_spidey.zip` from the
original page, then run:

```powershell
python dreamcast/tools/build_steve_ditko_suit.py --archive <downloaded-zip> --output <fresh-folder>/steve-ditko
```

Install the resulting folder in either game's `mods/suits`. The builder checks
the original archive checksum, maps its eight main BMPs to the native body
materials, and verifies pixel-identical PNG conversion. It excludes the extra
`New folder` alternate texture. The selector displays **Steve Ditko**, credits
**Dat Mental Gamer**, and uses standard Spider-Man powers.

## Quick Change (red), SM1 and SM2

[Improved Quick Change Costume](https://gamebanana.com/mods/249032) by Dat Mental
Gamer replaces the mask and gloves with their red versions. Download the original
`improved_quick_change.zip`, then run:

```powershell
python dreamcast/tools/build_quick_change_red_suit.py --archive <downloaded-zip> --output <fresh-folder>/quick-change-red
```

Install the output folder in either game's `mods/suits`. The builder checks the
archive checksum, preserves both mod textures pixel-for-pixel, and copies seven
unchanged SM1 Quick Change textures. It uses the Quick Change body with standard
Spider-Man powers and displays **Quick Change (red)** / **By Dat Mental Gamer**.
