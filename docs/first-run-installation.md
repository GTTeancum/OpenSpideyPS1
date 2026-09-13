# First-run disc installation

Published builds of both games are one Windows executable. They do not invoke a shell,
ship a separate extractor, or retain a dependency on the selected disc image.

## User flow

On first launch, the game opens its normal renderer window and identifies the required
retail dump by common name and disc ID:

| Executable | Required dump | Disc ID |
|---|---|---|
| `SpiderMan.exe` | Spider-Man (USA) | SLUS-00875 |
| `SpiderMan2.exe` | Spider-Man 2: Enter Electro (USA) | SLUS-01378 |

The download contains the executable and `mods/suits/`; no retail disc or extracted
game files are included. Browse accepts a CUE sheet, a single-track BIN, or an ISO.
Validation reads the USA boot ID in `SYSTEM.CNF` and checks that its boot file exists.
Other games and regions are rejected. There are no disc hashes, exact boot-size
checks, or revision-specific lead-out checks.

BIN/ISO layouts are detected from their ISO9660 volume descriptor: raw 2352-byte
Mode 1/2, 2336-byte Mode 2, or cooked 2048-byte sectors. Raw Mode 2 images preserve
XA/STR subheaders and audio/video payloads. A cooked ISO cannot restore XA bytes
already discarded by the tool that produced it; use the original raw dump for
complete audio/video. Multi-track dumps should be opened through their CUE sheet.

Extraction stays in the game window and reports its current stage, current file, file
count, elapsed time, and byte-accurate progress. Normal ISO files are written loose;
XA and STR files retain their 2336-byte Mode 2 sectors; every `CD.WAD` entry is also
unpacked. Files are written through `.partial` names and the disc manifest is committed
last, so closing the program during setup cannot create an apparently complete install.

The resulting layout is relative to the executable:

```text
SpiderMan.exe (or SpiderMan2.exe)
game/
  recompone-disc.json
  CD.HED
  CD.WAD
  wad/
assets/
  builtin/
    bundle.json
    *.psx
    packs/
settings.json
```

After the manifest exists, the game opens only `game/`; the original disc image can be
archived. Bundled Dreamcast models, imported suits, and their host-resolution texture
packs come from a deterministic ZIP resource inside the executable and are repaired or
updated automatically under `assets/builtin`. Neither executable asks for a Dreamcast
disc or for the other Spider-Man game.

Bundle updates retire obsolete files only when their hashes still match the previous
bundle's ownership manifest. Retired bytes are kept under `assets/builtin/.retired/`,
outside the active pack folders, for recovery; modified obsolete files and unowned
files are preserved. Files still owned by the current bundle are repaired as needed.
The previous manifest is kept until retirement finishes, so interrupted updates can
resume safely. Repeated startup also verifies content hashes, not just file lengths.

## Release maintenance

Rebuild both embedded asset payloads after an approved conversion changes:

```powershell
python dreamcast/tools/build_bundled_runtime_assets.py
python dreamcast/tools/build_sm2_mod_actor.py
dotnet publish spiderman/port/SpiderMan.csproj -c Release
dotnet publish spiderman2/port/SpiderMan2.csproj -c Release
```

Regression checks for upgrades, recovery, ownership and real embedded payloads:

```powershell
dotnet run --project tools/RecompOne/tests/BundledAssetsRegression/BundledAssetsRegression.csproj -c Release -- --real-bundles .
```

The asset builder includes only root runtime `.psx` files and the selected texture-pack
trees. It fixes ZIP timestamps and ordering and records every extracted file's byte
length and SHA-256 in `bundle.json`; proof renders, conversion logs, and source media
are never embedded.

## Standalone runtime and release smoke

Both EXEs bundle the .NET runtime, GLFW, OpenAL, SDL, ImGui, native file dialogs,
and the release x64 Visual C++ runtime. The payload self-extracts into .NET's per-user
cache; it needs no separate DLL download or VC++ installer. Windows/UCRT and the
installed graphics driver remain OS dependencies. See
[the native payload provenance](../tools/RecompOne/native/win-x64/README.md).
Published builds never search parent folders for a developer's existing extraction.

Run the disc-validation regression with:

```powershell
dotnet run --project tools/RecompOne/tests/DiscInstallRegression -c Release
```

`dreamcast/tools/smoke_standalone_release.py --game sm1` (then `sm2`) creates an
EXE-plus-mods ZIP and a fresh test installation, passes the retail image through the
normal in-window installer, and captures the main menu and gameplay. Run each again
with `--restart` to verify a custom Miles Morales suit and launch without an image
argument. The harness records the paths of loaded CRT libraries, which must come
from that EXE's extraction cache. It uses only process-local game input and native
render captures. `RECOMP_HOST_PROOF` optionally captures one frame from the target
application's own framebuffer, including its installer; it never reads the desktop.

Release proofs are under `proof_render/standalone-release/`. Do not distribute its
extracted test `package/game/` directories. Only the explicitly created release ZIPs
are download artifacts. Remove disposable test installations after verification.
