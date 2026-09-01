#!/usr/bin/env python3
"""Stage the Dreamcast-mesh SM2 Spider-Man actor with all retail costume skins.

SM2 uses one animated ``spidey.psx`` actor and chooses one of nineteen
``sp_texNN.psx`` texture libraries.  The texture libraries do not share one fixed
record order, so this tool preserves every retail library byte-for-byte instead of
normalizing or transcoding it.  Audit-only merged actors let Multitool prove that each
library is structurally usable without changing the files supplied to the game.
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
from typing import Any

import pack_sm2_costume_to_dc as native_pack


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACTOR = (
    ROOT
    / "dreamcast"
    / "converted"
    / "sm2-costume-tests"
    / "runtime"
    / "default"
    / "spidey.psx"
)
DEFAULT_TEXTURES = ROOT / "spiderman2" / "extracted" / "wad"
DEFAULT_OUTPUT = ROOT / "dreamcast" / "converted" / "sm2-spider-man-runtime"
COSTUME_COUNT = 19
SPECIAL_BUILDER = ROOT / "dreamcast" / "tools" / "build_sm2_special_dc_costumes.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", type=Path, default=DEFAULT_ACTOR)
    parser.add_argument("--textures", type=Path, default=DEFAULT_TEXTURES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--multitool", type=Path)
    return parser.parse_args()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def texture_records(data: bytes, layout: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for record_number in range(layout["textureCount"]):
        pointer = native_pack.u32(
            data, layout["texturePointerTable"] + record_number * 4
        )
        if pointer + 20 > len(data):
            raise ValueError(f"texture record {record_number} points past EOF")
        flags, palette_size, cache_id, index, width, height = struct.unpack_from(
            "<IIIIHH", data, pointer
        )
        if index in seen_indices:
            raise ValueError(f"duplicate texture index {index}")
        seen_indices.add(index)
        if width == 0 or height == 0:
            raise ValueError(f"texture index {index} has zero dimensions")
        if palette_size == 16:
            byte_width = ((width + 3) & ~3) // 2
            payload_size = byte_width * height
            if height % 2 and byte_width % 4:
                payload_size += 2
        elif palette_size == 256:
            byte_width = (width + 1) & ~1
            payload_size = byte_width * height
            if height % 2 and byte_width % 4:
                payload_size += 2
        else:
            raise ValueError(
                f"texture index {index} uses unsupported palette size {palette_size}"
            )
        if pointer + 20 + payload_size > len(data):
            raise ValueError(f"texture index {index} payload extends past EOF")
        records.append(
            {
                "record": record_number,
                "index": index,
                "hash": f"0x{layout['textureHashes'][index]:08X}",
                "width": width,
                "height": height,
                "paletteSize": palette_size,
                "cacheId": f"0x{cache_id:08X}",
                "flags": f"0x{flags:08X}",
                "payloadBytes": payload_size,
            }
        )
    expected = set(range(len(layout["textureHashes"])))
    if seen_indices != expected:
        raise ValueError(
            f"texture record indices are {sorted(seen_indices)}, expected {sorted(expected)}"
        )
    return sorted(records, key=lambda item: item["index"])


def main() -> None:
    args = parse_args()
    actor = args.actor.resolve()
    texture_root = args.textures.resolve()
    output = args.output.resolve()
    audit_root = output / "audit-models"
    output.mkdir(parents=True, exist_ok=True)
    audit_root.mkdir(parents=True, exist_ok=True)

    multitool = native_pack.resolve_multitool(args.multitool)
    actor_data = actor.read_bytes()
    actor_layout = native_pack.container_layout(actor_data)
    actor_destination = output / "spidey.psx"
    shutil.copyfile(actor, actor_destination)

    entries: list[dict[str, Any]] = []
    expected_face_count: int | None = None
    with tempfile.TemporaryDirectory(prefix="sm2-costume-pack-audit-") as temporary:
        temporary_root = Path(temporary)
        for slot in range(COSTUME_COUNT):
            name = f"sp_tex{slot:02d}.psx"
            source = texture_root / name
            library_data = source.read_bytes()
            layout = native_pack.container_layout(library_data)
            if len(layout["textureHashes"]) != len(actor_layout["textureHashes"]):
                raise ValueError(
                    f"{name} has {len(layout['textureHashes'])} hashes; actor has "
                    f"{len(actor_layout['textureHashes'])}"
                )
            if layout["textureCount"] != len(layout["textureHashes"]):
                raise ValueError(
                    f"{name} has {layout['textureCount']} texture records and "
                    f"{len(layout['textureHashes'])} hashes"
                )

            records = texture_records(library_data, layout)
            destination = output / name
            shutil.copyfile(source, destination)
            if destination.read_bytes() != library_data:
                raise ValueError(f"{name} changed while staging")

            # This merged file is never supplied to the game. Replacing the actor's
            # hash table with this costume's table makes face indices resolve through
            # the exact library being audited by the standalone model parser.
            audit_data = native_pack.replace_texture_section(
                actor_data, layout["textureHashes"], library_data
            )
            audit_model = audit_root / name
            audit_model.write_bytes(audit_data)
            audit_dump = native_pack.dump_mesh(
                multitool,
                audit_model,
                temporary_root / f"sp_tex{slot:02d}.json",
            )
            face_count = sum(mesh["FaceCount"] for mesh in audit_dump["Meshes"])
            if expected_face_count is None:
                expected_face_count = face_count
            elif face_count != expected_face_count:
                raise ValueError(
                    f"{name} parsed {face_count} faces; expected {expected_face_count}"
                )
            face_hashes = {
                face["TextureHash"]
                for mesh in audit_dump["Meshes"]
                for face in mesh["Faces"]
            }
            unknown = face_hashes.difference(layout["textureHashes"])
            if unknown:
                raise ValueError(
                    f"{name} audit actor has unknown hashes: "
                    + ", ".join(f"0x{value:08X}" for value in sorted(unknown))
                )
            entries.append(
                {
                    "slot": slot,
                    "runtimeFile": str(destination),
                    "runtimeBytes": len(library_data),
                    "runtimeSha256": sha256(library_data),
                    "retailByteExact": True,
                    "materialHashCount": len(layout["textureHashes"]),
                    "textureRecordCount": layout["textureCount"],
                    "recordsByIndex": records,
                    "auditModel": str(audit_model),
                    "auditModelSha256": sha256(audit_data),
                    "auditFaceCount": face_count,
                    "status": "pass",
                }
            )

    subprocess.run(
        [
            sys.executable,
            str(SPECIAL_BUILDER),
            "--output",
            str(output),
        ],
        check=True,
    )
    special_report_path = output / "special-dc-costumes.json"
    special_report = json.loads(special_report_path.read_text(encoding="utf-8"))

    report = {
        "schemaVersion": 1,
        "status": "pass",
        "scope": "SM2 Spider-Man and costumes only; NPC and enemy actors remain retail SM2 assets",
        "runtimePolicy": (
            "one native Dreamcast-mesh spidey.psx plus nineteen byte-exact retail "
            "sp_texNN.psx libraries; topology-changing slots 13 and 17 additionally "
            "stage dedicated Dreamcast actors and texture companions"
        ),
        "environmentPolicy": "retail PS1 SM2 environments are unchanged",
        "actor": {
            "source": str(actor),
            "runtimeFile": str(actor_destination),
            "bytes": len(actor_data),
            "sha256": sha256(actor_data),
            "meshCount": actor_layout["meshCount"],
            "materialCount": len(actor_layout["textureHashes"]),
            "faceCount": expected_face_count,
        },
        "costumeCount": len(entries),
        "costumes": entries,
        "specialTopologyCostumes": {
            "report": str(special_report_path),
            "status": special_report["status"],
            "slots": [entry["slot"] for entry in special_report["results"]],
            "hostTexturePack": special_report["hostTexturePack"],
        },
    }
    report_path = output / "costume-pack.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"PASS: staged one Dreamcast-mesh SM2 Spider-Man actor and "
        f"{len(entries)} retail costume libraries"
    )
    print(f"runtime assets: {output}")
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
