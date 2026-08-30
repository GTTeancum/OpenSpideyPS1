# Spider-Man 2 port — open work

Ordered by what blocks the most. Ruling things out is most of the value, so the things
that turned out *not* to be a fault are recorded with their evidence.

**Where it stands.** The game boots, plays both intro movies, reaches the title and the
menus, and a new game reaches episode 1 mission 0 and holds live gameplay. One
scripted run, from a cold boot, reproduces this reliably.

What is verified, and how:

| | evidence |
|---|---|
| Boot, Activision and Vicarious Visions logos | captured frames of each, rendering correctly |
| Intro FMV | captured 320x240 MDEC frames decode correctly (Black Cat, Shocker) |
| Title, main menu, difficulty select, pause menu, GAME OVER | captured frames of each |
| Attract-mode demo | renders 3D gameplay with the DEMO overlay |
| Level cinematic and Daily Bugle headline | both play; the headline reaches its last frame and sets the game's own "done" flag |
| **First level (E1M0)** | reached through the real menu path in 3 of 3 runs, geometry loading at frames 3712/3724/3746 |
| **Live gameplay** | 10,000+ frames in E1M0 with **no frozen stretch**: 103 distinct captures after the level load |
| **HUD** | health bar, web cartridge count (`x 07`), Spidey portrait, spider-sense compass, pickups with shadows |
| **Frame rate** | `DrawOTag` 28.5/s, `PutDispEnv` 28.5/s, presents 29.5/s against the 30 fps target; 33.6 ms per frame |
| **Pacing model** | `VSync(0)` and `VSync(-1)` both **zero** during gameplay — like Spider-Man, this game never waits on a vblank and paces on `DrawSync`, so `GpuBusy` is what holds it at 30 |
| **Audio** | mixer peak 32766 (100%), RMS 4209, up to 7 SPU voices; XA and MDEC both feed the movies |
| **Controls** | `up` walks him forward, off a rooftop, into a fall and a death — the GAME OVER screen is the proof that input, physics, collision and the death path all work |
| **Level select** | `SPIDEY_LEVEL=e1m1` redirects the archive lookups and E1M1 loads and plays |
| **Cheats** | all ten codes' handlers read off and reproduced; `SPIDEY_CHEATS=all` installs |
| Stability | zero exceptions across every run in this session |

---

## 1. Not a fault: the Daily Bugle headline waits for the player

This looked exactly like a hang and took the longest to settle, so the reasoning is
worth keeping.

**Symptom.** After NEW GAME the level cinematic played, then the Daily Bugle headline
played, and then the picture stopped changing — 241 consecutive identical captures, from
frame 8000 to frame 20000. Frames were still being presented at full rate, so the
watchdog never fired: it watches for frames stopping, and frames had not stopped.

**Three wrong candidates, each killed by a measurement:**

| candidate | what killed it |
|---|---|
| The game sees no pad and auto-pauses | the runtime has no focus-pause, and the pad demonstrably works — it navigated the menus |
| It waits for a voice to go silent, and the envelope never decays | dumping SPU state during the stall: `live=0`, no voice sounding at all |
| The stream reader runs off the end of the STR and stops delivering | counters say `skipped=0` and the reader delivered every frame it queued |

**What it actually is.** `MovieNextFrame` (`0x80030D08`) calls `StGetNext`, reads the
STR header's frame number, stores it at `gp+1944`, and sets a "finished" flag at
`gp+1912` once it reaches the target at `gp+1952`. Tracing those three words:

```
[movie] f7942 frame=18 target=18 done=1
```

The movie **completes correctly**. The game then sits in a loop that does nothing but
poll input and service sound — `func_80076424` (a button debounce, 36 calls per pass)
and `SpuGetVoiceEnvelope` (24 voices per pass) filling the whole call ring, with no
drawing. That is a "press a button to continue" screen. A single `cross` at frame 9204
loaded `E1M0_G.psx` immediately.

So the port is behaving correctly and the headline is waiting for the player, exactly as
on hardware. It is called out here because the failure mode — a frozen picture, full
frame rate, no watchdog — reads as a hang and is worth recognising quickly next time.

## 2. Not verified: finishing the level

The same limit the Spider-Man port hit. A timed button script cannot play a 3D action
level to its end; in this game it walks Spider-Man off a rooftop within a minute or two,
which is how the controls got verified but is not progress. Doing it properly needs a
person at the controls or navigation driven from the game's own state.

A recorded-input system (`SPIDEY_REC` / `SPIDEY_PLAY` in the Spider-Man port) is the
obvious next step and is not ported here: recording a route needs a person once, and
after that the route replays.

## 3. Not started

- **Widescreen.** The Spider-Man port's `Wide.cs` is not ported. Nothing here has looked
  at whether this game's projection responds the same way.
- **Costumes.** `WASHMCHN` unlocks them and `SPIDEY_CHEATS=costumes` sets that flag, but
  there is no direct selector like the Spider-Man port's `SPIDEY_COSTUME`.
- **Memory card.** Not exercised at all. The runtime's card fixes from the Spider-Man
  port are in the shared runtime and should apply, but "should" is not evidence.
- **The other 43 levels.** Only `e1m0` and `e1m1` have been loaded. The Spider-Man port
  booted 21 prefixes directly and held 7000 frames in each; the same sweep has not been
  run here.
- **Game-internals instrumentation.** `mkconfig.py` emits no `GameTrace`-style hooks,
  because every one of them is a global or a structure layout that has to be found in
  *this* executable first, and a hook pointed at a plausible-looking wrong address
  reports confident nonsense. Only the nine names in `funcmaps/manual.json` plus
  `MovieNextFrame` have been read and confirmed.

## 4. Carried over: the harness bug is still in the Spider-Man port

The unresolved-anchor bug described in README.md — a step waiting on an archive sits at
frame `-1`, and `frame >= -1 && frame < -1 + hold` is true on frames 0..hold-2, so every
anchored script also presses its button at boot — is fixed in `spiderman2/patches/
Capture.cs` and **still present in `spiderman/patches/Capture.cs`**, which is where this
copy came from. It was left alone deliberately: the two games' patch directories are
siloed, and changing Spider-Man's input harness would invalidate its recorded routes and
its verification runs. It should be fixed there, with a re-verification pass.
