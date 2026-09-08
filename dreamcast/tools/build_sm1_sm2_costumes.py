#!/usr/bin/env python3
"""Build the SM2-exclusive costumes as self-contained SM1 actors.

The native SM2 costume pages and the high-detail Dreamcast body are retained. SM1's
compatible hierarchy/animation metadata replaces SM2's. The imported costumes retain
their authored SM2 wing pixels: seven are visible, while Prodigy and Venom Earth-X
remain transparent. The other retail disc is build input only; these outputs are the
files shipped to SM1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

import pack_sm2_costume_to_dc as native_pack


ROOT = Path(__file__).resolve().parents[2]
PACKER = ROOT / "dreamcast" / "tools" / "pack_sm2_costume_to_dc.py"
DEFAULT_SM1_SKELETON = ROOT / "spiderman" / "extracted" / "wad" / "spidey.psx"
DEFAULT_SM2_MODEL = ROOT / "spiderman2" / "extracted" / "wad" / "spidey.psx"
DEFAULT_SM2_TEXTURES = ROOT / "spiderman2" / "extracted" / "wad"
DEFAULT_OUTPUT = ROOT / "dreamcast" / "converted" / "sm1-sm2-costumes"
DEFAULT_MAPPINGS = (
    ROOT / "dreamcast" / "manifests" / "sm1-sm2-costume-native-maps"
)
IMPORTED_COSTUMES = (
    (1, "sp2phoenix"),
    (2, "sp2prodigy"),
    (3, "sp2dusk"),
    (4, "sp2insulated"),
    (5, "sp2rossred"),
    (6, "sp2rosswhite"),
    (7, "sp2venomx"),
    (8, "sp2negative"),
    (18, "sp2battle"),
)
AUTHORED_WINGED_SLOTS = frozenset({1, 3, 4, 5, 6, 8, 18})
AUTHORED_WINGLESS_SLOTS = frozenset({2, 7})
PALETTE_NAMESPACE = b"OpenSpideyPS1/SM1-imported-SM2-costume-palette/v1\0"
# The converted actor's material table, keyed by the texture record's semantic
# index. SM2 costume libraries do not all store their records in the same order
# (Dusk is the clearest counterexample), so translating the hash array by ordinal
# cross-wires texture pages even though every library contains the same 14 indices.
SM1_RUNTIME_HASH_BY_TEXTURE_INDEX = {
    0: 0x1A501534,
    1: 0x933EF22C,
    2: 0x08BD6474,
    3: 0xDC38D248,
    4: 0x4E1E5E1A,
    5: 0x1527743E,
    6: 0x3ED5F30B,
    7: 0xCEB60740,
    8: 0x3BC194AE,
    9: 0x42985F7A,
    10: 0xE9587C6D,
    11: 0x197BC27A,
    12: 0x21AFE1A6,
    13: 0x7FFB7AAD,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def texture_records(data: bytes, layout: dict) -> list[int]:
    return [
        native_pack.u32(data, layout["texturePointerTable"] + index * 4)
        for index in range(layout["textureCount"])
    ]


def remapped_palette_id(slot: int, ordinal: int, old_id: int) -> int:
    digest = hashlib.sha256(
        PALETTE_NAMESPACE + struct.pack("<III", slot, ordinal, old_id)
    ).digest()
    value = struct.unpack_from("<I", digest)[0]
    return value or 1


def prepare_texture_library(
    source: Path,
    slot: int,
    *,
    hide_wings: bool = False,
) -> tuple[bytes, dict]:
    data = bytearray(source.read_bytes())
    layout = native_pack.container_layout(data)
    if len(layout["textureHashes"]) != len(SM1_RUNTIME_HASH_BY_TEXTURE_INDEX):
        raise ValueError(
            f"{source} has {len(layout['textureHashes'])} material hashes; "
            f"expected {len(SM1_RUNTIME_HASH_BY_TEXTURE_INDEX)}"
        )
    records = texture_records(data, layout)
    texture_indices = [native_pack.u32(data, pointer + 12) for pointer in records]
    if set(texture_indices) != set(SM1_RUNTIME_HASH_BY_TEXTURE_INDEX):
        raise ValueError(
            f"{source} texture indices {sorted(texture_indices)} do not match the "
            f"converted actor indices {sorted(SM1_RUNTIME_HASH_BY_TEXTURE_INDEX)}"
        )
    cursor = layout["textureSection"]
    palette4_count = native_pack.u32(data, cursor)
    cursor += 4
    declarations: list[tuple[int, int]] = []
    for _ in range(palette4_count):
        current_id = native_pack.u32(data, cursor)
        declarations.append((cursor, current_id))
        cursor += 4 + 16 * 2

    palette8_count = native_pack.u32(data, cursor)
    cursor += 4
    for _ in range(palette8_count):
        current_id = native_pack.u32(data, cursor)
        declarations.append((cursor, current_id))
        cursor += 4 + 256 * 2
    old_ids = list(dict.fromkeys(current_id for _, current_id in declarations))
    remap = {
        old_id: remapped_palette_id(slot, ordinal, old_id)
        for ordinal, old_id in enumerate(old_ids)
    }
    if len(set(remap.values())) != len(remap):
        raise ValueError(f"{source} generated duplicate palette-cache ids")
    for offset, old_id in declarations:
        struct.pack_into("<I", data, offset, remap[old_id])
    for pointer in records:
        old_id = native_pack.u32(data, pointer + 8)
        if old_id not in remap:
            raise ValueError(
                f"{source} texture record refers to undeclared palette 0x{old_id:08X}"
            )
        struct.pack_into("<I", data, pointer + 8, remap[old_id])
    translated_hashes = tuple(
        SM1_RUNTIME_HASH_BY_TEXTURE_INDEX[index] for index in texture_indices
    )
    struct.pack_into(
        f"<{len(translated_hashes)}I",
        data,
        layout["hashCountOffset"] + 4,
        *translated_hashes,
    )
    return bytes(data), {
        "source": str(source),
        "paletteCacheIdsRemapped": len(remap),
        "materialHashesTranslatedForSm1": len(translated_hashes),
        "materialHashTranslation": "by-texture-index",
        "wingPolicy": (
            "dedicated-appended-magenta-key" if hide_wings else "preserved"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sm1-skeleton", type=Path, default=DEFAULT_SM1_SKELETON)
    parser.add_argument("--sm2-model", type=Path, default=DEFAULT_SM2_MODEL)
    parser.add_argument("--sm2-textures", type=Path, default=DEFAULT_SM2_TEXTURES)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--slots",
        default=",".join(str(slot) for slot, _ in IMPORTED_COSTUMES),
        help="comma-separated SM2 texture slots to build",
    )
    parser.add_argument("--multitool", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    authored_slots = AUTHORED_WINGED_SLOTS | AUTHORED_WINGLESS_SLOTS
    imported_slots = {slot for slot, _ in IMPORTED_COSTUMES}
    if authored_slots != imported_slots or AUTHORED_WINGED_SLOTS & AUTHORED_WINGLESS_SLOTS:
        raise RuntimeError("authored wing policy must classify every imported costume exactly once")
    selected_slots = {
        int(value.strip()) for value in args.slots.split(",") if value.strip()
    }
    available_slots = {slot for slot, _ in IMPORTED_COSTUMES}
    if not selected_slots or not selected_slots <= available_slots:
        raise ValueError(
            f"--slots must select one or more of {sorted(available_slots)}"
        )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    default_mapping = args.mappings.resolve() / "sp2default.json"
    if not default_mapping.is_file():
        raise FileNotFoundError(f"default web-wing face map is missing: {default_mapping}")

    with tempfile.TemporaryDirectory(prefix="sm1-sm2-costumes-") as temporary:
        temporary_root = Path(temporary)
        prepared_default, default_report = prepare_texture_library(
            args.sm2_textures.resolve() / "sp_tex00.psx", 0
        )
        prepared_default_path = temporary_root / "sp_tex00.psx"
        prepared_default_path.write_bytes(prepared_default)
        actor_path = output / "sp2body.psx"
        actor_textures = temporary_root / "packed-sp_tex00.psx"
        pack_report = output / "sp2body-pack.json"
        command = [
            sys.executable,
            str(PACKER),
            "--sm2-model",
            str(args.sm2_model.resolve()),
            "--skeleton-model",
            str(args.sm1_skeleton.resolve()),
            "--sm2-textures",
            str(prepared_default_path),
            "--mapping",
            str(default_mapping),
            "--output-model",
            str(actor_path),
            "--output-textures",
            str(actor_textures),
            "--report",
            str(pack_report),
        ]
        if args.multitool is not None:
            command.extend(("--multitool", str(args.multitool.resolve())))
        subprocess.run(command, check=True)

        # Slot 19 is an independently selectable copy of the default SM2 actor.
        # Keep a separately named file even though its initial pixels/stat profile
        # match default SM1 Spider-Man; this prevents later texture/model upgrades
        # from coupling the two roster entries.
        default_actor_path = output / "sp2default.psx"
        shutil.copy2(actor_path, default_actor_path)

        for slot, runtime_stem in IMPORTED_COSTUMES:
            if slot not in selected_slots:
                continue
            source = args.sm2_textures.resolve() / f"sp_tex{slot:02d}.psx"
            mapping_path = args.mappings.resolve() / f"{runtime_stem}.json"
            if not mapping_path.is_file():
                raise FileNotFoundError(
                    f"approved native face map is missing for slot {slot}: {mapping_path}"
                )
            prepared, report = prepare_texture_library(
                source,
                slot,
            )
            texture_path = output / f"sp2tex{slot:02d}.psx"
            texture_path.write_bytes(prepared)
            runtime_path = output / f"{runtime_stem}.psx"
            pack_report_path = output / f"{runtime_stem}.json"
            command = [
                sys.executable,
                str(PACKER),
                "--sm2-model",
                str(args.sm2_model.resolve()),
                "--skeleton-model",
                str(args.sm1_skeleton.resolve()),
                "--sm2-textures",
                str(texture_path),
                "--mapping",
                str(mapping_path),
                "--output-model",
                str(runtime_path),
                "--output-textures",
                str(texture_path),
                "--report",
                str(pack_report_path),
            ]
            if args.multitool is not None:
                command.extend(("--multitool", str(args.multitool.resolve())))
            subprocess.run(command, check=True)
            report.update(
                {
                    "sm2Slot": slot,
                    "authoredWingState": (
                        "visible"
                        if slot in AUTHORED_WINGED_SLOTS
                        else "transparent"
                    ),
                    "runtimeFile": str(runtime_path),
                    "runtimeBytes": runtime_path.stat().st_size,
                    "runtimeSha256": sha256(runtime_path.read_bytes()),
                    "textureLibrary": str(texture_path),
                    "textureLibrarySha256": sha256(texture_path.read_bytes()),
                    "textureRepeat": json.loads(pack_report_path.read_text(encoding="utf-8"))["textureRepeat"],
                    "nativeFaceMap": str(mapping_path),
                    "nativeFaceMapSha256": sha256(mapping_path.read_bytes()),
                    "packReport": str(pack_report_path),
                }
            )
            results.append(report)

    actor_data = actor_path.read_bytes()
    report = {
        "schemaVersion": 1,
        "status": "pass",
        "scope": "selected SM2-exclusive actors with source-authored wing visibility plus default SM2 with wings",
        "selectedSlots": sorted(selected_slots),
        "sm1Skeleton": str(args.sm1_skeleton.resolve()),
        "sm2Model": str(args.sm2_model.resolve()),
        "actor": {
            "runtimeFile": str(actor_path),
            "runtimeBytes": len(actor_data),
            "runtimeSha256": sha256(actor_data),
            "embeddedDefaultWing": default_report,
            "packReport": str(pack_report),
        },
        "defaultWingedCostume": {
            "nativeFaceMap": str(default_mapping),
            "nativeFaceMapSha256": sha256(default_mapping.read_bytes()),
            "runtimeFile": str(default_actor_path),
            "runtimeBytes": default_actor_path.stat().st_size,
            "runtimeSha256": sha256(default_actor_path.read_bytes()),
            "unlockedByDefault": True,
        },
        "costumes": results,
    }
    report_path = output / "sm1-sm2-costumes.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"PASS: built {len(results)} source-authored SM2-exclusive actors and one winged default at {output}"
    )
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
