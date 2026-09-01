#!/usr/bin/env python3
"""Prototype Dreamcast-v6 to Spider-Man-PS1-v4 character converter.

The Dreamcast and PlayStation releases use the same high-level Neversoft PSX
container, object hierarchy and segmented character representation, but the
Dreamcast revision widens face UVs and embeds 16-bit PVR textures.  SM1's MIPS
loader understands the v4 geometry and 4/8-bit CLUT texture forms only.

This tool performs the mechanical bridge without consulting a disc image.  It
consumes loose files produced by first-run extraction:

* a Dreamcast character ``.PSX``;
* that file's already-decoded PNG directory; and
* an output directory used through ``SPIDEY_ASSET_DIR``.

It writes a v4 character file plus an optional texture-only companion.  The
geometry conversion preserves objects, hierarchy chunks, mesh names, material
hashes, vertices, normals, primitive flags and post-mesh data.  Only v6 UVs and
embedded texture encoding change.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import math
from pathlib import Path
import struct
from typing import Iterable, Mapping

from PIL import Image


MAGENTA_555 = 0x7C1F
WING_HASH = 0xDC38D248
WING_SIZE = 64
PALETTE_CACHE_ID_DOMAIN = b"OpenSpideyPS1/DC-palette-cache-id/v1\0"

# Bag-Man's Dreamcast head is two nested shells: Peter's 52-vertex head sits
# behind a 49-vertex paper bag with transparent eye holes. Preserve that source
# geometry and both authored textures; the PS1 renderer adaptation must solve
# their ordering without deleting the inner head or baking it into the paper.
BAGMAN_FACE_HASH = 0x5808C4DD
BAGMAN_BAG_HASH = 0x2F94F220
BAGMAN_HEAD_MESH = 7
BAGMAN_HEAD_VERTEX_COUNT = 100
BAGMAN_HEAD_FACE_COUNT = 179
BAGMAN_INNER_FACE_COUNT = 86
BAGMAN_INNER_DEPTH_MARKER = 0x6000

# The two Dreamcast Jameson containers use the same high-detail mesh and route
# almost every face through the Dreamcast 0x0800 indexed-RGB lighting path.  The
# three bytes at face+8 are indices in that mode, not literal RGB components.
# SM1 cannot consume the Dreamcast RGB table correctly: retaining the mode makes
# the suit technicolor, while replacing only the indices still sends the face
# through the wrong lookup path and makes it nearly black.  Identify the actor by
# its stable mesh-name set, clear 0x0800, and supply the retail SM1 neutral packet
# color together.  Geometry, normals, UVs, materials, and Dreamcast texture pixels
# remain unchanged.
JAMESON_MESH_NAMES = frozenset(
    {
        0x2E3D7A9A,
        0x29015E62,
        0x91B327E2,
        0x18C31025,
        0x6A29F344,
        0x65F57C73,
        0xC6E95BEA,
        0x01F8AF89,
        0x570403DA,
        0x7E37569E,
        0xE086C172,
        0xDE08F649,
        0x33365911,
        0x1A011294,
        0x34942A30,
        0xE1966537,
    }
)
JAMESON_FACE_LIGHTING = bytes((110, 110, 110))
SCORPION_TAIL_MESH_NAMES = frozenset(
    {
        0xBE6FFB9F,
        0x2766AA25,
        0x50619AB3,
        0xCE050F10,
        0xB9023F86,
        0x200B6E3C,
        0x570C5EAA,
    }
)
SCORPION_HOOK_MESH_NAME = 0xAF6C87FE
SCORPION_SPLINE_RUNTIME_TEXTURE_INDEX = 18
SCORPION_SPLINE_RUNTIME_TEXTURE_HASH = 0x35A7A03D
SCORPION_SPLINE_COMPATIBILITY_SIZE = (64, 64)

# SM2's four-corner membranes were authored against its lower-detail torso and
# leave a visible triangular hole below each Dreamcast shoulder.  These are
# surface vertices on the recipient's upper-arm parts at the front/underside
# armpit root.  The added seam triangles remain rigid to the same upper-arm
# bone as the donor's outer wing corners while meeting the denser DC silhouette.
WING_SEAM_ROOT_VERTICES = {
    4: 55,
    9: 55,
}
WING_SEAM_ROOT_UV = (0, 32)


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def i16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def pack_u16(value: int) -> bytes:
    return struct.pack("<H", value)


def pack_u32(value: int) -> bytes:
    return struct.pack("<I", value)


@dataclass(frozen=True)
class Texture:
    offset: int
    unk: int
    palette_size: int
    texture_id: int
    index: int
    width: int
    height: int
    pixel_format: int
    payload_offset: int
    payload_size: int
    end: int


@dataclass(frozen=True)
class ParsedModel:
    data: bytes
    version: int
    magic: int
    meta_top: int
    object_count: int
    mesh_count: int
    mesh_pointer_table_offset: int
    mesh_pointers: tuple[int, ...]
    tagged_chunks: bytes
    mesh_names: tuple[int, ...]
    texture_hashes: tuple[int, ...]
    textures: tuple[Texture, ...]
    mesh_ends: tuple[int, ...]
    texture_dimensions: dict[int, tuple[int, int]]
    post_mesh_offset: int


@dataclass(frozen=True)
class SkeletonDonor:
    """SM1-native object order, hierarchy, and animation for a DC mesh set."""

    objects: tuple[bytes, ...]
    tagged_chunks: bytes
    mesh_names: tuple[int, ...]
    face_lighting_by_mesh: dict[int, tuple[bytes, ...]]


@dataclass(frozen=True)
class WingTemplate:
    mesh_index: int
    vertices: tuple[bytes, ...]
    vertex_normals: tuple[bytes, ...]
    faces: tuple[bytes, ...]
    face_normals: tuple[bytes, ...]


@dataclass(frozen=True)
class AttachmentSource:
    attachment_index: int
    mesh_index: int
    vertex_index: int
    vertex: bytes
    normal: bytes


@dataclass(frozen=True)
class WingDonor:
    templates: dict[int, WingTemplate]
    attachment_sources: dict[int, AttachmentSource]
    mesh_names: tuple[int, ...]


@dataclass(frozen=True)
class Ps1TextureAsset:
    width: int
    height: int
    palette: tuple[int, ...]
    payload: bytes


def tagged_chunk_payload(data: bytes, tag_wanted: int) -> bytes:
    """Read one tagged metadata payload from any supported PSX container."""
    cursor = u32(data, 4)
    while True:
        tag = u32(data, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(data, cursor)
        cursor += 4
        payload = data[cursor : cursor + size]
        if len(payload) != size:
            raise ValueError(f"tag 0x{tag:08X} extends past EOF")
        if tag == tag_wanted:
            return payload
        cursor += size
    raise ValueError(f"tag 0x{tag_wanted:08X} not found")


def rewrite_tagged_chunks(
    tagged_chunks: bytes,
    replacements: Mapping[int, bytes],
    removals: Iterable[int] = (),
) -> bytes:
    """Replace/remove metadata chunks while preserving all untouched bytes."""
    removed = set(removals)
    seen: set[int] = set()
    cursor = 0
    output = bytearray()
    while True:
        tag = u32(tagged_chunks, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(tagged_chunks, cursor)
        cursor += 4
        payload = tagged_chunks[cursor : cursor + size]
        cursor += size
        if len(payload) != size:
            raise ValueError(f"tag 0x{tag:08X} extends past tagged metadata")
        if tag in removed:
            continue
        payload = replacements.get(tag, payload)
        seen.add(tag)
        output.extend(pack_u32(tag))
        output.extend(pack_u32(len(payload)))
        output.extend(payload)
    for tag, payload in replacements.items():
        if tag in seen or tag in removed:
            continue
        output.extend(pack_u32(tag))
        output.extend(pack_u32(len(payload)))
        output.extend(payload)
    output.extend(pack_u32(0xFFFFFFFF))
    return bytes(output)


def parse_skeleton_donor(path: Path) -> SkeletonDonor:
    """Read only the SM1-native skeleton metadata needed by a converted actor."""
    data = path.read_bytes()
    if len(data) < 16:
        raise ValueError(f"{path} is too small to be a PSX container")
    version, magic = struct.unpack_from("<HH", data, 0)
    if version not in (3, 4) or magic != 2:
        raise ValueError(f"expected PS1 v3/v4 magic 0002 donor, got v{version} magic {magic:04X}")
    object_count = u32(data, 8)
    objects = tuple(
        data[12 + index * 36 : 12 + (index + 1) * 36]
        for index in range(object_count)
    )
    mesh_count_offset = 12 + object_count * 36
    mesh_count = u32(data, mesh_count_offset)
    if mesh_count != object_count:
        raise ValueError(
            f"skeleton donor has {object_count} objects but {mesh_count} meshes"
        )
    mesh_pointer_table = mesh_count_offset + 4
    mesh_pointers = tuple(
        u32(data, mesh_pointer_table + index * 4) for index in range(mesh_count)
    )
    cursor = u32(data, 4)
    tagged_start = cursor
    while True:
        tag = u32(data, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(data, cursor)
        cursor += 4 + size
        if cursor > len(data):
            raise ValueError("skeleton donor tagged chunk extends past EOF")
    tagged_chunks = data[tagged_start:cursor]
    mesh_names = tuple(u32(data, cursor + index * 4) for index in range(mesh_count))
    if len(set(mesh_names)) != len(mesh_names):
        raise ValueError("skeleton donor contains duplicate mesh names")
    face_lighting_by_mesh = {
        name: tuple(face[8:11] for face in mesh_parts(data, pointer)[3])
        for name, pointer in zip(mesh_names, mesh_pointers)
    }
    return SkeletonDonor(objects, tagged_chunks, mesh_names, face_lighting_by_mesh)


def skeleton_mesh_order(model: ParsedModel, donor: SkeletonDonor) -> tuple[int, ...]:
    """Map donor object order to the matching Dreamcast meshes by stable name."""
    if model.object_count != len(donor.objects) or model.mesh_count != len(donor.mesh_names):
        raise ValueError(
            "skeleton donor and Dreamcast model have different object/mesh counts"
        )
    by_name = {name: index for index, name in enumerate(model.mesh_names)}
    if len(by_name) != model.mesh_count:
        raise ValueError("Dreamcast model contains duplicate mesh names")
    missing = [name for name in donor.mesh_names if name not in by_name]
    extra = [name for name in model.mesh_names if name not in set(donor.mesh_names)]
    if missing or extra:
        raise ValueError(
            "skeleton donor mesh-name set differs from Dreamcast model "
            f"(missing={len(missing)}, extra={len(extra)})"
        )
    return tuple(by_name[name] for name in donor.mesh_names)


@dataclass(frozen=True)
class WingTransfer:
    templates: dict[int, WingTemplate]
    reference_map: dict[int, int]
    inserted_sources: dict[int, tuple[AttachmentSource, ...]]
    insertion_points: tuple[tuple[int, int], ...]


def parse_mesh_end(data: bytes, offset: int, version: int) -> int:
    if version not in (4, 6):
        raise ValueError(f"only v4/v6 mesh headers are supported, got v{version}")
    vertex_count, normal_count, face_count = struct.unpack_from("<HHH", data, offset + 2)
    cursor = offset + 28 + vertex_count * 8 + normal_count * 8
    for _ in range(face_count):
        if cursor + 4 > len(data):
            raise ValueError(f"face header at 0x{cursor:X} exceeds file")
        face_length = u16(data, cursor + 2)
        if face_length < 16 or cursor + face_length > len(data):
            raise ValueError(f"invalid face length {face_length} at 0x{cursor:X}")
        cursor += face_length
    return cursor


def mesh_parts(data: bytes, offset: int) -> tuple[bytearray, list[bytes], list[bytes], list[bytes]]:
    """Split one native mesh into its header, vertices, normals and face records."""
    vertex_count, normal_count, face_count = struct.unpack_from("<HHH", data, offset + 2)
    header = bytearray(data[offset : offset + 28])
    cursor = offset + 28
    vertices = [data[cursor + index * 8 : cursor + (index + 1) * 8] for index in range(vertex_count)]
    cursor += vertex_count * 8
    normals = [data[cursor + index * 8 : cursor + (index + 1) * 8] for index in range(normal_count)]
    cursor += normal_count * 8
    faces: list[bytes] = []
    for _ in range(face_count):
        length = u16(data, cursor + 2)
        faces.append(data[cursor : cursor + length])
        cursor += length
    return header, vertices, normals, faces


def collect_attachment_sources(data: bytes, pointers: Iterable[int]) -> tuple[AttachmentSource, ...]:
    """Collect the file-wide type-1 stitch sources in native traversal order."""
    sources: list[AttachmentSource] = []
    for mesh_index, pointer in enumerate(pointers):
        _, vertices, normals, _ = mesh_parts(data, pointer)
        for vertex_index, vertex in enumerate(vertices):
            if u16(vertex, 6) != 1:
                continue
            if vertex_index >= len(normals):
                raise ValueError(f"mesh {mesh_index} stitch source lacks a vertex normal")
            sources.append(
                AttachmentSource(
                    len(sources),
                    mesh_index,
                    vertex_index,
                    vertex,
                    normals[vertex_index],
                )
            )
    return tuple(sources)


def load_wing_templates(path: Path) -> WingDonor:
    """Read the shipped SM2 wing primitives without fabricating geometry or weights."""
    data = path.read_bytes()
    version, magic = struct.unpack_from("<HH", data, 0)
    if (version, magic) != (4, 2):
        raise ValueError(f"wing donor must be a PS1 v4 model, got v{version} magic {magic:04X}")
    object_count = u32(data, 8)
    mesh_count_offset = 12 + object_count * 36
    mesh_count = u32(data, mesh_count_offset)
    if mesh_count != 18:
        raise ValueError(f"wing donor must have the 18-part Spider-Man hierarchy, got {mesh_count}")
    pointer_table = mesh_count_offset + 4
    pointers = [u32(data, pointer_table + index * 4) for index in range(mesh_count)]

    attachment_sources = {
        source.attachment_index: source
        for source in collect_attachment_sources(data, pointers)
    }

    # These are the exact four native vertices used by SM2's wing faces.  Type-2
    # vertices remain stitched references; type-0 vertices remain rigid to the
    # upper-arm part.  Only the face-local indices are compacted for injection.
    definitions = {
        4: (0, 8, 30, 31),
        9: (0, 8, 30, 5),
    }
    templates: dict[int, WingTemplate] = {}
    referenced_attachments: set[int] = set()
    for mesh_index, source_indices in definitions.items():
        _, donor_vertices, donor_normals, donor_faces = mesh_parts(data, pointers[mesh_index])
        vertex_count = len(donor_vertices)
        if len(donor_normals) < vertex_count + len(donor_faces):
            raise ValueError(f"wing donor mesh {mesh_index} lacks per-vertex/per-face normals")
        wing_faces = [face for face in donor_faces if len(face) >= 20 and u32(face, 16) == 7]
        if len(wing_faces) not in (3, 4):
            raise ValueError(f"wing donor mesh {mesh_index} has {len(wing_faces)} wing faces")

        vertices: list[bytes] = []
        vertex_normals: list[bytes] = []
        remap = {source: target for target, source in enumerate(source_indices)}
        for source in source_indices:
            vertex = donor_vertices[source]
            if u16(vertex, 6) == 2:
                referenced_attachments.add(u16(vertex, 2))
            vertices.append(vertex)
            vertex_normals.append(donor_normals[source])

        faces: list[bytes] = []
        face_normals: list[bytes] = []
        for face in wing_faces:
            converted = bytearray(face)
            for slot in range(4):
                source = converted[4 + slot]
                if source in remap:
                    converted[4 + slot] = remap[source]
            normal_index = u32(face, 12)
            if normal_index >= len(donor_normals):
                raise ValueError(f"wing donor face normal {normal_index} is out of range")
            face_normals.append(donor_normals[normal_index])
            faces.append(bytes(converted))
        templates[mesh_index] = WingTemplate(
            mesh_index,
            tuple(vertices),
            tuple(vertex_normals),
            tuple(faces),
            tuple(face_normals),
        )
    missing = sorted(referenced_attachments.difference(attachment_sources))
    if missing:
        raise ValueError(f"wing donor has unresolved stitch references: {missing}")
    return WingDonor(
        templates,
        {index: attachment_sources[index] for index in referenced_attachments},
        parse_skeleton_donor(path).mesh_names,
    )


def prepare_wing_transfer(model: ParsedModel, donor: WingDonor) -> WingTransfer:
    """Translate SM2 stitch indices to exact DC sources, adding exact sources when absent.

    A stitched reference is the PS1 character format's native single-bone
    weighting mechanism. Some SM2 wing positions also occur in the denser DC
    model, but their high-detail surface normals differ. Donor-exact source
    copies are therefore added to the corresponding DC body parts so position,
    normal and bone influence all remain exact without altering DC body faces.
    """
    if (
        len(donor.mesh_names) != model.mesh_count
        or set(donor.mesh_names) != set(model.mesh_names)
    ):
        raise ValueError("wing donor and target model have different mesh-name sets")
    target_index_by_name = {
        mesh_name: mesh_index for mesh_index, mesh_name in enumerate(model.mesh_names)
    }

    # Attachment sources and wing-bearing meshes are identified by their stable
    # object names, not their numeric positions. Alternate costumes can reorder
    # same-named hand/forearm parts while retaining the same 18-part hierarchy;
    # treating the donor's numeric index as the target index then stitches a wing
    # corner to the wrong body part.
    remapped_sources = {
        donor_index: AttachmentSource(
            source.attachment_index,
            target_index_by_name[donor.mesh_names[source.mesh_index]],
            source.vertex_index,
            source.vertex,
            source.normal,
        )
        for donor_index, source in donor.attachment_sources.items()
    }
    remapped_templates = {
        target_index_by_name[donor.mesh_names[template.mesh_index]]: WingTemplate(
            target_index_by_name[donor.mesh_names[template.mesh_index]],
            template.vertices,
            template.vertex_normals,
            template.faces,
            template.face_normals,
        )
        for template in donor.templates.values()
    }

    target_sources = collect_attachment_sources(model.data, model.mesh_pointers)
    exact: dict[tuple[int, bytes, bytes], AttachmentSource] = {
        (source.mesh_index, source.vertex, source.normal): source for source in target_sources
    }
    inserted: dict[int, list[AttachmentSource]] = {}
    matches: dict[int, AttachmentSource | None] = {}
    for donor_index, source in remapped_sources.items():
        match = exact.get((source.mesh_index, source.vertex, source.normal))
        matches[donor_index] = match
        if match is None:
            inserted.setdefault(source.mesh_index, []).append(source)

    # Inserting a new type-1 source shifts every later file-wide attachment
    # index.  Record each old-index insertion point so existing DC type-2
    # references can be advanced without changing what they follow.
    old_counts_by_mesh: dict[int, int] = {}
    running = 0
    for mesh_index in range(model.mesh_count):
        running += sum(source.mesh_index == mesh_index for source in target_sources)
        old_counts_by_mesh[mesh_index] = running
    insertion_points = tuple(
        (old_counts_by_mesh[mesh_index], len(sources))
        for mesh_index, sources in sorted(inserted.items())
    )

    def shift_old(index: int) -> int:
        return index + sum(count for point, count in insertion_points if index >= point)

    reference_map: dict[int, int] = {}
    for donor_index, source in remapped_sources.items():
        match = matches[donor_index]
        if match is not None:
            reference_map[donor_index] = shift_old(match.attachment_index)
            continue
        sources = inserted[source.mesh_index]
        ordinal = sources.index(source)
        point = old_counts_by_mesh[source.mesh_index]
        earlier_insertions = sum(
            count for other_point, count in insertion_points if other_point < point
        )
        reference_map[donor_index] = point + earlier_insertions + ordinal

    return WingTransfer(
        remapped_templates,
        reference_map,
        {mesh: tuple(sources) for mesh, sources in inserted.items()},
        insertion_points,
    )


def attachment_reorder_map(
    model: ParsedModel,
    mesh_order: tuple[int, ...],
    wing_transfer: WingTransfer | None,
) -> dict[int, int]:
    """Map post-insertion stitch indices into the emitted mesh traversal order.

    Type-1 vertices form one file-wide attachment table in mesh/vertex traversal
    order, while type-2 vertices store an index into that table.  A skeleton donor
    can reorder same-named meshes (notably the alternate left/right hand parts),
    so retaining the old indices would weight stitched vertices to unrelated body
    parts.  Wing source insertions are already reflected in the intermediate
    indices produced by ``prepare_wing_transfer``; this map performs the remaining
    mesh-order permutation.
    """
    if mesh_order == tuple(range(model.mesh_count)):
        return {}

    additions = wing_transfer.inserted_sources if wing_transfer else {}
    keys_by_mesh: dict[int, tuple[tuple[int, int], ...]] = {}
    for mesh_index, pointer in enumerate(model.mesh_pointers):
        _, vertices, _, _ = mesh_parts(model.data, pointer)
        source_count = sum(u16(vertex, 6) == 1 for vertex in vertices)
        source_count += len(additions.get(mesh_index, ()))
        keys_by_mesh[mesh_index] = tuple(
            (mesh_index, ordinal) for ordinal in range(source_count)
        )

    intermediate = tuple(
        key
        for mesh_index in range(model.mesh_count)
        for key in keys_by_mesh[mesh_index]
    )
    emitted = tuple(
        key for mesh_index in mesh_order for key in keys_by_mesh[mesh_index]
    )
    if len(intermediate) != len(emitted) or set(intermediate) != set(emitted):
        raise ValueError("attachment reorder does not preserve the source set")
    emitted_index = {key: index for index, key in enumerate(emitted)}
    return {
        index: emitted_index[key] for index, key in enumerate(intermediate)
    }


def remap_attachment_references(mesh: bytes, mapping: Mapping[int, int]) -> bytes:
    """Retarget every stitched vertex in one converted mesh."""
    if not mapping:
        return mesh
    header, vertices, normals, faces = mesh_parts(mesh, 0)
    remapped: list[bytes] = []
    for vertex in vertices:
        if u16(vertex, 6) != 2:
            remapped.append(vertex)
            continue
        old_reference = u16(vertex, 2)
        if old_reference not in mapping:
            raise ValueError(
                f"stitched vertex references missing attachment {old_reference}"
            )
        adjusted = bytearray(vertex)
        struct.pack_into("<H", adjusted, 2, mapping[old_reference])
        remapped.append(bytes(adjusted))
    return bytes(header) + b"".join(remapped) + b"".join(normals) + b"".join(faces)


def parse_model(path: Path) -> ParsedModel:
    data = path.read_bytes()
    if len(data) < 16:
        raise ValueError(f"{path} is too small to be a PSX container")
    version, magic = struct.unpack_from("<HH", data, 0)
    if version != 6 or magic != 2:
        raise ValueError(f"expected Dreamcast v6 magic 0002, got v{version} magic {magic:04X}")

    meta_top = u32(data, 4)
    object_count = u32(data, 8)
    mesh_count_offset = 12 + object_count * 36
    mesh_count = u32(data, mesh_count_offset)
    mesh_pointer_table_offset = mesh_count_offset + 4
    mesh_pointers = tuple(
        u32(data, mesh_pointer_table_offset + index * 4) for index in range(mesh_count)
    )

    cursor = meta_top
    while True:
        tag = u32(data, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(data, cursor)
        cursor += 4 + size
        if cursor > len(data):
            raise ValueError("tagged chunk extends past EOF")
    tagged_chunks = data[meta_top:cursor]

    mesh_names = tuple(u32(data, cursor + index * 4) for index in range(mesh_count))
    cursor += mesh_count * 4
    texture_hash_count = u32(data, cursor)
    cursor += 4
    texture_hashes = tuple(
        u32(data, cursor + index * 4) for index in range(texture_hash_count)
    )
    cursor += texture_hash_count * 4

    palette4_count = u32(data, cursor)
    cursor += 4 + palette4_count * (4 + 16 * 2)
    palette8_count = u32(data, cursor)
    cursor += 4 + palette8_count * (4 + 256 * 2)

    actual_count = u32(data, cursor)
    cursor += 4
    if actual_count == 0xFFFFFFFF:
        detail_count = u32(data, cursor)
        cursor += 4 + detail_count * 36
        cubemap_count = u32(data, cursor)
        cursor += 4 + cubemap_count * 36
        actual_count = u32(data, cursor)
        cursor += 4
    cursor += actual_count * 4  # physical texture-header pointers

    textures: list[Texture] = []
    dimensions: dict[int, tuple[int, int]] = {}
    for _ in range(actual_count):
        offset = cursor
        unk, palette_size, texture_id, index = struct.unpack_from("<IIII", data, cursor)
        width, height = struct.unpack_from("<HH", data, cursor + 16)
        cursor += 20
        pixel_format = 0
        if palette_size == 65536:
            pixel_format, payload_size = struct.unpack_from("<II", data, cursor)
            cursor += 8
        elif palette_size == 256:
            padded_width = (width + 1) & ~1
            payload_size = padded_width * height
            if height % 2 and padded_width % 4:
                payload_size += 2
        elif palette_size == 16:
            padded_width = ((width + 3) & ~3) // 2
            payload_size = padded_width * height
            if height % 2 and padded_width % 4:
                payload_size += 2
        else:
            raise ValueError(f"unsupported palette size {palette_size} at 0x{offset:X}")
        payload_offset = cursor
        cursor += payload_size
        textures.append(
            Texture(
                offset,
                unk,
                palette_size,
                texture_id,
                index,
                width,
                height,
                pixel_format,
                payload_offset,
                payload_size,
                cursor,
            )
        )
        dimensions[index] = (width, height)

    mesh_ends = tuple(parse_mesh_end(data, pointer, version) for pointer in mesh_pointers)
    post_mesh_offset = max(mesh_ends)
    return ParsedModel(
        data=data,
        version=version,
        magic=magic,
        meta_top=meta_top,
        object_count=object_count,
        mesh_count=mesh_count,
        mesh_pointer_table_offset=mesh_pointer_table_offset,
        mesh_pointers=mesh_pointers,
        tagged_chunks=tagged_chunks,
        mesh_names=mesh_names,
        texture_hashes=texture_hashes,
        textures=tuple(textures),
        mesh_ends=mesh_ends,
        texture_dimensions=dimensions,
        post_mesh_offset=post_mesh_offset,
    )


def find_texture_png(texture_dir: Path, texture: Texture) -> Path:
    suffix = f"_{texture.offset:08X}.png".lower()
    matches = [path for path in texture_dir.rglob("*.png") if path.name.lower().endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(
            f"expected one decoded PNG ending in {suffix} under {texture_dir}, found {len(matches)}"
        )
    return matches[0]


def is_bagman_model(model: ParsedModel) -> bool:
    return (
        model.mesh_count > BAGMAN_HEAD_MESH
        and len(model.texture_hashes) > 6
        and model.texture_hashes[5] == BAGMAN_FACE_HASH
        and model.texture_hashes[6] == BAGMAN_BAG_HASH
    )


def is_jameson_model(model: ParsedModel) -> bool:
    return (
        model.mesh_count == len(JAMESON_MESH_NAMES)
        and frozenset(model.mesh_names) == JAMESON_MESH_NAMES
    )


def scorpion_spline_texture_index(model: ParsedModel) -> int | None:
    """Return the Dreamcast hook texture index for the audited Scorpion rig.

    Scorpion's last seven objects are animation controls for a runtime-generated
    spline, not visible cube geometry. Dreamcast stores the shared hook/tube art
    at material index 0. Retail SM1 stores the equivalent skin in a dedicated
    procedural slot at index 18, which the spline renderer selects independently
    of the hook's ordinary face packets. Conversion therefore retains index 0 for
    the authored hook and emits an index-18 compatibility alias for the tube.
    """
    required_names = SCORPION_TAIL_MESH_NAMES | {SCORPION_HOOK_MESH_NAME}
    if model.mesh_count != 24 or not required_names <= set(model.mesh_names):
        return None

    hook_mesh_index = model.mesh_names.index(SCORPION_HOOK_MESH_NAME)
    _, _, _, hook_faces = mesh_parts(model.data, model.mesh_pointers[hook_mesh_index])
    texture_indices = {
        u32(face, 16)
        for face in hook_faces
        if len(face) >= 20 and (u16(face, 0) & 0x0003)
    }
    if len(texture_indices) != 1:
        raise ValueError(
            "Scorpion hook no longer has exactly one procedural-tail texture"
        )

    texture_index = next(iter(texture_indices))
    dimensions = model.texture_dimensions.get(texture_index)
    if dimensions != (128, 128):
        raise ValueError(
            "Scorpion Dreamcast spline skin no longer matches the audited "
            f"128x128 source (texture {texture_index}: {dimensions})"
        )
    return texture_index


def scorpion_spline_runtime_alias(model: ParsedModel) -> tuple[int, int] | None:
    """Return ``(Dreamcast source index, SM1 runtime index)`` for Scorpion's tube."""
    source_index = scorpion_spline_texture_index(model)
    if source_index is None:
        return None
    if len(model.texture_hashes) != SCORPION_SPLINE_RUNTIME_TEXTURE_INDEX:
        raise ValueError(
            "Scorpion Dreamcast texture table no longer ends immediately before "
            f"runtime spline slot {SCORPION_SPLINE_RUNTIME_TEXTURE_INDEX}"
        )
    return source_index, SCORPION_SPLINE_RUNTIME_TEXTURE_INDEX


