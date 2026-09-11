# Unlimited roster: Miles Morales through Buzz

The batch converter packages these thirteen Gameloft models as custom native
actors for both games. All use standard Spider-Man powers. Each suit includes
Gameloft credit, its original diffuse RGB, closed fists, and shared installation
instructions. The display names fit without abbreviating them; `sp-dr` is the
filesystem ID for **SP//DR**.

## Reproduce

Use the previously extracted Unlimited collection, Python with Pillow, Blender
4.5, and the existing donor assets required by `build_unlimited_actor.py`:

```powershell
python dreamcast/tools/build_unlimited_roster.py --collection C:/Programming/SMU-Costumes --output C:/Models/UnlimitedRoster --blender "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe"
```

Output must be a fresh directory outside the source collection. Add
`--only miles-morales` (or another ID in the table) to build one costume.
The collection catalogue is read as UTF-8 with BOM support. Original FBX and
texture hashes are recorded in `source-provenance.json`; prepared input hashes,
actor hash, attachment checks and part budgets are in `native-report.json`.
Copy only each verified `mods/suits/<id>` directory into the game's suits folder.
The builder does not stage automatically: structural success still requires
native visual review.

| Display name | Mod ID | Collection source | Preparation |
| --- | --- | --- | --- |
| Miles Morales | `miles-morales` | `milesmorales` | Original topology |
| The Amazing Spider | `the-amazing-spider` | `amazing_spider` | Head .45; torso .55; cape adjustment |
| 1602 | `1602` | `1602` | Head .30; minimum component size 5 |
| MCU Homemade | `mcu-homemade` | `homemade` | Head .30; minimum component size 5 |
| Ends of the Earth | `ends-of-the-earth` | `endofearth` | Original topology |
| Bullet Points | `bullet-points` | `bulletpoints` | Original topology |
| All-New | `all-new` | `spiderman_newdesign` | Original topology |
| Secret-War | `secret-war` | `secretwar` | Original topology |
| Ghost Spider | `ghost-spider` | `ghost` | Head .45 |
| Prodigy | `prodigy` | `prodigy` | Head .45 |
| SP//DR | `sp-dr` | `spdr` | Head .40; torso .35; minimum component size 5 |
| Hornet | `hornet` | `hornet` | Head .45 |
| Buzz | `buzz` | `buzz` | Head .45; torso .40; minimum component size 5 |

All-New is the user-confirmed [All-New Spider-Man](https://spiderman-unlimited-mobile-game.fandom.com/wiki/All-New_Spider-Man), the All-New, All-Different / Spider-Armor MK IV design. The
collection's `newarmor` is a different costume and is not used here.

## Geometry and capes

The source models use Gameloft's Clown001 skeletal rig. The established converter
fits that rig to the native hierarchy, retains shared attachment vertices and
collapses animation to dominant native bones. It does not import new animations
or add runtime skinning. The Dreamcast conversion pipeline is unaffected.

Some heads, goggles and armor assemblies exceed the native limit of 256 vertices
per part, including referenced vertices. `prepare_unlimited_roster.py` identifies
connected components by dominant bone names and reduces only the selected head
or torso components. UVs and bone groups survive Blender decimation. Small head
assemblies on 1602 and Homemade require the lower component-size threshold.
These are recipes for this source collection, not a universal quality guarantee.

The Amazing Spider's cape follows the existing spine joints. Arm influence on
its two shells is reassigned to Spine3 and the shells move .025 source units
behind the shoulders. Each shell expands .004 along its normals to separate its
inside and outside. The cape shells retain their topology. There is no cloth
simulation or independent cape animation. The extracted Prodigy model has no cape. Native smoke checks must include a side view and a crouch before approval.

The Amazing Spider also places the inner cape and some cuffs in a repeated UV
tile (U between 1.64 and 2.0). Native page addressing sampled the wrong texture
area. The preparation translates each repeated polygon back into the base tile
as a unit, preserving its texture placement without altering the image. The
other twelve fitted models have no UV coordinates outside [0, 1].

## Verification and storage

Review each generated capture individually. The smoke routes cover SM1's opening
rooftop stance, jump and crouch, and SM2's opening rooftop side stance, run and fall,
using the process-local capture harness at 4x scale with widescreen enabled.
They do not establish full-level or full-animation coverage. Successful native
exit, active mod ID and byte-for-byte staging comparisons supplement visual review.

Current work and native proofs are under `proof_render/unlimited-roster/`.
Keep compact final captures, source/native reports and the final mod folders.
Remove failed candidates, copied FBX/TGA sources, donor dumps and duplicate builds
after verification; the extracted source collection remains outside the repo.

All thirteen models passed the native part budgets and both game smoke routes;
all 78 final captures were reviewed individually. Staged files were compared by
SHA-256 against the reviewed packages. The [manifest](unlimited-roster-manifest.json)
records source hashes, preparation arguments, final actor hashes and geometry budgets.
SM1 now has 34 mod suits plus 20 stock suits; SM2 has 35 mod suits plus 19 stock
suits. Both have six free slots out of sixty.

The cape correction normalizes 972 UV coordinate entries. Numeric comparison
confirmed that this UV correction changes neither geometry nor bone assignments.
The other twelve packages reproduced byte-for-byte with the batch wrapper.

Automatic approval review blocked temporary-build deletion with a generic
"blocked by policy" response. Cleanup remains pending; generated assets and
proofs are ignored by Git and are not part of the source commit.
