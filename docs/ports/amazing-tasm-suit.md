# Amazing (TASM)

`amazing-tasm` packages only the red-and-blue suit from Dat Mental Gamer's
https://gamebanana.com/mods/380766. Credits include the author and Beenox and
Neversoft, as listed on the source page. The symbiote version is excluded.

```powershell
python dreamcast/tools/build_amazing_tasm_suit.py --archive PATH_TO_ARCHIVE --output NEW_SUIT_FOLDER
```

Use GameBanana file 806768, `sm2000_tasm2012_redsuit_bb1fb.zip`, MD5
`1ad64ed7645963dacbb303f4d9b0fe9d`. The eight standard `spidey/*.bmp` texture
offsets map to the bundled SM1 body's materials. Use `0005DDAC.bmp`; the
additional `0005DDACwithbelt.bmp` is an optional variant, not the default.
The builder verifies all output RGB pixels and dimensions against the source.

The suit uses `model: spiderman` and standard Spider-Man powers in both games.
Geometry, rigid vertex ownership and animation bindings remain inherited from
the bundled wingless SM1 actor. No executable changes are required. Every
package contains the shared instructions and author credits.

Before staging, run the game-native process-local smoke scripts and inspect
all three captures per game individually. Check active suit registration and
successful exit in each log. Keep current proofs under
`proof_render/amazing-tasm/sm1` and `proof_render/amazing-tasm/sm2`.
Copy the complete package into each staged game's `mods/suits/amazing-tasm`,
compare every file and preserve the selected-suit file. This adds one costume
per game, leaving 21 free slots in each.

Validated on 2026-09-11: both native runs exited successfully, and all six
captures were individually reviewed (SM1 stance/jump/crouch; SM2 stance/run/fall).
All eight textures passed source RGB comparisons. All 22 staged files matched
the source package. Coverage is an opening-level smoke check in each game.
