# Spider-Man port — open work

Ordered by what blocks the most. Ruling things out is most of the value here, so the
things that turned out *not* to be the cause are recorded with their evidence.

**Where it stands.** The game boots, plays its logos and FMV, reaches the title and every
menu, and plays at the rate it was built for. Twenty-one level prefixes were booted
directly and every one reached gameplay. The memory card saves and loads.

What is verified, and how:

| | evidence |
|---|---|
| Boot, Activision/Neversoft logos, intro FMV | captured movie frames decode correctly |
| Title, main menu, difficulty, pause, memory card, SPECIAL, COSTUME VIEWER, LOAD/SAVE | captured frames of each |
| **Frame rate** | gameplay loop measured at 29.9/s, matching the 30 fps the game was built around; was running at 131/s |
| **Levels** | 21 prefixes booted directly, each reaching gameplay and holding 7000 frames, with a screenshot each -- all eight story levels plus the bonus l9 set |
| **Memory card save** | a save written through the menus appears on the card as `BASLUS-00875SPD`, and LOAD GAME lists it back by the name typed with its level and difficulty |
| **Costumes** | symbiote renders the black suit and swaps the HUD icon; peterparker renders street clothes and changes the HUD portrait and cartridge count |
| Input | Spider-Man walks, crawls, swings and fights across captures; menus navigate |
| Audio | mixer peak 86%, RMS ~2700, 17 SPU voices active, XA streaming |
| Stability | thousands of frames per level across 21 levels, zero exceptions |

Not yet verified, and honestly so:

- **Finishing a level.** Blind scripted input moves Spider-Man around and fights, but it
  cannot play a 3D action level to its end -- level 1 act 1 needs web-swinging across
  rooftops to reach the bank. The act-advance trigger is opcode **0xB5**, dispatched
  through the table at `0x80094ACC` to `0x8005D7E8`, and it is a conditional gate on
  trigger state rather than a call that can simply be invoked, so forcing it would mean
  reproducing that state rather than exercising the real path. Doing this properly needs
  either a human at the controls or navigation driven from the game's own state.

---

## 1. Fixed: the game ran at four times speed, and it paces itself two ways

The visible symptom was simply "too fast". The cause took three wrong guesses to find,
and all three were wrong because I measured a counter that looked like a frame rate and
was not one:

| counter | what it actually is |
|---|---|
| `TriggerPass` | once per **level load**, not per frame |
| `DrawOTag` | once per **rendering pass**; in menus several run per frame |
| the frame number in the log | the console's **vblank counter**, not presented frames |

Sampling all of them side by side against one wall clock (`patches/Rates.cs`) is what
made it readable. In level, the real numbers were `PutDispEnv` and `DrawOTag` both at
**131/s** with `VSync(0)` and `VSync(-1)` at **zero**.

That is the whole finding: **during gameplay Spider-Man never waits for a vblank.** It
paces itself on the GPU finishing. The loop at `0x8002C284` is

```
8002C284:  jal 0x8005E234          ; a slice of per-poll work
8002C28C:  jal 0x8005E748
8002C294:  jal DrawSync            ; a0 = 1 -- non-blocking "how much is left?"
8002C29C:  bne v0, zero, 8002C284  ; still drawing? go round again
8002C2A4:  jal 0x80061308          ; swap buffers, submit the next table
```

`DrawSync` in the runtime was `c.V0 = 0` -- the GPU is never busy -- so the spin exited
immediately every time and the frame loop ran flat out.

The menus are a *different* mechanism: they do wait on vblanks, through `RunFrame`
(`0x8002AA0C`), and were running one frame per vblank instead of one per two.

So there are two fixes, and either alone leaves half the game at full tilt:

- **`Runtime.VBlanksPerFrame = 2`** -- a frame is worth two vblanks, which paces
  everything that waits on `VSync`, and keeps the vblank counter advancing at a true
  60 Hz so anything timing itself in vblanks still measures real seconds.
- **`GpuBusy`** -- a submitted ordering table keeps the GPU busy for a frame period, so
  `DrawSync` reports work outstanding and the gameplay spin waits the way it does on
  hardware.

**What this deliberately does not attempt.** A fill-rate model of the real GPU would not
have been enough. On hardware most of a frame is the CPU's own work -- game logic, GTE
transforms, building the table -- and a recompile does all of that in a fraction of a
millisecond, so even a perfect rasteriser model would still come out several times too
fast. The cadence is what is reproducible, so the budget is expressed as a frame period.
`SPIDEY_HZ` sets it; 30 is correct for this title, and `SPIDEY_HZ=0` frees it.

