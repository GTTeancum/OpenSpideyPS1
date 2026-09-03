"""Transfer an SM2 costume onto the untouched high-detail Dreamcast mesh.

The two meshes share Neversoft's bind-pose coordinate system but not topology.
For every Dreamcast loop, this tool finds the closest point on the matching
SM2 rigid body surface and copies the source triangle's barycentric UV.  Joint
groups deliberately include their adjacent source segment so shoulders,
wrists, hips, ankles, and feet inherit the source-authored transition.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Vector
from mathutils.geometry import barycentric_transform, closest_point_on_tri


sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_tpose_glb import (  # noqa: E402
    bake_pose,
    blender_compatible_glb,
    clear_scene,
    export_glb,
    pose_arms,
)


TARGET_WING_MATERIAL = "tex_dc38d248"
FULL_SURFACE_GROUPS = {
    "Spidey_Spidey_Left_Shin01",
    "Spidey_Spidey_Right_Shin01",
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--textures-output", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--oracle-source",
        required=True,
        help="untouched default SM2 GLB with geometry/UVs matching --source",
    )
    parser.add_argument("--blend-output")
    parser.add_argument("--mapping-output")
    parser.add_argument(
        "--hide-wings",
        action="store_true",
        help=(
            "keep the Dreamcast wing geometry and transferred UVs, but assign "
            "a fully transparent material for wingless SM1 costume imports"
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
        raise RuntimeError(f"material {material.name} has no texture image")
    return nodes[0].image


def gltf_uv(uv: Vector) -> list[float]:
    """Convert Blender's imported UV convention back to glTF's convention."""
    return [float(uv.x), float(1.0 - uv.y)]


def polygon_snapshot(
    target: bpy.types.Object,
    polygon: bpy.types.MeshPolygon,
    materials: list[bpy.types.Material],
    *,
    material_index: int | None = None,
) -> dict[str, object]:
    """Capture one triangle in the native packer's stable GLB identity format."""
    mesh = target.data
    resolved_material_index = (
        int(polygon.material_index)
        if material_index is None
        else int(material_index)
    )
    material = materials[resolved_material_index]
    image = material_image(material)
    return {
        "materialIndex": resolved_material_index,
        "material": material.name,
        "image": image.name,
        "imageSize": [int(image.size[0]), int(image.size[1])],
        "vertexIndices": [
            int(mesh.loops[index].vertex_index) for index in polygon.loop_indices
        ],
        "positions": [
            [
                float(value)
                for value in mesh.vertices[mesh.loops[index].vertex_index].co
            ]
            for index in polygon.loop_indices
        ],
        "uvs": [
            gltf_uv(mesh.uv_layers.active.data[index].uv)
            for index in polygon.loop_indices
        ],
    }


def sample_image(image: bpy.types.Image, uv: Vector) -> Vector:
    width, height = int(image.size[0]), int(image.size[1])
    x = min(int((float(uv.x) % 1.0) * width), width - 1)
    y = min(int((float(uv.y) % 1.0) * height), height - 1)
    offset = (y * width + x) * 4
    pixels = image.pixels
    return Vector((pixels[offset], pixels[offset + 1], pixels[offset + 2]))


def dominant_group_name(obj: bpy.types.Object, vertex_index: int) -> str | None:
    memberships = obj.data.vertices[vertex_index].groups
    if not memberships:
        return None
    strongest = max(memberships, key=lambda membership: membership.weight)
    return obj.vertex_groups[strongest.group].name


def polygon_group_name(obj: bpy.types.Object, polygon: bpy.types.MeshPolygon) -> str | None:
    totals: dict[str, float] = {}
    for vertex_index in polygon.vertices:
        for membership in obj.data.vertices[vertex_index].groups:
            name = obj.vertex_groups[membership.group].name
            totals[name] = totals.get(name, 0.0) + membership.weight
    return max(totals, key=totals.get) if totals else None


