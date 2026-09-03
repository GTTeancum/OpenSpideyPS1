"""Surface-bake an SM2 PS1 costume onto donor-exact winged DC Spider-Man.

Run with Blender. Both inputs are loose-file-derived GLBs. The source is the
SM2 low-detail model carrying one ``sp_texNN`` library; the target is the
high-detail DC model reconstructed from the donor-exact winged PSX binary.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

import bpy
import bmesh
from mathutils import Vector


sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_tpose_glb import (  # noqa: E402
    bake_pose,
    blender_compatible_glb,
    clear_scene,
    export_glb,
    pose_arms,
)
from transfer_sm2_costume_to_dc_oracle import (  # noqa: E402
    closest_hit as oracle_closest_hit,
    source_groups_for,
    triangle_group_name,
    triangle_uv_at,
)


TARGET_WING_MATERIAL = "tex_dc38d248"
SOURCE_WING_MATERIAL = "tex_ceb60740"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--textures-output", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--blend-output")
    parser.add_argument("--validation-output")
    parser.add_argument(
        "--hide-wings",
        action="store_true",
        help="retain the donor wing geometry/UVs but make its texture transparent",
    )
    parser.add_argument(
        "--split-by-bone",
        action="store_true",
        help=(
            "duplicate donor materials per dominant bone so intentional DC atlas "
            "overlaps cannot make unrelated body parts overwrite one another"
        ),
    )
    parser.add_argument(
        "--atlas-by-bone",
        action="store_true",
        help=(
            "author one non-overlapping UV atlas/material per rigid Dreamcast "
            "body part before isolated surface baking"
        ),
    )
    parser.add_argument(
        "--split-by-uv-island",
        action="store_true",
        help=(
            "duplicate donor materials per original UV island and rigid body "
            "part so overlapping Dreamcast atlas regions cannot overwrite"
        ),
    )
    parser.add_argument("--cage-extrusion", type=float, default=1.5)
    parser.add_argument("--max-ray-distance", type=float, default=3.0)
    parser.add_argument("--margin", type=int, default=1)
    parser.add_argument(
        "--resolution-scale",
        type=int,
        default=1,
        help="integer multiplier for the donor texture page dimensions",
    )
    parser.add_argument(
        "--align-source-by-bone",
        action="store_true",
        help=(
            "conform each SM2 rigid body segment to the matching Dreamcast "
            "segment bounds before the selected-to-active surface bake"
        ),
    )
    parser.add_argument(
        "--cpu-surface",
        action="store_true",
        help=(
            "keep the original Dreamcast UVs and rasterize the SM2 surface "
            "appearance into those texture pages without Cycles ray baking"
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


def image_node(material: bpy.types.Material) -> bpy.types.ShaderNodeTexImage:
    if not material.use_nodes or material.node_tree is None:
        raise RuntimeError(f"material {material.name} has no node tree")
    candidates = [node for node in material.node_tree.nodes if node.type == "TEX_IMAGE"]
    if not candidates:
        raise RuntimeError(f"material {material.name} has no image texture node")
    node = candidates[0]
    material.node_tree.nodes.active = node
    return node


def prepare_bake_images(
    target: bpy.types.Object,
    costume_name: str,
    resolution_scale: int,
) -> dict[str, tuple[bpy.types.Image, bpy.types.ShaderNodeTexImage]]:
    if resolution_scale < 1:
        raise ValueError("resolution scale must be at least one")
    images: dict[str, tuple[bpy.types.Image, bpy.types.ShaderNodeTexImage]] = {}
    for slot in target.material_slots:
        material = slot.material
        if material is None:
            continue
        old_node = image_node(material)
        old = old_node.image
        width = old.size[0] if old is not None else 256
        height = old.size[1] if old is not None else 256
        image = bpy.data.images.new(
            f"{costume_name}_{material.name}",
            width=max(int(width) * resolution_scale, 1),
            height=max(int(height) * resolution_scale, 1),
            alpha=True,
        )
        # The source palette alpha is not a reliable body-opacity signal, so a
        # temporary impossible body color marks untouched bake texels.  It is
        # completely replaced and validated before any artifact is saved.
        image.generated_color = (1.0, 0.0, 1.0, 1.0)
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.name = f"{costume_name} surface bake"
        node.image = image
        node.interpolation = "Closest"
        material.node_tree.nodes.active = node
        images[material.name] = (image, node)
    return images


def oracle_signature(target: bpy.types.Object) -> dict[str, object]:
    """Capture the donor-authored data that a surface bake must not alter."""
    uv_layer = target.data.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Dreamcast oracle has no active UV layer")

    def digest(values: object) -> str:
        encoded = json.dumps(values, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    positions = [
        [coordinate.hex() for coordinate in vertex.co]
        for vertex in target.data.vertices
    ]
    uvs = [
        [coordinate.hex() for coordinate in loop.uv]
        for loop in uv_layer.data
    ]
    material_indices = [polygon.material_index for polygon in target.data.polygons]
    material_slots = [
        slot.material.name if slot.material is not None else None
        for slot in target.material_slots
    ]
    return {
        "vertexCount": len(positions),
        "loopCount": len(uvs),
        "polygonCount": len(material_indices),
        "materialSlotCount": len(material_slots),
        "positionSha256": digest(positions),
        "uvSha256": digest(uvs),
        "polygonMaterialIndexSha256": digest(material_indices),
        "materialSlots": material_slots,
        "materialSlotsSha256": digest(material_slots),
    }


def polygon_group_name(
    target: bpy.types.Object,
    polygon: bpy.types.MeshPolygon,
) -> str:
    totals: dict[str, float] = {}
    for vertex_index in polygon.vertices:
        for membership in target.data.vertices[vertex_index].groups:
            group_name = target.vertex_groups[membership.group].name
            totals[group_name] = totals.get(group_name, 0.0) + membership.weight
    return max(totals, key=totals.get) if totals else "unweighted"


def dominant_group_name(obj: bpy.types.Object, vertex_index: int) -> str | None:
    memberships = obj.data.vertices[vertex_index].groups
    if not memberships:
        return None
    strongest = max(memberships, key=lambda membership: membership.weight)
    return obj.vertex_groups[strongest.group].name


def group_bounds(obj: bpy.types.Object) -> dict[str, tuple[Vector, Vector]]:
    points: dict[str, list[Vector]] = {}
    for vertex in obj.data.vertices:
        group_name = dominant_group_name(obj, vertex.index)
        if group_name is not None:
            points.setdefault(group_name, []).append(vertex.co.copy())
    return {
        group_name: (
            Vector(tuple(min(point[axis] for point in values) for axis in range(3))),
            Vector(tuple(max(point[axis] for point in values) for axis in range(3))),
        )
        for group_name, values in points.items()
    }


def align_source_by_bone(
    source: bpy.types.Object,
    target: bpy.types.Object,
) -> dict[str, object]:
    """Move only the disposable bake source into the DC donor's part bounds.

    Both games use matching rigid-body group names for the costume surface, but
    their low- and high-detail meshes differ enough that a world-space ray can
    cross a thin head or calf.  Normalizing within each named segment preserves
    front/back and joint position before the source is projected onto the
    untouched Dreamcast mesh.
    """
    source_bounds = group_bounds(source)
    target_bounds = group_bounds(target)
    matched_groups = sorted(source_bounds.keys() & target_bounds.keys())
    moved_vertices = 0
    unmatched_vertices = 0
    for vertex in source.data.vertices:
        group_name = dominant_group_name(source, vertex.index)
        if group_name not in source_bounds or group_name not in target_bounds:
            unmatched_vertices += 1
            continue
        source_minimum, source_maximum = source_bounds[group_name]
        target_minimum, target_maximum = target_bounds[group_name]
        result = Vector()
        for axis in range(3):
            source_extent = source_maximum[axis] - source_minimum[axis]
            if abs(source_extent) <= 1e-6:
                result[axis] = (
                    target_minimum[axis] + target_maximum[axis]
                ) * 0.5
                continue
            fraction = (
                vertex.co[axis] - source_minimum[axis]
            ) / source_extent
            result[axis] = target_minimum[axis] + fraction * (
                target_maximum[axis] - target_minimum[axis]
            )
        vertex.co = result
        moved_vertices += 1
    source.data.update()
    return {
        "strategy": "dominant matching bone normalized to Dreamcast bounds",
        "matchedGroups": matched_groups,
        "movedVertices": moved_vertices,
        "unmatchedVertices": unmatched_vertices,
    }


def split_materials_by_bone(target: bpy.types.Object) -> dict[str, object]:
    """Isolate donor-atlas writes while retaining every original loop UV."""
    original_materials = [slot.material for slot in target.material_slots]
    if any(material is None for material in original_materials):
        raise RuntimeError("Dreamcast oracle contains an empty material slot")
    polygon_original_indices = [
        polygon.material_index for polygon in target.data.polygons
    ]
    original_indices = [polygon.material_index for polygon in target.data.polygons]
    attribute = target.data.attributes.get("dc_oracle_material_index")
    if attribute is None:
        attribute = target.data.attributes.new(
            "dc_oracle_material_index",
            type="INT",
            domain="FACE",
        )
    for polygon, original_index in zip(
        target.data.polygons,
        original_indices,
        strict=True,
    ):
        attribute.data[polygon.index].value = original_index

    keys: list[tuple[int, str]] = []
    for polygon, original_index in zip(
        target.data.polygons,
        original_indices,
        strict=True,
    ):
        original = original_materials[original_index]
        assert original is not None
        if original.name.casefold().startswith(TARGET_WING_MATERIAL):
            group_name = "wings"
        else:
            group_name = polygon_group_name(target, polygon)
        keys.append((original_index, group_name))

    target.data.materials.clear()
    material_indices: dict[tuple[int, str], int] = {}
    records: list[dict[str, object]] = []
    for original_index, group_name in dict.fromkeys(keys):
        original = original_materials[original_index]
        assert original is not None
        material = original.copy()
        clean_group = re.sub(r"[^A-Za-z0-9_.-]+", "_", group_name)
        material.name = f"{original.name}__{clean_group}"
        material["dc_oracle_material"] = original.name
        material["dc_oracle_material_index"] = original_index
        material["dc_oracle_bone_group"] = group_name
        target.data.materials.append(material)
        material_indices[(original_index, group_name)] = len(target.data.materials) - 1
        records.append(
            {
                "outputMaterial": material.name,
                "oracleMaterial": original.name,
                "oracleMaterialIndex": original_index,
                "boneGroup": group_name,
            }
        )

    for polygon, key in zip(target.data.polygons, keys, strict=True):
        polygon.material_index = material_indices[key]
    return {
        "strategy": "original Dreamcast material plus dominant donor bone",
        "outputMaterialCount": len(records),
        "materials": records,
    }


def split_materials_by_uv_island(target: bpy.types.Object) -> dict[str, object]:
    """Isolate overlapping donor UV islands without changing loop UV values."""
    uv_layer = target.data.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Dreamcast oracle has no active UV layer")
    original_materials = [slot.material for slot in target.material_slots]
    if any(material is None for material in original_materials):
        raise RuntimeError("Dreamcast oracle contains an empty material slot")

    polygon_original_indices = [
        int(polygon.material_index) for polygon in target.data.polygons
    ]
    polygon_groups = [
        (
            "wings"
            if original_materials[polygon.material_index]
            .name.casefold()
            .startswith(TARGET_WING_MATERIAL)
            else polygon_group_name(target, polygon)
        )
        for polygon in target.data.polygons
    ]
    polygon_keys = list(zip(polygon_original_indices, polygon_groups, strict=True))

    edge_uses: dict[
        tuple[int, int],
        list[tuple[int, dict[int, tuple[float, float]]]],
    ] = {}
    for polygon in target.data.polygons:
        uv_at_vertex = {
            int(target.data.loops[loop_index].vertex_index): tuple(
                float(value) for value in uv_layer.data[loop_index].uv
            )
            for loop_index in polygon.loop_indices
        }
        vertices = [int(index) for index in polygon.vertices]
        for index, vertex_a in enumerate(vertices):
            vertex_b = vertices[(index + 1) % len(vertices)]
            edge = tuple(sorted((vertex_a, vertex_b)))
            edge_uses.setdefault(edge, []).append((polygon.index, uv_at_vertex))

    adjacency = [set() for _ in target.data.polygons]
    for edge, uses in edge_uses.items():
        if len(uses) < 2:
            continue
        vertex_a, vertex_b = edge
        for left_index in range(len(uses)):
            left_polygon, left_uvs = uses[left_index]
            for right_polygon, right_uvs in uses[left_index + 1 :]:
                if polygon_keys[left_polygon] != polygon_keys[right_polygon]:
                    continue
                continuous = all(
                    max(
                        abs(left_uvs[vertex][axis] - right_uvs[vertex][axis])
                        for axis in range(2)
                    )
                    <= 1e-6
                    for vertex in (vertex_a, vertex_b)
                )
                if continuous:
                    adjacency[left_polygon].add(right_polygon)
                    adjacency[right_polygon].add(left_polygon)

    components: list[list[int]] = []
    visited: set[int] = set()
    for polygon in target.data.polygons:
        if polygon.index in visited:
            continue
        component = []
        stack = [polygon.index]
        visited.add(polygon.index)
        while stack:
            polygon_index = stack.pop()
            component.append(polygon_index)
            for neighbour in adjacency[polygon_index]:
                if neighbour in visited:
                    continue
                visited.add(neighbour)
                stack.append(neighbour)
        components.append(component)

    target.data.materials.clear()
    records: list[dict[str, object]] = []
    for component_index, component in enumerate(components):
        first_polygon = component[0]
        original_index, group_name = polygon_keys[first_polygon]
        original = original_materials[original_index]
        assert original is not None
        if group_name == "wings":
            material = original
        else:
            material = original.copy()
            clean_group = re.sub(r"[^A-Za-z0-9_.-]+", "_", group_name)
            material.name = (
                f"{original.name}__{clean_group}__island_{component_index:03d}"
            )
            material["dc_oracle_material"] = original.name
            material["dc_oracle_material_index"] = original_index
            material["dc_oracle_bone_group"] = group_name
            material["dc_oracle_uv_island"] = component_index
        target.data.materials.append(material)
        material_index = len(target.data.materials) - 1
        for polygon_index in component:
            target.data.polygons[polygon_index].material_index = material_index
        records.append(
            {
                "outputMaterial": material.name,
                "oracleMaterial": original.name,
                "oracleMaterialIndex": original_index,
                "boneGroup": group_name,
                "uvIsland": component_index,
                "polygonCount": len(component),
            }
        )
    return {
        "strategy": "original Dreamcast material, rigid body, and UV island",
        "outputMaterialCount": len(records),
        "materials": records,
    }


def atlas_materials_by_bone(target: bpy.types.Object) -> dict[str, object]:
    """Give each rigid body part independent UV space without changing geometry."""
    original_materials = [slot.material for slot in target.material_slots]
    if any(material is None for material in original_materials):
        raise RuntimeError("Dreamcast oracle contains an empty material slot")
    polygon_original_indices = [
        polygon.material_index for polygon in target.data.polygons
    ]
    polygon_groups = [
        (
            "wings"
            if original_materials[polygon.material_index]
            .name.casefold()
            .startswith(TARGET_WING_MATERIAL)
            else polygon_group_name(target, polygon)
        )
        for polygon in target.data.polygons
    ]
    groups = list(dict.fromkeys(polygon_groups))

    target.data.materials.clear()
    material_indices: dict[str, int] = {}
    records: list[dict[str, object]] = []
    for group_name in groups:
        polygon_index = polygon_groups.index(group_name)
        original_index = polygon_original_indices[polygon_index]
        original = original_materials[original_index]
        assert original is not None
        material = original.copy()
        clean_group = re.sub(r"[^A-Za-z0-9_.-]+", "_", group_name)
        material.name = (
            original.name
            if group_name == "wings"
            else f"dc_part_atlas__{clean_group}"
        )
        material["dc_oracle_bone_group"] = group_name
        target.data.materials.append(material)
        material_indices[group_name] = len(target.data.materials) - 1
        records.append(
            {
                "outputMaterial": material.name,
                "boneGroup": group_name,
                "oracleSeedMaterial": original.name,
            }
        )
    for polygon, group_name in zip(target.data.polygons, polygon_groups, strict=True):
        polygon.material_index = material_indices[group_name]

    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_mesh = bmesh.from_edit_mesh(target.data)
    edit_mesh.faces.ensure_lookup_table()
    for group_name in groups:
        if group_name == "wings":
            continue
        for face, face_group in zip(edit_mesh.faces, polygon_groups, strict=True):
            face.select = face_group == group_name
        bmesh.update_edit_mesh(target.data, loop_triangles=False, destructive=False)
        bpy.ops.uv.smart_project(
            angle_limit=math.radians(66.0),
            island_margin=0.03,
            area_weight=0.0,
            correct_aspect=True,
            scale_to_bounds=True,
        )
    bpy.ops.object.mode_set(mode="OBJECT")
    return {
        "strategy": "one smart-projected UV atlas per rigid Dreamcast body part",
        "outputMaterialCount": len(records),
        "materials": records,
    }


def validate_oracle_unchanged(
    before: dict[str, object],
    target: bpy.types.Object,
    material_expansion: dict[str, object] | None,
    allow_uv_remap: bool = False,
) -> dict[str, object]:
    after = oracle_signature(target)
    fields = [
        "vertexCount",
        "loopCount",
        "polygonCount",
        "positionSha256",
    ]
    if not allow_uv_remap:
        fields.append("uvSha256")
    if material_expansion is None:
        fields.extend(
            (
                "materialSlotCount",
                "polygonMaterialIndexSha256",
                "materialSlotsSha256",
            )
        )
    checks = {field: before[field] == after[field] for field in fields}
    if not all(checks.values()):
        failures = [field for field, passed in checks.items() if not passed]
        raise RuntimeError(
            "surface bake altered Dreamcast oracle data: " + ", ".join(failures)
        )
    return {
        "oracle": "original Dreamcast Spider-Man geometry, UVs, and material assignments",
        "passed": True,
        "checks": checks,
        "materialExpansion": material_expansion,
        "uvRemapped": allow_uv_remap,
        "before": before,
        "after": after,
    }


def bake_body(
    source: bpy.types.Object,
    target: bpy.types.Object,
    cage_extrusion: float,
    max_ray_distance: float,
    margin: int,
) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.bake.use_selected_to_active = True
    # Group-isolated passes intentionally accumulate into the prepared atlas
    # images.  Clearing here would erase every body part baked by an earlier
    # pass and leave only the last group in alphabetical order.
    scene.render.bake.use_clear = False
    scene.render.bake.cage_extrusion = cage_extrusion
    scene.render.bake.max_ray_distance = max_ray_distance
    scene.render.bake.margin = margin
    bpy.ops.object.bake(type="EMIT", target="IMAGE_TEXTURES")


def duplicate_group_part(
    obj: bpy.types.Object,
    group_name: str,
) -> bpy.types.Object:
    """Create a disposable copy containing only one rigid anatomical part."""
    keep = {
        polygon.index
        for polygon in obj.data.polygons
        if polygon_group_name(obj, polygon) == group_name
    }
    if not keep:
        raise RuntimeError(f"{obj.name} has no polygons for group {group_name}")

    part = obj.copy()
    part.data = obj.data.copy()
    part.name = f"{obj.name}__BAKE_PART__{group_name}"
    bpy.context.scene.collection.objects.link(part)

    mesh = bmesh.new()
    mesh.from_mesh(part.data)
    mesh.faces.ensure_lookup_table()
    remove = [face for face in mesh.faces if face.index not in keep]
    bmesh.ops.delete(mesh, geom=remove, context="FACES")
    mesh.to_mesh(part.data)
    mesh.free()
    part.data.update()

    used_material_indices = sorted(
        {polygon.material_index for polygon in part.data.polygons}
    )
    used_materials = [part.data.materials[index] for index in used_material_indices]
    remap = {
        old_index: new_index
        for new_index, old_index in enumerate(used_material_indices)
    }
    for polygon in part.data.polygons:
        polygon.material_index = remap[polygon.material_index]
    part.data.materials.clear()
    for material in used_materials:
        part.data.materials.append(material)
    return part


def bake_body_by_group(
    source: bpy.types.Object,
    target: bpy.types.Object,
    cage_extrusion: float,
    max_ray_distance: float,
    margin: int,
) -> dict[str, object]:
    """Bake each matching rigid part without rays reaching adjacent anatomy."""
    source_groups = {
        polygon_group_name(source, polygon) for polygon in source.data.polygons
    }
    target_groups = {
        polygon_group_name(target, polygon)
        for polygon in target.data.polygons
        if not target.material_slots[polygon.material_index]
        .material.name.casefold()
        .startswith(TARGET_WING_MATERIAL)
    }
    source_bounds = group_bounds(source)
    target_bounds = group_bounds(target)
    group_map: dict[str, str] = {}
    semantic_aliases = {
        "Spidey_Spidey_Torso01": "Spidey_Spidey_Torso02",
    }
    for target_group in target_groups:
        if target_group in source_groups:
            group_map[target_group] = target_group
            continue
        if semantic_aliases.get(target_group) in source_groups:
            group_map[target_group] = semantic_aliases[target_group]
            continue
        target_minimum, target_maximum = target_bounds[target_group]
        target_center = (target_minimum + target_maximum) * 0.5
        group_map[target_group] = min(
            source_groups,
            key=lambda source_group: (
                ((source_bounds[source_group][0] + source_bounds[source_group][1]) * 0.5)
                - target_center
            ).length_squared,
        )

    baked_groups: list[str] = []
    for group_name in sorted(target_groups):
        source_part = duplicate_group_part(source, group_map[group_name])
        target_part = duplicate_group_part(target, group_name)
        try:
            bake_body(
                source_part,
                target_part,
                cage_extrusion,
                max_ray_distance,
                margin,
            )
            baked_groups.append(group_name)
        finally:
            source_data = source_part.data
            target_data = target_part.data
            bpy.data.objects.remove(source_part, do_unlink=True)
            bpy.data.objects.remove(target_part, do_unlink=True)
            bpy.data.meshes.remove(source_data)
            bpy.data.meshes.remove(target_data)
    return {
        "strategy": "selected-to-active isolated by matching rigid body group",
        "groups": baked_groups,
        "groupMap": group_map,
    }


def cpu_surface_bake(
    source: bpy.types.Object,
    target: bpy.types.Object,
    images: dict[str, tuple[bpy.types.Image, bpy.types.ShaderNodeTexImage]],
) -> dict[str, object]:
    """Bake by native-coordinate surface correspondence into donor UV pages.

    The Dreamcast mesh, loop UVs, and UV seams remain authoritative.  Each
    covered donor texel is lifted to the corresponding 3D point on the donor
    triangle, matched only against the analogous SM2 rigid body surface, and
    sampled from the SM2 costume.  This avoids both cross-body projection rays
    and per-polygon UV discontinuities.
    """
    source_mesh = source.data
    target_mesh = target.data
    source_uv = source_mesh.uv_layers.active
    target_uv = target_mesh.uv_layers.active
    if source_uv is None or target_uv is None:
        raise RuntimeError("source and Dreamcast oracle must have active UV layers")

    source_mesh.calc_loop_triangles()
    target_mesh.calc_loop_triangles()
    source_triangles = list(source_mesh.loop_triangles)
    triangles_by_group: dict[str, list[bpy.types.MeshLoopTriangle]] = {}
    for triangle in source_triangles:
        group_name = triangle_group_name(source, triangle)
        if group_name is not None:
            triangles_by_group.setdefault(group_name, []).append(triangle)

    source_materials = [slot.material for slot in source.material_slots]
    if any(material is None for material in source_materials):
        raise RuntimeError("SM2 source contains an empty material slot")
    source_image_pixels: dict[str, tuple[int, int, list[float]]] = {}
    for material in source_materials:
        assert material is not None
        node = image_node(material)
        if node.image is None:
            raise RuntimeError(f"SM2 material {material.name} has no image")
        image = node.image
        source_image_pixels[material.name] = (
            int(image.size[0]),
            int(image.size[1]),
            list(image.pixels),
        )

    output_buffers = {
        material_name: list(image.pixels)
        for material_name, (image, _) in images.items()
    }
    coverage = {
        material_name: bytearray(int(image.size[0]) * int(image.size[1]))
        for material_name, (image, _) in images.items()
    }
    surface_cache: dict[
        tuple[str, ...],
        tuple[list[bpy.types.MeshLoopTriangle], Vector, Vector],
    ] = {}

    def source_surface(target_group: str | None):
        group_names = source_groups_for(target_group)
        if group_names not in surface_cache:
            candidates = [
                triangle
                for group_name in group_names
                for triangle in triangles_by_group.get(group_name, ())
            ]
            if not candidates:
                raise RuntimeError(f"no SM2 surface for Dreamcast group {target_group}")
            vertex_indices = {
                vertex_index
                for triangle in candidates
                for vertex_index in triangle.vertices
            }
            minimum = Vector(
                tuple(
                    min(source_mesh.vertices[index].co[axis] for index in vertex_indices)
                    for axis in range(3)
                )
            )
            maximum = Vector(
                tuple(
                    max(source_mesh.vertices[index].co[axis] for index in vertex_indices)
                    for axis in range(3)
                )
            )
            surface_cache[group_names] = (candidates, minimum, maximum)
        return surface_cache[group_names]

    written_texels = 0
    overlap_texels = 0
    processed_triangles = 0
    for triangle in target_mesh.loop_triangles:
        polygon = target_mesh.polygons[triangle.polygon_index]
        material = target.material_slots[polygon.material_index].material
        if material is None:
            raise RuntimeError("Dreamcast oracle contains an empty material slot")
        if material.name.casefold().startswith(TARGET_WING_MATERIAL):
            continue
        if material.name not in images:
            raise RuntimeError(f"no output image prepared for {material.name}")

        image = images[material.name][0]
        width, height = int(image.size[0]), int(image.size[1])
        uvs = [target_uv.data[loop_index].uv.copy() for loop_index in triangle.loops]
        xs = [uv.x * width for uv in uvs]
        ys = [uv.y * height for uv in uvs]
        minimum_x = max(int(math.floor(min(xs) - 0.5)), 0)
        maximum_x = min(int(math.ceil(max(xs) - 0.5)), width - 1)
        minimum_y = max(int(math.floor(min(ys) - 0.5)), 0)
        maximum_y = min(int(math.ceil(max(ys) - 0.5)), height - 1)
        a, b, c = uvs
        denominator = (b.y - c.y) * (a.x - c.x) + (c.x - b.x) * (a.y - c.y)
        if abs(denominator) <= 1e-12:
            continue

        candidates, surface_minimum, surface_maximum = source_surface(
            polygon_group_name(target, polygon)
        )
        target_vertices = [target_mesh.vertices[index] for index in triangle.vertices]
        buffer = output_buffers[material.name]
        mask = coverage[material.name]
        for y in range(minimum_y, maximum_y + 1):
            sample_y = (y + 0.5) / height
            for x in range(minimum_x, maximum_x + 1):
                sample_x = (x + 0.5) / width
                weight_a = (
                    (b.y - c.y) * (sample_x - c.x)
                    + (c.x - b.x) * (sample_y - c.y)
                ) / denominator
                weight_b = (
                    (c.y - a.y) * (sample_x - c.x)
                    + (a.x - c.x) * (sample_y - c.y)
                ) / denominator
                weight_c = 1.0 - weight_a - weight_b
                if min(weight_a, weight_b, weight_c) < -1e-7:
                    continue

                point = (
                    target_vertices[0].co * weight_a
                    + target_vertices[1].co * weight_b
                    + target_vertices[2].co * weight_c
                )
                normal = (
                    target_vertices[0].normal * weight_a
                    + target_vertices[1].normal * weight_b
                    + target_vertices[2].normal * weight_c
                )
                if normal.length_squared > 1e-12:
                    normal.normalize()
                source_triangle, source_point, _ = oracle_closest_hit(
                    point,
                    normal,
                    candidates,
                    source_mesh,
                    surface_minimum,
                    surface_maximum,
                )
                source_uv_value = triangle_uv_at(
                    source_mesh,
                    source_triangle,
                    source_point,
                )
                source_material = source_materials[source_triangle.material_index]
                assert source_material is not None
                source_width, source_height, source_pixels = source_image_pixels[
                    source_material.name
                ]
                source_u = min(max(float(source_uv_value.x), 0.0), 1.0)
                source_v = min(max(float(source_uv_value.y), 0.0), 1.0)
                source_x = min(int(source_u * source_width), source_width - 1)
                source_y = min(int(source_v * source_height), source_height - 1)
                source_offset = (source_y * source_width + source_x) * 4
                output_index = y * width + x
                output_offset = output_index * 4
                if mask[output_index]:
                    overlap_texels += 1
                else:
                    written_texels += 1
                mask[output_index] = 1
                buffer[output_offset : output_offset + 4] = source_pixels[
                    source_offset : source_offset + 4
                ]
                buffer[output_offset + 3] = 1.0
        processed_triangles += 1

    per_image = []
    for material_name, (image, _) in images.items():
        if material_name.casefold().startswith(TARGET_WING_MATERIAL):
            continue
        image.pixels = output_buffers[material_name]
        image.update()
        per_image.append(
            {
                "material": material_name,
                "coveredTexels": int(sum(coverage[material_name])),
                "totalTexels": len(coverage[material_name]),
            }
        )
    return {
        "strategy": "CPU rasterization into original Dreamcast UV pages",
        "processedDreamcastTriangles": processed_triangles,
        "writtenTexels": written_texels,
        "overlapWrites": overlap_texels,
        "images": per_image,
    }


def copy_source_wing(
    source: bpy.types.Object,
    target: bpy.types.Object,
    images: dict[str, tuple[bpy.types.Image, bpy.types.ShaderNodeTexImage]],
) -> None:
    source_material = next(
        (
            slot.material
            for slot in source.material_slots
            if slot.material is not None
            and slot.material.name.casefold().startswith(SOURCE_WING_MATERIAL)
        ),
        None,
    )
    target_material = next(
        (
            slot.material
            for slot in target.material_slots
            if slot.material is not None
            and slot.material.name.casefold().startswith(TARGET_WING_MATERIAL)
        ),
        None,
    )
    if source_material is None or target_material is None:
        raise RuntimeError(
            "source lacks CEB60740 or target lacks native DC38D248 wing material"
        )
    source_image = image_node(source_material).image
    target_image = images[target_material.name][0]
    if source_image is None:
        raise RuntimeError("SM2 wing material has no source image")
    old_width, old_height = int(target_image.size[0]), int(target_image.size[1])
    new_width, new_height = int(source_image.size[0]), int(source_image.size[1])
    if new_width <= 0 or new_height <= 0:
        raise RuntimeError("SM2 wing texture has invalid dimensions")

    if new_width > old_width or new_height > old_height:
        raise RuntimeError(
            f"source wing page {new_width}x{new_height} exceeds donor page "
            f"{old_width}x{old_height}"
        )
    # Neversoft UV bytes are pixel coordinates. Keep the donor-normalized UVs
    # untouched and place the smaller SM2 page into the equivalent pixel region
    # of the original Dreamcast-sized image.
    source_pixels = list(source_image.pixels)
    target_pixels = [0.0] * (old_width * old_height * 4)
    for y in range(new_height):
        for x in range(new_width):
            source_offset = (y * new_width + x) * 4
            target_offset = (y * old_width + x) * 4
            target_pixels[target_offset : target_offset + 4] = source_pixels[
                source_offset : source_offset + 4
            ]
    target_image.pixels = target_pixels
    target_image.update()
    # The native PS1 model draws reverse-winding copies.  Static GLB proofs
    # collapse those copies, so the surviving membrane must be two-sided.
    target_material.use_backface_culling = False


def hide_target_wings(
    target: bpy.types.Object,
    images: dict[str, tuple[bpy.types.Image, bpy.types.ShaderNodeTexImage]],
) -> None:
    target_material = next(
        (
            slot.material
            for slot in target.material_slots
            if slot.material is not None
            and slot.material.name.casefold().startswith(TARGET_WING_MATERIAL)
        ),
        None,
    )
    if target_material is None:
        raise RuntimeError("target lacks native DC38D248 wing material")
    target_image = images[target_material.name][0]
    width, height = int(target_image.size[0]), int(target_image.size[1])
    target_image.pixels = [1.0, 0.0, 1.0, 0.0] * (width * height)
    target_image.update()
    target_material.use_backface_culling = False
    if hasattr(target_material, "surface_render_method"):
        target_material.surface_render_method = "DITHERED"


def fill_unbaked_texels(
    images: dict[str, tuple[bpy.types.Image, bpy.types.ShaderNodeTexImage]],
) -> dict[str, object]:
    """Fill projection misses from the nearest baked texel in the same atlas."""
    records: list[dict[str, object]] = []
    for material_name, (image, _) in images.items():
        if material_name.casefold().startswith(TARGET_WING_MATERIAL):
            continue
        width, height = int(image.size[0]), int(image.size[1])
        pixels = list(image.pixels)
        count = width * height
        visited = bytearray(count)
        queue: deque[int] = deque()
        for pixel_index in range(count):
            offset = pixel_index * 4
            is_sentinel = (
                pixels[offset] > 0.50
                and pixels[offset + 1] < 0.25
                and pixels[offset + 2] > 0.25
            )
            if not is_sentinel:
                visited[pixel_index] = 1
                queue.append(pixel_index)
        baked_count = len(queue)
        if baked_count == 0:
            records.append(
                {
                    "material": material_name,
                    "bakedTexels": 0,
                    "filledTexels": 0,
                }
            )
            continue
        while queue:
            pixel_index = queue.popleft()
            x = pixel_index % width
            y = pixel_index // width
            neighbours = []
            if x > 0:
                neighbours.append(pixel_index - 1)
            if x + 1 < width:
                neighbours.append(pixel_index + 1)
            if y > 0:
                neighbours.append(pixel_index - width)
            if y + 1 < height:
                neighbours.append(pixel_index + width)
            source_offset = pixel_index * 4
            for neighbour in neighbours:
                if visited[neighbour]:
                    continue
                visited[neighbour] = 1
                target_offset = neighbour * 4
                pixels[target_offset : target_offset + 4] = pixels[
                    source_offset : source_offset + 4
                ]
                pixels[target_offset + 3] = 1.0
                queue.append(neighbour)
        for pixel_index in range(count):
            pixels[pixel_index * 4 + 3] = 1.0
        image.pixels = pixels
        image.update()
        records.append(
            {
                "material": material_name,
                "bakedTexels": baked_count,
                "filledTexels": count - baked_count,
            }
        )
    return {"strategy": "nearest covered texel within isolated body-part atlas", "images": records}


def connect_baked_images(
    target: bpy.types.Object,
    images: dict[str, tuple[bpy.types.Image, bpy.types.ShaderNodeTexImage]],
) -> None:
    for slot in target.material_slots:
        material = slot.material
        if material is None or material.name not in images:
            continue
        image, _ = images[material.name]
        tree = material.node_tree
        tree.nodes.clear()
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        node.interpolation = "Linear"
        tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
        tree.links.new(node.outputs["Color"], principled.inputs["Base Color"])
        tree.links.new(node.outputs["Color"], principled.inputs["Emission Color"])
        tree.links.new(node.outputs["Alpha"], principled.inputs["Alpha"])
        principled.inputs["Emission Strength"].default_value = 1.0
        principled.inputs["Roughness"].default_value = 0.8


def save_images(
    images: dict[str, tuple[bpy.types.Image, bpy.types.ShaderNodeTexImage]],
    output: str,
) -> None:
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    for material_name, (image, _) in images.items():
        image.filepath_raw = str((root / f"{material_name}.png").resolve())
        image.file_format = "PNG"
        image.save()


def save_blend(path: str, target: bpy.types.Object, name: str) -> None:
    target.name = f"{name}_DC_ORACLE_SURFACE_BAKE"
    target.data.name = f"{name}_DC_ORACLE_MESH"
    target["dc_oracle_geometry"] = True
    target["dc_oracle_uvs_unchanged"] = True
    target["dc_oracle_material_assignments_unchanged"] = True
    target["costume_color_source"] = "SM2 surface appearance"
    bpy.ops.file.pack_all()
    Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(path).resolve()))


def main() -> None:
    args = parse_args()
    split_modes = sum(
        int(enabled)
        for enabled in (
            args.split_by_bone,
            args.atlas_by_bone,
            args.split_by_uv_island,
        )
    )
    if split_modes > 1:
        raise ValueError(
            "choose only one of --split-by-bone, --atlas-by-bone, or "
            "--split-by-uv-island"
        )
    clear_scene()
    with tempfile.TemporaryDirectory(prefix="spidey-costume-bake-") as temporary_root:
        target_path = blender_compatible_glb(os.path.abspath(args.target), temporary_root)
        source_path = blender_compatible_glb(os.path.abspath(args.source), temporary_root)
        target_armature, target_mesh, target_group = import_group(target_path)
        source_armature, source_mesh, source_group = import_group(source_path)

        oracle_before = oracle_signature(target_mesh)
        source_alignment = (
            align_source_by_bone(source_mesh, target_mesh)
            if args.align_source_by_bone
            else None
        )
        material_expansion = (
            split_materials_by_uv_island(target_mesh)
            if args.split_by_uv_island
            else atlas_materials_by_bone(target_mesh)
            if args.atlas_by_bone
            else split_materials_by_bone(target_mesh)
            if args.split_by_bone
            else None
        )
        images = prepare_bake_images(
            target_mesh,
            args.name,
            args.resolution_scale,
        )
        isolated_bake = None
        if args.cpu_surface:
            isolated_bake = cpu_surface_bake(source_mesh, target_mesh, images)
        elif args.split_by_bone or args.atlas_by_bone or args.split_by_uv_island:
            isolated_bake = bake_body_by_group(
                source_mesh,
                target_mesh,
                args.cage_extrusion,
                args.max_ray_distance,
                args.margin,
            )
        else:
            bake_body(
                source_mesh,
                target_mesh,
                args.cage_extrusion,
                args.max_ray_distance,
                args.margin,
            )
        coverage_fill = fill_unbaked_texels(images)
        if args.hide_wings:
            hide_target_wings(target_mesh, images)
        else:
            copy_source_wing(source_mesh, target_mesh, images)
        connect_baked_images(target_mesh, images)
        save_images(images, args.textures_output)
        validation = validate_oracle_unchanged(
            oracle_before,
            target_mesh,
            material_expansion,
            allow_uv_remap=args.atlas_by_bone,
        )
        validation["sourceAlignment"] = source_alignment
        validation["surfaceBake"] = isolated_bake or {
            "strategy": "selected-to-active whole body"
        }
        validation["coverageFill"] = coverage_fill
        if args.validation_output:
            validation_path = Path(args.validation_output).resolve()
            validation_path.parent.mkdir(parents=True, exist_ok=True)
            validation_path.write_text(json.dumps(validation, indent=2) + "\n")

        for obj in source_group:
            bpy.data.objects.remove(obj, do_unlink=True)
        pose_arms(target_armature)
        baked = bake_pose(target_armature)
        if not baked:
            raise RuntimeError("target had no skinned mesh to bake into the T-pose")
        export_glb(args.output, baked)
        if args.blend_output:
            save_blend(args.blend_output, baked[0], args.name)
    print(f"wrote {args.name} DC surface bake in a static T-pose: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
