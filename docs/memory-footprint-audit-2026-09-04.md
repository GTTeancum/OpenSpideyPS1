# Memory footprint audit — September 4, 2026

## Conclusion

The current PC host contains substantial avoidable overhead; the PS1 game and
costume files do not explain its approximately 622 MiB peak. This audit identifies
**76.65 MiB of unnecessary/redundant allocated payload** before reducing rendering
quality: 40 MiB of always-allocated debugging arrays, 16.65 MiB of duplicate native
font source data, and 20 MiB of retained CPU font-atlas pixels after GPU upload.
This is an allocation-reduction opportunity, not a measured post-fix reduction in
Windows private bytes: no production changes were made.

Additional major costs are a conservative 48 MiB vertex-storage arrangement, a
69.31 MiB overall font path, and 84.5 MiB of nominal game rendering textures at
4x. These overlap the findings above; **do not add every number in this report**.
Some are useful resources whose implementation needs scaling/redesign, not deletion.

## Method and measured baseline

A fresh SM2 opening-level/default-costume run used the existing Release binary,
modern Gl45 renderer, 4x scale, FXAA and 16:9. Exactly one game process ran;
allocation hooks, synthetic upload/presentation stress and forced-GC probes were
disabled. A full dump was collected around 60 seconds. The game exited normally
at 7,200 vblanks, after 131.01 seconds. Its native final capture was inspected
individually and confirms gameplay. This is a memory diagnostic, not another soak
or a comprehensive visual acceptance test.

- Loading peak private bytes: **620.39 MiB**, at approximately 15–16 seconds.
- Immediately before dump collection: **556.70 MiB private**, **373.41 MiB working set**.
- Managed GC allocated heap extent: **79.56 MiB**, including free space/uncollected objects.
- Managed GC committed segments reported by SOS: **85.57 MiB**, one GC heap.
- CLR loader heaps: **15.24 MiB**; JIT code heaps: **16.57 MiB**.
- The dump memory map contains **205.08 MiB private write-combined mappings** and
  **340.45 MiB ordinary private read/write mappings**, plus smaller categories.

Dump collection touches memory and increased working set substantially afterward;
post-dump working-set readings are not an undisturbed baseline. Mapped module
sizes, GC commitment, graphics backing and process-private counters have different
accounting rules; they must not be blindly summed.

Evidence: [collection and raw results](C:/Programming/GitHub/OpenSpideyPS1/proof_render/memory-footprint-audit-2026-09-04/),
[heap summary](C:/Programming/GitHub/OpenSpideyPS1/proof_render/memory-footprint-audit-2026-09-04/heap-summary.txt),
[object ownership](C:/Programming/GitHub/OpenSpideyPS1/proof_render/memory-footprint-audit-2026-09-04/object-owners.txt).
The dump and scripts are local diagnostic artifacts, not shipping content.
Runtime SHA256: `8D6D7DCAEC3173ABD66C96C7E274D7B8A52C72DA268AFB64411CD8A0937BEEE4`.

## Ranked findings

### 1. Debugging storage allocated even when unused — 40 MiB

| Allocation | Payload | Evidence |
|---|---:|---|
| RAM read/write timestamps | 16 MiB | Two 2,097,152-element UInt32 arrays in RamLogger; instance fields verified in dump; TrackReads was false. |
| Front/back RAM heatmap images | 16 MiB | Two static 2048x1024 RGBA arrays; matching 8 MiB arrays found in dump. |
| Memory-editor freeze mask | 8 MiB | PSMemory allocates one Boolean per guest RAM byte; dump shows `_frozenCount = 0`. |

Sources: [RamLogger.cs](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Memory/RamLogger.cs:8),
[HostWindow.cs](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Host/Window/HostWindow.cs:95),
[PSMemory.cs](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Memory/PSMemory.cs:37).

The timestamp logger also records ordinary RAM writes regardless of whether the
RAM viewer is open. That is CPU work as well as memory overhead. These facilities
should be lazy/debug-only; any optional freeze representation can also be sparse.
Do not remove unrelated memory-write notifications or projection-depth tracking.

### 2. Font infrastructure — 69.31 MiB of identifiable payload

The game loads Latin, icon and CJK font resources at startup regardless of the
selected language. Combined source size is 17,463,056 bytes / **16.65 MiB**.

| Font allocation | Payload |
|---|---:|
| Our native copies retained in FontSet | 16.65 MiB |
| Separate ImGui-owned copies of the same data | 16.65 MiB |
| CPU alpha atlas, 2048x2048 | 4 MiB |
| CPU RGBA atlas, 2048x2048 | 16 MiB |
| GPU RGBA8 atlas, 2048x2048 | 16 MiB |

This is not just an estimate from file sizes. The native dump parser followed the
ImGui context/atlas pointers, verified both CPU pixel pointers, and SHA256-compared
all three pairs of font-source buffers at distinct native addresses. The GPU
texture wrapper confirms dimensions, RGBA8 format and one mip level.