Measured after: gameplay loop **29.9/s**, presents **29.9/s** -- the game's own loop is
the pacer again.

---

## 1b. The cheat table, and unlocking the game for testing

Reaching level 6 legitimately means playing five levels of a 3D action game, which a
timed button script cannot do. The game's own cheat system is the way in.

23 codes live at `0x800A55D0` as `{typed string, effect}` pairs. `0x8006F7EC` walks that
table comparing what was typed, and `0x8006F540` dispatches the matched index through a
jump table at `0x80095B34` to a handler. Every handler is three or four instructions, so
`patches/Cheats.cs` writes the same words directly rather than calling into game code:

| code | effect | write |
|---|---|---|
| `EEL NATS` | everything | `0x800A5708..0x5718 = -1`, `+0x78`/`+0x55` = 1, level select = 1 |
| `XCLSIOR` | level select | `0x800B4F80 = 1` |
| `RUSTCRST` | invulnerable | `0x800B4F6C = 1` |
| `STRUDL` | webbing | `0x800B4F98 = 1` |
| `LLADNEK` | debug info | `0x800B4F8C = 1` |
| `WATCH EM` / `CVIEW EM` / `CMC BUFF` | viewers | `0x800A5710` / `0x570C` / `0x5714 = -1` |

Off unless asked for: `SPIDEY_CHEATS=all`, or a comma list of
`everything,levelselect,invuln,webbing,debug,bighead,viewers`. The flags are re-asserted
every frame, because that block is the same memory the memory-card save is built from.

Verified on screen: with the flags set, CONTINUE is enabled on the main menu and the
wheel's centre shows a level title instead of being blank.

## 1d. Fixed: every level reachable directly, and the three that faulted

`SPIDEY_LEVEL=<prefix>` boots straight into any of the 47 level prefixes by rewriting
the level's name at the archive lookup. **21 tested, all 21 reach gameplay and hold 7000
frames** with a screenshot each:

```
l1a1 l1a2 l1a3 l1a4   l2a1 l2a2   l3a1 l3a2 l3a3   l4a1
l5a1 l5a2 l5a3        l6a1 l6a2   l7a1 l7a2        l8a1 l8a2   l9a1 l9a3
```

That spans every one of the eight story levels plus the bonus l9 set, interiors,
rooftops, the sewers and boss encounters.

Three of them (l2a1, l5a1, l5a3) faulted at first, and the cause was the same each time. Resources persist across
the acts of a level, so an act's list only asks for what is not already resident -- level
5 act 2 loads the `venom` model and act 3 lists only `venom2`, relying on act 2's still
being there. Jump straight to act 3 and it never was.

The game does not survive a missing model. `ModelFind` (`0x800694B8`) returns -1, and its
caller at `0x8005904C` stores that into a **byte**, so -1 becomes 0xFF and it indexes
record 255 of a 40-record table. That lands 16 KB past the end, in static data that is
all 0xFF, and the pointer read out is 0xFFFFFFFF. A `lw` from 0xFFFFFFFF is unaligned, so
real hardware would take an address error too -- the path simply cannot be reached in
normal play, because the model is always resident.

`patches/ModelGuard.cs` answers the lookup instead of letting it fail, preferring the
digit pairing the resource lists use (`venom` <-> `venom2`) and otherwise the resident
name sharing the longest prefix -- which is how the variants are named, and is what
matches level 2's `henchman` to the resident `Henchngt`. Only active when SPIDEY_LEVEL is
set.

**A dead end worth not repeating.** The first attempt added an alias *record* to the
table instead. That is much worse than the problem: two records pointing at one model
means the game owns the same pointer twice, and it turned a clean 0xFFFFFFFF fault into
wild addresses and broke levels that had been fine. Placing the alias in the first free
slot also stole the slot the next real model was going to use, because the game fills the
table from the bottom as a level loads. `patches/ModelAlias.cs` keeps that attempt behind
`SPIDEY_ALIAS=1` as a record of it. Answer the lookup; do not touch the table.

## 1e. Fixed: the memory card save, which was a two-sided deadlock

The save now works end to end. MEMORY CARD -> SAVE GAME DATA -> INPUT NAME -> FINISH
writes `BASLUS-00875SPD` to the card, and LOAD GAME lists it back by the name typed, with
the right level and difficulty beside it.

