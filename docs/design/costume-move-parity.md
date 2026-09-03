# Costume and move parity

## Scope

SM1 exposes the imported SM2 costumes as independent entries while copying only the
paired SM1 donor abilities. SM1's original costumes stay wingless; imported SM2
costumes retain their authored underarm-wing state. Ported content ships with the
recompilation and never requires the other retail disc.

## SM1 costume roster

SM1 now has twenty independent entries. Every row owns its own model, saved selection,
unlock bit, and copied ability word; no imported row is an alias of an original row.

| Slot | Costume | Model | Ability copied from | Unlock |
|---:|---|---|---|---|
| 0 | Spider-Man | `spidey.psx` | Spider-Man | From start |
| 1 | Spider-Man 2099 | `sp2099.psx` | Spider-Man 2099 | Retail rule |
| 2 | Symbiote Spider-Man | `spsymbi.psx` | Symbiote Spider-Man | Retail rule |
| 3 | Captain Universe | `spuniv.psx` | Captain Universe | Retail rule |
| 4 | Spidey Unlimited | `spunlim.psx` | Spidey Unlimited | Retail rule |
| 5 | Amazing Bag Man | `spbagman.psx` | Amazing Bag Man | Retail rule |
| 6 | Scarlet Spidey | `spscar.psx` | Scarlet Spidey | Retail rule |
| 7 | Ben Reilly | `spreilly.psx` | Ben Reilly | Retail rule |
| 8 | Quick Change Spidey | `spquick.psx` | Quick Change Spidey | Retail rule |
| 9 | Peter Parker | `sppark.psx` | Peter Parker | Retail rule |
| 10 | Spider-Phoenix | `sp2phoenix.psx` | Captain Universe | With slot 3 |
| 11 | Prodigy | `sp2prodigy.psx` | Amazing Bag Man | With slot 5 |
| 12 | Dusk | `sp2dusk.psx` | Spidey Unlimited | With slot 4 |
| 13 | Insulated Spider-Man | `sp2insulated.psx` | Spider-Man 2099 | With slot 1 |
| 14 | Alex Ross Spider-Man | `sp2rossred.psx` | Scarlet Spidey | With slot 6 |
| 15 | Alex Ross White Spider-Man | `sp2rosswhite.psx` | Ben Reilly | With slot 7 |
| 16 | Venom Earth-X | `sp2venomx.psx` | Symbiote Spider-Man | With slot 2 |
| 17 | Negative Zone Spider-Man | `sp2negative.psx` | Quick Change Spidey | With slot 8 |
| 18 | Battle-Damaged Spider-Man | `sp2battle.psx` | Spider-Man | With Peter Parker |
| 19 | Spider-Man (Web Wings) | `sp2default.psx` | Spider-Man | From start |

Peter Parker still unlocks the ninth SM2-exclusive suit, Battle-Damaged Spider-Man,
but Peter's ability word is not copied by any import. Default SM1 Spider-Man is the one
ability set copied twice, producing the deliberate trio of SM1 default, Battle-Damaged,
and default SM2 Spider-Man with web wings.

## Runtime and persistence design

The retail selected byte remains a safe 0–9 proxy because several unexpanded shell
resource tables index it directly. The real 0–19 selection and a signature occupy the
three unused padding bytes beside that saved byte, leaving every retail unlock word
intact. Old saves are backfilled in place: existing retail unlock bits are preserved,
each unlocked original mirrors into its paired import, and slots 0 and 19 are always
available. Saves from the initial high-bit implementation migrate once into the padding
field. The retail `everything` cheat preserves the extended selection while unlocking
all twenty rows.

SM1's retail viewer only overlays PS1 texture pages onto one actor. The port replaces
that transition with a full unload/reload of the same `spidey` model-cache slot, so the
active viewer actor keeps a stable slot reference while its complete Dreamcast model,
skeleton, and baked texture pages change. The list widget uses its dormant scroll
window and keeps six rows above the rotate/zoom legend; imported rows have authored names, power summaries,
and paired-unlock text in the right-hand panel.

SM2 imports are baked after SM2's loader resolves their VRAM pages. Texture record 7
keeps the authored SM2 result: Spider-Phoenix, Dusk, Insulated, both Alex Ross suits,
Negative Zone, and Battle-Damaged are winged; Prodigy and Venom Earth-X resolve to
transparent wing pages and remain wingless. The separately selectable slot 19 is the
default SM2 Spider-Man with visible web wings.

The retail texture registry at `0x80099A18` has room for only seventeen eight-byte
records before the animation-event pointer table at `0x80099AA0`. A Dreamcast actor
can register more materials than that by itself, so retaining the retail allocation
corrupted animation pointers during player construction. The recompilation relocates
the registry to `0x80780000..0x807C0000`, raises its capacity to 32,768 records, and
checks the real port allocation at each append. No material, texture page, or model
detail is removed to satisfy the old PS1 limit.

## Validation

`dreamcast/tools/validate_sm1_costume_viewer_runtime.py` drives the real COSTUME VIEWER
inside exactly one game process. It selects all twenty rows in order, requires every
complete actor to reload through one stable cache slot, and writes one native 4× 16-bpp
capture per entry plus asset and frame hashes. `SPIDEY_COSTUME_SELF_TEST=1` separately
executes all nine save migrations, all twenty persistent selection round trips, all
twenty independent ability words, the no-Peter-donor rule, and the sole default-ability
trio against live `PSMemory`.

`dreamcast/tools/validate_sm1_costume_models_runtime.py --slots 10,11,12,13,14,15,16,17,18,19
--proof-mode gameplay` additionally constructs every import as the live L1A1 player and
requires its post-constructor ability configuration before accepting any capture.
`dreamcast/tools/validate_sm1_costume_state_runtime.py` records the live-memory save,
unlock, and ability assertions as a standalone proof report.
