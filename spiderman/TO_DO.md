# Spider-Man port — open work

Ordered by what blocks the most. Ruling things out is most of the value here, so the
things that turned out *not* to be the cause are recorded with their evidence.

**Where it stands.** The port boots, plays the intro FMV, reaches the title screen and
menus, and now loads a level completely: the `l1a1` trigger list, both actor code
overlays (`thug`, `blackcat`), the actor models, and the level geometry
(`L1A1_L/_O/_G.psx`). Actors spawn and gameplay trigger scripts run. It holds ~59 fps.
It then dies on the first gameplay frame inside the object renderer — item 1 below.

---

## 1. Crash on the first gameplay frame  — BLOCKER

```
unmapped address: 0x00A402CB
  at RenderObjectList (0x8002EED4)   <- lw s0, 4(s0) at 0x8002F248
  at func_8002DA0C -> func_8003565C -> func_8002BD5C -> func_8002C174 -> main loop
  overlays: main, shell, thug, blackcat
```

`RenderObjectList` walks a linked list through offset 4 and renders each node via
`func_8007C4D8(node + 100, 0, 1)`. The faulting address is exactly `s0 + 4`, so a
node's `next` pointer has become `0x00A402C7`.

**What is known:**

- The list is **valid on entry** every time. A hook that walks it before the body runs
  finds a clean chain terminating at 0 — including on the call that crashes:
  `0x8009C5D0 -> 0x801D48CC -> 0x801D4840 -> 0x801D47B4 -> 0x801D4728 -> 0`. So the
  corruption happens *during* the walk.
- `0x8009C5D0` is a legitimate node: it is a 168-byte block from the game's small-block
  pool, which `HeapInit` (0x800650C8) lays out at `0x8009C5C8` in the executable's BSS.
  A fresh one is prepended each frame.
- The bad value `0x00A402C7` is only ever seen written to the **stack** (0x807FFE98),
  not to any node, per a value guard over every tracked 32-bit write.
- The values involved (`0x00A402C7`, `0x00A502C6`, `0x0FCE08F1`, `0x03FF040B`) look
  like packed GTE output rather than pointers, and this renderer is GTE-heavy.

**Ruled out, with evidence:**

- *Stack or saved-register corruption.* A stack-balance and callee-saved-register audit
  over all 3,314 functions (`"spAudit": true`, see `Diagnostics/SpAudit.cs`) reports
  **zero** violations in this build. It did find real ones earlier — see item 6.
- *Missing GTE opcodes.* The only GTE function codes these two routines use are
  0x01, 0x06, 0x10, 0x12, 0x29, 0x2A, 0x3D and 0x3E, and the runtime implements all of
  them. Their *results* have not been checked against hardware, which is the obvious
  next step.
- *Unaligned load/store.* `LWL`/`LWR`/`SWL`/`SWR` in `PSMemory` were checked against the
  R3000 definition case by case and are correct, including the C# shift-count masking
  that makes a 32-bit shift silently wrong.
- *Heap exhaustion.* Fixed, and separately — see item 2.

**Next step.** Run the same scene with `SPIDEY_LENIENT=1` (unmapped reads return zero
instead of throwing) and it survives: exactly five bad reads at that one instant, then
2,500 clean frames. So this is one localised bad pointer, not a subsystem writing
rubbish. The screen stays flat yellow because nothing reaches the ordering table. The
thing to check next is whether the GTE gives the same numbers as hardware for the
`RTPT`/`NCLIP`/`AVSZ` sequence this renderer runs.

---

## 2. Fixed: the loading-screen freeze was an out-of-memory halt

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

## 3. Fixed: 15 fps and an unresponsive window

The game busy-polls `VSync(-1)` — 117,714 calls in 500 frames — and its wait loops never
call `VSync(0)`. Frames, CD service and pad refresh therefore only happened when the
call-ring stall breaker fired, which was set to **four million calls**: roughly one
service every 60 ms, so the window stopped responding and everything crawled.

Splitting `Runtime.ServiceOnly()` out of `PresentFrame()` fixed it. The breaker now runs
the cheap part often (rate-limited to 4 ms) and only delivers a real vblank when one is
due, because the vblank counter has to track real time or every timed wait in the game
finishes early. 15 fps → 59 fps, and game time per frame 60 ms → 16 ms.

---

## 4. FMV decodes to garbage

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

## 5. Audio unverified

`SpuInit`, `SpuSetCommonAttr`, `SpuSetKey` and `SpuWrite` are recovered and routed, and
the game loads `menu.VAB` / `l1a1.VAB` / `.SFX` banks, but nothing has been listened to.
`StSetStream`/`StGetNext`/`StSetRing` are recovered, so the XA path from `COMPILED.XA`
has its entry points; it has not been exercised.

---

## 6. RecompOne fixes made along the way

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
- **Diagnostics** worth keeping: `spAudit` (stack and callee-saved-register audit over
  every function), `MemGuard` (watch an address, or watch for a value, and print the
  call ring at the write), `FrameProfile` (present / throttle / game time per frame),
  register context on a failed dispatch, and the local-image overlay source (`path`).

---

## 7. Smaller things

- **Four libgpu symbols were not recovered**: `DrawOTagEnv`, `DrawSyncCallback`,
  `GetODE`, `ClearOTag`. `tools/mkconfig.py` deliberately emits no patch for a name it
  cannot find, so these are left recompiled rather than silently no-op'd.
- **17 residual unmapped-call targets** after closure converges — jump-table analysis
  running off the end of a real table into data. Chasing them to zero is chasing noise.
- **`Trace.cs` is inherited from the X-Men port** and is not wired to anything here.
