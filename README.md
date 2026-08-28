# OpenSpideyPS1

Native recompilations of Neversoft's PlayStation Spider-Man games, built with
[RecompOne](https://github.com/BlackLabelHQ/RecompOne). The PlayStation executable is
translated to C# ahead of time and linked against a runtime that reimplements the console's
libraries, so the result is an ordinary .NET application rather than an emulator.

|  |  |
|:--:|:--:|
| [![Level 1 rooftop](docs/screenshots/level1-rooftop.png)](docs/screenshots/level1-rooftop.png) | [![Level 5 sewers](docs/screenshots/level5-sewers.png)](docs/screenshots/level5-sewers.png) |
| **Level 1** — rooftops over Manhattan, with the health bar, web cartridge count and Spidey compass | **Level 5** — the sewers, reached by booting straight into the act with `SPIDEY_LEVEL=l5a3` |
| [![Level 7 office](docs/screenshots/level7-office.png)](docs/screenshots/level7-office.png) | [![Symbiote costume](docs/screenshots/costume-symbiote.png)](docs/screenshots/costume-symbiote.png) |
| **Level 7** — hanging from a web line in an office interior | **Costumes** — the symbiote suit, selected with `SPIDEY_COSTUME=symbiote` |

---

## The two games are siloed, deliberately

This repository holds **more than one game**, and they do not share game code, configuration,
data or build output. Only the recompiler and its runtime are shared.

```
tools/RecompOne/     the recompiler and runtime -- SHARED
spiderman/           Spider-Man (USA, SLUS-00875)      -- self-contained
spiderman2/          Spider-Man 2: Enter Electro       -- self-contained, not yet started
```

Each game directory owns its own `config/`, `patches/`, `port/`, `tools/` and `extracted/`.
Nothing in one game's directory refers to the other's, and neither is buildable from the
other's outputs.

**If you are adding the second game, keep it that way.** Put everything game-specific under
`spiderman2/`. Anything that would need to be shared belongs in `tools/RecompOne/`, and a
change there must be game-agnostic — the whole point of the split is that a fix for one game
cannot quietly break the other. Two games' worth of hand-written patches in one directory
becomes unpickable very quickly.

---

## What works

Spider-Man (USA) boots, plays its logos and intro movie, reaches every menu and plays.

- **Frame pacing.** The game never calls `VSync` during gameplay: it submits an ordering
  table and spins on `DrawSync` until the GPU has finished, and that spin *is* the frame. The
  runtime's `DrawSync` answered "idle" always, so the game ran at 131 fps. It is now paced by
  a GPU busy model and draws at 30.
- **Levels.** 21 level prefixes were booted directly and every one reached gameplay and held
  7000 frames — all eight story levels plus the bonus set.
- **Memory card.** Saves and loads. A save written through the menus appears on the card and
  is listed back by name with its level and difficulty.
- **Costumes, cheats, level select** are reachable, and settable directly from the command
  line for testing.
- **Audio.** SPU voices and XA streaming, both measured. The intro movie decodes at 14.84
  frames a second, which is the 15 fps an STR is.

Not verified: finishing a level. A timed button script cannot play a 3D action level to its
end, and the act-advance trigger gates on trigger state rather than being a call that can
simply be invoked. See [spiderman/TO_DO.md](spiderman/TO_DO.md).

---

## Building

You need the retail disc. **No game data is included here, and none should ever be committed** —
the executable, the archives, the overlays and the movies are all read from your own copy.

Needs .NET 10 and Python 3 with `numpy` and `PIL`. Put the disc at the repository root, then:

```bash
cd spiderman
python tools/disc.py extract extracted
python tools/cdwad.py extract extracted/wad
python tools/overlays.py build config/overlays
python tools/genmaps.py
python tools/build.py
```

`tools/build.py` runs the whole loop and stops when the unmapped-call count stops falling. It
converges at 3,314 functions across 31 modules.

```bash
./spiderman/port/bin/Release/net10.0/SpiderMan.exe
```

## Switches

```
SPIDEY_HZ=30               the rate the game runs at
SPIDEY_LEVEL=l5a3          boot straight into a level (47 prefixes, l1a1..l9a4)
SPIDEY_COSTUME=symbiote    spiderman 2099 symbiote captain unlimited bagman
                           scarlet benreilly quickchange peterparker
SPIDEY_CHEATS=all          the game's own cheats: everything, levelselect, invuln, ...
SPIDEY_SHOTS=1050,1500     write a PNG on these frames
SPIDEY_SNAP=crash          dump the game's RAM on the crash, or on named frames
```

The per-game notes are the interesting reading: [spiderman/README.md](spiderman/README.md) for
how the archive, the relocatable overlays and the SDK symbol recovery work, and
[spiderman/TO_DO.md](spiderman/TO_DO.md) for what each bug turned out to be — including the
several that turned out *not* to be the cause, recorded with their evidence.

## Licence

The code here is the port and its tooling. Spider-Man and its assets are the property of their
respective rights holders; nothing from the disc is distributed with it.
