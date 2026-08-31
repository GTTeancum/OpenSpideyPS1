"""Prepare Spider-Man 2's default suit for Spider-Man 1.

The two games use compatible PSX model data, but twelve texture-name hashes in
SM2's default texture library do not match the material hashes referenced by the
model when it is loaded by SM1.  The texture pixels and headers are already valid;
only the fourteen-entry name table needs to be translated.

Usage:
    python tools/port_sm2_default_suit.py
    python tools/port_sm2_default_suit.py --sm2-wad PATH --output PATH

The output directory can be passed to the port as SPIDEY_ASSET_DIR.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SM2_WAD = ROOT / "spiderman2" / "extracted" / "wad"
DEFAULT_OUTPUT = ROOT / "spiderman" / "extracted" / "asset-overrides" / "sm2-default"

SOURCE_HASHES = (
    0xE9587C6D,
    0x197BC27A,
    0x2F5237EE,
    0xB7F656CD,
    0x3622D2F9,
    0x51678BD1,
    0x51FD31B5,
    0xDC38D248,
    0xF0B0001F,
    0x841D8641,
    0x2CBE7299,
    0xA56327E3,
    0xB03D3BD5,
    0xE7B18C1F,
)

SM1_HASHES = (
    0xE9587C6D,
    0x197BC27A,
    0x21AFE1A6,
    0x4E1E5E1A,
    0x3BC194AE,
    0x1527743E,
    0x08BD6474,
    0xDC38D248,
    0xCEB60740,
    0x3ED5F30B,
    0x1A501534,
    0x933EF22C,
    0x42985F7A,
    0x7FFB7AAD,
)

TEXTURE_TABLE_OFFSET = 0x18
TEXTURE_COUNT_OFFSET = 0x14


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def convert_texture(source: Path, destination: Path) -> None:
    data = bytearray(source.read_bytes())
    if len(data) < TEXTURE_TABLE_OFFSET + len(SOURCE_HASHES) * 4:
        raise ValueError(f"{source} is too small to be an SM2 texture library")

    magic, metadata_pointer = struct.unpack_from("<II", data, 0)
    count = struct.unpack_from("<I", data, TEXTURE_COUNT_OFFSET)[0]
    hashes = struct.unpack_from(f"<{len(SOURCE_HASHES)}I", data, TEXTURE_TABLE_OFFSET)

    if magic != 0x00020004 or metadata_pointer != 0x10:
        raise ValueError(
            f"{source} has unexpected PSX texture header "
            f"(magic=0x{magic:08X}, metadata=0x{metadata_pointer:X})"
        )
    if count != len(SOURCE_HASHES):
        raise ValueError(f"{source} has {count} textures; expected {len(SOURCE_HASHES)}")
    if hashes != SOURCE_HASHES:
        actual = ", ".join(f"{value:08X}" for value in hashes)
        raise ValueError(f"{source} is not the expected SM2 default texture library: {actual}")

    struct.pack_into(f"<{len(SM1_HASHES)}I", data, TEXTURE_TABLE_OFFSET, *SM1_HASHES)
    destination.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sm2-wad", type=Path, default=DEFAULT_SM2_WAD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    model_source = args.sm2_wad / "spidey.psx"
    texture_source = args.sm2_wad / "sp_tex00.psx"
    for source in (model_source, texture_source):
        if not source.is_file():
            parser.error(f"missing extracted SM2 asset: {source}")

    args.output.mkdir(parents=True, exist_ok=True)
    model_output = args.output / "spidey.psx"
    texture_output = args.output / "sp_tex00.psx"

    shutil.copyfile(model_source, model_output)
    convert_texture(texture_source, texture_output)

    print(f"SM2 default suit prepared in {args.output.resolve()}")
    print(f"  spidey.psx   {model_output.stat().st_size:7d} bytes  sha256 {sha256(model_output)}")
    print(f"  sp_tex00.psx {texture_output.stat().st_size:7d} bytes  sha256 {sha256(texture_output)}")
    print(f"Run with SPIDEY_ASSET_DIR={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
