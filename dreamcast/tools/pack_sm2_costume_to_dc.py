#!/usr/bin/env python3
"""Pack an SM2 costume onto the high-detail Dreamcast Spider-Man actor.

The Blender GLB is only a UV/material proof.  This tool rebuilds the native v4
actor from the original Dreamcast v6 geometry, applies the proven per-face
mapping to the native face records, restores the SM2 hierarchy/animation data,
and embeds the original SM2 texture library.  Both open/closed hand variants
are mapped by their stable mesh names even though a static GLB shows only one.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONVERTER = ROOT / "spiderman" / "tools" / "port_dc_character.py"
DEFAULT_DC_MODEL = ROOT / "dreamcast" / "extracted" / "SPIDEY.PSX"
DEFAULT_DC_TEXTURES = ROOT / "dreamcast" / "decoded" / "textures" / "SPIDEY"
DEFAULT_SM2_MODEL = ROOT / "spiderman2" / "extracted" / "wad" / "spidey.psx"
DEFAULT_SM2_TEXTURES = ROOT / "spiderman2" / "extracted" / "wad" / "sp_tex00.psx"
DEFAULT_MAPPING = (
    ROOT
    / "dreamcast"
    / "converted"
    / "sm2-costume-tests"
    / "ports"
    / "default"
    / "native-face-map.json"
)
DEFAULT_OUTPUT_ROOT = (
    ROOT / "dreamcast" / "converted" / "sm2-costume-tests" / "runtime" / "default"
)
WING_HASH = 0xDC38D248
HAND_MESH_NAMES = frozenset(
    {
        0x08A2712E,
        0xBC8D77AD,
        0x7E8091DC,
        0xCAAF975F,
    }
)
MATERIAL_PATTERN = re.compile(r"tex_([0-9a-f]{8})", re.IGNORECASE)


def load_converter():
    spec = importlib.util.spec_from_file_location("dc_character_converter", CONVERTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load converter at {CONVERTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def material_hash(name: str) -> int:
    match = MATERIAL_PATTERN.search(name)
    if match is None:
        raise ValueError(f"material name does not contain a PSX hash: {name}")
    return int(match.group(1), 16)


def resolve_multitool(explicit: Path | None) -> Path:
    candidates = [
        explicit,
        Path(value) if (value := os.environ.get("MULTITOOL")) else None,
        Path(found) if (found := shutil.which("NeversoftMultitool")) else None,
        Path(
            r"C:\Users\smmel\AppData\Local\Temp\neversoft-multitool-codex"
            r"\src\NeversoftMultitool\bin\Debug\net10.0\NeversoftMultitool.exe"
        ),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("NeversoftMultitool was not found; pass --multitool")


def dump_mesh(multitool: Path, model: Path, output: Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(multitool), "psx-mesh-dump", str(model), "--json", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"mesh dump failed for {model} ({result.returncode}):\n"
            f"{result.stdout}{result.stderr}"
        )
    return json.loads(output.read_text(encoding="utf-8"))


def container_layout(data: bytes) -> dict[str, Any]:
    version, magic = struct.unpack_from("<HH", data, 0)
    if (version, magic) != (4, 2):
        raise ValueError(f"expected v4 PSX container, got v{version} magic {magic:04X}")
    object_count = u32(data, 8)
    mesh_count_offset = 12 + object_count * 36
    mesh_count = u32(data, mesh_count_offset)
    pointer_table = mesh_count_offset + 4
    mesh_pointers = tuple(
        u32(data, pointer_table + index * 4) for index in range(mesh_count)
    )
    cursor = u32(data, 4)
    while True:
        tag = u32(data, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(data, cursor)
        cursor += 4 + size
    mesh_names = tuple(u32(data, cursor + index * 4) for index in range(mesh_count))
    cursor += mesh_count * 4
    hash_count_offset = cursor
    hash_count = u32(data, cursor)
    cursor += 4
    texture_hashes = tuple(
        u32(data, cursor + index * 4) for index in range(hash_count)
    )
    cursor += hash_count * 4
    texture_section = cursor
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
    return {
        "meshCount": mesh_count,
        "meshPointerTable": pointer_table,
        "meshPointers": mesh_pointers,
        "meshNames": mesh_names,
        "hashCountOffset": hash_count_offset,
        "textureHashes": texture_hashes,
        "textureSection": texture_section,
        "texturePointerTable": cursor,
        "textureCount": texture_count,
    }


def emitted_slot_orders(face: dict[str, Any]) -> list[tuple[int, int, int]]:
    result = [(0, 2, 1)]
    if face["IsQuad"]:
        result.append((1, 2, 3))
    return result


def native_to_blender(position: dict[str, float]) -> tuple[float, float, float]:
    return (position["X"], position["Z"], -position["Y"])


def native_position(position: dict[str, float]) -> tuple[float, float, float]:
    return (position["X"], position["Y"], position["Z"])


def polygon_key(
    texture_hash: int,
    positions: Iterable[Iterable[float]],
    uvs: Iterable[Iterable[float]],
) -> tuple[Any, ...]:
    # JSON mesh dumps and Blender's imported floats differ at roughly 1e-6.
    # Four decimal places is still much tighter than the 1/36 native position grid.
    return (
        texture_hash,
        tuple(tuple(round(value, 4) for value in position) for position in positions),
        tuple(tuple(round(value, 7) for value in uv) for uv in uvs),
    )


def source_dimensions(mapping: dict[str, Any]) -> dict[int, tuple[int, int]]:
    result: dict[int, tuple[int, int]] = {}
    for polygon in mapping["polygons"]:
        for field in ("original", "mapped"):
            item = polygon[field]
            texture_hash = material_hash(item["material"])
            dimensions = tuple(item["imageSize"])
            if texture_hash in result and result[texture_hash] != dimensions:
                raise ValueError(
                    f"material {texture_hash:08X} has conflicting image dimensions"
                )
            result[texture_hash] = dimensions
    return result


def match_static_mapping(
    target_dump: dict[str, Any],
    mapping: dict[str, Any],
    dimensions: dict[int, tuple[int, int]],
) -> tuple[dict[tuple[int, int], list[tuple[int, dict[str, Any]]]], dict[str, int]]:
    lookup: dict[tuple[Any, ...], list[tuple[int, int, int]]] = defaultdict(list)
    for mesh in target_dump["Meshes"]:
        if mesh["NameHash"] in HAND_MESH_NAMES:
            continue
        mesh_index = mesh["MeshIndex"]
        for face in mesh["Faces"]:
            face_index = face["FaceIndex"]
            texture_hash = face["TextureHash"]
            if texture_hash == WING_HASH:
                continue
            width, height = dimensions[texture_hash]
            for triangle_index, slots in enumerate(emitted_slot_orders(face)):
                positions = [
                    native_to_blender(face["ResolvedWorldVertices"][slot])
                    for slot in slots
                ]
                uvs = [
                    (
                        (face["TextureCoordinates"][slot]["U"] + 0.5) / width,
                        (face["TextureCoordinates"][slot]["V"] + 0.5) / height,
                    )
                    for slot in slots
                ]
                lookup[polygon_key(texture_hash, positions, uvs)].append(
                    (mesh_index, face_index, triangle_index)
                )

    used: Counter[tuple[Any, ...]] = Counter()
    matched: dict[tuple[int, int], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    semantic_glb_polygons = 0
    for polygon in mapping["polygons"]:
        original = polygon["original"]
        key = polygon_key(
            material_hash(original["material"]),
            original["positions"],
            original["uvs"],
        )
        candidates = lookup.get(key, [])
        if not candidates:
            # Static geometry is proven complete below.  Any remaining GLB
            # polygons belong to alternate hand meshes or donor-exact wings.
            # Hands are mapped semantically because only one pose is visible in
            # a static export; wing packets retain their native UVs directly.
            semantic_glb_polygons += 1
            continue
        ordinal = used[key]
        if ordinal >= len(candidates):
            raise ValueError(
                f"static polygon {polygon['polygonIndex']} does not match a native target triangle"
            )
        mesh_index, face_index, triangle_index = candidates[ordinal]
        used[key] += 1
        matched[(mesh_index, face_index)].append((triangle_index, polygon))

    expected_static_polygons = sum(len(candidates) for candidates in lookup.values())
    matched_static_polygons = sum(len(items) for items in matched.values())
    if matched_static_polygons != expected_static_polygons:
        raise ValueError(
            f"static mapping proves {matched_static_polygons} of "
            f"{expected_static_polygons} native target triangles"
        )

    return matched, {
        "staticPolygons": len(mapping["polygons"]),
        "matchedStaticPolygons": matched_static_polygons,
        "semanticGlbPolygons": semantic_glb_polygons,
        "matchedNativeFaces": len(matched),
    }


def sub(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(x - y for x, y in zip(a, b))


def add(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(x + y for x, y in zip(a, b))


def mul(a: tuple[float, ...], amount: float) -> tuple[float, ...]:
    return tuple(x * amount for x in a)


def dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b))


def closest_point(
    point: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return the closest point and barycentric weights (Ericson region tests)."""
    ab = sub(b, a)
    ac = sub(c, a)
    ap = sub(point, a)
    d1 = dot(ab, ap)
    d2 = dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return a, (1.0, 0.0, 0.0)

    bp = sub(point, b)
    d3 = dot(ab, bp)
    d4 = dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return b, (0.0, 1.0, 0.0)

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        amount = d1 / (d1 - d3)
        return add(a, mul(ab, amount)), (1.0 - amount, amount, 0.0)

    cp = sub(point, c)
    d5 = dot(ab, cp)
    d6 = dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return c, (0.0, 0.0, 1.0)

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        amount = d2 / (d2 - d6)
        return add(a, mul(ac, amount)), (1.0 - amount, 0.0, amount)

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and d4 - d3 >= 0.0 and d5 - d6 >= 0.0:
        amount = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return add(b, mul(sub(c, b), amount)), (0.0, 1.0 - amount, amount)

    denominator = 1.0 / (va + vb + vc)
    v = vb * denominator
    w = vc * denominator
    return add(a, add(mul(ab, v), mul(ac, w))), (1.0 - v - w, v, w)


