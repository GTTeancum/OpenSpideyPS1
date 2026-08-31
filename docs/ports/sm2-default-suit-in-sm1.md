# Porting the SM2 default suit into SM1

This records the complete repeatable process used to run Spider-Man 2: Enter
Electro's default Spider-Man model and textures in Spider-Man 1. It is deliberately
about the method, not just the current output, so the same investigation can be
repeated for another costume.

No copyrighted game asset belongs in Git. The commands below operate on each user's
first-run loose-file extraction.

## Result and known geometry difference

The SM2 PS1 player model and its animation hierarchy load directly in SM1. Its geometry
is not identical by design: SM2's model has web-wing polygons beneath Spider-Man's arms,
whereas SM1's default model does not. The current port preserves those polygons and is
therefore an authentic SM2 model replacement, not an SM1-silhouette texture upgrade.

Leave that distinction explicit when evaluating the result. A future SM1-shaped hybrid
has two plausible routes:

1. delete the SM2 faces assigned to the web-wing material while retaining the SM2 model
   and texture atlas; or
2. adapt the remapped SM2 texture art to SM1's original mesh.

Neither geometry change has been made yet.

## 1. Import each game once

BIN/CUE is import media only. Both ports' runtime format is an extracted loose-file
directory with `recompone-disc.json`; `CD.WAD` is also expanded into `wad/`, and both
games serve archive entries from that directory at runtime. XA and STR files remain
individual files, but are stored as 2336-byte Mode 2 sectors so their subheaders and
audio/video payload survive. After extraction, launch from the directory and remove or
archive the images:

```text
SpiderMan.exe  <path-to-SM1-cue>     # first run: imports to loose files
SpiderMan.exe  <SM1-loose-directory> # every later run

SpiderMan2.exe <path-to-SM2-cue>     # first run: imports to loose files
SpiderMan2.exe <SM2-loose-directory> # every later run
```

In this repository the default development directories are `spiderman/extracted/` and
`spiderman2/extracted/`. `SPIDEY_DATA` selects a different import destination.

The two source assets for the default player are:

```text
spiderman2/extracted/wad/spidey.psx
spiderman2/extracted/wad/sp_tex00.psx
```

`spidey.psx` is the hierarchical model. `sp_tex00.psx` is costume texture slot zero.

## 2. Establish the raw-swap baseline

Copying both SM2 files over SM1's corresponding files proves that the model, bones,
and animations are compatible. The raw result has the correct silhouette but noisy,
apparently random colors. That symptom is evidence of a material-name mismatch, not a
bad mesh, corrupt palette, or incompatible pixel format.

Do not use a patched BIN as the permanent test route. SM2's `sp_tex00.psx` is 23,780
bytes and rounds to 24,576 bytes; SM1's is 21,668 bytes and rounds to 22,528. SM1's
CD.WAD ends exactly at the following disc file, so it cannot gain the extra sector
in-place. The loose-file loader has no fixed-slot limitation.

## 3. Separate model material hashes from texture-library names

Mesh dumps show thirteen canonical face-material hashes shared by both models. SM2 adds
one more, `DC38D248`. That does not mean the raw texture libraries use the same names.

A standalone Neversoft PSX texture library begins here:

| offset | type | meaning |
|---:|---:|---|
| `0x00` | `u32` | PSX texture magic, `00020004` here |
| `0x04` | `u32` | metadata pointer, `00000010` here |
| `0x10` | `u32` | metadata terminator, `FFFFFFFF` |
| `0x14` | `u32` | texture count |
| `0x18` | `u32[count]` | texture-name hash table |

Each later texture header has an `Index` field selecting an entry in that table. The
headers are not physically stored in index order. This distinction caused the first
conversion attempt to fail: writing the right hashes in header order produced
recognizable textures on the wrong body parts.

## 4. Translate by header index

The confirmed SM2-to-SM1 table is:

