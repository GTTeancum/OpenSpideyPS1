# The Human Spider

`the-human-spider`, displayed as **The Human Spider**, packages Dat Mental
Gamer's default-suit reskin from https://gamebanana.com/mods/311084.
The author credits Treyarch and Activision for the original Spider-Man:
The Movie Game (2002) textures. Both the author and original texture credits
are included in the package README; the author also appears in suit comments.

## Rebuild

```powershell
python dreamcast/tools/build_human_spider_suit.py --archive PATH_TO_ARCHIVE --output NEW_SUIT_FOLDER
```

Use GameBanana file 629911, `the_human_spider_sm2000_v1.zip`, with MD5
`b786f352db523722b70d3b68ac2684b2`. The archive contains eight BMPs under
`spidey/`. Their Dreamcast payload offsets map to the same eight body materials
as the Steve Ditko reskin. Each saved PNG is compared against the source RGB
pixels and dimensions; no resizing or recoloring occurs.

The package uses `model: spiderman` and standard Spider-Man powers in both
games. This selects the bundled wingless SM1 body, preserving its geometry,
vertex ownership and animation bindings. No actor or executable edit is needed.
Every package includes the shared `instructions.txt`.

## Verify and stage

Run the native process-local scripted smoke harness in both games and inspect
each stance and movement capture individually. Verify the active mod ID and
eight registered textures in the logs. Keep the current native proofs under
`proof_render/human-spider/sm1` and `proof_render/human-spider/sm2`.

After review, copy the complete package to each staged game's
`mods/suits/the-human-spider`. Compare every staged file against its source and
preserve `selected-suit.txt`. This addition leaves 22 free slots in each game.

Validated on 2026-09-11: both native runs exited successfully. All six captures
were reviewed individually across SM1 stance/jump/crouch and SM2 stance/run/fall.
The eight PNGs passed source-pixel comparisons, and all 22 staged files matched
the package. This is an opening-level smoke check, not an all-level playthrough.