Finding it meant reading the game's own card code. `0x80014F80` is the save routine, and
it opens with `a1 = 0x00010200` -- O_CREAT plus one block. The trace only ever showed
`flags=0x1`, so that path was never reached: it is gated on a state word the game only
sets once its card poll succeeds. That poll is `0x800152FC`, which tests the four card
events in turn and **gives up after 120 tries, reporting the card as failed**. The save
then refuses to run, and the shell sits on "NOW SAVING DATA" forever.

Nothing ever satisfied the poll, because of two faults that had to be fixed together --
which is why fixing either alone looked like it changed nothing:

- **`_card_info_subfunc` (B 0x4D) was a no-op.** libmcrd issues it before touching a
  sector and waits for the resulting card event, so the state machine stalled before
  any read or write. It now queues a completion.
- **`PumpCard` only delivered on idle frames.** Delivery was gated on the memory-spin
  idle breaker, on the assumption that a game waiting for a card spins on memory.
  Spider-Man waits by calling `TestEvent` in a loop, which is real work and never trips
  that breaker, so it received no completions at all. Delivery no longer depends on it;
  a pending completion is re-delivered every frame until it ages out.

Together those close the loop: the runtime only produced card events as a side effect of
sector I/O, and the game would not issue sector I/O until it saw a card event.

Ruled out along the way, and worth not re-trying: planting a directory entry so the
read-only `open` would succeed (the game still wrote nothing, putting the stall upstream
of file I/O), and `_card_chan` returning stale `v0` (a real bug, fixed, but not this
one). The event plumbing itself was fine -- `TestEvent` acknowledges a ready event and
resets it correctly, and the `delivered 0+0` counts were deliveries to an already
signalled event rather than a matching failure.

## 1g. Open: pushing the HUD out to the widened margins

Two attempts, both recorded because the second one looks like it should work.

The HUD sits at fixed screen coordinates, so in a widened target it is inset from the new
edges by the margin. `RenderPrimEvent` already lets a listener rewrite a primitive's X, so
the shift itself is easy and belongs in the game's patches rather than the backend. The
hard part is deciding *what* to move.

- **Sprites only.** Nothing moved. The HUD is not drawn from rectangles -- it is textured
  quads, the same primitive the world uses -- so vertex count does not separate them.
- **Screen-aligned quads, shifted by which outer third they fall in.** This finds the HUD
  correctly but tears it apart: the health bar smears into streaks and the compass comes
  apart. A HUD element is built from *several* quads, and the bar straddles the third
  boundary, so some of its quads shift and its neighbours do not.

Which is the real constraint: **a positional rule cannot work per primitive**, because
centred text is one quad per character and would split down the middle of the screen the
same way.

That leaves two honest options. Scale positions *and* sizes about the screen centre --
consistent, no tearing, but stretches the HUD by a third. Or group consecutive
screen-aligned primitives into runs, take the bounding box of each run, and shift the
whole run by one amount. The second gives what was asked for and is the one to build;
draw order is available, so the grouping is tractable.

## 1c. Open: driving the menus needs to be closed-loop

Directional input works -- a run that presses RIGHT twice moves the highlight from
CONTINUE to SPECIAL, captured. What is not reliable is *when* to press. The frame a
screen appears on moves by hundreds between runs, and pressing into the gap either does
nothing or falls through to the next screen: six STARTs meant to hold the menu went
title -> menu -> level -> pause.

The fix is to stop timing presses and read the menu's own selection variable, pressing
until it matches the target. Finding it is a RAM diff: snapshot with one item
highlighted, press, snapshot again, and look for the small integer that changed by one.
That single variable unblocks the level select, the memory-card save route, and any
other menu the port needs to be driven through.

---

## 2. Fixed: the first-gameplay-frame crash was a missed branch-and-link

Recorded because the mechanism is easy to hit again. The object renderer walks a linked
list and keeps the current node in `s0` across a call to the packet writer at
`0x8007C4D8`. `s0` came back as rubbish, and the crash landed on the next
`lw s0, 4(s0)`.

The packet writer is hand-written and calls its own interior routines with **`bltzal`
and `bgezal`** — REGIMM *branch-and-link*. Those set `ra` exactly as `jal` does, so the
matching `jr ra` returns to a point inside the same function. The local-return analysis
only recognised `jal`, so those returns were emitted as ordinary function returns: the
epilogue never ran, the frame was never popped, and the caller's saved registers came
back from the wrong addresses. Fixed by treating `bltzal`/`bgezal` with an interior
target the same as `jal`.