@dataclass(frozen=True)
class SourceTriangle:
    positions: tuple[tuple[float, float, float], ...]
    uvs: tuple[tuple[float, float], ...]
    texture_hash: int


def mesh_triangles(
    source_dump: dict[str, Any],
    dimensions: dict[int, tuple[int, int]],
) -> dict[int, list[SourceTriangle]]:
    result: dict[int, list[SourceTriangle]] = {}
    for mesh in source_dump["Meshes"]:
        triangles: list[SourceTriangle] = []
        for face in mesh["Faces"]:
            texture_hash = face["TextureHash"]
            width, height = dimensions[texture_hash]
            for slots in emitted_slot_orders(face):
                triangles.append(
                    SourceTriangle(
                        tuple(
                            native_position(face["ResolvedWorldVertices"][slot])
                            for slot in slots
                        ),
                        tuple(
                            (
                                (face["TextureCoordinates"][slot]["U"] + 0.5)
                                / width,
                                (face["TextureCoordinates"][slot]["V"] + 0.5)
                                / height,
                            )
                            for slot in slots
                        ),
                        texture_hash,
                    )
                )
        result[mesh["NameHash"]] = triangles
    return result


def semantic_face_mapping(
    face: dict[str, Any],
    candidates: list[SourceTriangle],
) -> tuple[int, list[tuple[float, float]]]:
    slot_count = 4 if face["IsQuad"] else 3
    positions = [
        native_position(face["ResolvedWorldVertices"][slot])
        for slot in range(slot_count)
    ]
    center = tuple(
        sum(position[axis] for position in positions) / slot_count
        for axis in range(3)
    )
    nearest: tuple[float, SourceTriangle] | None = None
    for triangle in candidates:
        location, _ = closest_point(center, *triangle.positions)
        distance = dot(sub(center, location), sub(center, location))
        if nearest is None or distance < nearest[0]:
            nearest = (distance, triangle)
    if nearest is None:
        raise ValueError("semantic target mesh has no source triangles")
    triangle = nearest[1]
    mapped_uvs: list[tuple[float, float]] = []
    for position in positions:
        _, weights = closest_point(position, *triangle.positions)
        mapped_uvs.append(
            tuple(
                sum(weights[index] * triangle.uvs[index][axis] for index in range(3))
                for axis in range(2)
            )
        )
    return triangle.texture_hash, mapped_uvs


