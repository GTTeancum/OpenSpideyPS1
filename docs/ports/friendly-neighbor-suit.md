# Friendly Neighbor

`friendly-neighbor`, displayed as **Friendly Neighbor**, uses the default
Classic variant of WizByte's Spider-Man (John Romita Sr.) pack:
https://gamebanana.com/mods/665138. Author:
https://gamebanana.com/members/5278375. Credit is included in the manifest and
README. Bonus masks, alternate palettes, the Symbiote and global HUD are excluded.

```powershell
python dreamcast/tools/build_friendly_neighbor_suit.py --archive PATH_TO_ARCHIVE --output NEW_SUIT_FOLDER
```

Use GameBanana file 1663238, `spider-man_john_romita_sr_.zip`, MD5
`0e2f2221d50382a0933cba7a4d8b834d`. The eight `Classic/spidey` body PNGs use
emulator texture names and the opposite vertical orientation to our decoded
native donor textures. Compare their atlas layouts against
`dreamcast/decoded/textures/SPIDEY`: face, chest/back emblems, finger patches,
sole and red/blue boundaries establish the mapping and vertical flip.

| Source PNG stem | Native material | Region |
| --- | --- | --- |
| aef9fccb | 9D39C02B | Legs |
| b01f944a | 29AF154F | Chest |
| e1e08580 | 154B7D71 | Upper arms |
| 29c42eb7 | 42991273 | Head |
| 849133f4 | D7669388 | Boots |
| 4a842b4e | D8425644 | Back |
| 1ed2b960 | F82D1471 | Hands |
| f8030f8d | FBC5A5A0 | Feet |

Preserve all eight images at 1024x1024. Convert palette images to RGB and flip
vertically; compare output pixels against that exact transform. Do not resize
or recolor. The 32 MiB decoded RGBA total fits the host texture budget.
Use the bundled wingless SM1 body and standard Spider-Man powers in both games;
no geometry, ownership, animation or executable edits are required. Include the
shared `instructions.txt` in each package.

Verify native stance and movement captures individually in both games before
staging. Preserve selection files and compare every staged file to the source.
Keep current native proofs under `proof_render/friendly-neighbor/sm1` and `sm2`.
Installation leaves 20 free slots in each game.

Validated on 2026-09-11: both native smoke runs exited successfully. All six
captures were individually reviewed across stance, jump/crouch, run and fall.
All eight textures passed transformed-pixel comparisons; all 22 staged files
matched the package. These checks cover one opening level in each game.
Temporary extracted inspection textures were removed after review.
