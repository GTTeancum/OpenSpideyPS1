"""Transfer an SM2 suit's UVs/materials onto the high-detail DC Spider-Man.

Run with Blender.  Unlike an image bake, nearest-surface transfer does not write
multiple target polygons into overlapping Dreamcast UV islands.  Every non-wing
target loop receives a barycentrically interpolated UV from the nearest SM2 source
triangle and uses that triangle's original SM2 material.  The donor-exact target
wing UVs are preserved and paired with the source's native DC38D248 material.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform, closest_point_on_tri


sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_tpose_glb import (  # noqa: E402
    bake_pose,
    blender_compatible_glb,
    clear_scene,
    export_glb,
    pose_arms,
)


WING_MATERIAL = "tex_dc38d248"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--textures-output", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--mapping-output",
        help=(
            "optional JSON sidecar containing the original target triangle identity "
            "and the transferred SM2 material/UVs for native PSX repacking"
        ),
    )
    return parser.parse_args(argv)


def import_group(path: str) -> tuple[bpy.types.Object, bpy.types.Object, set[bpy.types.Object]]:
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    created = set(bpy.context.scene.objects).difference(before)
    armatures = [obj for obj in created if obj.type == "ARMATURE"]
    meshes = [
        obj
        for obj in created
        if obj.type == "MESH" and any(mod.type == "ARMATURE" for mod in obj.modifiers)
    ]
    if len(armatures) != 1 or len(meshes) != 1:
        raise RuntimeError(
            f"expected one armature and one skinned mesh in {path}, found "
            f"{len(armatures)} and {len(meshes)}"
        )
    return armatures[0], meshes[0], created


def material_image(material: bpy.types.Material) -> bpy.types.Image:
    if not material.use_nodes or material.node_tree is None:
        raise RuntimeError(f"material {material.name} has no node tree")
    nodes = [node for node in material.node_tree.nodes if node.type == "TEX_IMAGE"]
    if not nodes or nodes[0].image is None:
        raise RuntimeError(f"material {material.name} has no image")
    return nodes[0].image


def save_source_images(source: bpy.types.Object, output: str) -> None:
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    saved: set[str] = set()
    for slot in source.material_slots:
        material = slot.material
        if material is None or material.name in saved:
            continue
        image = material_image(material)
        image.filepath_raw = str((root / f"{material.name}.png").resolve())
        image.file_format = "PNG"
        image.save()
        saved.add(material.name)


def gltf_uv(uv: Vector) -> list[float]:
    """Convert Blender's imported UV convention back to glTF's convention."""
    return [float(uv.x), float(1.0 - uv.y)]


def polygon_snapshot(
    target: bpy.types.Object,
    polygon: bpy.types.MeshPolygon,
    materials: list[bpy.types.Material],
) -> dict[str, object]:
    mesh = target.data
    material = materials[polygon.material_index]
    image = material_image(material)
    return {
        "materialIndex": polygon.material_index,
        "material": material.name,
        "image": image.name,
        "imageSize": [int(image.size[0]), int(image.size[1])],
        "vertexIndices": [int(mesh.loops[index].vertex_index) for index in polygon.loop_indices],
        "positions": [
            [float(value) for value in mesh.vertices[mesh.loops[index].vertex_index].co]
            for index in polygon.loop_indices
        ],
        "uvs": [gltf_uv(mesh.uv_layers.active.data[index].uv) for index in polygon.loop_indices],
    }


def transfer_surface(
    source: bpy.types.Object,
    target: bpy.types.Object,
) -> tuple[dict[str, int], list[dict[str, object]]]:
    source_mesh = source.data
    target_mesh = target.data
    source_uv = source_mesh.uv_layers.active
    target_uv = target_mesh.uv_layers.active
    if source_uv is None or target_uv is None:
        raise RuntimeError("source and target must both have active UV layers")

    source_mesh.calc_loop_triangles()
    triangles = list(source_mesh.loop_triangles)
    vertices = [vertex.co.copy() for vertex in source_mesh.vertices]
    triangle_vertices = [tuple(triangle.vertices) for triangle in triangles]
    bvh = BVHTree.FromPolygons(vertices, triangle_vertices, all_triangles=True)

    source_materials = [slot.material for slot in source.material_slots]
    if any(material is None for material in source_materials):
        raise RuntimeError("source contains an empty material slot")
    source_wing_index = next(
        (
            index
            for index, material in enumerate(source_materials)
            if material.name.casefold().startswith(WING_MATERIAL)
        ),
        None,
    )
    target_wing_indices = {
        index
        for index, slot in enumerate(target.material_slots)
        if slot.material is not None
        and slot.material.name.casefold().startswith(WING_MATERIAL)
    }
    if source_wing_index is None or not target_wing_indices:
        raise RuntimeError("source or target lacks native DC38D248 wing material")
    source_wing_material = source_materials[source_wing_index]
    target_wing_material = next(
        target.material_slots[index].material for index in target_wing_indices
    )
    source_wing_image = material_image(source_wing_material)
    target_wing_image = material_image(target_wing_material)
    u_scale = target_wing_image.size[0] / source_wing_image.size[0]
    v_scale = target_wing_image.size[1] / source_wing_image.size[1]
    target_wing_polygons = {
        polygon.index
        for polygon in target_mesh.polygons
        if polygon.material_index in target_wing_indices
    }

    original_target_materials = [slot.material for slot in target.material_slots]
    if any(material is None for material in original_target_materials):
        raise RuntimeError("target contains an empty material slot")
    mappings = [
        {
            "polygonIndex": int(polygon.index),
            "isWing": polygon.index in target_wing_polygons,
            "original": polygon_snapshot(target, polygon, original_target_materials),
        }
        for polygon in target_mesh.polygons
    ]

    target_mesh.materials.clear()
    for material in source_materials:
        target_mesh.materials.append(material)

    transferred_polygons = 0
    transferred_loops = 0
    preserved_wing_polygons = 0
    misses = 0
    for polygon in target_mesh.polygons:
        if polygon.index in target_wing_polygons:
            polygon.material_index = source_wing_index
            for loop_index in polygon.loop_indices:
                target_uv.data[loop_index].uv.x *= u_scale
                # glTF V is imported as 1-V. Scale about that pivot so the
                # exported coordinate retains the same source pixel position.
                target_uv.data[loop_index].uv.y = 1.0 + (
                    target_uv.data[loop_index].uv.y - 1.0
                ) * v_scale
            preserved_wing_polygons += 1
            continue

        center_hit = bvh.find_nearest(polygon.center)
        if center_hit is None or center_hit[2] is None:
            misses += 1
            continue
        center_triangle = triangles[center_hit[2]]
        polygon.material_index = center_triangle.material_index
        transferred_polygons += 1
        a, b, c = (source_mesh.vertices[index].co for index in center_triangle.vertices)
        uv_a, uv_b, uv_c = (
            Vector((*source_uv.data[index].uv, 0.0))
            for index in center_triangle.loops
        )

        for loop_index in polygon.loop_indices:
            point = target_mesh.vertices[target_mesh.loops[loop_index].vertex_index].co
            location = closest_point_on_tri(point, a, b, c)
            uv = barycentric_transform(location, a, b, c, uv_a, uv_b, uv_c)
            target_uv.data[loop_index].uv = uv.xy
            transferred_loops += 1

    if misses:
        raise RuntimeError(f"nearest-surface transfer missed {misses} elements")
    for polygon, mapping in zip(target_mesh.polygons, mappings, strict=True):
        mapping["mapped"] = polygon_snapshot(target, polygon, source_materials)
    return (
        {
            "transferredPolygons": transferred_polygons,
            "transferredLoops": transferred_loops,
            "preservedWingPolygons": preserved_wing_polygons,
        },
        mappings,
    )


def main() -> None:
    args = parse_args()
    clear_scene()
    with tempfile.TemporaryDirectory(prefix="spidey-costume-transfer-") as temporary_root:
        target_path = blender_compatible_glb(os.path.abspath(args.target), temporary_root)
        source_path = blender_compatible_glb(os.path.abspath(args.source), temporary_root)
        target_armature, target_mesh, target_group = import_group(target_path)
        _, source_mesh, source_group = import_group(source_path)

        save_source_images(source_mesh, args.textures_output)
        counts, mappings = transfer_surface(source_mesh, target_mesh)
        if args.mapping_output:
            mapping_path = Path(args.mapping_output).resolve()
            mapping_path.parent.mkdir(parents=True, exist_ok=True)
            mapping_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "name": args.name,
                        "source": os.path.abspath(args.source),
                        "target": os.path.abspath(args.target),
                        "polygonCount": len(mappings),
                        "counts": counts,
                        "polygons": mappings,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        for obj in source_group:
            bpy.data.objects.remove(obj, do_unlink=True)
        pose_arms(target_armature)
        baked = bake_pose(target_armature)
        if not baked:
            raise RuntimeError("target had no skinned mesh to bake into the T-pose")
        export_glb(args.output, baked)

    print(
        f"wrote {args.name} nearest-surface DC transfer: {os.path.abspath(args.output)}; "
        f"polygons={counts['transferredPolygons']}, loops={counts['transferredLoops']}, "
        f"wingPolygons={counts['preservedWingPolygons']}"
    )


if __name__ == "__main__":
    main()