## 3. Fixed: the loading-screen freeze was an out-of-memory halt

Worth recording because the symptom pointed nowhere near the cause. The window went
"Not Responding" on the level loading screen, with no recompiled code executing at all.

`0x80064F98` is `j 0x80064F98` — a jump to itself. The function at `0x80064F74` clears
the screen to a colour and then spins there forever: it is Spider-Man's fatal-error
halt, and its only caller is the failure path of `HeapAlloc`.

The heap was being exhausted by the overlay loader, and that was **self-inflicted**.
`OverlayPatches` used to let the allocator run and then overwrite the pointer it
returned with the overlay's fixed base. The real heap block — tens of kilobytes per
overlay — was then never freed, because the game only ever frees the fixed address it
was handed, which is not a heap block. The pre-hook now returns `false` so the
allocator never runs for those allocations.

---

## 4. Fixed: 15 fps and an unresponsive window

The game busy-polls `VSync(-1)` — 117,714 calls in 500 frames — and its wait loops never
call `VSync(0)`. Frames, CD service and pad refresh therefore only happened when the
call-ring stall breaker fired, which was set to **four million calls**: roughly one
service every 60 ms, so the window stopped responding and everything crawled.

Splitting `Runtime.ServiceOnly()` out of `PresentFrame()` fixed it. The breaker now runs
the cheap part often (rate-limited to 4 ms) and only delivers a real vblank when one is
due, because the vblank counter has to track real time or every timed wait in the game
finishes early. 15 fps → 59 fps, and game time per frame 60 ms → 16 ms.

---

## 5. FMV decodes to garbage

The intro movie plays — MDEC runs, the display switches to 320x240 24bpp, frames
advance — but the picture is a green/magenta dither rather than an image. The mode
switch is right, so this is the decode or the path into VRAM.

Spider-Man's `.STR` files are ordinary Sony STR with BS v2 frames, which is thoroughly
documented and has a mature reference decoder in
[jpsxdec](https://github.com/m35/jpsxdec/blob/readme/jpsxdec/PlayStation1_STR_format.txt);
[psx-spx](https://psx-spx.consoledev.net/macroblockdecodermdec/) covers the MDEC side.
Comparing one decoded frame against jpsxdec's output for the same sector would settle
where it diverges. Not attempted yet.

---

## 6. Audio unverified

`SpuInit`, `SpuSetCommonAttr`, `SpuSetKey` and `SpuWrite` are recovered and routed, and
the game loads `menu.VAB` / `l1a1.VAB` / `.SFX` banks, but nothing has been listened to.
`StSetStream`/`StGetNext`/`StSetRing` are recovered, so the XA path from `COMPILED.XA`
has its entry points; it has not been exercised.

---

## 7. RecompOne fixes made along the way

All game-agnostic; see `tools/recompone-spiderman-changes.patch`.

- **`CdInit` returned the wrong value.** libcd returns 1 on success, not 0, so the
  game's retry loop spun forever on a black screen.
- **`jr ra` is not always a return.** Hand-written routines call their own interior
  entry points with `jal`, so the matching `jr ra` comes back *inside* the function.
  Emitting that as a function return skipped the epilogue and leaked the frame, which
  is what stopped the level's init script dead: `s1` held the script pointer across the
  call and came back as 0. Told apart by whether an `lw ra` precedes the `jr` — with a
  24-instruction window, because a full epilogue is a dozen instructions and a shorter
  window misreads ordinary returns. Self-recursion is excluded: a `jal` to the
  function's own first instruction makes a fresh frame and must return normally.
  `bltzal`/`bgezal` count as calls here too — see item 2.
- **Diagnostics** worth keeping: `spAudit` (stack and callee-saved-register audit over
  every function), `MemGuard` (watch an address, or watch for a value, and print the
  call ring at the write), `FrameProfile` (present / throttle / game time per frame),
  register context on a failed dispatch, and the local-image overlay source (`path`).

---

## 8. Smaller things

- **Four libgpu symbols were not recovered**: `DrawOTagEnv`, `DrawSyncCallback`,
  `GetODE`, `ClearOTag`. `tools/mkconfig.py` deliberately emits no patch for a name it
  cannot find, so these are left recompiled rather than silently no-op'd.
- **17 residual unmapped-call targets** after closure converges — jump-table analysis
  running off the end of a real table into data. Chasing them to zero is chasing noise.
- **`Trace.cs` is inherited from the X-Men port** and is not wired to anything here.
