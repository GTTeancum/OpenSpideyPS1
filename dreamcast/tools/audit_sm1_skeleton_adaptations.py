#!/usr/bin/env python3
"""Independently verify SM1 skeleton donors used by Dreamcast actor ports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
JAMESON_ACTORS = {"JAMESON", "JJVIEWER"}
SCORPION_TAIL_MESHES = {
    0xBE6FFB9F,
    0x2766AA25,
    0x50619AB3,
    0xCE050F10,
    0xB9023F86,
    0x200B6E3C,
    0x570C5EAA,
}
SCORPION_HOOK_MESH = 0xAF6C87FE
SCORPION_HOOK_TEXTURE_INDEX = 0
SCORPION_SPLINE_RUNTIME_TEXTURE_INDEX = 18
SCORPION_SPLINE_RUNTIME_TEXTURE_HASH = 0x35A7A03D
SCORPION_SPLINE_COMPATIBILITY_SIZE = (64, 64)


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def mesh_parts(data: bytes, offset: int) -> dict[str, Any]:
    vertex_count, normal_count, face_count = struct.unpack_from("<HHH", data, offset + 2)
    cursor = offset + 28
    vertices = data[cursor : cursor + vertex_count * 8]
    cursor += vertex_count * 8
    normals = data[cursor : cursor + normal_count * 8]
    cursor += normal_count * 8
    faces: list[bytes] = []
    for _ in range(face_count):
        length = u16(data, cursor + 2)
        faces.append(data[cursor : cursor + length])
        cursor += length
    return {
        "counts": [vertex_count, normal_count, face_count],
        "vertices": vertices,
        "normals": normals,
        "faces": faces,
    }


def v4_texture_sizes(data: bytes, cursor: int, mesh_count: int) -> dict[int, tuple[int, int]]:
    """Parse generated v4 texture dimensions after the tagged metadata terminator."""
    cursor += mesh_count * 4
    texture_name_count = u32(data, cursor)
    cursor += 4 + texture_name_count * 4

    palette4_count = u32(data, cursor)
    cursor += 4 + palette4_count * (4 + 16 * 2)
    palette8_count = u32(data, cursor)
    cursor += 4 + palette8_count * (4 + 256 * 2)

    texture_count = u32(data, cursor)
    cursor += 4
    offsets = struct.unpack_from(f"<{texture_count}I", data, cursor) if texture_count else ()
    sizes: dict[int, tuple[int, int]] = {}
    for header_offset in offsets:
        _, _, _, texture_index, width, height = struct.unpack_from(
            "<IIIIHH", data, header_offset
        )
        sizes[texture_index] = (width, height)
    return sizes


def v4_texture_hashes(data: bytes, cursor: int, mesh_count: int) -> tuple[int, ...]:
    cursor += mesh_count * 4
    texture_name_count = u32(data, cursor)
    cursor += 4
    return struct.unpack_from(f"<{texture_name_count}I", data, cursor)


def converted_v6_uvs(face: bytes, dimensions: tuple[int, int]) -> bytes:
    """Reproduce the converter's normalized v6-to-byte UV mapping."""
    width, height = dimensions
    output = bytearray()
    for slot in range(4):
        u = u16(face, 20 + slot * 2)
        v = struct.unpack_from("<h", face, 28 + slot * 2)[0]
        output.extend(((u * width // 512) & 0xFF, (v * height // 512) & 0xFF))
    return bytes(output)


def parse(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    version, magic = struct.unpack_from("<HH", data, 0)
    object_count = u32(data, 8)
    objects = tuple(
        data[12 + index * 36 : 12 + (index + 1) * 36]
        for index in range(object_count)
    )
    mesh_count_offset = 12 + object_count * 36
    mesh_count = u32(data, mesh_count_offset)
    pointer_table = mesh_count_offset + 4
    pointers = tuple(u32(data, pointer_table + index * 4) for index in range(mesh_count))

    cursor = u32(data, 4)
    tagged_start = cursor
    chunks: dict[int, bytes] = {}
    while True:
        tag = u32(data, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(data, cursor)
        cursor += 4
        chunks[tag] = data[cursor : cursor + size]
        cursor += size
    tagged = data[tagged_start:cursor]
    names = tuple(u32(data, cursor + index * 4) for index in range(mesh_count))
    meshes = {name: mesh_parts(data, pointer) for name, pointer in zip(names, pointers)}
    texture_sizes = v4_texture_sizes(data, cursor, mesh_count) if version in (3, 4) else {}
    texture_hashes = v4_texture_hashes(data, cursor, mesh_count) if version in (3, 4) else ()
    return {
        "path": str(path.resolve()),
        "version": version,
        "magic": magic,
        "objects": objects,
        "tagged": tagged,
        "chunks": chunks,
        "names": names,
        "meshes": meshes,
        "textureSizes": texture_sizes,
        "textureHashes": texture_hashes,
    }


def verify_actor(entry: dict[str, Any]) -> dict[str, Any]:
    name = entry["name"]
    source = parse(Path(entry["source"]))
    output = parse(Path(entry["output"]))
    donor = parse(Path(entry["skeletonDonor"]))
    full_skeleton = entry["skeletonPolicy"].startswith("SM1-native object order")
    expected_names = donor["names"] if full_skeleton else source["names"]
    expected_objects = donor["objects"] if full_skeleton else source["objects"]
    checks: dict[str, bool] = {
        "sourceIsV6": source["version"] == 6 and source["magic"] == 2,
        "outputIsV4": output["version"] == 4 and output["magic"] == 2,
        "donorIsV4": donor["version"] in (3, 4) and donor["magic"] == 2,
        "meshNameSetMatchesSource": set(output["names"]) == set(source["names"]),
        "meshOrderMatchesPolicy": output["names"] == expected_names,
        "objectTableMatchesPolicy": output["objects"] == expected_objects,
        "taggedMetadataMatchesDonor": output["tagged"] == donor["tagged"],
    }
    for mesh_name in output["names"]:
        source_mesh = source["meshes"].get(mesh_name)
        output_mesh = output["meshes"].get(mesh_name)
        checks[f"mesh:{mesh_name:08X}:countsPreserved"] = (
            source_mesh is not None
            and output_mesh is not None
            and source_mesh["counts"] == output_mesh["counts"]
        )
        checks[f"mesh:{mesh_name:08X}:verticesPreserved"] = (
            source_mesh is not None
            and output_mesh is not None
            and source_mesh["vertices"] == output_mesh["vertices"]
        )
        checks[f"mesh:{mesh_name:08X}:normalsPreserved"] = (
            source_mesh is not None
            and output_mesh is not None
            and source_mesh["normals"] == output_mesh["normals"]
        )

    if name in JAMESON_ACTORS:
        checks["allFacesUseRetailNeutralLighting"] = all(
            face[8:11] == bytes((110, 110, 110))
            for mesh in output["meshes"].values()
            for face in mesh["faces"]
        )
        checks["dreamcastRgbAnimationRemoved"] = 0x73424752 not in output["chunks"]
        checks["allFacesClearIndexedRgbMode"] = all(
            (u16(face, 0) & 0x0800) == 0
            for mesh in output["meshes"].values()
            for face in mesh["faces"]
        )

    if name == "SCORPION":
        checks["allSevenTailMeshesPresent"] = (
            SCORPION_TAIL_MESHES <= set(output["names"])
        )
        for mesh_name in SCORPION_TAIL_MESHES:
            output_mesh = output["meshes"].get(mesh_name)
            donor_mesh = donor["meshes"].get(mesh_name)
            checks[f"tail:{mesh_name:08X}:retailCountsExact"] = (
                output_mesh is not None
                and donor_mesh is not None
                and output_mesh["counts"] == donor_mesh["counts"]
            )
            checks[f"tail:{mesh_name:08X}:retailVerticesExact"] = (
                output_mesh is not None
                and donor_mesh is not None
                and output_mesh["vertices"] == donor_mesh["vertices"]
            )
            checks[f"tail:{mesh_name:08X}:retailFacesExact"] = (
                output_mesh is not None
                and donor_mesh is not None
                and output_mesh["faces"] == donor_mesh["faces"]
            )

        source_hook = source["meshes"].get(SCORPION_HOOK_MESH)
        output_hook = output["meshes"].get(SCORPION_HOOK_MESH)
        checks["proceduralTailHookPresent"] = source_hook is not None and output_hook is not None
        checks["proceduralTailCompatibilityPageIs64x64"] = (
            output["textureSizes"].get(SCORPION_SPLINE_RUNTIME_TEXTURE_INDEX)
            == SCORPION_SPLINE_COMPATIBILITY_SIZE
        )
        checks["proceduralTailRuntimeAliasHasRetailSemanticHash"] = (
            len(output["textureHashes"]) > SCORPION_SPLINE_RUNTIME_TEXTURE_INDEX
            and output["textureHashes"][SCORPION_SPLINE_RUNTIME_TEXTURE_INDEX]
            == SCORPION_SPLINE_RUNTIME_TEXTURE_HASH
        )
        if source_hook is not None and output_hook is not None:
            source_faces = source_hook["faces"]
            output_faces = output_hook["faces"]
            checks["proceduralTailHookFaceCountPreserved"] = len(source_faces) == len(output_faces)
            paired_faces = list(zip(source_faces, output_faces))
            checks["proceduralTailHookUsesOnlySplineTexture"] = all(
                (u16(output_face, 0) & 0x0003)
                and u32(output_face, 16) == SCORPION_HOOK_TEXTURE_INDEX
                for output_face in output_faces
            )
            hook_dimensions = output["textureSizes"].get(SCORPION_HOOK_TEXTURE_INDEX)
            checks["proceduralTailHookUvsMatchItsCompatibilityPage"] = (
                len(source_faces) == len(output_faces)
                and hook_dimensions is not None
                and all(
                    output_face[20:28]
                    == converted_v6_uvs(source_face, hook_dimensions)
                    for source_face, output_face in paired_faces
                )
            )
            output_us = [
                output_face[20 + slot * 2]
                for output_face in output_faces
                for slot in range(4)
            ]
            checks["proceduralTailHookUvsSpanBothSkinHalves"] = (
                hook_dimensions is not None
                and min(output_us) < hook_dimensions[0] <= max(output_us)
            )

    failed = [key for key, passed in checks.items() if not passed]
    return {
        "name": name,
        "source": source["path"],
        "output": output["path"],
        "donor": donor["path"],
        "policy": entry["skeletonPolicy"],
        "checkCount": len(checks),
        "failedChecks": failed,
        "status": "pass" if not failed else "fail",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch = args.batch.resolve()
    manifest_path = batch / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [entry for entry in manifest["entries"] if entry.get("skeletonDonor")]
    actors = [verify_actor(entry) for entry in entries]
    status = "pass" if actors and all(actor["status"] == "pass" for actor in actors) else "fail"
    report = {
        "schemaVersion": 1,
        "batch": str(batch),
        "actorCount": len(actors),
        "actors": actors,
        "status": status,
    }
    output = (
        args.output.resolve()
        if args.output is not None
        else batch / "skeleton-adaptation-audit.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{status.upper()}: {len(actors)} SM1 skeleton adaptations")
    for actor in actors:
        print(
            f"  {actor['name']:10s} {actor['status']:4s} "
            f"checks={actor['checkCount']} failed={len(actor['failedChecks'])}"
        )
    print(f"report: {output}")
    if status != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
