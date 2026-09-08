# First-run disc installation

Published builds of both games are one Windows executable. They do not invoke a shell,
ship a separate extractor, or retain a dependency on the selected disc image.

## User flow

On first launch, the game opens its normal renderer window and identifies the required
retail dump by common name and disc ID:

| Executable | Required dump | Disc ID |
|---|---|---|
| `SpiderMan.exe` | Spider-Man (USA) | SLUS-00875 |
| `SpiderMan2.exe` | Spider-Man 2: Enter Electro (USA) (Rev 1) | SLUS-01378 |

The Browse button accepts the CUE sheet belonging to the BIN/CUE dump. Validation uses
the boot executable size and SHA-256, `SYSTEM.CNF` SHA-256, and exact data-track
lead-out; a different game, region, revision, partial dump, or rebuilt image is refused
before anything is installed.

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

After the manifest exists, the game opens only `game/`; the original BIN/CUE can be
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
