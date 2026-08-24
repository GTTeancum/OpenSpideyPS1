# Spider-Man port — open work

Ordered by what blocks the most. Ruling things out is most of the value here, so the
things that turned out *not* to be the cause are recorded with their evidence.

---

## 1. Entering a level: actor resources are never loaded  — BLOCKER

**Symptom.** New Game → difficulty → intro FMV → the level cover (`L1COV.rle`) draws,
then on the first trigger tick:

```
unmapped call: 0x00000000
  s1=00000000                       <- the object pointer itself is null
  active overlays: main, shell
  at func_8005B014   (level trigger interpreter)
  at func_8005DAE0   (trigger list walk)
```

**What is actually happening.** `func_8005DAE0` walks the trigger list loaded from
`l1a1_t.trg`. Type-1 entries pass a filter (`func_8005AFAC`, a `0xFF`-terminated byte
list membership test — it legitimately passes) and reach `func_8005B014`, which is a
~28-case switch that spawns one actor kind per case by name. Each case calls
`SpawnActor` (`0x8001BEC4`) and then dereferences the pointer it returns.

`SpawnActor` hashes the name, walks the list of **resident** overlays at `gp+1480`, and
calls a constructor out of the matching overlay's table. On a miss it returns *without
writing its out-pointer*, so the caller reads a stale stack slot and dereferences it.
That is why the failure surfaces as a null vtable call far from its cause.

**The real gap is data, not code.** Tracing every archive lookup
(`SPIDEY_TRACE_WAD=1`) shows the level asks for exactly:

```
sp_tex00.psx  l1a1.VAB  l1a1.SFX  l1a1_t.trg  L1COV.rle
```

and then stops. It never asks for `l1a1_l.psx`, `l1a1_o.psx`, `l1a1_g.psx` (the level
geometry) or `thug.psx` (the actor's model) — all of which are present in CD.WAD and
resolve fine when asked for. Every lookup the game *does* make succeeds.

**The same machinery works elsewhere.** The main menu's attract demo runs the whole
sequence correctly on its own:

```
dem1.VAB  dem1.SFX  dem1_t.trg  Dem1_L.psx  henchman.psx  expgrnd.psx
Dem1_O.psx  Dem1_G.psx  -> LoadOverlay("thug") -> SpawnActor("thug")
```

Geometry, actor models, and the actor's code overlay, loaded by the game itself with no
help. So the loader, the archive reader, the overlay path and the spawn path are all
functional; what is missing is whatever kicks that sequence off for a *real* level after
the cover screen. That is the next thing to find.

**Ruled out, with evidence:**

- *The FMV corrupting the CD state.* Skipping the movie entirely (START during
  playback — no 24bpp frames captured at all) produces a byte-identical failure at the
  same point.
- *The overlay code never loading.* `patches/GameTrace.cs` loads a missing overlay
  on demand at spawn (`SPIDEY_NO_ONDEMAND=1` disables it). `thug` then loads and its
  constructor runs — and fails one level deeper, reading `0xFFFFFFFF` out of the
  resource table at `0x800A0904 + idx*64 + 0x10`. Uninitialised because the *model*
  was never loaded. Code residency was a real gap but not the root one.
- *The overlay-load script command being unreachable.* `call_8005CAF8` (the trigger
  command that calls `LoadOverlay`) is emitted and dispatched from four jump tables. It
  is reachable; it simply never runs.
- *My own instrumentation.* An early version of the `SpawnActor` hook zeroed `a3` "so
  a miss is unambiguous". `a3` is passed straight to the overlay constructor and is not
  always a writable word, so that corrupted the front end. The hook is read-only now —
  but removing it did **not** change the crash, so it was never the cause of this one.

**Where to look next.** The cover-screen state is the seam: the demo path has no cover
and works, the real path shows a cover and stops. Find what displays `L*COV.rle` and
what it is supposed to hand off to. `func_8006F294` is the shell driver and does
`LoadOverlay(name, 1)` then `SpawnActor(name, 1, ...)` at `0x8006F4DC` — the game's own
load-then-spawn idiom, and a good place to start reading.

---

## 2. Memory corruption in the attract demo

Letting the main menu sit long enough for the attract demo to play loads everything
correctly, renders black, and then dies:

```
unmapped address: 0x80800004     (RAM top + 4)
```

preceded by a garbage filename ending in `.bin` printed from a corrupted name buffer —
so something is scribbling before this, and the wild read is a consequence.

Not caused by the 8 MB RAM. `PSMemory` resolves RAM as `phys % ram.Length`; at 8 MB
`0x80800004` is genuinely outside the array, and it is outside RAM on real hardware too.
The address is a corrupted pointer, not a mirroring artefact.

Timing-sensitive: it moves or disappears depending on how much logging is on, because
the game paces off the wall clock. Reproduce with a fixed script and match captures by
content, never by frame number.

---

## 3. FMV decodes to garbage

The intro movie plays — MDEC runs, the display switches to 320x240 24bpp, frames
advance — but the picture is a green/magenta dither pattern rather than an image. The
display mode is right, so this is the decode or the path into VRAM, not the mode switch.
Untouched so far; the level blocker mattered more.

---

## 4. Audio unverified

`SpuInit`, `SpuSetCommonAttr`, `SpuSetKey` and `SpuWrite` are all recovered and routed,
and the game loads `menu.VAB` / `l1a1.VAB` / `.SFX` banks, but nothing has actually been
listened to. `StSetStream`/`StGetNext`/`StSetRing` are recovered, so the XA path from
`COMPILED.XA` (190 MB) has its entry points; it has not been exercised.

---

## 5. Smaller things

- **Four libgpu symbols were not recovered**: `DrawOTagEnv`, `DrawSyncCallback`,
  `GetODE`, `ClearOTag`. `tools/mkconfig.py` deliberately emits no patch for a name it
  cannot find, so these are simply left recompiled rather than silently no-op'd. If any
  of them turns out to reach hardware through libgpu's queue it will need pinning by
  hand in `manual.json`. Nothing so far suggests the game calls them.
- **17 residual unmapped-call targets** after closure converges. Expected: jump-table
  analysis running off the end of a real table into the data after it. Chasing them to
  zero is chasing noise.
- **`Trace.cs` is inherited from the X-Men port** and its hooks are not wired to
  anything here. Harmless, but it is dead weight.
