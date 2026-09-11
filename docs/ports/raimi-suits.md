# Raimi suits

Two texture-only suits from Dat Mental Gamer's **Spider-Man 3 Wii Costumes**:

- `raimi-red-blue`: **Raimi (red & blue)**, wingless SM1 Dreamcast Spider-Man
  body with standard Spider-Man powers.
- `raimi-symbiote`: **Raimi (symbiote)**, Dreamcast Symbiote body with unlimited
  webbing from the native Symbiote powers profile.

Source: https://gamebanana.com/mods/296326

Author: https://gamebanana.com/members/1614404

The source page also credits Beenox, Vicarious Visions and Treyarch for the
Spider-Man 3 Wii textures. Both packages retain these credits in their README,
and the author credit appears in each suit's in-game comments.

## Build

Download GameBanana file 593969, `spider_man_3_suits_from_wii_61699.zip`.
The builder requires MD5 `e5ddf243f8501698b72eb66824290287`.

```powershell
python dreamcast/tools/build_raimi_suits.py --archive PATH_TO_ARCHIVE --output NEW_SUIT_ROOT
```

The output contains two complete folders ready for `mods/suits` in either game.
Each includes `suit.json`, eight PNGs, credits and the shared `instructions.txt`.
The symbiote package also includes `actor.psx`, copied byte-for-byte from the
bundled SM1 `spsymbi.psx`. SM2's built-in `symbiote` model option otherwise uses
its shared actor, whose material hashes do not match these textures. An initial
SM2 capture exposed that mismatch despite successful texture registration.
The builder resolves the author's BMP offsets against the converted donor
material table, checks that all eight source textures are mapped, and compares
decoded RGB pixels after saving. It does not resize, recolor or regenerate any
texture. Geometry, rigid ownership and animation bindings are inherited from the
existing bundled donors; no geometry edits or executable modification is needed.

## Verification and staging

Use the game-native scripted capture path in private runtimes, selecting each
mod by ID. Inspect stance, crouch/jump and movement views in both games. Verify
material placement, body silhouette, limb joins and absence of unintended wings.
Confirm each log registers eight PNGs and activates the expected mod/model.

Stage only after reviewing the captures. Copy each package into the matching
folder under both staged games' `mods/suits`, verify file hashes and preserve
the user's selection. Keep the current direct PNG proofs under
`proof_render/raimi/<suit-id>-sm1` and `proof_render/raimi/<suit-id>-sm2`.

Validated on 2026-09-11: all sixteen PNGs match the original BMP RGB pixels;
all twelve final native captures were individually reviewed across both suits
and both games. The final four smoke runs exited successfully. These cover the
opening rooftop and movement poses, not an all-level playthrough. Both staged
games have 23 free slots after installation. Superseded captures were removed.
