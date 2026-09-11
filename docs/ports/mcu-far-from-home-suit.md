# MCU Far From Home

`mcu-far-from-home`, displayed as **MCU Far From Home**, packages the eight
textures from https://gamebanana.com/mods/249041. The page credits Spider-Wuss
as modeler: https://gamebanana.com/members/1767938. That credit is retained in
the suit manifest and README. The supplied archive contains no model geometry.

```powershell
python dreamcast/tools/build_mcu_far_from_home_suit.py --archive PATH_TO_RAR --output NEW_SUIT_FOLDER
```

Use GameBanana file 506819, `far_from_home.rar`, MD5
`0ae61beaf26411a4115c0097b0c85283`. The builder uses 7-Zip to read only the eight
known `spidey/*.bmp` members to memory; use `--sevenzip` to override its path.
The filenames use the standard SM1 body texture offsets. Each PNG is compared
against its decoded source RGB pixels and dimensions, without resizing,
recoloring or flipping.

The package uses the bundled wingless SM1 body and standard Spider-Man powers
in both games. Geometry, rigid vertex assignments and animation bindings are
inherited unchanged. The shared `instructions.txt` is included.

Inspect each of the three native smoke captures per game before staging under
`mods/suits/mcu-far-from-home`. Verify successful exit and the active mod ID in
both logs. Compare every staged file and preserve selected-suit files. Current
proofs belong under `proof_render/mcu-far-from-home/sm1` and `sm2`.
Installation leaves 19 free slots per game.

Validated on 2026-09-11: both native runs exited successfully. All six captures
were individually reviewed across SM1 stance/jump/crouch and SM2 stance/run/fall.
All eight textures passed source-pixel comparisons, and all 22 staged files
matched the package. Coverage is one opening level in each game.
