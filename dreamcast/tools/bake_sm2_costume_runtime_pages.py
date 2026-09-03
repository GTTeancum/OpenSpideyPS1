#!/usr/bin/env python3
"""Bake an SM2 costume's post-loader VRAM pages into a standalone actor.

SM1 and SM2 use incompatible retail costume overlay tables.  This tool avoids
feeding an SM2 overlay through SM1: it pairs a default SM2 runtime page dump with
the selected costume's dump by exact VRAM destination, then writes the resolved
pixels and palettes into the converted Dreamcast actor itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

import pack_sm2_costume_to_dc as native_pack


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACTOR = ROOT / "dreamcast" / "converted" / "sm2-spider-man-runtime" / "spidey.psx"
MAGENTA_555 = 0x7C1F
FNV_OFFSET = 1469598103934665603
FNV_PRIME = 1099511628211
# The converted Dreamcast wing faces resolve to SM2's dedicated CEB60740 page,
# which is semantic texture index 7.
WING_TEXTURE_INDEX = 7


def fnv1a64(data: bytes) -> int:
    value = FNV_OFFSET
    for byte in data:
        value = ((value ^ byte) * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return value


def parse_actor(data: bytes) -> tuple[dict, dict[tuple[int, int], int], list[dict]]:
    layout = native_pack.container_layout(data)
    cursor = layout["textureSection"]
    palettes: dict[tuple[int, int], int] = {}
    palette4_count = native_pack.u32(data, cursor)
    cursor += 4
    for _ in range(palette4_count):
        palette_id = native_pack.u32(data, cursor)
        palettes[(16, palette_id)] = cursor + 4
        cursor += 4 + 16 * 2
    palette8_count = native_pack.u32(data, cursor)
    cursor += 4
    for _ in range(palette8_count):
        palette_id = native_pack.u32(data, cursor)
        palettes[(256, palette_id)] = cursor + 4
        cursor += 4 + 256 * 2

    records = []
    for ordinal in range(layout["textureCount"]):
        pointer = native_pack.u32(data, layout["texturePointerTable"] + ordinal * 4)
        flags, palette_size, palette_id, texture_index, width, height = struct.unpack_from(
            "<IIIIHH", data, pointer
        )
        payload_size = width * height if palette_size == 256 else width * height // 2
        palette_offset = palettes[(palette_size, palette_id)]
        palette = struct.unpack_from(
            f"<{palette_size}H", data, palette_offset
        )
        payload = data[pointer + 20 : pointer + 20 + payload_size]
        used = (
            set(payload)
            if palette_size == 256
            else {nibble for byte in payload for nibble in (byte & 0xF, byte >> 4)}
        )
        clut_bytes = bytearray()
        for index in sorted(used):
            color = palette[index]
            runtime_color = 0 if color == MAGENTA_555 else color | 0x8000
            clut_bytes.extend((index, runtime_color & 0xFF, runtime_color >> 8))
        bpp = 8 if palette_size == 256 else 4
        key = (
            f"{fnv1a64(struct.pack('<BHH', bpp, width, height) + payload):016x}_"
            f"{fnv1a64(bytes(clut_bytes)):016x}"
        )
        records.append(
            {
                "ordinal": ordinal,
                "hash": layout["textureHashes"][ordinal],
                "flags": flags,
                "paletteSize": palette_size,
                "paletteOffset": palette_offset,
                "payloadOffset": pointer + 20,
                "payloadSize": payload_size,
                "textureIndex": texture_index,
                "width": width,
                "height": height,
                "bpp": bpp,
                "key": key,
            }
        )
    return layout, palettes, records


def load_pages(root: Path) -> list[dict]:
    pages = []
    for path in sorted(root.glob("*.json")):
        page = json.loads(path.read_text(encoding="utf-8"))
        page["stem"] = path.stem
        page["root"] = root
        pages.append(page)
    return pages


def page_by_key(pages: list[dict], key: str) -> dict:
    matches = [page for page in pages if page["stem"] == key]
    if len(matches) != 1:
        raise ValueError(f"runtime page key {key} resolved {len(matches)} times")
    return matches[0]


def matching_destination(pages: list[dict], source: dict) -> dict:
    fields = ("bpp", "width", "height", "texpage", "clut")
    matches = [page for page in pages if all(page[field] == source[field] for field in fields)]
    if len(matches) != 1:
        location = ", ".join(f"{field}={source[field]}" for field in fields)
        raise ValueError(f"runtime destination {location} resolved {len(matches)} times")
    return matches[0]


def file_palette(runtime_bytes: bytes) -> tuple[int, ...]:
    colors = struct.unpack(f"<{len(runtime_bytes) // 2}H", runtime_bytes)
    return tuple(MAGENTA_555 if color == 0 else color & 0x7FFF for color in colors)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", type=Path, default=DEFAULT_ACTOR)
    parser.add_argument("--default-pages", type=Path, required=True)
    parser.add_argument("--costume-pages", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--hide-wings", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = bytearray(args.actor.resolve().read_bytes())
    _, _, records = parse_actor(data)
    default_pages = load_pages(args.default_pages.resolve())
    costume_pages = load_pages(args.costume_pages.resolve())
    results = []

    for record in records:
        source = page_by_key(default_pages, record["key"])
        destination = matching_destination(costume_pages, source)
        page_root = destination["root"]
        payload = (page_root / f"{destination['stem']}.bin").read_bytes()
        runtime_palette = (page_root / f"{destination['stem']}.clut.bin").read_bytes()
        palette = file_palette(runtime_palette)
        if len(payload) != record["payloadSize"]:
            raise ValueError(
                f"texture {record['textureIndex']} payload is {len(payload)} bytes; "
                f"expected {record['payloadSize']}"
            )
        if len(palette) != record["paletteSize"]:
            raise ValueError(
                f"texture {record['textureIndex']} palette has {len(palette)} entries; "
                f"expected {record['paletteSize']}"
            )
        if args.hide_wings and record["textureIndex"] == WING_TEXTURE_INDEX:
            palette = (MAGENTA_555,) * record["paletteSize"]
        struct.pack_into(
            f"<{record['paletteSize']}H", data, record["paletteOffset"], *palette
        )
        data[record["payloadOffset"] : record["payloadOffset"] + len(payload)] = payload
        results.append(
            {
                "ordinal": record["ordinal"],
                "textureIndex": record["textureIndex"],
                "materialHash": f"0x{record['hash']:08X}",
                "runtimeDestination": {
                    field: destination[field]
                    for field in ("bpp", "width", "height", "texpage", "clut")
                },
                "defaultPage": source["stem"],
                "costumePage": destination["stem"],
                "wingHidden": (
                    args.hide_wings and record["textureIndex"] == WING_TEXTURE_INDEX
                ),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    report_path = args.report or args.output.with_suffix(".json")
    report_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "pass",
                "actor": str(args.actor.resolve()),
                "output": str(args.output.resolve()),
                "textureCount": len(results),
                "wingPolicy": "magenta-keyed" if args.hide_wings else "preserved",
                "textures": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"PASS: baked {len(results)} resolved runtime pages into {args.output.resolve()}")
    print(f"report: {report_path.resolve()}")


if __name__ == "__main__":
    main()
