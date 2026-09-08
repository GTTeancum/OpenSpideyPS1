# Magenta Man for Spider-Man 2

Copy this folder into `mods/suits` beside `SpiderMan2.exe`. Restart the game and
select **SPECIAL → COSTUMES → MAGENTA MAN**. Reskins are always unlocked; SM2
supports up to 12 installed reskins alongside its 19 original costumes.

## Choose appearance and powers independently

`model` chooses the body and its matching texture layout. `abilities.profile`
chooses one original SM2 costume as the **powers donor**. Changing the powers
profile keeps your painted appearance, model, and texture files.

For example, Magenta Man can use Prodigy's double jump, enhanced strength and
enhanced web swinging while keeping the SM2 Spider-Man body and web wings:

```json
"model": "sm2-spiderman",
"abilities": {
  "profile": "prodigy"
}
```

Replace those fields in `suit.json`; the snippet is not a complete manifest.
Choose one profile at a time. Profiles inherit the original game's behavior;
you cannot combine donors, invent powers, or select an enemy's moveset with JSON.
The original donor costume does not need to be unlocked to use it for a reskin.

## Donor powersets

Use the exact identifier in the left column. All 19 native SM2 profiles are
available, including the SM2-specific double-jump and enhanced-swing donors.

| `abilities.profile` | Costume powers |
| --- | --- |
| `spiderman` | Standard Spider-Man abilities |
| `spider-phoenix` | Invulnerability, enhanced strength, enhanced web swing |
| `prodigy` | Double jump, enhanced strength, enhanced web swing |
| `dusk` | Stealth |
| `insulated` | Enhanced strength and electrical resistance |
| `alex-ross-red` | Double jump |
| `alex-ross-white` | Enhanced web swing |
| `venom-earth-x` | Enhanced strength and unlimited webbing |
| `negative-zone` | No additional costume powers |
| `symbiote` | Unlimited webbing |
| `2099` | Enhanced strength |
| `captain-universe` | Invulnerability, enhanced strength, unlimited webbing |
| `unlimited` | Stealth mode |
| `bagman` | No Spidey belt |
| `scarlet` | No additional costume powers |
| `ben-reilly` | No additional costume powers |
| `quick-change` | No Spidey belt |
| `peter-parker` | No Spidey belt |
| `battle-damaged` | No additional costume powers |

For double jump alone, choose `alex-ross-red`. For enhanced swinging alone,
choose `alex-ross-white`. For unlimited webbing alone, choose `symbiote`.
`unlimited` means the Unlimited costume's stealth profile, **not unlimited webbing**.
Insulated's menu lists enhanced strength; its native costume identity also enables
the game's electrical-resistance behavior.

**GAME POWERS** uses the original costume wording automatically. Keep `name` to
18 characters. Comments share the panel with the donor's power list; if a donor
with more powers makes the mod fail validation, shorten `comments`.

## Paint or migrate a suit

The six built-in model bases are `spiderman` (SM1), `scarlet-spider`, `symbiote`,
`quick-change`, `peter-parker`, and `sm2-spiderman` (SM2, including web wings).
They are appearance choices, separate from the donor powerset.

This sample uses `sm2-spiderman` and fourteen matching materials. Paint the PNGs
in `textures`; preserve proportions and transparent regions. Larger PNGs up to
4096 pixels per side are accepted within the decoded-memory budget. Upscaling
alone does not add detail. `TEMPLATE` contains painting guides and is ignored by
the game.

An existing SM1 reskin can run in SM2 with its original model and matching PNGs.
Keep or explicitly add `"model": "spiderman"` for an SM1 default-body reskin;
do not change it to `sm2-spiderman` without also supplying that body's texture
layout. In SM2, an omitted `model` defaults to the SM2 body. Keep an accepted
profile or choose one from the table above; shared names retain their SM2 donor
behavior. Give each installed mod a unique `id` and folder name. Keep the existing
SM2 Magenta Man when adding the SM1 sample under a different ID.

To share a suit, include `suit.json`, the referenced PNGs, and these instructions.
No external model, executable code, or donor costume files are needed.
