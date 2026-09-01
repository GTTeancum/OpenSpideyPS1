# Spider-Man Dreamcast reference extraction

This directory contains the reproducible extraction notes for the US Dreamcast release
added as a reference for the two PS1 recompilations. Raw disc content and generated output
are intentionally ignored by Git:

- `extracted/` is the complete mounted GD-ROM filesystem.
- `decoded/` contains converted images, models, scripts, audio and movies.

The source set is the five-track `Spider-Man v1.000 (2001)(Activision)(US)[!].gdi` image.
Its checksums are:

| file | bytes | SHA-256 |
|---|---:|---|
| `Spider-Man v1.000 (2001)(Activision)(US)[!].gdi` | 149 | `23935700F5C0BD0593A7F37C0A1D422DB1CC510752133A927D4598981B8A310C` |
| `track01.bin` | 1,340,640 | `9C43FAC96BCBE308EBF541ED27A25C568942E5D9E9DA8878B47626C3FBDBE25B` |
| `track02.raw` | 1,166,592 | `A7BA4AA5DDC7DAF858B6D10848BC700CFD35416D6A73A90DDCC84F62665C1813` |
| `track03.bin` | 267,728,160 | `D9B127A41EE77A09F90484DA651566878513C78B35E22985F9F7B599BE20E752` |
| `track04.raw` | 990,192 | `807586D4EDCB7CB644045CC66D0511CD809E1F9DEC660D531206B53ED8EFD794` |
| `track05.bin` | 916,336,848 | `2230D94D438DAC19E656DE1AF94A29CF9AC2935013365C8513BF26C9A6129FA8` |

## Extraction result

The complete filesystem is 844 files (799,717,104 bytes). This includes the two CDDA
tracks as `extracted/cdda/track02.wav` and `track04.wav`. A recursive archive scan found
no WAD/PRE-style nested archives; unlike the PS1 release, the Dreamcast data track is
already laid out as ordinary files.

Decoded output:

| output | result | verification |
|---|---:|---|
| `decoded/textures/` | 9,097 PNGs from all 297 `.PSX` containers | all 9,097 reopened successfully |
| `decoded/bitmaps-all/` | 115 BMP + 8 RLE images | 123/123 converted |
| `decoded/pvr/` | one standalone PVR image | 1/1 converted |
| `decoded/meshes/` | 207 glTF binary models, 370,105 triangles | every GLB rendered successfully |
| `decoded/triggers/` | 68 JSON files, 12,437 trigger nodes | all 68 parsed and reopened |
| `decoded/audio/` | 2,291 unique WAV samples | every WAV has a valid RIFF/WAVE header |
| `decoded/fmv/` | 27 H.264/AAC MP4 files | every file fully decoded with zero errors |

Ninety `.PSX` files contain textures, level-light data or other non-mesh payloads, so the
mesh converter correctly reports no mesh data for those files. Audio conversion resolves
179 of 180 source banks. `LAA1.SFX` is the lone exception: the disc contains no matching
`LAA1.KAT` or `LAA1.VAB`, and several sibling banks score equally as possible aliases, so
choosing one would invent data. The original file remains intact in `extracted/`.

## Movies

All 27 Sofdec streams are usable standard MP4s after conversion. The 21 story movies are
320x192 at approximately 30 fps; the six logo/legal streams are 160x128 or 320x240. Every
movie contains stereo audio. Total duration is 1,248.026 seconds (20:48).

The movie inventory with exact codec, duration, frame-rate and audio metadata is at
`decoded/fmv/inventory.csv`. A midpoint frame from every story movie is collected in
[`../docs/texture-dumps/dreamcast-fmv-contact-sheet.png`](../docs/texture-dumps/dreamcast-fmv-contact-sheet.png).

## Default Spider-Man model

The Dreamcast model is a genuine high-detail replacement, not merely a filtered PS1
texture set:

| release | objects | vertices | faces | normals | attachments | native texture texels |
|---|---:|---:|---:|---:|---:|---:|
| Spider-Man PS1 | 18 | 368 | 372 | 740 | 81 | 24,576 |
| Enter Electro PS1 | 18 | 361 | 369 | 730 | 77 | 28,672 |
| Spider-Man Dreamcast | 18 | 1,161 | 1,980 | 3,141 | 124 | 299,008 |

Dreamcast uses eight 64x64-to-256x256 textures with a different UV atlas, totaling 12.2x
the texels of Spider-Man PS1. Enter Electro PS1 does not reuse the denser Dreamcast mesh,
but its black-webbed texture treatment is visibly much closer to the Dreamcast redesign
than to Spider-Man PS1's mostly unlined red surfaces. That supports an art-lineage theory,
not a literal model copy: the PS1 sequel retained the PS1 polygon budget and its own
13/14-material layout.

The decoded Dreamcast GLB is `decoded/meshes/SPIDEY.glb`; five inspection renders are in
`decoded/model-renders/`. The native textures and a front render are also collected in
[`../docs/texture-dumps/spidey-default/`](../docs/texture-dumps/spidey-default/).