def static_face_mappings(
    face: dict[str, Any],
    polygons: list[tuple[int, dict[str, Any]]],
) -> tuple[list[tuple[int, list[tuple[float, float]]]], bool]:
    by_triangle = {triangle_index: polygon for triangle_index, polygon in polygons}
    expected = 2 if face["IsQuad"] else 1
    if set(by_triangle) != set(range(expected)):
        raise ValueError(
            f"native face {face['FaceIndex']} has incomplete static triangle mapping"
        )
    first = by_triangle[0]["mapped"]
    texture_hash = material_hash(first["material"])
    if not face["IsQuad"]:
        # Emitted order is native slots 0,2,1.
        mapped = first["uvs"]
        return [
            (texture_hash, [tuple(mapped[0]), tuple(mapped[2]), tuple(mapped[1])])
        ], False

    second = by_triangle[1]["mapped"]
    second_hash = material_hash(second["material"])
    # glTF emits a native quad as two triangles.  Nearest-surface transfer can
    # choose a different source triangle for each half.  If their material or
    # shared-corner UVs differ, preserve the transfer exactly by replacing the
    # native quad with its two emitted native triangles.
    split = second_hash != texture_hash or any(
        abs(a - b) > 1e-6
        for a, b in zip(first["uvs"][2], second["uvs"][0])
    ) or any(
        abs(a - b) > 1e-6
        for a, b in zip(first["uvs"][1], second["uvs"][1])
    )
    if split:
        return [
            (texture_hash, [tuple(uv) for uv in first["uvs"]]),
            (second_hash, [tuple(uv) for uv in second["uvs"]]),
        ], True
    return [
        (
            texture_hash,
            [
                tuple(first["uvs"][0]),
                tuple(first["uvs"][2]),
                tuple(first["uvs"][1]),
                tuple(second["uvs"][2]),
            ],
        )
    ], False


