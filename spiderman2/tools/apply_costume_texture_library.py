#!/usr/bin/env python3
"""Relocate a loose SM2 ``sp_texNN.psx`` library into ``spidey.psx``.

The output is a proof/authoring model for mesh conversion. It uses only loose
files and preserves the shipped model and texture bytes; only absolute texture
header pointers are rebased to their new location.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import struct


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def layout(data: bytes) -> tuple[int, tuple[int, ...], int, int]:
    version, magic = struct.unpack_from("<HH", data, 0)
    if (version, magic) != (4, 2):
        raise ValueError(f"expected v4 PSX container, got v{version} magic {magic:04X}")
    object_count = u32(data, 8)
    mesh_count = u32(data, 12 + object_count * 36)
    cursor = u32(data, 4)
    while True:
        tag = u32(data, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(data, cursor)
        cursor += 4 + size
    cursor += mesh_count * 4
    hash_count = u32(data, cursor)
    cursor += 4
    hashes = tuple(u32(data, cursor + index * 4) for index in range(hash_count))
    cursor += hash_count * 4
    section = cursor
    palette4_count = u32(data, cursor)
    cursor += 4 + palette4_count * (4 + 16 * 2)
    palette8_count = u32(data, cursor)
    cursor += 4 + palette8_count * (4 + 256 * 2)
    texture_count = u32(data, cursor)
    cursor += 4
    if texture_count == 0xFFFFFFFF:
        detail_count = u32(data, cursor)
        cursor += 4 + detail_count * 36
        cubemap_count = u32(data, cursor)
        cursor += 4 + cubemap_count * 36
        texture_count = u32(data, cursor)
        cursor += 4
    return section, hashes, cursor, texture_count


def merge(model: bytes, library: bytes) -> bytes:
    model_section, model_hashes, _, _ = layout(model)
    library_section, library_hashes, library_pointers, texture_count = layout(library)
    if len(model_hashes) != len(library_hashes):
        raise ValueError(
            f"model has {len(model_hashes)} material hashes but library has {len(library_hashes)}"
        )
    output = bytearray(model[:model_section] + library[library_section:])
    delta = model_section - library_section
    output_pointer_table = library_pointers + delta
    for index in range(texture_count):
        old_pointer = u32(library, library_pointers + index * 4)
        struct.pack_into("<I", output, output_pointer_table + index * 4, old_pointer + delta)
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--textures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = merge(args.model.read_bytes(), args.textures.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    print(f"wrote {args.output.resolve()} ({len(result):,} bytes)")


if __name__ == "__main__":
    main()
