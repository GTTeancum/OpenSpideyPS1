# Playbook: PS1 disc image to playable recompilation

A repeatable process for taking a PlayStation game from `bin`/`cue` to a native,
playable build using [RecompOne](https://github.com/BlackLabelHQ/RecompOne), written up
from the X-Men: Mutant Academy 2 port so the next game does not have to rediscover it.

Texture work is deliberately out of scope here.

---

## About this document

Be aware of where it comes from, because it changes how much to trust each part.

The session that produced this document **did not do the recompilation**. It began at
"continue via handoff" with the port already playable, and spent its time on textures.
So this is not a transcript of the original work and does not claim to be.

- **The process below is reconstructed** from what that work left behind: `tools/`,
  `config/xmen.json`, the patches, the committed function maps, and `port/README.md`,
  which documents the reasoning in detail and is the better source for anything here
  that reads as a summary.
- **The original prompt is not recoverable** — it is not in this session's history. The
  template in the next section is written to produce the same outcome, not quoted.
- **The operating rules are the ones requested**, not ones observed working.

Where this document states a fact about the game (overlay bases, patch reasons, the
RecompOne fixes), that came from reading the repository and is reliable. Where it
generalises to *other* games, that is inference from one example.

---

## How to run it: the prompt

Paste something like this, with the paths changed:

> Recompile `<GAME>` from `<path to .cue>` into a fully playable PC build using
> RecompOne at `tools/RecompOne`. Target: boots, plays through to real gameplay,
> stable frame rate, no freezes on the main path.
>
> Work in **one continuous turn**. Ask me anything you need **before you start** —
> once you begin, do not stop for any reason: not to confirm an approach, not to
> report progress, not to ask whether to continue. If you hit a decision you cannot
> resolve, pick the option you can defend, note it, and keep going. If something is
> blocked, work every other part of the task and tell me what was blocked at the end.
>
> Verify as you go. Run the thing rather than reasoning about whether it should work.
> A build that compiles is not evidence it runs.

### Why one turn

Every stop costs a rebuild of context, and this work is a long chain where each step's
output is the next step's input. The map pipeline alone is several recompile cycles.
Bring-up debugging is a loop of *run, read the log, form a hypothesis, patch, run
again*, and that loop is where the value is — interrupting it to report is pure loss.

### Questions up front, not during

Legitimate things to ask before starting, because they change the plan:

- Which disc image, which region, and is it a complete multi-track dump?
- Should local RecompOne fixes go upstream, or stay local?
- Is a windowed debug build wanted, or a shipping single-file build?
- Is there a target beyond "boots and plays" — two-player, endings, options screens?

Once running: no check-ins. Pick, document, continue.

---

## What you need

| | |
|---|---|
| disc image | `.cue` + `.bin` (multi-track) or `.chd` |
| RecompOne | checked out somewhere local; expect to modify it |
| .NET SDK | 10 for this port |
| Python | with `numpy`, `PIL` for the map tooling |

Expect to make changes to RecompOne itself. Every non-trivial game hits something the
recompiler or its runtime does not handle, and the fixes are usually game-agnostic.

---

## The process

### 1. Find the executable and the overlays

`SYSTEM.CNF` on the disc names the boot executable (`SLUS_013.82` here). That is the
main module.

Overlays are the harder half. This game loads 38 of them — two per character
(`DATA/REL_CODE/ONE/<CHR>_REL1.R`, `.../TWO/<CHR>_REL2.R`), plus `FRONT.BIN` and
`PRACTICE.BIN` — each at a **fixed load address** that has to be recovered:

```
*_REL1.R    0x80107EF0
*_REL2.R    0x80110EF0
FRONT.BIN   0x801C9000
PRACTICE.BIN 0x801EF000
```

Get these wrong and everything downstream is garbage. They come from reading the
game's loader code. Note that all overlays of a class share a base but differ in size —
which is why overlay eviction by containment is not quite correct (see `TO_DO.md`).

### 2. Linear-sweep function maps

RecompOne generates raw maps per module (`tools/genmaps.sh` is the pattern):

```bash
dotnet run --project ../tools/RecompOne/RecompOne.Recompiler -c Release -- \
  --generate-function-file -linear-sweep -disc "$CUE" \
  -base 0x80107EF0 -file DATA/REL_CODE/ONE/CYC_REL1.R -out config/funcmaps/CYC_rel1_sweep.json
```

Treat the output as **raw material, not answers**. A linear sweep decodes every word as
a possible instruction, so data that happens to look like `jal` invents function starts
inside real functions. Keep the sweeps as `*_sweep.json` and never edit them; the
refined maps are derived.

### 3. Match the SDK — the step that makes it possible

The game statically links PsyQ. Matching each library function's code against the
executable, with relocated fields masked and ambiguities resolved by cross-checking
relocation targets, recovered **258 SDK symbols** (`tools/psyq_signatures.py` →
`config/funcmaps/psyq_main.json`).

**This is the pivot of the whole project.** RecompOne routes `libgpu`, `libcd`,
`libpad` and `libcdstream` calls to its runtime *by name*. Naming `VSync`, `DrawOTag`,
`CdRead` is what turns raw hardware access into something the host can serve. Skip or
botch this and you are emulating a GPU instead of calling into one.

A few one-instruction library stubs no signature can distinguish get resolved by hand
into `manual.json`.

### 4. Refine the maps

`tools/fixmaps.py` rebuilds each map around one rule — a real function start is:

- the first word of the module, or
- a symbol already identified, or
- a `jal` target read from inside a function already proven to end in a return, or
- a pointer target landing on a boundary nothing can fall through into.

Extents are natural: walk forward tracking the furthest forward branch, stop at the
first return past it. **Allow overlaps** — a function can legitimately be entered in the
middle, and forbidding that loses real code.

### 5. Recompile and close the call graph

RecompOne turns every control transfer leaving a function into `Dispatcher.Call(addr)`.
A target nothing defines throws `unmapped call` the first time the game takes that path
— a latent crash, not a build error, which is why this needs closing deliberately.

`tools/closure.py` scans the generated C# for them and feeds back the ones that decode
as code. `tools/build.sh` iterates until it stops finding new ones:

```bash
bash tools/genmaps.sh   # first time only
bash tools/build.sh     # maps -> recompile -> closure -> repeat -> build
```

It converges in a few passes. A residue that never resolves (about 60 here) is normal:
jump-table analysis running off the end of a real table into data, unreachable by any
real path. Stop when the count stops falling — chasing it to zero is chasing noise.

### 6. Patch what the runtime does not cover

Wired in `config/xmen.json`, implemented in `patches/`. Two categories:

**Whole subsystems that must be replaced as a set.** The runtime takes over
`DrawOTag`/`DrawSync`/`PutDrawEnv`/`PutDispEnv`, which bypasses libgpu's internal DMA
command queue. Every *other* libgpu call that reaches hardware dispatches through that
same queue — so leaving them recompiled walks a queue nothing fills and calls a null
entry. Half-replacing a subsystem is worse than not replacing it.

**Entry points the game uses that the runtime does not implement.** This game
initialises input through `PadInitMtap`, not `PadInitDirect`. It passes two 34-byte
buffers 0x22 apart — only slot 0 of each port — so forwarding to direct mode gives
exactly the layout it expects.

### 7. Bring-up: the failure classes to expect

These were all real here and are all game-agnostic. Recognising the shape saves days.

**Idle loops that never exit.** A game waits for an interrupt by spinning on a variable
its handler writes. Interrupts only arrive while presenting a frame, so a wait loop that
never calls `VSync` itself hangs forever. Fix: a long run of memory reads with no
intervening write presents a frame and delivers the vblank. Same problem when the loop
body is a call rather than a read — hence a call-count breaker too.

**Jump tables that leave the function.** A switch case that is a tail jump lands on the
*next* function. Stopping analysis at the first such entry silently discards every case
after it; those fall through to the indirect fallback and crash on whatever input
selects one. This caused the mid-fight freeze here.

**BIOS calls that complete too early.** libmcrd starts a card operation, clears its
event flags, *then* waits on them. A completion delivered inside the call is wiped by
that clear and the wait never ends. Queue completions and re-offer them while the game
idles.

**Timers that only move when you look.** `VSync(-1)` reads the vblank counter without
waiting; on hardware it advances by itself, so games poll it. If it only advances when a
frame is presented, a poll loop never progresses.

**Plain recompiler bugs.** `MoveImage` read its destination from the wrong registers,
so every VRAM-to-VRAM copy landed somewhere else. Symptom was garbled overlays and
texture data scattered through the frame — which looks like a *graphics* problem and
isn't.

### 8. Verify by running, and make it headless

Build a capture harness early; it pays for itself immediately. `patches/Capture.cs`:

| | |
|---|---|
| `XMENMA2_SHOTS=2700,3900` | screenshot at these frames |
| `XMENMA2_SHOT_EVERY=150` | ...or every N frames |
| `XMENMA2_EXIT=4200` | quit after frame N |
| `XMENMA2_SCRIPT=2900:cross:10` | press a button at a frame, for N frames |

Frames are read from the GPU backend, so a capture is what the console drew, not what
the desktop showed. With this you can leave a run going and diff the output.

Two traps found the hard way:

- **The game paces off the wall clock, not the frame counter.** Two runs of the same
  script diverge by the character-select screen. Comparing two runs at the same frame
  number does not work — capture a burst and match by content.
- **Exact-frame matching skips.** During a 15 fps FMV the counter jumps by more than
  one, so a shot requested inside that window can be stepped straight over and never
  fire. Ask for frames after the FMV, or use `SHOT_EVERY`.

### 9. Diagnostics worth having on day one

`patches/Diag.cs`: one timestamped log per run, frame-tagged, flushed immediately, with
a watchdog that dumps where the game was when it stopped, plus crash capture. Freezes
are the dominant failure mode and they are unreadable without this.

Optional per-overlay tracing (`callRing`) lets you instrument one overlay at a time,
which is the only practical way to find where an overlay's state machine stalls.

### 10. Publish, then *launch what you published*

Single-file .NET publishing has a trap that cost real time here:
`IncludeNativeLibrariesForSelfExtract` puts native libraries in a temp folder while
`AppContext.BaseDirectory` still points at the executable. Silk.NET searches
`BaseDirectory`, so GLFW and OpenAL are never found — **the published build comes up
with no window and no audio while the ordinary build is fine**, and the build log says
nothing. Use `IncludeAllContentForSelfExtract`.

Resolve paths through `Environment.ProcessPath`, not `AppContext.BaseDirectory`, and set
the working directory from it, so saves and settings land beside the exe.

> **Verify a publish by launching it, not by reading build output.** This failed
> silently for an unknown number of sessions.

---

## Working rules that mattered

- **Measure, do not infer.** Two wrong conclusions here came from plausible reasoning
  over insufficient data: "the game draws no 16bpp textures" (true of short runs, false
  overall) and a texture diagnosis built on a metric that scored blocky output as
  more detailed than clean output. Both were caught by looking at the actual thing.
- **A number is not evidence until you know what it measures.** Check a metric against
  a case whose answer you already know before trusting it.
- **Verify a candidate before believing it.** A byte that looked like a menu cursor
  (`[20, 26, 32, 38]`, six per press) was a frame counter that wraps at 77, aliasing
  against a 160-frame sample interval. One extra observation killed it.
- **Keep the evidence.** Deleting screenshots before checking them invalidated a whole
  differential search — there was no way to tell whether the input had even registered.
- **Record what did not work**, in `TO_DO.md`, with the reason. Ruling things out is
  most of the value and it is invisible unless written down.

---

## Rough shape of the effort

Ordered by how much time they took here, largest first:

1. Bring-up debugging — freezes, stalls, the jump-table bug
2. The function-map pipeline, especially SDK signature matching
3. Patches for uncovered subsystems
4. Verification harness and diagnostics
5. Publishing

The map pipeline is mostly mechanical once the approach is right. Bring-up is not, and
it is where a stop-and-report cadence hurts most.
