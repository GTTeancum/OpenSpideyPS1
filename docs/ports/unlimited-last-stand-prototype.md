# Spider-Man Unlimited: Last Stand native actor prototype

Historical prototype notes: the current installable suit workflow is documented in [Unlimited costume mods](unlimited-costume-mods.md). The limitations below describe the original prototype.

This experiment imports the user's Last Stand FBX into SM1's existing native
character path. It does not implement weighted runtime skinning or expand the
data-only suit manifest to accept arbitrary model files. Original source files
remain untouched; generated models and captures live under `proof_render/last-stand`.

## Source and fit

The supplied `Mesh_LastStand` contains 1,370 vertices, 2,736 triangles, one diffuse
material, and up to four bone influences per vertex. The audited rig uses the
`Clown001` bone naming scheme. The diffuse image is 1024×1024. Normal and specular
maps are not consumed by the existing native character shader.

The fitter maps the pelvis, two torso sections, head, arms, hands, legs, and feet
onto the bundled SM1 Spider-Man hierarchy. It fits limb lengths to native bone
pivots while preserving transverse shape. Source weights blend the bind-pose fit;
runtime vertices then follow one dominant native bone. Fingers are posed into
fists before their influences are collapsed into the two rigid hands.

The native format supports type-1 attachment sources and type-2 references.
Cross-part triangles retain shared vertices through those references, keeping
the original connected surface instead of cutting open joints and adding caps.
Faces are assigned to a part after all their attachment sources so the game's
sequential vertex processing never reads a future source. Original UVs and all
2,736 source triangles are retained. Native alternate hand slots duplicate the
hand geometry, yielding 3,204 stored triangles; they are not all visible together.

The final partition uses at most 235 vertices in a part and 216 attachment
sources. The actor is approximately 490 KiB. The original donor hierarchy,
animations, and support textures remain in the container. No renderer or game
buffer expansion was needed for this particular model.

## Texture encoding

Use a private material and palette identity. The compatibility page is a
256×256 indexed image; a matching host texture pack supplies the original
1024×1024 RGBA diffuse. Native UVs are byte coordinates with inverted V relative
to Blender, and native triangle winding reverses Blender slots 1 and 2.

The Dreamcast quantizer compensates for the multitool's image correction.
An FBX texture requires undoing that compensation before writing native texels.
Failing to do so maps jacket colors onto trousers and sleeves even though the
offline Blender preview is correct. Hash the actual uploaded index/palette
payload when generating the host replacement key.

## Reproduce

Requirements: Blender, Python with Pillow, the repository's bundled SM1 actor,
and the existing NeversoftMultitool with `psx-mesh-dump` support. Use a fresh
output directory; the builder refuses to overwrite an existing proof run.

```powershell
python dreamcast/tools/build_unlimited_actor.py `
  --source 'C:\Users\smmel\Downloads\Last Stand Spider-Man (Mesh_LastStand)' `
  --output proof_render/last-stand-rebuild `
  --id last-stand-spiderman --name 'Last Stand' `
  --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' `
  --preview
```

Supply `--multitool` if it is not found automatically. The builder hashes source
files, extracts the donor, fits the FBX, packs the actor and diffuse replacement,
and parses the native output independently. It rejects unresolved attachments,
parts exceeding 256 vertices, rejected faces, lost triangles, and source changes.
Its successful result is deliberately a **structural pass**, pending native
visual review. Blender images alone do not establish native rendering correctness.

## Verification and remaining scope

The first working body revision was inspected in native SM1 rooftop standing,
jump, and deep landing-crouch captures. Those poses retained connected shoulders,
elbows, hips, and knees. The game exited normally. A pre-capture timing sample
reported 59.1 emulated vblanks/sec (about 29.6 game frames/sec), with 33.67 ms game
work per frame. This is a short smoke result, not a complete performance comparison
or an all-animation compatibility claim.

Both native hand variants use fists at the user's request. Separate open or
web-shooting finger poses remain future work. Other Unlimited costumes may use
different rigs, topology, proportions, materials, or transparency; they require
their own mapping and capacity review. This tool is an audited starting point
for this source rig, not a universal automatic converter.