| index | SM2 name | SM1-compatible name | observed region |
|---:|---:|---:|---|
| 0 | `E9587C6D` | `E9587C6D` | shared material |
| 1 | `197BC27A` | `197BC27A` | shared material |
| 2 | `2F5237EE` | `21AFE1A6` | body atlas piece |
| 3 | `B7F656CD` | `4E1E5E1A` | body atlas piece |
| 4 | `3622D2F9` | `3BC194AE` | body atlas piece |
| 5 | `51678BD1` | `1527743E` | body atlas piece |
| 6 | `51FD31B5` | `08BD6474` | body atlas piece |
| 7 | `DC38D248` | `DC38D248` | SM2-only detail/web-wing material |
| 8 | `F0B0001F` | `CEB60740` | body atlas piece |
| 9 | `841D8641` | `3ED5F30B` | webbed hand/limb region |
| 10 | `2CBE7299` | `1A501534` | mask/face region |
| 11 | `A56327E3` | `933EF22C` | blue torso region |
| 12 | `B03D3BD5` | `42985F7A` | red torso region |
| 13 | `E7B18C1F` | `7FFB7AAD` | solid red region |

Only the 56 bytes at `0x18..0x4F` change. Pixel data, CLUTs, dimensions, texture
headers, model data, and animation data remain untouched.

For a new suit, repeat the reasoning rather than copying this table blindly:

1. dump the candidate model's face-material hashes;
2. parse the candidate texture library's count and hash table;
3. decode every texture and record its header `Index`;
4. identify the target material for each decoded region;
5. build the translation in index order;
6. reject unexpected source tables instead of silently converting the wrong revision;
7. test a complete animation rotation and gameplay, looking for stable wrong regions as
   well as obvious noise.

## 5. Run the checked converter

From the repository root:

```text
python spiderman/tools/port_sm2_default_suit.py
```

Custom paths are supported:

```text
python spiderman/tools/port_sm2_default_suit.py \
  --sm2-wad <SM2-loose-wad-directory> \
  --output <override-directory>
```

The converter validates the magic, metadata pointer, count, and all fourteen original
hashes before writing anything. It copies `spidey.psx` unchanged and rewrites the hash
table in `sp_tex00.psx`.

Known output for the USA Rev 1 source used during discovery:

| output | bytes | SHA-256 |
|---|---:|---|
| `spidey.psx` | 275,840 | `e4864f82fae6086d54c96ccb6f28ff772ced625a0daafd850108e7325d189601` |
| `sp_tex00.psx` | 23,780 | `f43cc360ca00e720a5b299e226a21443657c1c2364a1d8af77566f5925283336` |

Point SM1 at the output directory with `SPIDEY_ASSET_DIR`. Overrides are matched by
filename; files not present there continue to come from SM1's `extracted/wad/`
directory. This same precedence rule is the reusable path for later costumes.

## 6. Reproduce the animated verification

The capture harness injects controller state only inside the recompiled game process.
It does not send host keyboard, mouse, or controller input.

```text
SPIDEY_ASSET_DIR=<override-directory>
SPIDEY_SCRIPT=title.bmr+120:start:12
SPIDEY_SHOTS=2400,2520,2640,2760,2880
SPIDEY_EXIT=3000
SpiderMan.exe <SM1-loose-directory>
```

`title.bmr` is the deterministic archive-load anchor; the numeric frame at which it
loads can move between runs. Inspect every requested frame. The successful run showed
the red-and-blue SM2 art, black web lines, white eyes, stable region assignment, the
SM2 underarm wings, and normal animated pose/rotation across all five captures.

The harness must ignore unresolved anchored steps (`Frame == -1`). Without that guard,
an anchored Start step also fires at boot because frame zero falls inside the old
`-1..Hold-2` interval.

## 7. Files that implement the path

- `spiderman/tools/port_sm2_default_suit.py`: validated binary conversion.
- `spiderman/patches/AssetOverrides.cs`: SM1 game-side target for the loose-WAD hook.
- `spiderman/patches/OverlayPatches.cs`: observes WAD lookup names and adjusts the
  allocation to the host file's sector-rounded size.
- `spiderman/tools/mkconfig.py`: attaches the `CdWadRead` pre-hook on regeneration.
- `tools/RecompOne/RecompOne.Runtime/Cdrom/Disc/LooseDiscImage.cs`: shared loose-file
  media implementation and one-time image importer for both games.
- `tools/RecompOne/RecompOne.Runtime/Assets/LooseWadOverrides.cs`: shared loose archive
  loader and optional override-directory precedence for both games.
- `spiderman/patches/Capture.cs`: process-local deterministic input and GPU captures.