def source_groups_for(target_group: str | None) -> tuple[str, ...]:
    if target_group is None:
        return ()
    neighbours = {
        "Spidey_Spidey_Torso01": (
            "Spidey_Spidey_Torso02",
            "Spidey_Spidey_Pelvis01",
        ),
        "mesh_00000005": (
            "Spidey_Spidey_Left_Hand01",
            "Spidey_Spidey_Left_Forearm01",
        ),
        "mesh_0000000A": (
            "Spidey_Spidey_Right_Hand01",
            "Spidey_Spidey_Right_Forearm01",
        ),
        "mesh_0000000E": (
            "mesh_0000000E",
            "Spidey_Spidey_Right_Shin01",
        ),
        "mesh_00000011": (
            "mesh_00000011",
            "Spidey_Spidey_Left_Shin01",
        ),
        "Spidey_Spidey_Left_Thigh01": (
            "Spidey_Spidey_Left_Thigh01",
            "Spidey_Spidey_Pelvis01",
        ),
        "Spidey_Spidey_Right_Thigh01": (
            "Spidey_Spidey_Right_Thigh01",
            "Spidey_Spidey_Pelvis01",
        ),
    }
    return neighbours.get(target_group, (target_group,))


def triangle_group_name(obj: bpy.types.Object, triangle: bpy.types.MeshLoopTriangle) -> str | None:
    totals: dict[str, float] = {}
    for vertex_index in triangle.vertices:
        for membership in obj.data.vertices[vertex_index].groups:
            name = obj.vertex_groups[membership.group].name
            totals[name] = totals.get(name, 0.0) + membership.weight
    return max(totals, key=totals.get) if totals else None


def closest_hit(
    point: Vector,
    normal: Vector,
    triangles: list[bpy.types.MeshLoopTriangle],
    mesh: bpy.types.Mesh,
    surface_minimum: Vector,
    surface_maximum: Vector,
    oracle_mesh: bpy.types.Mesh | None = None,
    oracle_materials: list[bpy.types.Material] | None = None,
    target_color: Vector | None = None,
    color_weight: float = 0.0,
) -> tuple[bpy.types.MeshLoopTriangle, Vector, float]:
    center = (surface_minimum + surface_maximum) * 0.5
    extents = surface_maximum - surface_minimum
    depth_delta = point.y - center.y
    principal_axis = max(range(3), key=lambda axis: abs(extents[axis]))
    cross_axes = [axis for axis in range(3) if axis != principal_axis]

    def radial(value: Vector) -> Vector:
        return Vector(
            (
                (value[cross_axes[0]] - center[cross_axes[0]])
                / max(abs(extents[cross_axes[0]]), 1e-6),
                (value[cross_axes[1]] - center[cross_axes[1]])
                / max(abs(extents[cross_axes[1]]), 1e-6),
            )
        )

    query_radial = radial(point)
    candidates: list[
        tuple[float, float, float, bpy.types.MeshLoopTriangle, Vector]
    ] = []
    for triangle in triangles:
        a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
        location = closest_point_on_tri(point, a, b, c)
        distance = float((location - point).length_squared)
        # Front and rear surfaces on the head and limbs can be less than a unit
        # apart.  Preserve the query's authored depth half whenever possible.
        wrong_depth = (
            abs(depth_delta) > 0.15
            and (location.y - center.y) * depth_delta < 0.0
        )
        candidate_radial = radial(location)
        radial_dot = 1.0
        if query_radial.length > 0.08 and candidate_radial.length > 0.08:
            radial_dot = float(
                query_radial.normalized().dot(candidate_radial.normalized())
            )
        normal_dot = max(-1.0, min(1.0, float(normal.dot(triangle.normal))))
        normal_error = 1.0 - normal_dot
        color_error = 0.0
        if (
            oracle_mesh is not None
            and oracle_materials is not None
            and target_color is not None
        ):
            oracle_triangle = oracle_mesh.loop_triangles[triangle.index]
            oracle_uv = triangle_uv_at(oracle_mesh, oracle_triangle, location)
            oracle_material = oracle_materials[oracle_triangle.material_index]
            oracle_color = sample_image(material_image(oracle_material), oracle_uv)
            color_error = float((oracle_color - target_color).length_squared)
        candidates.append(
            (
                (1000.0 if wrong_depth else 0.0)
                + max(0.0, 0.55 - radial_dot) * 1000.0,
                distance
                + normal_error * 0.75
                + (1.0 - radial_dot) * 0.25
                + color_error * color_weight,
                -radial_dot,
                triangle,
                location,
            )
        )
    if not candidates:
        raise RuntimeError("anatomical source surface has no triangles")
    score, distance, _, triangle, location = min(
        candidates, key=lambda item: item[:3]
    )
    return triangle, location, distance


