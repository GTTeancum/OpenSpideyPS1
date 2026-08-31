#!/usr/bin/env python3
"""Audit every generated actor page against its full-resolution texture pack.

This is intentionally independent of ``port_dc_character.py``. It parses the
generated v4 containers directly, reconstructs the runtime replacement keys,
and proves that each key resolves to the original Dreamcast RGBA pixels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
FNV_OFFSET = 1469598103934665603
FNV_PRIME = 1099511628211
MAGENTA_555 = 0x7C1F


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pack-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def image_identity(path: Path) -> tuple[tuple[int, int], str]:
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    return image.size, hashlib.sha256(
        struct.pack("<II", image.width, image.height) + image.tobytes()
    ).hexdigest()


def fnv1a64(data: bytes) -> int:
    value = FNV_OFFSET
    for byte in data:
        value = ((value ^ byte) * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return value


def replacement_key(
    width: int,
    height: int,
    palette: tuple[int, ...],
    payload: bytes,
) -> str:
    if width & 1 or len(payload) != width * height:
        raise ValueError(f"invalid compact 8-bit page {width}x{height} ({len(payload)} bytes)")
    index_hash = fnv1a64(struct.pack("<BHH", 8, width, height) + payload)
    clut_bytes = bytearray()
    for index in sorted(set(payload)):
        color = palette[index]
        runtime_color = 0 if color == MAGENTA_555 else color | 0x8000
        clut_bytes.extend((index, runtime_color & 0xFF, runtime_color >> 8))
    return f"{index_hash:016x}_{fnv1a64(bytes(clut_bytes)):016x}"


def parse_generated_textures(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 16 or struct.unpack_from("<H", data, 0)[0] != 4:
        raise ValueError("not a generated v4 model")

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
    cursor += 4
    cursor += palette4_count * (4 + 16 * 2)

    palette8_count = u32(data, cursor)
    cursor += 4
    palettes: dict[int, tuple[int, ...]] = {}
    for _ in range(palette8_count):
        cache_id = u32(data, cursor)
        cursor += 4
        palette = struct.unpack_from("<256H", data, cursor)
        cursor += 256 * 2
        if cache_id in palettes and palettes[cache_id] != palette:
            raise ValueError(f"conflicting palette declarations for 0x{cache_id:08X}")
        palettes[cache_id] = palette

    texture_count = u32(data, cursor)
    cursor += 4
    offsets = (
        struct.unpack_from(f"<{texture_count}I", data, cursor)
        if texture_count
        else ()
    )
    records: dict[int, dict[str, Any]] = {}
    for header_offset in offsets:
        _, palette_size, cache_id, texture_index, width, height = struct.unpack_from(
            "<IIIIHH", data, header_offset
        )
        if palette_size != 256:
            raise ValueError(
                f"texture {texture_index} has unsupported palette size {palette_size}"
            )
        if cache_id not in palettes:
            raise ValueError(
                f"texture {texture_index} references missing palette 0x{cache_id:08X}"
            )
        if texture_index in records:
            raise ValueError(f"duplicate texture index {texture_index}")
        payload_size = width * height
        payload = data[header_offset + 20 : header_offset + 20 + payload_size]
        if len(payload) != payload_size:
            raise ValueError(f"texture {texture_index} payload is truncated")
        records[texture_index] = {
            "cacheId": cache_id,
            "size": (width, height),
            "runtimeKey": replacement_key(width, height, palettes[cache_id], payload),
        }
    if texture_count != texture_name_count:
        raise ValueError(
            f"texture-name count {texture_name_count} != record count {texture_count}"
        )
    return {
        "paletteDeclarationCount": palette8_count,
        "paletteIds": sorted(palettes),
        "records": records,
    }


def main() -> None:
    args = parse_args()
    batch = args.batch.resolve()
    manifest_path = (args.manifest or batch / "manifest.json").resolve()
    pack_manifest_path = (
        args.pack_manifest
        or batch / "packs" / "dreamcast-sm1-actors" / "texture-manifest.json"
    ).resolve()
    output = (args.output or pack_manifest_path.with_name("texture-audit.json")).resolve()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pack_manifest = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
    actor_entries = {
        entry["name"].upper(): entry
        for entry in manifest["entries"]
        if entry["action"] == "converted_v6_to_v4"
    }
    mappings_by_actor: dict[str, list[dict[str, Any]]] = {}
    for mapping in pack_manifest["entries"]:
        mappings_by_actor.setdefault(mapping["actor"].upper(), []).append(mapping)

    errors: list[str] = []
    actor_reports: dict[str, dict[str, Any]] = {}
    source_identity_by_key: dict[str, str] = {}
    expected_pack_files: set[str] = set()
    verified_mappings = 0

    for actor, entry in sorted(actor_entries.items()):
        path = Path(entry["output"])
        try:
            parsed = parse_generated_textures(path)
            records = parsed["records"]
            mappings = mappings_by_actor.get(actor, [])
            mapped_indices = {int(mapping["textureIndex"]) for mapping in mappings}
            expected_unmapped = {max(records)} if actor == "SPIDEY" and records else set()
            if set(records) - mapped_indices != expected_unmapped:
                raise ValueError(
                    f"unmapped compact records {sorted(set(records) - mapped_indices)}; "
                    f"expected {sorted(expected_unmapped)}"
                )
            if mapped_indices - set(records):
                raise ValueError(
                    f"pack maps missing records {sorted(mapped_indices - set(records))}"
                )

            normal_ids = {
                records[index]["cacheId"] for index in mapped_indices
            }
            expected_declarations = int(bool(mapped_indices)) + int(bool(expected_unmapped))
            if len(normal_ids) != int(bool(mapped_indices)):
                raise ValueError(f"actor pages use {len(normal_ids)} compatibility CLUTs")
            if parsed["paletteDeclarationCount"] != expected_declarations:
                raise ValueError(
                    f"has {parsed['paletteDeclarationCount']} palette declarations; "
                    f"expected {expected_declarations}"
                )

            for mapping in mappings:
                index = int(mapping["textureIndex"])
                record = records[index]
                if list(record["size"]) != list(mapping["compatibilitySize"]):
                    raise ValueError(f"texture {index} compatibility size mismatch")
                if record["runtimeKey"] != mapping["runtimeKey"]:
                    raise ValueError(
                        f"texture {index} runtime key {record['runtimeKey']} != "
                        f"manifest {mapping['runtimeKey']}"
                    )

                source = Path(mapping["source"])
                packed = Path(mapping["output"])
                source_size, source_digest = image_identity(source)
                pack_size, pack_digest = image_identity(packed)
                if source_size != tuple(mapping["hostSize"]) or pack_size != source_size:
                    raise ValueError(f"texture {index} host dimensions mismatch")
                if source_digest != mapping["sha256"] or pack_digest != source_digest:
                    raise ValueError(f"texture {index} source/pack RGBA mismatch")
                if packed.stem != mapping["runtimeKey"]:
                    raise ValueError(f"texture {index} pack filename does not match key")

                prior = source_identity_by_key.get(mapping["runtimeKey"])
                if prior is not None and prior != source_digest:
                    raise ValueError(f"texture {index} key collides with distinct RGBA pixels")
                source_identity_by_key[mapping["runtimeKey"]] = source_digest
                expected_pack_files.add(packed.name)
                verified_mappings += 1

            actor_reports[actor] = {
                "recordCount": len(records),
                "mappedCount": len(mappings),
                "paletteDeclarationCount": parsed["paletteDeclarationCount"],
                "paletteIds": [f"0x{value:08X}" for value in parsed["paletteIds"]],
                "status": "pass",
            }
        except Exception as error:
            errors.append(f"{actor}: {error}")
            actor_reports[actor] = {"status": "fail", "error": str(error)}

    scorpion_mappings = mappings_by_actor.get("SCORPION", [])
    scorpion_aliases = [
        mapping
        for mapping in scorpion_mappings
        if mapping.get("role") == "SM1 procedural spline runtime alias"
    ]
    if len(scorpion_aliases) != 1:
        errors.append(
            "SCORPION: expected exactly one SM1 procedural spline runtime alias"
        )
    else:
        alias = scorpion_aliases[0]
        source_mapping = next(
            (
                mapping
                for mapping in scorpion_mappings
                if int(mapping["textureIndex"]) == int(alias["sourceTextureIndex"])
            ),
            None,
        )
        if (
            int(alias["textureIndex"]) != 18
            or int(alias["sourceTextureIndex"]) != 0
            or list(alias["compatibilitySize"]) != [64, 64]
            or list(alias["hostSize"]) != [128, 128]
            or source_mapping is None
            or alias["source"] != source_mapping["source"]
            or alias["sha256"] != source_mapping["sha256"]
        ):
            errors.append(
                "SCORPION: spline alias does not map runtime index 18 to the "
                "source-exact 128x128 Dreamcast index-0 skin through a 64x64 page"
            )

    unexpected_actors = sorted(set(mappings_by_actor) - set(actor_entries))
    if unexpected_actors:
        errors.append(f"pack contains non-converted actors: {unexpected_actors}")
    if verified_mappings != pack_manifest["mappingCount"]:
        errors.append(
            f"verified mapping count {verified_mappings} != manifest "
            f"{pack_manifest['mappingCount']}"
        )
    if len(source_identity_by_key) != pack_manifest["uniqueRuntimeKeyCount"]:
        errors.append(
            f"verified unique key count {len(source_identity_by_key)} != manifest "
            f"{pack_manifest['uniqueRuntimeKeyCount']}"
        )

    texture_root = pack_manifest_path.parent / "textures"
    actual_pack_files = {path.name for path in texture_root.glob("*.png")}
    if actual_pack_files != expected_pack_files:
        errors.append(
            f"pack file set mismatch; missing={sorted(expected_pack_files - actual_pack_files)} "
            f"extra={sorted(actual_pack_files - expected_pack_files)}"
        )

    report = {
        "schemaVersion": 1,
        "batchManifest": str(manifest_path),
        "packManifest": str(pack_manifest_path),
        "convertedActorCount": len(actor_entries),
        "verifiedMappingCount": verified_mappings,
        "verifiedUniqueRuntimeKeyCount": len(source_identity_by_key),
        "packFileCount": len(actual_pack_files),
        "perActor": actor_reports,
        "errors": errors,
        "status": "pass" if not errors else "fail",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        print(f"report: {output}")
        raise SystemExit(1)
    print(
        f"PASS: {len(actor_entries)} converted actors; {verified_mappings} mappings; "
        f"{len(source_identity_by_key)} unique runtime keys; "
        f"{len(actual_pack_files)} exact full-resolution PNGs"
    )
    print(f"report: {output}")


if __name__ == "__main__":
    main()