[FontSet.cs](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Host/Window/FontSet.cs:44)
sets `FontDataOwnedByAtlas = 0`; in the shipped ImGui 1.90.8 implementation,
[AddFont copies non-owned input](https://github.com/ocornut/imgui/blob/v1.90.8/imgui_draw.cpp).
Our own copies are retained as well. The shipped Silk font-upload code does not
call ClearTexData afterward. [Native verification](C:/Programming/GitHub/OpenSpideyPS1/proof_render/memory-footprint-audit-2026-09-04/native-fonts.txt).

First opportunities: release our redundant source copies safely, clear CPU atlas
pixels after upload, and manage font rebuild/teardown ownership explicitly. That
targets **36.65 MiB** without changing the rendered font atlas. Language-aware
loading and a single-channel GPU atlas offer further potential, but need separate
design/visual validation; localization should not simply be deleted.

### 3. Vertex buffers — 48 MiB, conservatively sized

The CPU array reserves **262,144 vertices x 48 bytes = 12 MiB**. The recently added
fenced upload ring reserves three equally sized segments: **36 MiB**. Both were
confirmed in source; the CPU object is in the dump and the fixed native mapping
was verified by the earlier allocation probe.

[GlCore.cs](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Gpu/Backends/Common/GlCore.cs:19),
[GlVertexStream.cs](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Gpu/Backends/Common/GlVertexStream.cs:21).

The bounded ring repaired a demonstrated pressure failure but was not sized from
measured peak batch demand. Profile batch/upload high-water marks, then shrink or
adapt storage while retaining correct fencing and support for large models. No
specific savings are established yet; reverting to unbounded uploads is not a fix.

### 4. Rendering surfaces — 84.5 MiB, excluding fonts and vertex buffers

Dump instance fields and allocation logs confirm:

| Game rendering resource | Nominal payload at current settings |
|---|---:|
| Two primary display color textures | 15 MiB |
| Two coverage and two HUD-free world textures | 30 MiB |
| Presentation, widescreen-completion and FXAA textures | 22.5 MiB |
| Scaled VRAM and base-resolution staging texture | 17 MiB |
| Total | 84.5 MiB |

Each display-sized surface is 2048x960 RGBA8, or 7.5 MiB. Scaling both axes by
four multiplies pixel storage by sixteen. Optional post-processing and VRAM
overlap scratch textures were **not allocated** in this snapshot and are excluded.

The widescreen-completion implementation specifically costs **37.5 MiB** in
coverage/world/completion surfaces and adds geometry passes. Those are currently
functional dependencies, not debug-only textures that can safely be switched off.
They need a renderer design audit for reuse, lower-cost representations and pass
fusion. Retain correct widescreen geometry, HUD and perspective mapping.

[Display allocation](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Gpu/Backends/Common/GlDisplayRt.cs:37),
[coverage passes](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Gpu/Backends/Common/GlCore.cs:1022),
[VRAM](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Gpu/Backends/Gl45/Gl45Vram.cs:15).

Display initialization also constructs **45 MiB of temporary zero-filled CPU
arrays** across the six surfaces, then clears those GPU surfaces again. Scaled
VRAM/staging initialization creates another **17 MiB** of temporary arrays.
These are cumulative initialization allocations, not 62 MiB of permanently live
objects or proof of the entire loading peak. Eliminate redundant upload copies
while preserving deterministic initialization.

### 5. Future HD/mod texture memory policy has holes

[Replacement upload](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Gpu/Backends/Common/GlCore.cs:501)
generates mipmaps but selects non-mipmapped Linear minification. GPU cache accounting
counts only level zero and has a 512 MiB soft budget, excluding textures used this
frame from eviction. Separately,
[LoadTexture](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Assets/AssetReplacerManager.cs:428)
retains decoded RGBA data on each asset; GPU eviction does not evict that CPU data.

This is a scalability problem, not a claim that 512 MiB is preallocated. In this
particular default-suit snapshot the generic replacement GPU cache reported zero
bytes and no ReplacementTexture instances were found. It does **not** explain this
run's hundreds of MiB. Address CPU and GPU residency together, count actual mip
storage, and preserve HD texture capability rather than restoring PS1 limits.

## Additional findings and exclusions

- Embedded bundle extraction copies the entire ZIP into MemoryStream, then copies
  it again with ToArray before checking the installed payload. SM1's current ZIP
  is 20.11 MiB; SM2's is 1.28 MiB. The two payload-sized copies alone are about
  40.21 / 2.55 MiB of temporary storage, with possible MemoryStream growth overhead.
  Stream hashing/extraction is preferable. These are not permanent gameplay costs.
  [BundledAssets.cs](C:/Programming/GitHub/OpenSpideyPS1/tools/RecompOne/RecompOne.Runtime/Cdrom/BundledAssets.cs:58).
- The guest RAM allocation is 8 MiB. Existing model override arenas use extended
  guest addresses: reducing it blindly to 2 MiB would not be a safe optimization.
- Server GC is configured, but SOS reports one heap here. There is no evidence
  for blaming a separate large GC heap per CPU core in this run.
- The runtime references Roslyn, but its compiler assemblies were not present in
  this module snapshot. Package/file size is not evidence of resident private RAM.
- The AMD driver image maps 60.86 MiB, but mapped image size is not equivalent to
  private bytes. Do not label that entire image as another 60.86 MiB of private bloat.
- Source and prior rate measurements show service-only window calls can repeat
  presentation/FXAA/UI work between actual game frames. Together with unconditional
  RAM-write tracking, this warrants a CPU audit before targeting a 733 MHz machine;
  this report does not quantify CPU savings.

## Limits and recommended order

The 40 MiB debug buffers and duplicate/retained font data are concrete first
targets. Then measure/right-size vertex streaming, remove initialization copies,
and audit rendering surfaces and texture residency. No visual downgrade is needed
to begin that work.

The **entire private-byte total is not yet attributed allocation by allocation**.
Graphics mappings include driver backing/staging, and native heap/GC bookkeeping
still needs deeper attribution. Resource payload sizes are not a complete Windows
accounting ledger. No measured stock-64-MiB Xbox feasibility claim follows from
this audit.

The runtime/source findings apply to both games because these systems are shared;
fresh heap measurement in this audit is SM2 only. No production code, assets,
renderer settings, commits or pushes were changed. Only report/diagnostic artifacts
were created. Final game-process count: zero.
