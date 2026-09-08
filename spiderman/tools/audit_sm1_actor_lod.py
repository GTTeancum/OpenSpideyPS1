#!/usr/bin/env python3
"""Verify a single-LOD conversion against a prior full-detail asset, using bytes only."""
import argparse
import json
from pathlib import Path
import struct


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def layout(data):
    objects = u32(data, 8)
    count_offset = 12 + 36 * objects
    count = u32(data, count_offset)
    pointers = [u32(data, count_offset + 4 + 4 * i) for i in range(count)]
    cursor = u32(data, 4)
    while u32(data, cursor) != 0xFFFFFFFF:
        cursor += 8 + u32(data, cursor + 4)
    names = cursor + 4
    return objects, pointers, names


def audit(reference, candidate):
    old, new = reference.read_bytes(), candidate.read_bytes()
    objects, before, old_names = layout(old)
    new_objects, after, new_names = layout(new)
    assert objects == new_objects == len(after), 'one emitted mesh required per object'
    assert old[12:12 + 36 * objects] == new[12:12 + 36 * objects], 'object records changed'
    assert old[old_names:old_names + objects * 4] == new[new_names:new_names + objects * 4], 'base mesh identities changed'
    def texture_tail(data, start):
        tail = bytearray(data[start:])
        cursor = 4 + 4 * u32(tail, 0)  # texture hashes
        cursor += 4 + u32(tail, cursor) * 36  # 4-bit palettes
        cursor += 4 + u32(tail, cursor) * 516  # 8-bit palettes
        textures = u32(tail, cursor)
        cursor += 4
        for index in range(textures):
            offset = cursor + 4 * index
            struct.pack_into('<I', tail, offset, u32(tail, offset) - start)
        return tail
    assert texture_tail(old, old_names + len(before) * 4) == texture_tail(new, new_names + len(after) * 4), 'texture data changed'
    sources = references = 0
    for i, pointer in enumerate(after):
        old_end = before[i + 1] if i + 1 < len(before) else u32(old, 4)
        new_end = after[i + 1] if i + 1 < len(after) else u32(new, 4)
        a, b = old[before[i]:old_end], new[pointer:new_end]
        assert a[:24] == b[:24] and a[28:] == b[28:], f'geometry/material bytes changed in mesh {i}'
        assert struct.unpack_from('<HH', b, 24) == (32767, 65535), f'LOD link remains in mesh {i}'
        count = struct.unpack_from('<H', b, 2)[0]
        for j in range(count):
            _, ref, _, flags = struct.unpack_from('<4H', b, 28 + j * 8)
            if flags & 2:
                assert ref < sources, f'premature stitch {ref} in mesh {i}, vertex {j}'
                references += 1
            if flags & 1:
                sources += 1
    return dict(objects=objects, meshes_before=len(before), meshes_after=len(after),
                geometry_preserved=True, textures_preserved=True, sources=sources,
                references=references, premature_references=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.reference, args.candidate), indent=2))
