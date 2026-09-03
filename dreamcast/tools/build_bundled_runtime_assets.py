#!/usr/bin/env python3
"""Build deterministic, executable-embedded runtime asset payloads.

Only ship-consumed files are included: root actor/texture PSX files plus each game's
host-resolution texture pack. Conversion reports, Blender proofs, logs, and source-disc
material never enter the executable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def inputs(source: Path, pack_name: str) -> list[tuple[Path, str]]:
    files = [(path, path.name) for path in sorted(source.glob("*.psx"))]
    pack = source / "packs" / pack_name
    files.extend(
        (path, path.relative_to(source).as_posix())
        for path in sorted(pack.rglob("*"))
        if path.is_file()
    )
    if not files:
        raise FileNotFoundError(f"no runtime assets found under {source}")
    return files


def build(source: Path, pack_name: str, output: Path, game: str) -> None:
    selected = inputs(source, pack_name)
    manifest = {
        "schemaVersion": 1,
        "game": game,
        "files": [
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            }
            for path, relative in selected
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path, relative in selected:
            info = zipfile.ZipInfo(relative, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
        info = zipfile.ZipInfo("bundle.json", FIXED_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(
            info,
            (json.dumps(manifest, indent=2) + "\n").encode(),
            compresslevel=9,
        )
    temporary.replace(output)
    print(
        f"{game}: {len(selected)} files -> {output.relative_to(ROOT)} "
        f"({output.stat().st_size:,} bytes, "
        f"{hashlib.sha256(output.read_bytes()).hexdigest().upper()})"
    )


def main() -> None:
    build(
        ROOT / "dreamcast" / "converted" / "all-characters",
        "dreamcast-sm1-actors",
        ROOT / "spiderman" / "port" / "bundled" / "runtime-assets.zip",
        "Spider-Man",
    )
    build(
        ROOT / "dreamcast" / "converted" / "sm2-spider-man-runtime",
        "dreamcast-sm2-special-costumes",
        ROOT / "spiderman2" / "port" / "bundled" / "runtime-assets.zip",
        "Spider-Man 2: Enter Electro",
    )


if __name__ == "__main__":
    main()