def triangle_uv_at(
    mesh: bpy.types.Mesh,
    triangle: bpy.types.MeshLoopTriangle,
    location: Vector,
) -> Vector:
    a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
    uv_a, uv_b, uv_c = (
        Vector((*mesh.uv_layers.active.data[index].uv, 0.0))
        for index in triangle.loops
    )
    return barycentric_transform(location, a, b, c, uv_a, uv_b, uv_c).xy


def normalize_polygon_uv_wrap(
    mesh: bpy.types.Mesh,
    uv_layer: bpy.types.MeshUVLoopLayer,
    polygon: bpy.types.MeshPolygon,
) -> None:
    """Keep a target triangle on one repeat of its source texture.

    Neversoft UVs deliberately cross integer texture boundaries.  Source
    triangles keep their corners on adjacent repeats (for example 1.24 beside
    0.24), but independently projected Dreamcast loops can mix those values in
    one triangle.  Raster interpolation then traverses the full texture.  An
    integer translation is visually identical under REPEAT, so choose the
    compact equivalent independently for U and V.
    """
    loop_indices = list(polygon.loop_indices)
    for axis in (0, 1):
        values = [float(uv_layer.data[index].uv[axis]) for index in loop_indices]
        best_offsets = min(
            itertools.product(range(-2, 3), repeat=len(values)),
            key=lambda offsets: (
                max(value + offset for value, offset in zip(values, offsets))
                - min(value + offset for value, offset in zip(values, offsets)),
                sum(abs(offset) for offset in offsets),
            ),
        )
        for loop_index, value, offset in zip(loop_indices, values, best_offsets):
            uv_layer.data[loop_index].uv[axis] = value + offset


def triangle_neighbourhood(
    seed: bpy.types.MeshLoopTriangle,
    triangles: list[bpy.types.MeshLoopTriangle],
    rings: int = 1,
) -> list[bpy.types.MeshLoopTriangle]:
    """Return a small source-UV-local neighbourhood around ``seed``.

    glTF import duplicates vertices at authored UV seams.  Requiring shared
    vertex indices prevents one Dreamcast polygon from interpolating between
    unrelated source islands, while the ring limit prevents distant points in
    one large limb island from being combined by one target triangle.
    """
    triangles_at_vertex: dict[int, list[bpy.types.MeshLoopTriangle]] = {}
    for triangle in triangles:
        for vertex_index in triangle.vertices:
            triangles_at_vertex.setdefault(vertex_index, []).append(triangle)
    result: list[bpy.types.MeshLoopTriangle] = []
    queued = {seed.index}
    queue = [(seed, 0)]
    while queue:
        triangle, depth = queue.pop(0)
        result.append(triangle)
        if depth >= rings:
            continue
        for vertex_index in triangle.vertices:
            for neighbour in triangles_at_vertex.get(vertex_index, ()):
                if neighbour.index in queued:
                    continue
                queued.add(neighbour.index)
                queue.append((neighbour, depth + 1))
    return result


