#!/usr/bin/env python3
"""Prove compact PSX actor textures and host-resolution replacements independently.

The converted v4 model intentionally contains compact paletted pages that fit the
original emulated-VRAM upload path.  The recomp texture pack must replace those
pages with the original Dreamcast PNGs before the host GPU samples them.  This
audit ties all three artifacts together:

* texture records parsed directly from the converted model;
* PNGs produced from that model by an independent extractor; and
* original Dreamcast PNGs plus the host texture pack and runtime replacement log.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rgba_digest(path: Path) -> tuple[tuple[int, int], str]:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        digest = hashlib.sha256(
            struct.pack("<II", rgba.width, rgba.height) + rgba.tobytes()
        ).hexdigest()
        return rgba.size, digest


def parse_texture_records(path: Path) -> dict[int, dict[str, Any]]:
    """Return generated PSX texture records keyed by texture index."""
    data = path.read_bytes()
    metadata_offset = u32(data, 4)
    object_count = u32(data, 8)
    mesh_count_offset = 12 + object_count * 36
    mesh_count = u32(data, mesh_count_offset)

    cursor = metadata_offset
    while True:
        tag = u32(data, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(data, cursor)
        cursor += 4 + size

    cursor += mesh_count * 4
    texture_name_count = u32(data, cursor)
    cursor += 4 + texture_name_count * 4

    palette4_count = u32(data, cursor)
    cursor += 4 + palette4_count * (4 + 16 * 2)
    palette8_count = u32(data, cursor)
    cursor += 4 + palette8_count * (4 + 256 * 2)

    texture_count = u32(data, cursor)
    cursor += 4
    header_offsets = struct.unpack_from(f"<{texture_count}I", data, cursor)
    records: dict[int, dict[str, Any]] = {}
    for header_offset in header_offsets:
        _, palette_size, texture_id, texture_index, width, height = struct.unpack_from(
            "<IIIIHH", data, header_offset
        )
        if palette_size not in (16, 256):
            raise ValueError(
                f"texture {texture_index} at 0x{header_offset:X} is not paletted"
            )
        records[texture_index] = {
            "headerOffset": header_offset,
            "paletteSize": palette_size,
            "textureId": texture_id,
            "size": (width, height),
        }
    return records


def make_contact_sheet(rows: list[dict[str, Any]], output: Path) -> None:
    cell_width = 320
    cell_height = 300
    label_height = 38
    columns = ("Converted model (nearest 4x)", "Original Dreamcast", "Runtime pack")
    sheet = Image.new("RGBA", (cell_width * 3, label_height + cell_height * len(rows)), "#20242a")
    draw = ImageDraw.Draw(sheet)
    for column, title in enumerate(columns):
        draw.text((column * cell_width + 8, 10), title, fill="white")

    for row_index, row in enumerate(rows):
        y0 = label_height + row_index * cell_height
        images = []
        for key in ("extracted", "source", "pack"):
            with Image.open(row[key]) as opened:
                images.append(opened.convert("RGBA"))
        target_size = images[1].size
        images[0] = images[0].resize(target_size, Image.Resampling.NEAREST)
        for column, image in enumerate(images):
            available = (cell_width - 16, cell_height - 42)
            scale = min(available[0] / image.width, available[1] / image.height, 1.0)
            shown = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.NEAREST,
            )
            x = column * cell_width + (cell_width - shown.width) // 2
            y = y0 + 24 + (cell_height - 36 - shown.height) // 2
            sheet.alpha_composite(shown, (x, y))
        compact = "x".join(str(value) for value in row["compactSize"])
        host = "x".join(str(value) for value in row["hostSize"])
        draw.text((8, y0 + 4), f"index {row['textureIndex']}: {compact} -> {host}", fill="#d8dee9")

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(output, quality=95)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", default="SPBAGMAN")
    parser.add_argument(
        "--converted-model",
        type=Path,
        default=ROOT / "dreamcast" / "converted" / "all-characters" / "spbagman.psx",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=(
            ROOT
            / "dreamcast"
            / "converted"
            / "all-characters"
            / "packs"
            / "dreamcast-sm1-actors"
            / "texture-manifest.json"
        ),
    )
    parser.add_argument(
        "--extracted",
        type=Path,
        default=(
            ROOT
            / "dreamcast"
            / "converted"
            / "bagman-texture-pixel-audit-20260831"
            / "extracted"
            / "spbagman"
        ),
    )
    parser.add_argument(
        "--runtime-log",
        type=Path,
        default=(
            ROOT
            / "dreamcast"
            / "converted"
            / "all-characters-costumes-runtime-current"
            / "05-bagman"
            / "console.log"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / "dreamcast"
            / "converted"
            / "bagman-texture-pixel-audit-20260831"
            / "report.json"
        ),
    )
    parser.add_argument(
        "--contact-sheet",
        type=Path,
        default=(
            ROOT
            / "dreamcast"
            / "converted"
            / "bagman-texture-pixel-audit-20260831"
            / "texture-parity.png"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    actor = args.actor.upper()
    entries = [entry for entry in manifest["entries"] if entry["actor"].upper() == actor]
    if not entries:
        raise ValueError(f"manifest contains no entries for {actor}")

    records = parse_texture_records(args.converted_model)
    runtime_log = args.runtime_log.read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    for entry in entries:
        texture_index = int(entry["textureIndex"])
        record = records[texture_index]
        extracted = args.extracted / (
            f"{args.converted_model.stem}_{record['headerOffset']:08X}.png"
        )
        source = Path(entry["source"])
        pack = Path(entry["output"])
        for required in (source, pack, extracted):
            if not required.is_file():
                raise FileNotFoundError(required)

        source_size, source_rgba = rgba_digest(source)
        pack_size, pack_rgba = rgba_digest(pack)
        extracted_size, extracted_rgba = rgba_digest(extracted)
        compact_size = tuple(entry["compatibilitySize"])
        host_size = tuple(entry["hostSize"])
        runtime_key = str(entry["runtimeKey"])
        runtime_pattern = re.compile(
            rf"\[assets\] page {re.escape(runtime_key.split('_', 1)[0])}: "
            rf"{compact_size[0]}x{compact_size[1]} -> {host_size[0]}x{host_size[1]} "
            rf"\(4x, 4x\)"
        )
        row = {
            "textureIndex": texture_index,
            "modelHeaderOffset": f"0x{record['headerOffset']:08X}",
            "source": str(source),
            "extracted": str(extracted),
            "pack": str(pack),
            "compactSize": list(compact_size),
            "hostSize": list(host_size),
            "recordSizeMatchesCompact": tuple(record["size"]) == compact_size,
            "extractedSizeMatchesRecord": extracted_size == tuple(record["size"]),
            "sourceSizeMatchesHost": source_size == host_size,
            "packSizeMatchesHost": pack_size == host_size,
            "sourcePackBytesExact": sha256(source) == sha256(pack),
            "sourcePackRgbaExact": source_rgba == pack_rgba,
            "sourceExtractedRgbaExact": source_rgba == extracted_rgba,
            "sourceRgbaSha256": source_rgba,
            "extractedRgbaSha256": extracted_rgba,
            "packRgbaSha256": pack_rgba,
            "runtimeKey": runtime_key,
            "runtimeReplacementLogged": bool(runtime_pattern.search(runtime_log)),
        }
        rows.append(row)

    checks = {
        "allConvertedRecordsMatchCompactDimensions": all(
            row["recordSizeMatchesCompact"] for row in rows
        ),
        "allIndependentExtractionsMatchConvertedRecords": all(
            row["extractedSizeMatchesRecord"] for row in rows
        ),
        "allOriginalsMatchDeclaredHostDimensions": all(
            row["sourceSizeMatchesHost"] for row in rows
        ),
        "allPackFilesMatchDeclaredHostDimensions": all(
            row["packSizeMatchesHost"] for row in rows
        ),
        "allOriginalAndPackFilesByteExact": all(row["sourcePackBytesExact"] for row in rows),
        "allOriginalAndPackPixelsExact": all(row["sourcePackRgbaExact"] for row in rows),
        "allRuntimeReplacementsLogged": all(row["runtimeReplacementLogged"] for row in rows),
        "embeddedModelTexturesAreOriginalResolution": all(
            row["sourceExtractedRgbaExact"] for row in rows
        ),
    }
    report = {
        "schemaVersion": 1,
        "actor": actor,
        "convertedModel": str(args.converted_model.resolve()),
        "independentExtraction": str(args.extracted.resolve()),
        "runtimeLog": str(args.runtime_log.resolve()),
        "textureCount": len(rows),
        "checks": checks,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    make_contact_sheet(rows, args.contact_sheet)

    required = [value for key, value in checks.items() if key != "embeddedModelTexturesAreOriginalResolution"]
    if not all(required):
        failed = [key for key, value in checks.items() if not value and key != "embeddedModelTexturesAreOriginalResolution"]
        raise SystemExit(f"FAIL: {', '.join(failed)}")
    compact = sorted({tuple(row["compactSize"]) for row in rows})
    host = sorted({tuple(row["hostSize"]) for row in rows})
    print(
        f"PASS: {actor} {len(rows)}/{len(rows)} source/pack files are byte- and pixel-exact; "
        f"runtime replaced all pages; compact={compact}; host={host}"
    )
    print(f"report: {args.output.resolve()}")
    print(f"contact sheet: {args.contact_sheet.resolve()}")


if __name__ == "__main__":
    main()
