#!/usr/bin/env python3
"""Compare actor object tables, hierarchies, and animation chunks byte-for-byte."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HIER = 0x52454948
ANIMATION_TAGS = (0x2A, 0x2C)


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    version, magic = struct.unpack_from("<HH", data, 0)
    metadata_offset = u32(data, 4)
    object_count = u32(data, 8)
    objects = [data[12 + index * 36 : 12 + (index + 1) * 36] for index in range(object_count)]
    chunks: dict[int, bytes] = {}
    cursor = metadata_offset
    while True:
        tag = u32(data, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(data, cursor)
        cursor += 4
        chunks[tag] = data[cursor : cursor + size]
        cursor += size
    return {
        "path": str(path.resolve()),
        "version": version,
        "magic": magic,
        "objectCount": object_count,
        "objects": objects,
        "chunks": chunks,
    }


def summary(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": parsed["path"],
        "version": parsed["version"],
        "magic": f"0x{parsed['magic']:04X}",
        "objectCount": parsed["objectCount"],
        "objectTableSha256": digest(b"".join(parsed["objects"])),
        "chunks": {
            f"0x{tag:08X}": {"size": len(payload), "sha256": digest(payload)}
            for tag, payload in parsed["chunks"].items()
        },
    }


def compare(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    object_pairs = zip(left["objects"], right["objects"])
    matching_objects = [index for index, (a, b) in enumerate(object_pairs) if a == b]
    relevant_tags = sorted(set(left["chunks"]) | set(right["chunks"]))
    chunks = {}
    for tag in relevant_tags:
        a = left["chunks"].get(tag)
        b = right["chunks"].get(tag)
        chunks[f"0x{tag:08X}"] = {
            "leftSize": len(a) if a is not None else None,
            "rightSize": len(b) if b is not None else None,
            "exact": a == b if a is not None and b is not None else False,
        }
    return {
        "left": left["path"],
        "right": right["path"],
        "matchingObjectIndices": matching_objects,
        "allObjectsExact": (
            len(left["objects"]) == len(right["objects"])
            and len(matching_objects) == len(left["objects"])
        ),
        "hierarchyExact": chunks.get(f"0x{HIER:08X}", {}).get("exact", False),
        "animation": {
            f"0x{tag:02X}": chunks.get(f"0x{tag:08X}")
            for tag in ANIMATION_TAGS
            if f"0x{tag:08X}" in chunks
        },
        "chunks": chunks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[
            ROOT / "dreamcast" / "extracted" / "SPIDEY.PSX",
            ROOT / "dreamcast" / "extracted" / "SPBAGMAN.PSX",
            ROOT / "dreamcast" / "converted" / "all-characters" / "spbagman.psx",
            ROOT / "spiderman" / "extracted" / "wad" / "spidey.psx",
            ROOT / "dreamcast" / "extracted" / "BLACKCAT.PSX",
            ROOT / "spiderman" / "extracted" / "wad" / "blackcat.psx",
        ],
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dreamcast" / "converted" / "actor-skeleton-compatibility.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parsed = [parse(path) for path in args.paths]
    report = {
        "schemaVersion": 1,
        "actors": [summary(actor) for actor in parsed],
        "comparisons": [
            compare(parsed[left], parsed[right])
            for left in range(len(parsed))
            for right in range(left + 1, len(parsed))
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for actor in report["actors"]:
        chunks = actor["chunks"]
        anim = next((chunks.get(f"0x{tag:08X}") for tag in ANIMATION_TAGS if f"0x{tag:08X}" in chunks), None)
        hier = chunks.get(f"0x{HIER:08X}")
        print(
            f"{Path(actor['path']).name:14s} v{actor['version']} objects={actor['objectCount']} "
            f"anim={anim['size'] if anim else '-'}:{anim['sha256'][:12] if anim else '-'} "
            f"hier={hier['size'] if hier else '-'}:{hier['sha256'][:12] if hier else '-'}"
        )
    print(f"report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
