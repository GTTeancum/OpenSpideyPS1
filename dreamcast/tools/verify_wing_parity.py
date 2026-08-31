#!/usr/bin/env python3
"""Assert donor wing parity plus the recipient-specific DC armpit seam caps."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import struct
import sys


ROOT = Path(__file__).resolve().parents[2]
CONVERTER = ROOT / "spiderman" / "tools" / "port_dc_character.py"


def load_converter():
    spec = importlib.util.spec_from_file_location("dc_character_converter", CONVERTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load converter at {CONVERTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pointers(module, data: bytes) -> tuple[int, ...]:
    object_count = module.u32(data, 8)
    mesh_count = module.u32(data, 12 + object_count * 36)
    table = 16 + object_count * 36
    return tuple(module.u32(data, table + index * 4) for index in range(mesh_count))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dc-model",
        type=Path,
        default=ROOT / "dreamcast" / "extracted" / "SPIDEY.PSX",
    )
    parser.add_argument(
        "--donor",
        type=Path,
        default=ROOT / "spiderman2" / "extracted" / "wad" / "spidey.psx",
    )
    parser.add_argument(
        "--ported",
        type=Path,
        default=ROOT / "dreamcast" / "converted" / "sm1-winged-runtime" / "spidey.psx",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    module = load_converter()
    dc = module.parse_model(args.dc_model.resolve())
    donor = module.load_wing_templates(args.donor.resolve())
    donor_data = args.donor.read_bytes()
    output_data = args.ported.read_bytes()
    donor_pointers = pointers(module, donor_data)
    output_pointers = pointers(module, output_data)
    output_sources = {
        source.attachment_index: source
        for source in module.collect_attachment_sources(output_data, output_pointers)
    }

    face_total = 0
    for mesh_index, template in donor.templates.items():
        _, dc_vertices, _, dc_faces = module.mesh_parts(dc.data, dc.mesh_pointers[mesh_index])
        _, output_vertices, output_normals, output_faces = module.mesh_parts(
            output_data, output_pointers[mesh_index]
        )
        appended = output_vertices[len(dc_vertices) :]
        assert len(appended) == len(template.vertices), (
            mesh_index,
            len(appended),
            len(template.vertices),
        )

        for donor_vertex, output_vertex in zip(template.vertices, appended):
            donor_type = module.u16(donor_vertex, 6)
            assert module.u16(output_vertex, 6) == donor_type
            if donor_type != 2:
                assert output_vertex == donor_vertex
                continue
            assert output_vertex[0:2] == donor_vertex[0:2]
            assert output_vertex[4:8] == donor_vertex[4:8]
            donor_reference = module.u16(donor_vertex, 2)
            output_reference = module.u16(output_vertex, 2)
            donor_source = donor.attachment_sources[donor_reference]
            output_source = output_sources[output_reference]
            assert output_source.mesh_index == donor_source.mesh_index
            assert output_source.vertex == donor_source.vertex
            assert output_source.normal == donor_source.normal

        vertex_normal_start = len(dc_vertices)
        assert tuple(
            output_normals[
                vertex_normal_start : vertex_normal_start + len(template.vertex_normals)
            ]
        ) == template.vertex_normals

        assert len(output_faces) == len(dc_faces) + len(template.faces) + 2
        wing_face_start = len(dc_faces)
        wing_faces = output_faces[wing_face_start : wing_face_start + len(template.faces)]
        for donor_face, output_face in zip(template.faces, wing_faces):
            # Vertex, normal and texture indices relocate by construction. Every
            # authored field—including flags, packet color/mode and UV bytes—must match.
            donor_payload = donor_face[0:4] + donor_face[8:12] + donor_face[20:]
            output_payload = output_face[0:4] + output_face[8:12] + output_face[20:]
            assert output_payload == donor_payload
        donor_normal_start = len(output_normals) - len(template.face_normals) - 2
        assert tuple(
            output_normals[
                donor_normal_start : donor_normal_start + len(template.face_normals)
            ]
        ) == template.face_normals

        seam_faces = output_faces[-2:]
        seam_root = module.WING_SEAM_ROOT_VERTICES[mesh_index]
        torso_corner = len(dc_vertices)
        bicep_corner = torso_corner + 1
        assert tuple(seam_faces[0][4:7]) == (seam_root, bicep_corner, torso_corner)
        assert tuple(seam_faces[1][4:7]) == (torso_corner, bicep_corner, seam_root)
        expected_uvs = {
            seam_root: module.WING_SEAM_ROOT_UV,
            bicep_corner: (23, 32),
            torso_corner: (33, 62),
        }
        for seam_face in seam_faces:
            assert module.u32(seam_face, 16) == len(dc.texture_hashes)
            for slot, vertex_index in enumerate(seam_face[4:7]):
                assert tuple(seam_face[20 + slot * 2 : 22 + slot * 2]) == expected_uvs[vertex_index]
        face_total += len(template.faces)

    unresolved: list[tuple[int, int, int]] = []
    for mesh_index, pointer in enumerate(output_pointers):
        _, vertices, _, _ = module.mesh_parts(output_data, pointer)
        for vertex_index, vertex in enumerate(vertices):
            if module.u16(vertex, 6) != 2:
                continue
            reference = module.u16(vertex, 2)
            if reference not in output_sources:
                unresolved.append((mesh_index, vertex_index, reference))
    assert not unresolved, unresolved
    print(
        f"PASS: {face_total} donor wing faces exact plus 4 DC armpit seam faces; "
        f"donor UV/packet payloads and normals exact; "
        f"all stitched vertices preserve donor source geometry and bone ownership; "
        f"{len(output_sources)} output attachment sources; 0 unresolved stitches"
    )


if __name__ == "__main__":
    main()