def uv_byte(value: float, dimension: int) -> int:
    texel = math.floor(value * dimension - 0.5 + 0.5)
    return max(0, min(255, texel))


def rewrite_faces(
    target: bytes,
    target_dump: dict[str, Any],
    target_layout: dict[str, Any],
    static_matches: dict[tuple[int, int], list[tuple[int, dict[str, Any]]]],
    semantic_triangles: dict[int, list[SourceTriangle]],
    dimensions: dict[int, tuple[int, int]],
    output_hashes: tuple[int, ...],
) -> tuple[bytes, dict[str, int]]:
    texture_index = {texture_hash: index for index, texture_hash in enumerate(output_hashes)}
    if len(texture_index) != len(output_hashes):
        raise ValueError("SM2 model contains duplicate material hashes")
    counters: Counter[str] = Counter()
    first_mesh = min(target_layout["meshPointers"])
    output = bytearray(target[:first_mesh])
    mesh_offsets: list[int] = []

    for mesh in target_dump["Meshes"]:
        mesh_index = mesh["MeshIndex"]
        mesh_name = mesh["NameHash"]
        pointer = target_layout["meshPointers"][mesh_index]
        vertex_count, normal_count = struct.unpack_from("<HH", target, pointer + 2)
        original_face_count = len(mesh["Faces"])
        if normal_count != vertex_count + original_face_count:
            raise ValueError(
                f"target mesh {mesh_index} has {normal_count} normals; expected "
                f"{vertex_count} vertex plus {original_face_count} face normals"
            )
        vertex_normal_end = pointer + 28 + vertex_count * 8 + vertex_count * 8
        face_offset = pointer + 28 + vertex_count * 8 + normal_count * 8
        rebuilt_mesh = bytearray(target[pointer:vertex_normal_end])
        rebuilt_face_normals: list[bytes] = []
        rebuilt_faces: list[bytes] = []
        rebuilt_face_count = 0
        for face in mesh["Faces"]:
            face_index = face["FaceIndex"]
            length = u16(target, face_offset + 2)
            if not face["IsTextured"] or length < 28:
                raise ValueError(
                    f"target mesh {mesh_index} face {face_index} is not a v4 textured face"
                )

            native_face = target[face_offset : face_offset + length]
            split_quad = False
            if face["TextureHash"] == WING_HASH:
                mappings = [
                    (
                        WING_HASH,
                        [
                            (coordinate["U"], coordinate["V"])
                            for coordinate in face["TextureCoordinates"][
                                : 4 if face["IsQuad"] else 3
                            ]
                        ],
                    )
                ]
                counters["wingFaces"] += 1
                uv_is_native = True
            elif mesh_name in HAND_MESH_NAMES:
                candidates = semantic_triangles.get(mesh_name)
                if not candidates:
                    raise ValueError(f"SM2 donor lacks hand mesh {mesh_name:08X}")
                mapped_hash, mapped_uvs = semantic_face_mapping(face, candidates)
                mappings = [(mapped_hash, mapped_uvs)]
                counters["semanticHandFaces"] += 1
                uv_is_native = False
            else:
                polygons = static_matches.get((mesh_index, face_index))
                if not polygons:
                    raise ValueError(
                        f"target mesh {mesh_index} face {face_index} lacks a proven static mapping"
                    )
                mappings, split_quad = static_face_mappings(face, polygons)
                counters["staticMappedFaces"] += 1
                if split_quad:
                    counters["splitStaticQuads"] += 1
                uv_is_native = False

            indices = face["Indices"]
            split_indices = (
                ((indices[0], indices[2], indices[1]), (indices[1], indices[2], indices[3]))
                if split_quad
                else (None,)
            )
            for mapping_index, (mapped_hash, mapped_uvs) in enumerate(mappings):
                if mapped_hash not in texture_index:
                    raise ValueError(
                        f"mapped material {mapped_hash:08X} is absent from SM2 model"
                    )
                packet = bytearray(native_face)
                if split_quad:
                    # Bit 0x10 selects a triangle in this v4 face packet.  Both
                    # triangles reuse the quad's authored face normal.
                    struct.pack_into("<H", packet, 0, u16(packet, 0) | 0x0010)
                    packet[4:8] = bytes((*split_indices[mapping_index], 0))
                struct.pack_into("<H", packet, 12, vertex_count + rebuilt_face_count)
                struct.pack_into("<I", packet, 16, texture_index[mapped_hash])
                width, height = dimensions[mapped_hash]
                for slot, uv in enumerate(mapped_uvs):
                    if uv_is_native:
                        u, v = int(uv[0]), int(uv[1])
                    else:
                        u, v = uv_byte(uv[0], width), uv_byte(uv[1], height)
                    packet[20 + slot * 2] = u
                    packet[21 + slot * 2] = v
                original_normal = target[
                    vertex_normal_end + face_index * 8 :
                    vertex_normal_end + (face_index + 1) * 8
                ]
                if len(original_normal) != 8:
                    raise ValueError(
                        f"target mesh {mesh_index} face {face_index} lacks its face normal"
                    )
                rebuilt_face_normals.append(original_normal)
                rebuilt_faces.append(bytes(packet))
                rebuilt_face_count += 1
            face_offset += length

        if face_offset > len(target):
            raise ValueError(f"target mesh {mesh_index} faces extend past EOF")
        struct.pack_into("<H", rebuilt_mesh, 6, rebuilt_face_count)
        struct.pack_into("<H", rebuilt_mesh, 4, vertex_count + rebuilt_face_count)
        rebuilt_mesh.extend(b"".join(rebuilt_face_normals))
        rebuilt_mesh.extend(b"".join(rebuilt_faces))
        mesh_offsets.append(len(output))
        output.extend(rebuilt_mesh)

    while len(output) % 4:
        output.append(0)
    tagged_start = len(output)
    output.extend(target[u32(target, 4) :])
    struct.pack_into("<I", output, 4, tagged_start)
    for mesh_index, mesh_offset in enumerate(mesh_offsets):
        struct.pack_into(
            "<I",
            output,
            target_layout["meshPointerTable"] + mesh_index * 4,
            mesh_offset,
        )

    counters["totalFaces"] = sum(mesh["FaceCount"] for mesh in target_dump["Meshes"]) + counters[
        "splitStaticQuads"
    ]
    return bytes(output), dict(counters)


