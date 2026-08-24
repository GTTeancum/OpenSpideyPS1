# Spider-Man port — open work

Ordered by what blocks the most. Ruling things out is most of the value here, so the
things that turned out *not* to be the cause are recorded with their evidence.

**Where it stands.** The port boots, plays the intro FMV, reaches the title screen and
menus, and loads and runs a level: the `l1a1` trigger list, both actor code overlays
(`thug`, `blackcat`), the actor models and the level geometry (`L1A1_L/_O/_G.psx`).
Actors spawn, gameplay trigger scripts run, and it holds ~57 fps with no crash. What it
does not do is draw the level — item 1 below.

---

## 1. The level runs but draws nothing  — BLOCKER

The level loads, spawns its actors, runs its trigger scripts and holds ~57 fps with no
crash. The screen is a flat fill.

The geometry *is* reaching the GPU: a primitive dump on a level frame
(`SPIDEY_PRIMS=2500`) shows **1,422 primitives** — textured, gouraud-shaded quads with
sensible screen coordinates. They are all being clipped away. Each one carries a
drawing area of `[1023,1023..1023,1023]`, which admits nothing.

Where that comes from, and what it is not:

- The frame starts correctly. `GP0(0xE3)/(0xE4)` set `(0,0)-(511,239)` and
  `(0,256)-(511,495)` — the two buffers — exactly as expected.
- Interleaved with those, the game issues `0xE30FFFFF` / `0xE40FFFFF`, i.e. every
  coordinate bit set. The background fill and the first few primitives are drawn under
  a correct area; everything after the maximised pair is clipped.
- **Not `PutDrawEnv`.** A check for a clip that is empty or outside the framebuffer
  never fires, so libgpu is not being handed a bad DRAWENV.
- **Not `ClearImage`.** The runtime implements it with `GP0(0x02)`, a direct VRAM fill
  that ignores the drawing area entirely, so it neither sets nor restores one.

That leaves the game submitting those as `DR_AREA` primitives inside the ordering
table, which `DrawOTag` walks. The thing to check next is the order they come out in:
an OT is a back-to-front linked list, and if the walk emits a clip-change primitive
before the geometry it guards instead of after, this is exactly what it would look
like. Worth confirming against `GP0(0xE3)`'s real field widths too — on the retail
(old, 160-pin) GPU the Y coordinate is **9 bits**, 0..511, and the runtime masks it
with `0x3FF`. That is a genuine inaccuracy even though it is not the whole story here,
because `(1023,511)` clips just as thoroughly as `(1023,1023)`.

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