def save_source_images(source: bpy.types.Object, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    saved: set[str] = set()
    for slot in source.material_slots:
        material = slot.material
        if material is None or material.name in saved:
            continue
        image = material_image(material)
        image.filepath_raw = str((output / f"{material.name}.png").resolve())
        image.file_format = "PNG"
        image.save()
        saved.add(material.name)


def transparent_wing_material() -> bpy.types.Material:
    """Build a packed alpha-zero material without altering the source costume."""
    image = bpy.data.images.new(
        "wing_magenta_key_import_hidden",
        width=1,
        height=1,
        alpha=True,
    )
    image.pixels = (1.0, 0.0, 1.0, 0.0)
    image.pack()

    material = bpy.data.materials.new("wing_magenta_key_import_hidden")
    material.use_nodes = True
    material.use_backface_culling = False
    material.diffuse_color = (1.0, 0.0, 1.0, 0.0)
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
    texture = tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Closest"
    tree.links.new(texture.outputs["Color"], principled.inputs["Base Color"])
    tree.links.new(texture.outputs["Alpha"], principled.inputs["Alpha"])
    tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    return material


def transfer_surface(
    source: bpy.types.Object,
    target: bpy.types.Object,
    oracle_source: bpy.types.Object,
    *,
    hide_wings: bool = False,
) -> dict[str, object]:
    source_mesh = source.data
    target_mesh = target.data
    source_uv = source_mesh.uv_layers.active
    target_uv = target_mesh.uv_layers.active
    if source_uv is None or target_uv is None:
        raise RuntimeError("source and target must both have an active UV layer")

    source_mesh.calc_loop_triangles()
    oracle_mesh = oracle_source.data
    oracle_mesh.calc_loop_triangles()
    triangles = list(source_mesh.loop_triangles)
    if len(oracle_mesh.loop_triangles) != len(triangles):
        raise RuntimeError("costume and default SM2 oracle topology differ")
    triangles_by_group: dict[str, list[bpy.types.MeshLoopTriangle]] = {}
    for triangle in triangles:
        group_name = triangle_group_name(source, triangle)
        if group_name is not None:
            triangles_by_group.setdefault(group_name, []).append(triangle)

    source_parent = list(range(len(triangles)))

    def find_source(triangle_index: int) -> int:
        while source_parent[triangle_index] != triangle_index:
            source_parent[triangle_index] = source_parent[
                source_parent[triangle_index]
            ]
            triangle_index = source_parent[triangle_index]
        return triangle_index

    def union_source(left: int, right: int) -> None:
        left_root = find_source(left)
        right_root = find_source(right)
        if left_root != right_root:
            source_parent[right_root] = left_root

    source_triangles_at_vertex: dict[int, list[bpy.types.MeshLoopTriangle]] = {}
    source_triangle_vertices = {
        int(triangle.index): {int(index) for index in triangle.vertices}
        for triangle in triangles
    }
    for triangle in triangles:
        for vertex_index in triangle.vertices:
            source_triangles_at_vertex.setdefault(int(vertex_index), []).append(triangle)
    for attached in source_triangles_at_vertex.values():
        for left_offset, left in enumerate(attached):
            for right in attached[left_offset + 1 :]:
                if left.material_index == right.material_index:
                    union_source(left.index, right.index)

    source_components: dict[int, list[bpy.types.MeshLoopTriangle]] = {}
    for triangle in triangles:
        source_components.setdefault(find_source(triangle.index), []).append(triangle)

    source_materials = [slot.material for slot in source.material_slots]
    oracle_materials = [slot.material for slot in oracle_source.material_slots]
    target_materials = [slot.material for slot in target.material_slots]
    if any(
        material is None
        for material in source_materials + oracle_materials + target_materials
    ):
        raise RuntimeError("costume contains an empty material slot")
    if len(source_materials) != len(oracle_materials):
        raise RuntimeError("costume and default SM2 oracle material slots differ")
    original_target_uv = [loop.uv.copy() for loop in target_uv.data]
    original_target_material_indices = [
        int(polygon.material_index) for polygon in target_mesh.polygons
    ]
    original_polygon_snapshots = [
        polygon_snapshot(target, polygon, target_materials)
        for polygon in target_mesh.polygons
    ]
    wing_indices = {
        index
        for index, material in enumerate(target_materials)
        if material.name.casefold().startswith(TARGET_WING_MATERIAL)
    }
    if not wing_indices:
        raise RuntimeError("Dreamcast oracle has no wing material")

    # The Dreamcast mesh is the geometry oracle, including its four wing
    # triangles.  The SM2 costume is the appearance oracle: matching those
    # triangles by their native coordinates copies the costume's authored wing
    # texture (including a fully transparent texture for wingless costumes).
    source_wing_matches: dict[int, bpy.types.MeshLoopTriangle] = {}
    for polygon in target_mesh.polygons:
        original_material_index = original_target_material_indices[polygon.index]
        if original_material_index not in wing_indices:
            continue
        target_points = [target_mesh.vertices[index].co for index in polygon.vertices]
        candidates: list[tuple[float, bpy.types.MeshLoopTriangle]] = []
        for triangle in triangles:
            source_points = [source_mesh.vertices[index].co for index in triangle.vertices]
            forward = max(
                min((target_point - source_point).length_squared for source_point in source_points)
                for target_point in target_points
            )
            reverse = max(
                min((source_point - target_point).length_squared for target_point in target_points)
                for source_point in source_points
            )
            candidates.append((max(forward, reverse), triangle))
        distance, match = min(candidates, key=lambda item: item[0])
        if distance > 1e-8:
            raise RuntimeError(
                f"Dreamcast wing polygon {polygon.index} has no exact SM2 counterpart"
            )
        source_wing_matches[int(polygon.index)] = match

    target_mesh.materials.clear()
    for material in source_materials:
        target_mesh.materials.append(material)
    hidden_wing_material_index: int | None = None
    if hide_wings:
        hidden_wing_material_index = len(target_mesh.materials)
        target_mesh.materials.append(transparent_wing_material())

    records: list[dict[str, object]] = []
    transferred_loops = 0
    loop_distances: dict[int, float] = {}
    loop_source_triangles: dict[int, int] = {}
    for polygon in target_mesh.polygons:
        original_material_index = original_target_material_indices[polygon.index]
        if original_material_index in wing_indices:
            source_triangle = source_wing_matches[int(polygon.index)]
            polygon.material_index = (
                hidden_wing_material_index
                if hidden_wing_material_index is not None
                else source_triangle.material_index
            )
            for loop_index in polygon.loop_indices:
                vertex_index = target_mesh.loops[loop_index].vertex_index
                target_uv.data[loop_index].uv = triangle_uv_at(
                    source_mesh,
                    source_triangle,
                    target_mesh.vertices[vertex_index].co,
                )
            continue

        target_group = polygon_group_name(target, polygon)
        source_groups = source_groups_for(target_group)
        group_triangles = [
            triangle
            for group_name in source_groups
            for triangle in triangles_by_group.get(group_name, ())
        ]
        if not group_triangles:
            raise RuntimeError(f"no source triangles for target group {target_group}")
        group_vertices = {
            vertex_index
            for triangle in group_triangles
            for vertex_index in triangle.vertices
        }
        surface_minimum = Vector(
            tuple(
                min(source_mesh.vertices[index].co[axis] for index in group_vertices)
                for axis in range(3)
            )
        )
        surface_maximum = Vector(
            tuple(
                max(source_mesh.vertices[index].co[axis] for index in group_vertices)
                for axis in range(3)
            )
        )
        original_material = target_materials[original_material_index]
        center_uv = sum(
            (original_target_uv[index] for index in polygon.loop_indices),
            Vector((0.0, 0.0)),
        ) / len(polygon.loop_indices)
        target_center_color = sample_image(
            material_image(original_material),
            center_uv,
        )
        center_triangle, center_hit, center_distance = closest_hit(
            polygon.center,
            polygon.normal,
            group_triangles,
            source_mesh,
            surface_minimum,
            surface_maximum,
            oracle_mesh,
            oracle_materials,
            target_center_color,
            0.0,
        )
        polygon.material_index = center_triangle.material_index
        material_triangles = [
            triangle
            for triangle in group_triangles
            if triangle.material_index == center_triangle.material_index
        ]
        source_component = source_components[find_source(center_triangle.index)]
        component_triangles = (
            source_component
            if target_group in FULL_SURFACE_GROUPS
            else triangle_neighbourhood(center_triangle, source_component)
        )
        loop_records = []
        for loop_index in polygon.loop_indices:
            vertex_index = target_mesh.loops[loop_index].vertex_index
            point = target_mesh.vertices[vertex_index].co
            normal = target_mesh.vertices[vertex_index].normal
            target_loop_color = sample_image(
                material_image(original_material),
                original_target_uv[loop_index],
            )
            loop_triangle, location, distance = closest_hit(
                point,
                normal,
                component_triangles,
                source_mesh,
                surface_minimum,
                surface_maximum,
                oracle_mesh,
                oracle_materials,
                target_loop_color,
                0.0,
            )
            target_uv.data[loop_index].uv = triangle_uv_at(
                source_mesh,
                loop_triangle,
                location,
            )
            loop_distances[int(loop_index)] = distance
            loop_source_triangles[int(loop_index)] = int(loop_triangle.index)
            transferred_loops += 1
            loop_records.append(
                {
                    "loop": int(loop_index),
                    "sourceTriangle": int(loop_triangle.index),
                    "distance": distance ** 0.5,
                }
            )
        records.append(
            {
                "polygon": int(polygon.index),
                "targetGroup": target_group,
                "sourceGroups": list(source_groups),
                "sourceMaterial": source_materials[center_triangle.material_index].name,
                "centerTriangle": int(center_triangle.index),
                "centerDistance": center_distance ** 0.5,
                "loops": loop_records,
            }
        )

    # Use the untouched Dreamcast UV layout as the seam oracle.  Adjacent faces
    # are welded only when their original donor UVs agree at both endpoints of
    # the shared edge.  This removes accidental one-face patches without
    # flattening authored seams on the head, shoulders, knees, or feet.
    parent = list(range(len(target_mesh.loops)))

    def find(loop_index: int) -> int:
        while parent[loop_index] != loop_index:
            parent[loop_index] = parent[parent[loop_index]]
            loop_index = parent[loop_index]
        return loop_index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    edge_uses: dict[
        tuple[int, int],
        list[tuple[int, dict[int, int]]],
    ] = {}
    for polygon in target_mesh.polygons:
        if original_target_material_indices[polygon.index] in wing_indices:
            continue
        loops_at_vertex = {
            int(target_mesh.loops[loop_index].vertex_index): int(loop_index)
            for loop_index in polygon.loop_indices
        }
        vertices = [int(index) for index in polygon.vertices]
        for vertex_offset, vertex_a in enumerate(vertices):
            vertex_b = vertices[(vertex_offset + 1) % len(vertices)]
            edge = tuple(sorted((vertex_a, vertex_b)))
            edge_uses.setdefault(edge, []).append((polygon.index, loops_at_vertex))

    for edge, uses in edge_uses.items():
        if len(uses) < 2:
            continue
        vertex_a, vertex_b = edge
        for left_offset, (left_polygon, left_loops) in enumerate(uses):
            for right_polygon, right_loops in uses[left_offset + 1 :]:
                if (
                    target_mesh.polygons[left_polygon].material_index
                    != target_mesh.polygons[right_polygon].material_index
                ):
                    continue
                continuous = all(
                    (
                        original_target_uv[left_loops[vertex]]
                        - original_target_uv[right_loops[vertex]]
                    ).length
                    <= 1e-6
                    for vertex in (vertex_a, vertex_b)
                )
                continuous = continuous and all(
                    bool(
                        source_triangle_vertices[
                            loop_source_triangles[left_loops[vertex]]
                        ]
                        & source_triangle_vertices[
                            loop_source_triangles[right_loops[vertex]]
                        ]
                    )
                    for vertex in (vertex_a, vertex_b)
                )
                if not continuous:
                    continue
                union(left_loops[vertex_a], right_loops[vertex_a])
                union(left_loops[vertex_b], right_loops[vertex_b])

    loop_components: dict[int, list[int]] = {}
    for loop_index in loop_distances:
        loop_components.setdefault(find(loop_index), []).append(loop_index)
    unified_loops = 0
    for loop_indices in loop_components.values():
        if len(loop_indices) < 2:
            continue
        best_loop = min(loop_indices, key=lambda index: loop_distances[index])
        best_uv = target_uv.data[best_loop].uv.copy()
        for loop_index in loop_indices:
            if loop_index == best_loop:
                continue
            target_uv.data[loop_index].uv = best_uv
            unified_loops += 1

    for polygon in target_mesh.polygons:
        if polygon_group_name(target, polygon) in FULL_SURFACE_GROUPS:
            normalize_polygon_uv_wrap(target_mesh, target_uv, polygon)

    native_polygons = []
    for polygon in target_mesh.polygons:
        original_material_index = original_target_material_indices[polygon.index]
        is_wing = original_material_index in wing_indices
        mapped_material_index = (
            int(source_wing_matches[int(polygon.index)].material_index)
            if is_wing
            else int(polygon.material_index)
        )
        native_polygons.append(
            {
                "polygonIndex": int(polygon.index),
                "isWing": is_wing,
                "original": original_polygon_snapshots[polygon.index],
                # The native runtime hides wings through the source texture palette.
                # Keep the source wing material here even when the Blender review
                # uses its separate alpha-zero display material.
                "mapped": polygon_snapshot(
                    target,
                    polygon,
                    source_materials,
                    material_index=mapped_material_index,
                ),
            }
        )

    return {
        "schemaVersion": 2,
        "strategy": "native-coordinate, rigid-part-constrained nearest surface",
        "targetVertices": len(target_mesh.vertices),
        "targetPolygons": len(target_mesh.polygons),
        "polygonCount": len(native_polygons),
        "transferredLoops": transferred_loops,
        "wingPolygonsMatchedByNativeGeometry": len(source_wing_matches),
        "wingPolicy": "transparent-for-sm1-import" if hide_wings else "source-authored",
        "dreamcastContinuousEdgeLoopsUnified": unified_loops,
        "polygons": native_polygons,
        "records": records,
    }


def main() -> None:
    args = parse_args()
    clear_scene()
    with tempfile.TemporaryDirectory(prefix="spidey-dc-oracle-transfer-") as temporary_root:
        source_path = blender_compatible_glb(os.path.abspath(args.source), temporary_root)
        oracle_path = blender_compatible_glb(
            os.path.abspath(args.oracle_source), temporary_root
        )
        target_path = blender_compatible_glb(os.path.abspath(args.target), temporary_root)
        _, source_mesh, source_group = import_group(source_path)
        _, oracle_mesh, oracle_group = import_group(oracle_path)
        target_armature, target_mesh, _ = import_group(target_path)

        original_positions = [tuple(vertex.co) for vertex in target_mesh.data.vertices]
        save_source_images(source_mesh, Path(args.textures_output).resolve())
        mapping = transfer_surface(
            source_mesh,
            target_mesh,
            oracle_mesh,
            hide_wings=args.hide_wings,
        )
        if original_positions != [tuple(vertex.co) for vertex in target_mesh.data.vertices]:
            raise RuntimeError("transfer altered Dreamcast oracle vertex positions")
        for obj in source_group:
            bpy.data.objects.remove(obj, do_unlink=True)
        for obj in oracle_group:
            bpy.data.objects.remove(obj, do_unlink=True)

        pose_arms(target_armature)
        baked = bake_pose(target_armature)
        if not baked:
            raise RuntimeError("target had no skinned mesh to bake")
        export_glb(args.output, baked)
        if args.mapping_output:
            output = Path(args.mapping_output).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
        if args.blend_output:
            blend = Path(args.blend_output).resolve()
            blend.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.file.pack_all()
            bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    print(f"wrote {args.name} Dreamcast-oracle transfer: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