def replace_texture_section(
    model: bytes,
    output_hashes: tuple[int, ...],
    library: bytes,
) -> bytes:
    model_layout = container_layout(model)
    library_layout = container_layout(library)
    if library_layout["textureCount"] != len(output_hashes):
        raise ValueError(
            f"SM2 library has {library_layout['textureCount']} texture records but "
            f"the model has {len(output_hashes)} materials"
        )
    prefix = bytearray(model[: model_layout["hashCountOffset"]])
    prefix.extend(struct.pack("<I", len(output_hashes)))
    prefix.extend(struct.pack(f"<{len(output_hashes)}I", *output_hashes))
    new_section = len(prefix)
    old_section = library_layout["textureSection"]
    prefix.extend(library[old_section:])
    delta = new_section - old_section
    pointer_table = library_layout["texturePointerTable"] + delta
    for index in range(library_layout["textureCount"]):
        old_pointer = u32(library, library_layout["texturePointerTable"] + index * 4)
        struct.pack_into("<I", prefix, pointer_table + index * 4, old_pointer + delta)
    return bytes(prefix)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dc-model", type=Path, default=DEFAULT_DC_MODEL)
    parser.add_argument("--dc-textures", type=Path, default=DEFAULT_DC_TEXTURES)
    parser.add_argument("--sm2-model", type=Path, default=DEFAULT_SM2_MODEL)
    parser.add_argument("--sm2-textures", type=Path, default=DEFAULT_SM2_TEXTURES)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--multitool", type=Path)
    parser.add_argument(
        "--output-model", type=Path, default=DEFAULT_OUTPUT_ROOT / "spidey.psx"
    )
    parser.add_argument(
        "--output-textures", type=Path, default=DEFAULT_OUTPUT_ROOT / "sp_tex00.psx"
    )
    parser.add_argument(
        "--report", type=Path, default=DEFAULT_OUTPUT_ROOT / "pack-report.json"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    multitool = resolve_multitool(args.multitool)
    converter = load_converter()
    dc_model = converter.parse_model(args.dc_model.resolve())
    wing_donor = converter.load_wing_templates(args.sm2_model.resolve())
    skeleton_donor = converter.parse_skeleton_donor(args.sm2_model.resolve())
    if set(dc_model.mesh_names) != set(skeleton_donor.mesh_names):
        raise ValueError("Dreamcast and SM2 actors have different mesh-name sets")
    # Animation transforms address objects by numeric position. Name-match and
    # reorder alternate Dreamcast costume meshes onto the complete SM2 object
    # table; the converter also remaps every file-wide stitched-vertex reference
    # into that emitted order.
    metadata_mode = "complete SM2 skeleton donor"
    tagged_chunks = None
    build_skeleton_donor = skeleton_donor
    expected_mesh_names = skeleton_donor.mesh_names
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    dimensions = source_dimensions(mapping)

    # Scale 1 preserves the exact DC UV byte conversion used by the static GLB
    # proof.  Its temporary DC texture payload is replaced below by SM2's native
    # texture section and therefore never ships in this actor.
    base = converter.build_character(
        dc_model,
        args.dc_textures.resolve(),
        1,
        wing_donor,
        tagged_chunks=tagged_chunks,
        skeleton_donor=build_skeleton_donor,
    )
    base_layout = container_layout(base)
    sm2_model_layout = container_layout(args.sm2_model.read_bytes())
    if base_layout["meshNames"] != expected_mesh_names:
        raise ValueError("rebuilt Dreamcast mesh order does not match its metadata")

    with tempfile.TemporaryDirectory(prefix="sm2-dc-native-pack-") as temporary:
        temporary_root = Path(temporary)
        base_path = temporary_root / "spidey-dc-base.psx"
        base_dump_path = temporary_root / "spidey-dc-base.json"
        source_dump_path = temporary_root / "spidey-sm2-source.json"
        base_path.write_bytes(base)
        target_dump = dump_mesh(multitool, base_path, base_dump_path)
        source_dump = dump_mesh(multitool, args.sm2_model.resolve(), source_dump_path)

    static_matches, static_report = match_static_mapping(
        target_dump, mapping, dimensions
    )
    semantic_triangles = mesh_triangles(source_dump, dimensions)
    rewritten, face_report = rewrite_faces(
        base,
        target_dump,
        base_layout,
        static_matches,
        semantic_triangles,
        dimensions,
        sm2_model_layout["textureHashes"],
    )
    packed = replace_texture_section(
        rewritten,
        sm2_model_layout["textureHashes"],
        args.sm2_textures.read_bytes(),
    )

    # Reparse the final model before publishing it.  This also proves that all
    # rewritten indices resolve through the 14-entry SM2 material table.
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    args.output_model.write_bytes(packed)
    args.output_textures.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.sm2_textures, args.output_textures)
    with tempfile.TemporaryDirectory(prefix="sm2-dc-native-verify-") as temporary:
        final_dump_path = Path(temporary) / "spidey-final.json"
        final_dump = dump_mesh(multitool, args.output_model.resolve(), final_dump_path)
    final_face_count = sum(mesh["FaceCount"] for mesh in final_dump["Meshes"])
    final_hashes = {
        face["TextureHash"]
        for mesh in final_dump["Meshes"]
        for face in mesh["Faces"]
    }
    unknown_hashes = final_hashes.difference(sm2_model_layout["textureHashes"])
    if unknown_hashes:
        raise ValueError(
            "final actor contains unknown material hashes: "
            + ", ".join(f"{value:08X}" for value in sorted(unknown_hashes))
        )
    if final_face_count != face_report["totalFaces"]:
        raise ValueError(
            f"final actor parsed {final_face_count} faces; expected {face_report['totalFaces']}"
        )

    report = {
        "schemaVersion": 1,
        "scope": "native SM2 runtime actor; GLB is validation input only",
        "dcModel": str(args.dc_model.resolve()),
        "sm2Model": str(args.sm2_model.resolve()),
        "sm2TextureLibrary": str(args.sm2_textures.resolve()),
        "animationMetadata": metadata_mode,
        "staticMapping": str(args.mapping.resolve()),
        "outputModel": str(args.output_model.resolve()),
        "outputTextureLibrary": str(args.output_textures.resolve()),
        "outputModelBytes": len(packed),
        "outputModelSha256": sha256(packed),
        "outputTextureSha256": sha256(args.output_textures.read_bytes()),
        "meshCount": len(final_dump["Meshes"]),
        "materialCount": len(sm2_model_layout["textureHashes"]),
        "finalFaceCount": final_face_count,
        "staticProof": static_report,
        "faceMapping": face_report,
        "alternateHandMeshNames": [
            f"0x{value:08X}" for value in sorted(HAND_MESH_NAMES)
        ],
        "status": "pass",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"packed native SM2 Default actor: {args.output_model.resolve()} "
        f"({len(packed):,} bytes, {final_face_count:,} faces)"
    )
    print(
        f"mapped {face_report['staticMappedFaces']:,} static faces, "
        f"{face_report['semanticHandFaces']:,} alternate-hand faces, "
        f"and {face_report['wingFaces']:,} wing/seam faces"
    )
    print(f"report: {args.report.resolve()}")


if __name__ == "__main__":
    main()