## PS1 SM1 character ports

The repeatable v6-to-v4 actor conversion, donor-preserving Enter Electro wing transfer
with Dreamcast armpit seam fitting,
all-character census, loose-file runtime route, and visible L1A1 parity proof are
documented in
[`../docs/ports/dreamcast-characters-in-ps1-sm1.md`](../docs/ports/dreamcast-characters-in-ps1-sm1.md).

The batch currently contains 65 actor models: 51 converted Dreamcast v6 actors
and 14 actor/entity components that already ship in PS1 v3/v4 form. Default
Spider-Man is wing-capable but uses a transparent magenta wing texture; the proof
variant substitutes the retail SM2 black/white `DC38D248` artwork and has been
captured at 2560x1920 inside L1A1. Independent validation passes 65 GLBs, 847
decoded textures across the actors and costume companions, 325 object-review
renders, and an 18-level runtime matrix that
covers all 34 story-loaded actors. All ten playable models also pass the 4x main-menu
proof sequentially, and the 26 selectable Character Viewer entries have a separate
one-process 4x sweep. Those routes naturally cover 52 of the 65 batch entries;
the two otherwise unreachable SM1 actors (`HOSTAGEF` and `SYMBIOTE`) have recorded
viewer-slot probes, while `CLAW` is byte-identical across PS1 and Dreamcast. The ten
other non-routed entries are Dreamcast-only supplemental components and are not
invented as SM1 aliases. Only actor/model resources are overridden; environments
remain the PS1 originals. That viewer route caught and now guards SM1-native skeleton/
animation adaptations for Jameson, Scorpion, and viewer-only Peter Parker while
retaining their Dreamcast meshes and textures. Jameson's indexed-RGB face mode
is translated to SM1's neutral literal-lighting path, and Scorpion's procedural
tube receives SM1's required material-18 alias to the original Dreamcast skin.
A separate converter-independent texture-pack audit passes 51
converted actors, 618 mappings, 589 unique runtime keys, and 589 host PNGs whose
dimensions and RGBA pixels exactly match their Dreamcast sources. SM2 Default,
Prodigy, Dusk, and Ricochet also retain audited static T-pose mappings onto the DC
body with exact source wing UV/texture parity. The native runtime pack now covers
all nineteen Spider-Man slots with the Dreamcast body, SM2 hierarchy/animations,
all alternate hand meshes, authored wing seams, and byte-exact retail costume
libraries. Bag-Man and Peter Parker use their dedicated Dreamcast actors and
original-resolution host texture packs; ordinary interactive selection swaps the
complete processed actor binding for those topology-changing slots and restores
the shared actor for every other slot. The live-menu validator rejects FMV frames,
captures five 1280x960 `charlite.dat`-anchored frames per slot with only one game
process at a time, and has 19/19 evidence sets plus 95/95 manually reviewed frames.
Default retains a separate 8x menu/gameplay proof with exact-pixel wing close-ups.
A separate 30-actor SM2 structural audit identifies ten same-name DC actors and
the structural `HOSTAGE2` to `HOSTAGE` alias, but the current SM2 upgrade policy
selects Spider-Man only. All 29 NPC/enemy actors are explicit original-SM2
model-and-texture fallbacks, whether or not a same-name DC file exists. The GLBs
are audit artifacts only; both games continue to use `.psx` runtime assets.

The complete automated build/capture/validation entry point is
`tools/run_port_pipeline.py`; its aggregate result is written to
`converted/port-pipeline-report.json`.
The generated models remain private/ignored game data; the committed
`manifests/winged-spidey-lock.json` and `tools/verify_wing_build_lock.py` secure
the exact default-Spidey reconstruction by input/output hashes.

## Reproduction

The conversion used [Neversoft Multitool](https://github.com/slfx77/neversoft-multitool)
at commit `60d0b819436937ac29e04a6346cea634c0f73d69` and FFmpeg:

```text
NeversoftMultitool archive "Spider-Man v1.000 (2001)(Activision)(US)[!].gdi" -o dreamcast/extracted
NeversoftMultitool unpack dreamcast/extracted
NeversoftMultitool psx dreamcast/extracted -o dreamcast/decoded/textures --subdirs --no-dds
NeversoftMultitool psx-mesh dreamcast/extracted -o dreamcast/decoded/meshes --format glb
NeversoftMultitool rle <BMP-and-RLE-inputs> -o dreamcast/decoded/bitmaps-all
NeversoftMultitool pvr dreamcast/extracted -o dreamcast/decoded/pvr
NeversoftMultitool trg dreamcast/extracted -o dreamcast/decoded/triggers
NeversoftMultitool audio dreamcast/extracted -o dreamcast/decoded/audio
NeversoftMultitool sfd dreamcast/extracted -o dreamcast/decoded/fmv
```