def load_ps1_texture_asset(path: Path, texture_hash: int) -> Ps1TextureAsset:
    """Read one 8-bit texture and its exact CLUT from a loose PS1 library."""
    data = path.read_bytes()
    if len(data) < 16:
        raise ValueError(f"PS1 texture library is truncated: {path}")
    metadata_offset = u32(data, 4)
    object_count = u32(data, 8)
    mesh_count_offset = 12 + object_count * 36
    if mesh_count_offset + 4 > len(data):
        raise ValueError(f"PS1 texture library object table exceeds file: {path}")
    mesh_count = u32(data, mesh_count_offset)

    cursor = metadata_offset
    for _ in range(17):
        magic = u32(data, cursor)
        cursor += 4
        if magic == 0xFFFFFFFF:
            break
        length = u32(data, cursor)
        cursor += 4 + length
    else:
        raise ValueError(f"PS1 texture library metadata has no terminator: {path}")

    cursor += mesh_count * 4
    texture_name_count = u32(data, cursor)
    cursor += 4
    texture_names = struct.unpack_from(f"<{texture_name_count}I", data, cursor)
    cursor += texture_name_count * 4

    palette4_count = u32(data, cursor)
    cursor += 4
    palettes4: dict[int, tuple[int, ...]] = {}
    for _ in range(palette4_count):
        texture_id = u32(data, cursor)
        cursor += 4
        palettes4[texture_id] = struct.unpack_from("<16H", data, cursor)
        cursor += 16 * 2
    palette8_count = u32(data, cursor)
    cursor += 4
    palettes: dict[int, tuple[int, ...]] = {}
    for _ in range(palette8_count):
        texture_id = u32(data, cursor)
        cursor += 4
        palettes[texture_id] = struct.unpack_from("<256H", data, cursor)
        cursor += 256 * 2

    texture_count = u32(data, cursor)
    cursor += 4 + texture_count * 4
    for _ in range(texture_count):
        if cursor + 20 > len(data):
            raise ValueError(f"PS1 texture record exceeds file: {path}")
        _, palette_size, texture_id, index, width, height = struct.unpack_from(
            "<IIIIHH", data, cursor
        )
        cursor += 20
        if palette_size == 256:
            padded_width = (width + 1) & ~1
            payload_size = padded_width * height
            if height % 2 and padded_width % 4:
                payload_size += 2
        elif palette_size == 16:
            padded_width = (width + 3) & ~3
            payload_size = padded_width * height // 2
            if height % 2 and (padded_width // 2) % 4:
                payload_size += 2
        elif palette_size == 65536:
            # 16-bit records carry format/size words before their payload.
            payload_size = u32(data, cursor + 4)
            cursor += 8
        else:
            raise ValueError(f"unsupported PS1 palette size {palette_size} at 0x{cursor - 20:X}")

        payload = data[cursor : cursor + payload_size]
        cursor += payload_size
        name_hash = texture_names[index] if index < len(texture_names) else None
        if name_hash != texture_hash:
            continue
        palette = palettes.get(texture_id) if palette_size == 256 else palettes4.get(texture_id)
        if palette is None:
            raise ValueError(
                f"requested texture 0x{texture_hash:08X} lacks CLUT id {texture_id}"
            )
        if len(payload) != payload_size:
            raise ValueError(f"requested texture 0x{texture_hash:08X} payload is truncated")
        if palette_size == 256:
            return Ps1TextureAsset(width, height, tuple(palette), payload)
        if palette_size != 16:
            raise ValueError(f"requested texture 0x{texture_hash:08X} is not paletted")

        # Expand the donor's native 4-bit indices into an 8-bit payload without
        # touching the palette colors or the decoded texel layout.  The generated
        # DC companion uses one uniform 8-bit section, while the retail SM2 wing
        # artwork is a compact four-color/16-entry texture.
        byte_width = ((width + 3) & ~3) // 2
        expanded_indices: list[int] = []
        for y in range(height):
            for x in range(width):
                source = payload[y * byte_width + (x >> 1)]
                color_index = (source >> ((x & 1) * 4)) & 0xF
                expanded_indices.append(color_index)
        padded_width = (width + 1) & ~1
        expanded_payload = bytearray()
        for y in range(height):
            expanded_payload.extend(expanded_indices[y * width : (y + 1) * width])
            expanded_payload.extend(b"\x00" * (padded_width - width))
        if height % 2 and padded_width % 4:
            expanded_payload.extend(b"\x00\x00")
        expanded_palette = tuple(palette) + (MAGENTA_555,) * (256 - len(palette))
        return Ps1TextureAsset(
            width,
            height,
            expanded_palette,
            bytes(expanded_payload),
        )

    raise ValueError(f"texture hash 0x{texture_hash:08X} not found in {path}")


def rgb_to_555(rgb: tuple[int, int, int]) -> int:
    red, green, blue = rgb
    return ((red * 31 + 127) // 255) | (((green * 31 + 127) // 255) << 5) | (
        ((blue * 31 + 127) // 255) << 10
    )


def inverse_fix_indices(indices: list[int], width: int, height: int) -> bytes:
    """Invert ColorHelpers.FixPixelData for an 8-bit indexed image."""
    if len(indices) != width * height:
        raise ValueError("indexed pixel count does not match dimensions")

    # Undo the column-zero upward shift: move column zero down one row.
    stage3 = indices.copy()
    column = [indices[row * width] for row in range(height)]
    for row in range(height):
        stage3[row * width] = column[(row - 1) % height]

    # Undo the whole-image downward row shift.
    stage2 = [0] * len(indices)
    for row in range(height):
        source_row = (row + 1) % height
        stage2[row * width : (row + 1) * width] = stage3[
            source_row * width : (source_row + 1) * width
        ]

    # Undo each row's right shift, then its horizontal reversal.
    raw = [0] * len(indices)
    for row in range(height):
        row_values = stage2[row * width : (row + 1) * width]
        shifted_left = row_values[1:] + row_values[:1]
        raw[row * width : (row + 1) * width] = reversed(shifted_left)

    padded_width = (width + 1) & ~1
    output = bytearray()
    for row in range(height):
        output.extend(raw[row * width : (row + 1) * width])
        output.extend(b"\x00" * (padded_width - width))
    if height % 2 and padded_width % 4:
        output.extend(b"\x00\x00")
    return bytes(output)


def quantize_texture(
    path: Path,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> tuple[tuple[int, ...], bytes]:
    image = Image.open(path).convert("RGBA")
    return quantize_image(
        image,
        str(path),
        source_width,
        source_height,
        target_width,
        target_height,
    )


def quantize_image(
    image: Image.Image,
    source_label: str,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> tuple[tuple[int, ...], bytes]:
    image = image.convert("RGBA")
    if image.size != (source_width, source_height):
        raise ValueError(
            f"{source_label} is {image.size}, expected {(source_width, source_height)}"
        )
    source_identity = hashlib.sha256(
        struct.pack("<II", image.width, image.height) + image.tobytes()
    ).digest()
    if image.size != (target_width, target_height):
        image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)

    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    quantized = rgb.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    source_palette = quantized.getpalette() or []
    source_indices = list(quantized.getdata())
    alpha_values = list(alpha.getdata())

    used = sorted(set(source_indices))
    remap = {old: new + 1 for new, old in enumerate(used)}
    palette = [MAGENTA_555]
    for old in used:
        base = old * 3
        palette.append(rgb_to_555(tuple(source_palette[base : base + 3])))
    palette.extend([MAGENTA_555] * (256 - len(palette)))

    indices = [0 if alpha_value < 128 else remap[index] for index, alpha_value in zip(source_indices, alpha_values)]

    # Palette indices carry no visual meaning, so permute them deterministically
    # from the original Dreamcast pixels. The palette and texels move together,
    # leaving the compatibility image byte-for-byte identical after decoding while
    # giving visually distinct high-resolution sources distinct runtime identities
    # even when quarter-size quantization would otherwise collapse them together.
    active = list(range(1, len(used) + 1))
    permuted = sorted(
        active,
        key=lambda index: hashlib.sha256(source_identity + struct.pack("<H", index)).digest(),
    )
    identity_remap = dict(zip(active, permuted))
    identity_palette = [MAGENTA_555] * 256
    for old_index, new_index in identity_remap.items():
        identity_palette[new_index] = palette[old_index]
    indices = [identity_remap.get(index, 0) for index in indices]
    return tuple(identity_palette), inverse_fix_indices(indices, target_width, target_height)


def build_shared_actor_palette(
    model: ParsedModel,
    texture_dir: Path,
    dimensions: Mapping[int, tuple[int, int]],
) -> tuple[int, ...]:
    """Quantize all opaque actor texels into one 255-color compatibility CLUT."""
    opaque_rgb = bytearray()
    for texture in model.textures:
        path = find_texture_png(texture_dir, texture)
        image = Image.open(path).convert("RGBA")
        if image.size != (texture.width, texture.height):
            raise ValueError(
                f"{path} is {image.size}, expected {(texture.width, texture.height)}"
            )
        target = dimensions[texture.index]
        if image.size != target:
            image = image.resize(target, Image.Resampling.LANCZOS)
        for red, green, blue, alpha in image.getdata():
            if alpha >= 128:
                opaque_rgb.extend((red, green, blue))

    if not opaque_rgb:
        return tuple([MAGENTA_555] * 256)

    pixel_count = len(opaque_rgb) // 3
    atlas_width = min(1024, pixel_count)
    atlas_height = math.ceil(pixel_count / atlas_width)
    opaque_rgb.extend(b"\x00" * (atlas_width * atlas_height * 3 - len(opaque_rgb)))
    atlas = Image.frombytes("RGB", (atlas_width, atlas_height), bytes(opaque_rgb))
    quantized = atlas.quantize(
        colors=255,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    source_palette = quantized.getpalette() or []
    used = sorted(set(quantized.getdata()))
    colors = {
        rgb_to_555(tuple(source_palette[index * 3 : index * 3 + 3]))
        for index in used
    }
    # SM1 treats 0x7C1F as the transparency key regardless of source alpha.
    # Keep opaque magenta visible by nudging only that compatibility color.
    if MAGENTA_555 in colors:
        colors.remove(MAGENTA_555)
        colors.add(MAGENTA_555 - 1)

    # The palette layout itself is part of the host replacement key. Permute the
    # actor-level colors deterministically so visually identical compact pages in
    # unrelated models do not accidentally claim one another's full-resolution art.
    identity = hashlib.sha256(model.data).digest()
    ordered_colors = sorted(
        colors,
        key=lambda color: hashlib.sha256(identity + struct.pack("<H", color)).digest()
    )
    return tuple(
        [MAGENTA_555, *ordered_colors, *([MAGENTA_555] * (255 - len(ordered_colors)))]
    )


def quantize_image_to_shared_palette(
    image: Image.Image,
    source_label: str,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    palette: tuple[int, ...],
) -> bytes:
    """Encode one compact page against an actor-level RGB555 palette."""
    image = image.convert("RGBA")
    if image.size != (source_width, source_height):
        raise ValueError(
            f"{source_label} is {image.size}, expected {(source_width, source_height)}"
        )
    if image.size != (target_width, target_height):
        image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)

    palette_rgb = [
        (index, color & 31, (color >> 5) & 31, (color >> 10) & 31)
        for index, color in enumerate(palette[1:], start=1)
        if color != MAGENTA_555
    ]
    if not palette_rgb:
        raise ValueError("shared actor palette contains no opaque colors")
    nearest: dict[int, int] = {}
    indices: list[int] = []
    for red, green, blue, alpha in image.getdata():
        if alpha < 128:
            indices.append(0)
            continue
        color = rgb_to_555((red, green, blue))
        cached = nearest.get(color)
        if cached is None:
            r5, g5, b5 = color & 31, (color >> 5) & 31, (color >> 10) & 31
            cached = min(
                palette_rgb,
                key=lambda entry: (
                    (entry[1] - r5) ** 2
                    + (entry[2] - g5) ** 2
                    + (entry[3] - b5) ** 2
                ),
            )[0]
            nearest[color] = cached
        indices.append(cached)
    return inverse_fix_indices(indices, target_width, target_height)


def quantize_actor_textures(
    model: ParsedModel,
    texture_dir: Path,
    dimensions: Mapping[int, tuple[int, int]],
) -> dict[int, tuple[tuple[int, ...], bytes]]:
    """Return every compact actor page encoded against one shared palette."""
    palette = build_shared_actor_palette(model, texture_dir, dimensions)
    assets: dict[int, tuple[tuple[int, ...], bytes]] = {}
    for texture in model.textures:
        path = find_texture_png(texture_dir, texture)
        width, height = dimensions[texture.index]
        payload = quantize_image_to_shared_palette(
            Image.open(path),
            str(path),
            texture.width,
            texture.height,
            width,
            height,
            palette,
        )
        assets[texture.index] = (palette, payload)
    return assets


def quantize_scorpion_spline_alias(
    model: ParsedModel,
    texture_dir: Path,
    dimensions: Mapping[int, tuple[int, int]],
    actor_assets: Mapping[int, tuple[tuple[int, ...], bytes]],
) -> tuple[Texture, int, tuple[int, ...], bytes] | None:
    """Build SM1's index-18 tube page from the Dreamcast hook/tube artwork."""
    alias = scorpion_spline_runtime_alias(model)
    if alias is None:
        return None
    source_index, runtime_index = alias
    source_texture = next(
        texture for texture in model.textures if texture.index == source_index
    )
    palette = actor_assets[source_index][0]
    width, height = dimensions[runtime_index]
    source_png = find_texture_png(texture_dir, source_texture)
    payload = quantize_image_to_shared_palette(
        Image.open(source_png),
        str(source_png),
        source_texture.width,
        source_texture.height,
        width,
        height,
        palette,
    )
    return source_texture, runtime_index, palette, payload


def scaled_dimensions(
    model: ParsedModel,
    texture_scale: int,
    with_wings: bool,
) -> dict[int, tuple[int, int]]:
    if texture_scale < 1:
        raise ValueError("texture scale divisor must be at least one")
    dimensions: dict[int, tuple[int, int]] = {}
    for texture in model.textures:
        width = max(1, texture.width // texture_scale)
        height = max(1, texture.height // texture_scale)
        if width > 256 or height > 256:
            raise ValueError(
                f"texture {texture.index} remains {width}x{height}; PS1 UVs are bytes"
            )
        dimensions[texture.index] = (width, height)
    spline_alias = scorpion_spline_runtime_alias(model)
    if spline_alias is not None:
        _, runtime_index = spline_alias
        dimensions[runtime_index] = SCORPION_SPLINE_COMPATIBILITY_SIZE
    if with_wings:
        wing_index = len(model.texture_hashes) + int(spline_alias is not None)
        dimensions[wing_index] = (WING_SIZE, WING_SIZE)
    return dimensions


def generated_palette_cache_ids(
    model: ParsedModel,
    with_wings: bool,
) -> dict[int, int]:
    """Return stable ids for the generated actor-level CLUTs.

    Dreamcast texture records commonly use container-local ids (usually zero),
    while SM1 keeps palettes in a process-global cache keyed only by the 32-bit
    texture id. Reusing a local face/material index here makes a later actor
    inherit whichever actor first occupied that number.

    SM1 also has only 68 physical 8-bit CLUT slots. A Dreamcast scene can exceed
    that immediately (L1A1 loads 9 Spider-Man, 16 henchman, 11 thug, and 15 Black
    Cat palettes before counting level/UI assets). All compact compatibility pages
    for one converted actor therefore share one palette authored from that actor's
    complete texture set. This preserves a useful fallback image while reducing
    each high-detail actor to one physical CLUT. Original/full-color pixels remain
    in the host replacement pack and are not limited by this compatibility CLUT.
    """
    model_identity = hashlib.sha256(model.data).digest()
    indices = [texture.index for texture in model.textures]
    if len(indices) != len(set(indices)):
        raise ValueError("Dreamcast texture records contain duplicate material indices")

    def cache_id(label: bytes, used: set[int]) -> int:
        nonce = 0
        while True:
            digest = hashlib.sha256(
                PALETTE_CACHE_ID_DOMAIN
                + model_identity
                + label
                + struct.pack("<I", nonce)
            ).digest()
            candidate = u32(digest, 0)
            if candidate not in (0, 0xFFFFFFFF) and candidate not in used:
                return candidate
            nonce += 1

    used: set[int] = set()
    actor_id = cache_id(b"actor-shared\0", used)
    used.add(actor_id)
    ids = {index: actor_id for index in indices}
    spline_alias = scorpion_spline_runtime_alias(model)
    if spline_alias is not None:
        _, runtime_index = spline_alias
        if runtime_index in ids:
            raise ValueError(f"Scorpion spline runtime texture index {runtime_index} is occupied")
        ids[runtime_index] = actor_id
    if with_wings:
        wing_index = len(model.texture_hashes) + int(spline_alias is not None)
        ids[wing_index] = cache_id(b"wing\0", used)
    return ids


def convert_face(
    data: bytes,
    offset: int,
    dimensions: dict[int, tuple[int, int]],
    face_lighting: bytes | None = None,
    clear_indexed_rgb: bool = False,
) -> bytes:
    flags, old_length = struct.unpack_from("<HH", data, offset)
    textured = bool(flags & 0x0003)
    if not textured:
        output = bytearray(data[offset : offset + old_length])
        if face_lighting is not None:
            output[8:11] = face_lighting
        if clear_indexed_rgb:
            struct.pack_into("<H", output, 0, flags & ~0x0800)
        return bytes(output)

    texture_index = u32(data, offset + 16)
    if texture_index not in dimensions:
        raise ValueError(f"face at 0x{offset:X} uses missing texture index {texture_index}")
    width, height = dimensions[texture_index]
    us = struct.unpack_from("<HHHH", data, offset + 20)
    vs = struct.unpack_from("<hhhh", data, offset + 28)
    consumed = 36
    if old_length < consumed:
        raise ValueError(f"v6 textured face at 0x{offset:X} is only {old_length} bytes")

    def uv_byte(value: int, dimension: int) -> int:
        # Preserve the v6 normalized coordinate and PS1 repeat behavior.
        return math.floor(value * dimension / 512.0) & 0xFF

    output = bytearray()
    output.extend(data[offset : offset + 2])
    output.extend(pack_u16(old_length - 8))
    output.extend(data[offset + 4 : offset + 20])
    for slot in range(4):
        output.append(uv_byte(us[slot], width))
        output.append(uv_byte(vs[slot], height))
    output.extend(data[offset + consumed : offset + old_length])
    if face_lighting is not None:
        output[8:11] = face_lighting
    if clear_indexed_rgb:
        struct.pack_into("<H", output, 0, flags & ~0x0800)
    return bytes(output)


def convert_mesh(
    model: ParsedModel,
    mesh_index: int,
    dimensions: dict[int, tuple[int, int]],
    wing_transfer: WingTransfer | None,
    wing_index: int,
    face_lighting: bytes | tuple[bytes, ...] | None = None,
    clear_indexed_rgb: bool = False,
) -> bytes:
    data = model.data
    start = model.mesh_pointers[mesh_index]
    vertex_count, normal_count, face_count = struct.unpack_from("<HHH", data, start + 2)
    face_start = start + 28 + vertex_count * 8 + normal_count * 8
    output = bytearray(data[start:face_start])
    cursor = face_start
    if isinstance(face_lighting, tuple) and len(face_lighting) != face_count:
        raise ValueError(
            f"mesh {mesh_index} has {face_count} faces but donor supplies "
            f"{len(face_lighting)} face-lighting values"
        )
    for face_index in range(face_count):
        length = u16(data, cursor + 2)
        lighting = (
            face_lighting[face_index]
            if isinstance(face_lighting, tuple)
            else face_lighting
        )
        output.extend(
            convert_face(
                data,
                cursor,
                dimensions,
                lighting,
                clear_indexed_rgb,
            )
        )
        cursor += length
    if cursor != model.mesh_ends[mesh_index]:
        raise AssertionError("mesh parser and converter disagree on end offset")
    mesh = adapt_bagman_nested_head_for_ps1(model, mesh_index, bytes(output))
    if wing_transfer is None:
        return mesh
    mesh = adapt_mesh_for_wing_sources(mesh, mesh_index, wing_transfer)
    wing_template = wing_transfer.templates.get(mesh_index)
    if wing_template is None:
        return mesh
    return inject_wing(
        mesh,
        wing_template,
        wing_index,
        wing_transfer.reference_map,
    )


def adapt_bagman_nested_head_for_ps1(
    model: ParsedModel,
    mesh_index: int,
    mesh: bytes,
) -> bytes:
    """Mark the complete inner shell for SM1's native OT depth-offset channel.

    Dreamcast renders Peter's head and neck behind the paper bag with a depth
    buffer. SM1 face flags 0x6000 select a model-specific ordering-table offset.
    The runtime supplies that offset only for this audited 179-face head batch.
    No geometry, texture, UV, normal, or face ordering is changed here.
    """
    if mesh_index != BAGMAN_HEAD_MESH or not is_bagman_model(model):
        return mesh

    header, vertices, normals, faces = mesh_parts(mesh, 0)
    if (
        len(vertices) != BAGMAN_HEAD_VERTEX_COUNT
        or len(faces) != BAGMAN_HEAD_FACE_COUNT
        or len(normals) != len(vertices) + len(faces)
    ):
        raise ValueError(
            "Bag-Man nested-head counts no longer match the audited Dreamcast source"
        )

    inner_vertices: set[int] = set()
    bag_vertices: set[int] = set()
    inner_faces = 0
    marked_faces: list[bytes] = []
    for face in faces:
        flags = u16(face, 0)
        if (flags & 3) == 0:
            raise ValueError("Bag-Man head unexpectedly contains an untextured face")
        corners = 4 if flags & 0x20 else 3
        texture_index = u32(face, 16)
        adjusted = bytearray(face)
        if texture_index == 5:
            inner_faces += 1
            inner_vertices.update(face[4 : 4 + corners])
            struct.pack_into("<H", adjusted, 0, flags | BAGMAN_INNER_DEPTH_MARKER)
        elif texture_index in (6, 7):
            bag_vertices.update(face[4 : 4 + corners])
            if flags & BAGMAN_INNER_DEPTH_MARKER:
                raise ValueError("Bag-Man paper shell already uses the inner-depth marker")
        else:
            raise ValueError(
                f"Bag-Man head unexpectedly uses texture index {texture_index}"
            )
        marked_faces.append(bytes(adjusted))

    if (
        inner_faces != BAGMAN_INNER_FACE_COUNT
        or inner_vertices != set(range(52))
        or bag_vertices != {0, *range(52, 100)}
        or inner_vertices & bag_vertices != {0}
    ):
        raise ValueError("Bag-Man nested-head topology no longer matches the audited source")

    return header + b"".join(vertices) + b"".join(normals) + b"".join(marked_faces)


def adapt_mesh_for_wing_sources(
    mesh: bytes,
    mesh_index: int,
    transfer: WingTransfer,
) -> bytes:
    """Preserve existing stitches while adding any donor-exact attachment sources."""
    header, vertices, normals, faces = mesh_parts(mesh, 0)
    old_vertex_count = len(vertices)
    old_face_count = len(faces)
    if len(normals) != old_vertex_count + old_face_count:
        raise ValueError(
            f"DC mesh {mesh_index} is not in per-vertex/per-face normal form"
        )

    def shift_reference(index: int) -> int:
        return index + sum(
            count for point, count in transfer.insertion_points if index >= point
        )

    shifted_vertices: list[bytes] = []
    for vertex in vertices:
        if u16(vertex, 6) == 2:
            adjusted = bytearray(vertex)
            struct.pack_into("<h", adjusted, 2, shift_reference(u16(vertex, 2)))
            shifted_vertices.append(bytes(adjusted))
        else:
            shifted_vertices.append(vertex)
    vertices = shifted_vertices

    additions = transfer.inserted_sources.get(mesh_index, ())
    if not additions:
        return bytes(header) + b"".join(vertices) + b"".join(normals) + b"".join(faces)

    added_count = len(additions)
    adjusted_faces: list[bytes] = []
    for face in faces:
        adjusted = bytearray(face)
        struct.pack_into("<I", adjusted, 12, u32(face, 12) + added_count)
        adjusted_faces.append(bytes(adjusted))

    vertices.extend(source.vertex for source in additions)
    normals = (
        normals[:old_vertex_count]
        + [source.normal for source in additions]
        + normals[old_vertex_count:]
    )
    struct.pack_into("<HHH", header, 2, len(vertices), len(normals), len(adjusted_faces))
    return bytes(header) + b"".join(vertices) + b"".join(normals) + b"".join(adjusted_faces)


def inject_wing(
    mesh: bytes,
    template: WingTemplate,
    wing_index: int,
    reference_map: dict[int, int],
) -> bytes:
    header, vertices, normals, faces = mesh_parts(mesh, 0)
    old_vertex_count = len(vertices)
    old_face_count = len(faces)
    if len(normals) != old_vertex_count + old_face_count:
        raise ValueError(
            f"DC upper-arm mesh {template.mesh_index} is not in per-vertex/per-face normal form"
        )
    added_vertices = len(template.vertices)

    seam_root_index = WING_SEAM_ROOT_VERTICES.get(template.mesh_index)
    if seam_root_index is None or seam_root_index >= old_vertex_count:
        raise ValueError(
            f"DC upper-arm mesh {template.mesh_index} lacks wing seam root "
            f"vertex {seam_root_index}"
        )

    donor_vertices: list[bytes] = []
    for vertex in template.vertices:
        if u16(vertex, 6) != 2:
            donor_vertices.append(vertex)
            continue
        donor_reference = u16(vertex, 2)
        if donor_reference not in reference_map:
            raise ValueError(f"wing stitch reference {donor_reference} was not translated")
        adjusted = bytearray(vertex)
        struct.pack_into("<h", adjusted, 2, reference_map[donor_reference])
        donor_vertices.append(bytes(adjusted))

    # Existing face-normal indices move because the new vertex normals are
    # inserted before the old face-normal block.
    adjusted_faces: list[bytes] = []
    for face in faces:
        adjusted = bytearray(face)
        struct.pack_into("<I", adjusted, 12, u32(face, 12) + added_vertices)
        adjusted_faces.append(bytes(adjusted))

    wing_faces: list[bytes] = []
    new_face_normal_base = len(normals) + added_vertices
    for face_index, face in enumerate(template.faces):
        adjusted = bytearray(face)
        for slot in range(4):
            adjusted[4 + slot] = old_vertex_count + adjusted[4 + slot]
        struct.pack_into("<I", adjusted, 12, new_face_normal_base + face_index)
        struct.pack_into("<I", adjusted, 16, wing_index)
        wing_faces.append(bytes(adjusted))

    # Preserve all authored donor faces verbatim, then cap the recipient-only
    # gap between the donor torso corner (0), donor mid-bicep corner (1), and
    # the DC upper-arm surface.  Both windings are emitted because the native
    # donor represents its zero-thickness membrane the same way.
    seam_faces: list[bytes] = []
    seam_normals: list[bytes] = []
    torso_corner = old_vertex_count
    bicep_corner = old_vertex_count + 1
    seam_orders = (
        (seam_root_index, bicep_corner, torso_corner),
        (torso_corner, bicep_corner, seam_root_index),
    )
    semantic_uvs = {
        seam_root_index: WING_SEAM_ROOT_UV,
        bicep_corner: (23, 32),
        torso_corner: (33, 62),
    }
    triangle_prototype = next(face for face in template.faces if face[0] == 0x1F)
    forward_normal = template.face_normals[0]
    reverse_normal = struct.pack(
        "<hhhH",
        -i16(forward_normal, 0),
        -i16(forward_normal, 2),
        -i16(forward_normal, 4),
        u16(forward_normal, 6),
    )
    for face_index, order in enumerate(seam_orders):
        adjusted = bytearray(triangle_prototype)
        adjusted[4:8] = bytes((*order, 0))
        for slot, vertex_index in enumerate(order):
            u, v = semantic_uvs[vertex_index]
            adjusted[20 + slot * 2] = u
            adjusted[21 + slot * 2] = v
        adjusted[26:28] = b"\x00\x00"
        struct.pack_into(
            "<I",
            adjusted,
            12,
            new_face_normal_base + len(template.faces) + face_index,
        )
        struct.pack_into("<I", adjusted, 16, wing_index)
        seam_faces.append(bytes(adjusted))
        seam_normals.append(forward_normal if face_index == 0 else reverse_normal)

    vertices.extend(donor_vertices)
    normals = (
        normals[:old_vertex_count]
        + list(template.vertex_normals)
        + normals[old_vertex_count:]
        + list(template.face_normals)
        + seam_normals
    )
    adjusted_faces.extend(wing_faces)
    adjusted_faces.extend(seam_faces)
    struct.pack_into("<HHH", header, 2, len(vertices), len(normals), len(adjusted_faces))
    return bytes(header) + b"".join(vertices) + b"".join(normals) + b"".join(adjusted_faces)


def build_texture_section(
    model: ParsedModel,
    texture_dir: Path,
    output: bytearray,
    dimensions: dict[int, tuple[int, int]],
    with_wings: bool,
    visible_wing_proof: bool = False,
    wing_proof_asset: Ps1TextureAsset | None = None,
) -> tuple[list[int], list[tuple[int, ...]], list[bytes]]:
    palette_cache_ids = generated_palette_cache_ids(model, with_wings)
    actor_assets = quantize_actor_textures(model, texture_dir, dimensions)
    palettes: list[tuple[int, ...]] = []
    pixels: list[bytes] = []
    for texture in model.textures:
        palette, payload = actor_assets[texture.index]
        palettes.append(palette)
        pixels.append(payload)
    spline_alias_asset = quantize_scorpion_spline_alias(
        model,
        texture_dir,
        dimensions,
        actor_assets,
    )
    if spline_alias_asset is not None:
        _, _, alias_palette, alias_payload = spline_alias_asset
        palettes.append(alias_palette)
        pixels.append(alias_payload)
    wing_index = len(model.texture_hashes) + int(spline_alias_asset is not None)
    if with_wings:
        if visible_wing_proof:
            if wing_proof_asset is not None:
                if (wing_proof_asset.width, wing_proof_asset.height) != (WING_SIZE, WING_SIZE):
                    raise ValueError(
                        f"wing proof texture is {wing_proof_asset.width}x{wing_proof_asset.height}, "
                        f"expected {WING_SIZE}x{WING_SIZE}"
                    )
                palettes.append(wing_proof_asset.palette)
                pixels.append(wing_proof_asset.payload)
            else:
                # Fallback UV diagnostic for callers that do not provide retail art.
                proof_palette = [MAGENTA_555] * 256
                proof_palette[1:7] = [0x7FFF, 0x001F, 0x03E0, 0x7C00, 0x03FF, 0x7FE0]
                proof_indices: list[int] = []
                for y in range(WING_SIZE):
                    for x in range(WING_SIZE):
                        if x < 3 or y < 3 or x >= WING_SIZE - 3 or y >= WING_SIZE - 3:
                            value = 1
                        elif abs(x - y) < 2 or abs((WING_SIZE - 1 - x) - y) < 2:
                            value = 1
                        else:
                            value = 2 + ((x // 8) + (y // 8)) % 5
                        proof_indices.append(value)
                palettes.append(tuple(proof_palette))
                pixels.append(inverse_fix_indices(proof_indices, WING_SIZE, WING_SIZE))
        else:
            palettes.append(tuple([MAGENTA_555] * 256))
            pixels.append(bytes(WING_SIZE * WING_SIZE))

    output.extend(pack_u32(0))  # no 4-bit palettes
    # Dreamcast 16-bit textures do not need a CLUT, so their shipped TexId is
    # commonly zero. SM1's CLUT cache is global rather than model-local, so even
    # the face-facing material index is unsafe: Black Cat index 0 otherwise
    # reuses Spider-Man index 0's palette when both actors are resident. Use one
    # stable, model-scoped declaration for all of an actor's compact pages. The
    # wing proof remains separate because it is authored independently.
    palette_declarations: dict[int, tuple[int, ...]] = {}
    for texture, palette in zip(model.textures, palettes):
        palette_cache_id = palette_cache_ids[texture.index]
        existing = palette_declarations.get(palette_cache_id)
        if existing is not None and existing != palette:
            raise ValueError(
                f"palette-cache id 0x{palette_cache_id:08X} has conflicting actor palettes"
            )
        palette_declarations[palette_cache_id] = palette
    if spline_alias_asset is not None:
        _, runtime_index, alias_palette, _ = spline_alias_asset
        alias_palette_id = palette_cache_ids[runtime_index]
        existing = palette_declarations.get(alias_palette_id)
        if existing is not None and existing != alias_palette:
            raise ValueError(
                f"palette-cache id 0x{alias_palette_id:08X} has conflicting "
                "Scorpion spline palette"
            )
        palette_declarations[alias_palette_id] = alias_palette
    if with_wings:
        wing_palette_id = palette_cache_ids[wing_index]
        existing = palette_declarations.get(wing_palette_id)
        if existing is not None and existing != palettes[-1]:
            raise ValueError(
                f"palette-cache id 0x{wing_palette_id:08X} has conflicting wing palette"
            )
        palette_declarations[wing_palette_id] = palettes[-1]

    output.extend(pack_u32(len(palette_declarations)))
    for palette_cache_id, palette in palette_declarations.items():
        output.extend(pack_u32(palette_cache_id))
        output.extend(struct.pack("<256H", *palette))

    output.extend(pack_u32(len(pixels)))
    pointer_table = len(output)
    output.extend(b"\x00" * (4 * len(pixels)))
    header_offsets: list[int] = []
    for texture, payload in zip(model.textures, pixels[: len(model.textures)]):
        width, height = dimensions[texture.index]
        header_offsets.append(len(output))
        output.extend(
            struct.pack(
                "<IIIIHH",
                texture.unk,
                256,
                palette_cache_ids[texture.index],
                texture.index,
                width,
                height,
            )
        )
        output.extend(payload)
    if spline_alias_asset is not None:
        source_texture, runtime_index, _, alias_payload = spline_alias_asset
        width, height = dimensions[runtime_index]
        header_offsets.append(len(output))
        output.extend(
            struct.pack(
                "<IIIIHH",
                source_texture.unk,
                256,
                palette_cache_ids[runtime_index],
                runtime_index,
                width,
                height,
            )
        )
        output.extend(alias_payload)
    if with_wings:
        header_offsets.append(len(output))
        output.extend(
            struct.pack(
                "<IIIIHH",
                0,
                256,
                palette_cache_ids[wing_index],
                wing_index,
                WING_SIZE,
                WING_SIZE,
            )
        )
        output.extend(pixels[-1])
    for index, header_offset in enumerate(header_offsets):
        struct.pack_into("<I", output, pointer_table + index * 4, header_offset)
    return header_offsets, palettes, pixels


def write_common_texture_prefix(
    model: ParsedModel,
    output: bytearray,
    with_wings: bool,
    tagged_chunks: bytes | None = None,
    mesh_names: tuple[int, ...] | None = None,
) -> None:
    output.extend(model.tagged_chunks if tagged_chunks is None else tagged_chunks)
    output_names = model.mesh_names if mesh_names is None else mesh_names
    output.extend(struct.pack(f"<{len(output_names)}I", *output_names))
    spline_alias = scorpion_spline_runtime_alias(model)
    output.extend(
        pack_u32(
            len(model.texture_hashes)
            + int(spline_alias is not None)
            + int(with_wings)
        )
    )
    output.extend(struct.pack(f"<{len(model.texture_hashes)}I", *model.texture_hashes))
    if spline_alias is not None:
        output.extend(pack_u32(SCORPION_SPLINE_RUNTIME_TEXTURE_HASH))
    if with_wings:
        if WING_HASH in model.texture_hashes:
            raise ValueError("model already contains the SM2 wing material hash")
        output.extend(pack_u32(WING_HASH))


def build_character(
    model: ParsedModel,
    texture_dir: Path,
    texture_scale: int,
    wing_donor: WingDonor | None,
    visible_wing_proof: bool = False,
    wing_proof_asset: Ps1TextureAsset | None = None,
    tagged_chunks: bytes | None = None,
    skeleton_donor: SkeletonDonor | None = None,
) -> bytes:
    if skeleton_donor is not None and tagged_chunks is not None:
        raise ValueError("use either a complete skeleton donor or tagged chunks, not both")
    with_wings = wing_donor is not None
    wing_transfer = prepare_wing_transfer(model, wing_donor) if wing_donor else None
    dimensions = scaled_dimensions(model, texture_scale, with_wings)
    wing_index = len(model.texture_hashes) + int(
        scorpion_spline_runtime_alias(model) is not None
    )
    mesh_order = (
        tuple(range(model.mesh_count))
        if skeleton_donor is None
        else skeleton_mesh_order(model, skeleton_donor)
    )
    attachment_remap = attachment_reorder_map(model, mesh_order, wing_transfer)
    output_mesh_names = (
        model.mesh_names
        if skeleton_donor is None
        else skeleton_donor.mesh_names
    )
    output_tagged_chunks = (
        tagged_chunks
        if skeleton_donor is None
        else skeleton_donor.tagged_chunks
    )
    first_mesh_offset = min(model.mesh_pointers)
    output = bytearray(model.data[:first_mesh_offset])
    struct.pack_into("<H", output, 0, 4)
    if skeleton_donor is not None:
        object_table = b"".join(skeleton_donor.objects)
        output[12 : 12 + len(object_table)] = object_table
    mesh_offsets: list[int] = []
    default_face_lighting = JAMESON_FACE_LIGHTING if is_jameson_model(model) else None
    for mesh_index in mesh_order:
        mesh_name = model.mesh_names[mesh_index]
        face_lighting: bytes | tuple[bytes, ...] | None = default_face_lighting
        if skeleton_donor is not None and mesh_name in SCORPION_TAIL_MESH_NAMES:
            # Scorpion's seven untextured tail meshes are otherwise byte-exact
            # between Dreamcast and PS1; only the three per-face lighting bytes
            # differ. Dreamcast's values become black in SM1's v4 lighting path,
            # so retain the DC geometry/normals and restore the matching retail
            # lighting triplet for each of the six faces per segment.
            face_lighting = skeleton_donor.face_lighting_by_mesh[mesh_name]
        mesh_offsets.append(len(output))
        converted_mesh = convert_mesh(
            model,
            mesh_index,
            dimensions,
            wing_transfer,
            wing_index,
            face_lighting,
            is_jameson_model(model),
        )
        output.extend(remap_attachment_references(converted_mesh, attachment_remap))
    for index, mesh_offset in enumerate(mesh_offsets):
        struct.pack_into("<I", output, model.mesh_pointer_table_offset + index * 4, mesh_offset)

    while len(output) % 4:
        output.append(0)
    struct.pack_into("<I", output, 4, len(output))
    write_common_texture_prefix(
        model,
        output,
        with_wings,
        output_tagged_chunks,
        output_mesh_names,
    )
    build_texture_section(
        model,
        texture_dir,
        output,
        dimensions,
        with_wings,
        visible_wing_proof,
        wing_proof_asset,
    )
    return bytes(output)


def build_texture_library(
    model: ParsedModel,
    texture_dir: Path,
    texture_scale: int,
    with_wings: bool,
    visible_wing_proof: bool = False,
    wing_proof_asset: Ps1TextureAsset | None = None,
) -> bytes:
    dimensions = scaled_dimensions(model, texture_scale, with_wings)
    # Texture-only v4 container: header, zero meshes, metadata terminator,
    # texture hash table, palettes, then texture records.
    output = bytearray(struct.pack("<HHIII", 4, 2, 16, 0, 0))
    output.extend(pack_u32(0xFFFFFFFF))
    spline_alias = scorpion_spline_runtime_alias(model)
    output.extend(
        pack_u32(
            len(model.texture_hashes)
            + int(spline_alias is not None)
            + int(with_wings)
        )
    )
    output.extend(struct.pack(f"<{len(model.texture_hashes)}I", *model.texture_hashes))
    if spline_alias is not None:
        output.extend(pack_u32(SCORPION_SPLINE_RUNTIME_TEXTURE_HASH))
    if with_wings:
        output.extend(pack_u32(WING_HASH))
    build_texture_section(
        model,
        texture_dir,
        output,
        dimensions,
        with_wings,
        visible_wing_proof,
        wing_proof_asset,
    )
    return bytes(output)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--textures", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--output-textures", type=Path)
    parser.add_argument(
        "--wing-donor",
        type=Path,
        help="loose PS1 SM2 spidey.psx used to add its stitched web-wing primitives",
    )
    parser.add_argument(
        "--texture-scale",
        type=int,
        default=1,
        help="integer divisor for DC texture dimensions (default: 1, preserving source resolution)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = parse_model(args.model)
    wings = load_wing_templates(args.wing_donor) if args.wing_donor else None
    character = build_character(model, args.textures, args.texture_scale, wings)
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    args.output_model.write_bytes(character)
    print(
        f"wrote {args.output_model} ({len(character):,} bytes, sha256 {sha256(character)})"
    )
    if args.output_textures:
        library = build_texture_library(model, args.textures, args.texture_scale, wings is not None)
        args.output_textures.parent.mkdir(parents=True, exist_ok=True)
        args.output_textures.write_bytes(library)
        print(
            f"wrote {args.output_textures} ({len(library):,} bytes, sha256 {sha256(library)})"
        )
    print(
        f"converted {model.mesh_count} meshes and {len(model.textures)} textures; "
        f"post-mesh payload preserved from 0x{model.post_mesh_offset:X}"
    )


if __name__ == "__main__":
    main()
