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
import math
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
    parser.add_argument(
        "--oracle-source",
        help=(
            "default SM2 costume GLB with identical topology/UVs; its colors are "
            "compared with the original Dreamcast donor to disambiguate surfaces"
        ),
    )
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


def dominant_group_name(obj: bpy.types.Object, vertex_index: int) -> str | None:
    groups = obj.data.vertices[vertex_index].groups
    if not groups:
        return None
    strongest = max(groups, key=lambda membership: membership.weight)
    return obj.vertex_groups[strongest.group].name


def polygon_group_name(obj: bpy.types.Object, polygon: bpy.types.MeshPolygon) -> str | None:
    totals: dict[str, float] = {}
    for vertex_index in polygon.vertices:
        for membership in obj.data.vertices[vertex_index].groups:
            name = obj.vertex_groups[membership.group].name
            totals[name] = totals.get(name, 0.0) + membership.weight
    return max(totals, key=totals.get) if totals else None


def group_bounds(obj: bpy.types.Object) -> dict[str, tuple[Vector, Vector]]:
    points: dict[str, list[Vector]] = {}
    for vertex in obj.data.vertices:
        group_name = dominant_group_name(obj, vertex.index)
        if group_name is not None:
            points.setdefault(group_name, []).append(vertex.co.copy())
    return {
        group_name: (
            Vector(tuple(min(point[axis] for point in group_points) for axis in range(3))),
            Vector(tuple(max(point[axis] for point in group_points) for axis in range(3))),
        )
        for group_name, group_points in points.items()
    }


def map_group_point(
    point: Vector,
    group_name: str | None,
    target_bounds: dict[str, tuple[Vector, Vector]],
    source_bounds: dict[str, tuple[Vector, Vector]],
) -> Vector:
    if (
        group_name is None
        or group_name not in target_bounds
        or group_name not in source_bounds
    ):
        return point
    target_minimum, target_maximum = target_bounds[group_name]
    source_minimum, source_maximum = source_bounds[group_name]
    result = Vector()
    for axis in range(3):
        target_extent = target_maximum[axis] - target_minimum[axis]
        if abs(target_extent) <= 1e-6:
            result[axis] = (source_minimum[axis] + source_maximum[axis]) * 0.5
            continue
        fraction = (point[axis] - target_minimum[axis]) / target_extent
        result[axis] = source_minimum[axis] + fraction * (
            source_maximum[axis] - source_minimum[axis]
        )
    return result


def nearest_front_facing_hit(
    bvh: BVHTree,
    point: Vector,
    normal: Vector,
    bounds: tuple[Vector, Vector] | None = None,
) -> tuple[Vector, Vector, int, float] | None:
    """Find the closest surface on the same side of a thin body part.

    Pure distance is ambiguous on the head, forearms, and calves because the
    opposite side of the low-poly donor can be closer than the corresponding
    outward-facing triangle.  Search a local neighbourhood and reject candidates
    whose surface normal faces away from the target polygon.
    """
    nearest = bvh.find_nearest(point)
    if nearest is None or nearest[2] is None:
        return None

    nearest_distance = float(nearest[3])
    # Coordinates are in the original Neversoft model scale (roughly 90 units
    # tall).  This radius is wide enough to see both sides of a limb without
    # admitting unrelated body parts.
    radius = max(2.0, nearest_distance * 3.0 + 0.25)
    candidates = bvh.find_nearest_range(point, radius)
    if bounds is not None:
        candidates = same_radial_side(candidates, point, bounds)
    aligned = [
        hit
        for hit in candidates
        if hit[2] is not None and normal.dot(hit[1]) >= 0.1
    ]
    if not aligned:
        return nearest

    # Distance remains the primary selector after back-facing candidates have
    # been removed.  Prefer a more parallel surface only for near ties.
    return min(
        aligned,
        key=lambda hit: (float(hit[3]), -float(normal.dot(hit[1]))),
    )


def same_radial_side(
    candidates: list[tuple[Vector, Vector, int, float]],
    point: Vector,
    bounds: tuple[Vector, Vector],
) -> list[tuple[Vector, Vector, int, float]]:
    """Reject hits around the opposite side of a rigid body segment.

    A head, limb, hand, or foot is approximately a tube along its longest
    local axis.  Euclidean nearest-face tests can jump through that tube when
    the Dreamcast mesh is denser or broader.  Compare the angular direction in
    the two-axis cross-section so rear-head points cannot acquire front-eye UVs
    and calf/foot points cannot acquire their opposite-side texture strips.
    """
    minimum, maximum = bounds
    extents = maximum - minimum
    center = (minimum + maximum) * 0.5

    # The character's depth axis is globally local Y for every rigid segment.
    # Enforce that half-space first: a rear point must never select an eye/front
    # triangle merely because it is close around the side of a low-poly head.
    depth_delta = point.y - center.y
    if abs(depth_delta) > max(abs(extents.y) * 0.03, 1e-4):
        depth_side = [
            hit
            for hit in candidates
            if (hit[0].y - center.y) * depth_delta >= 0.0
        ]
        if depth_side:
            candidates = depth_side

    principal_axis = max(range(3), key=lambda axis: abs(extents[axis]))
    cross_axes = [axis for axis in range(3) if axis != principal_axis]

    def radial(value: Vector) -> Vector:
        result = Vector()
        result.x = (
            (value[cross_axes[0]] - center[cross_axes[0]])
            / max(abs(extents[cross_axes[0]]), 1e-6)
        )
        result.y = (
            (value[cross_axes[1]] - center[cross_axes[1]])
            / max(abs(extents[cross_axes[1]]), 1e-6)
        )
        return result.xy

    query = radial(point)
    if query.length <= 0.05:
        return candidates
    query.normalize()
    same_side = []
    for hit in candidates:
        candidate = radial(hit[0])
        if candidate.length <= 0.05:
            continue
        candidate.normalize()
        if query.dot(candidate) >= 0.70:
            same_side.append(hit)
    return same_side or candidates


def sample_image(image: bpy.types.Image, uv: Vector) -> Vector:
    width, height = int(image.size[0]), int(image.size[1])
    if width <= 0 or height <= 0:
        raise RuntimeError(f"image {image.name} has invalid dimensions")
    x = min(int((float(uv.x) % 1.0) * width), width - 1)
    y = min(int((float(uv.y) % 1.0) * height), height - 1)
    offset = (y * width + x) * 4
    pixels = image.pixels
    return Vector((pixels[offset], pixels[offset + 1], pixels[offset + 2]))


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


def nearest_oracle_hit(
    bvh: BVHTree,
    triangles: list[bpy.types.MeshLoopTriangle],
    point: Vector,
    normal: Vector,
    target_color: Vector,
    oracle_mesh: bpy.types.Mesh,
    oracle_materials: list[bpy.types.Material],
    bounds: tuple[Vector, Vector] | None = None,
) -> tuple[Vector, Vector, int, float] | None:
    """Use the two default costumes to reject a nearby but wrong body surface."""
    nearest = bvh.find_nearest(point)
    if nearest is None or nearest[2] is None:
        return None
    nearest_distance = float(nearest[3])
    radius = max(4.0, nearest_distance * 4.0 + 0.5)
    candidates = bvh.find_nearest_range(point, radius)
    if not candidates:
        return nearest
    if bounds is not None:
        candidates = same_radial_side(candidates, point, bounds)
    aligned = [hit for hit in candidates if normal.dot(hit[1]) >= 0.1]
    if aligned:
        candidates = aligned

    def score(hit: tuple[Vector, Vector, int, float]) -> tuple[float, float]:
        triangle = triangles[hit[2]]
        uv = triangle_uv_at(oracle_mesh, triangle, hit[0])
        material = oracle_materials[triangle.material_index]
        source_color = sample_image(material_image(material), uv)
        color_error = (source_color - target_color).length_squared
        alignment = normal.dot(hit[1])
        normal_error = max(0.0, 0.25 - alignment)
        return (
            float(hit[3]) + color_error * 8.0 + normal_error * 2.0,
            float(hit[3]),
        )

    return min(candidates, key=score)


def exhaustive_surface_hit(
    triangles: list[bpy.types.MeshLoopTriangle],
    mesh: bpy.types.Mesh,
    point: Vector,
    normal: Vector,
    bounds: tuple[Vector, Vector] | None,
    target_color: Vector | None = None,
    materials: list[bpy.types.Material] | None = None,
) -> tuple[Vector, Vector, int, float] | None:
    """Choose an anatomical match without a BVH neighbourhood cutoff.

    The two Spider-Man meshes are close enough for geometry to identify the
    body part, but not close enough for a local BVH query to reliably see the
    corresponding side of every broad Dreamcast polygon.  In particular, the
    nearest few head candidates can all be front-eye faces even for a rear DC
    polygon.  Body-part triangle counts are small, so score the complete part
    and make front/rear and radial side constraints hard filters.
    """
    if not triangles:
        return None

    minimum = maximum = center = extents = None
    if bounds is not None:
        minimum, maximum = bounds
        center = (minimum + maximum) * 0.5
        extents = maximum - minimum

    candidates: list[
        tuple[Vector, Vector, int, float, Vector, bpy.types.MeshLoopTriangle]
    ] = []
    for local_index, triangle in enumerate(triangles):
        a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
        location = closest_point_on_tri(point, a, b, c)
        delta = location - point
        if extents is None:
            normalized_delta = delta
        else:
            normalized_delta = Vector(
                tuple(delta[axis] / max(abs(extents[axis]), 1e-6) for axis in range(3))
            )
        candidates.append(
            (
                location,
                triangle.normal.copy(),
                local_index,
                float(delta.length),
                normalized_delta,
                triangle,
            )
        )

    if center is not None and extents is not None:
        depth_delta = point.y - center.y
        depth_threshold = max(abs(extents.y) * 0.03, 1e-4)
        if abs(depth_delta) > depth_threshold:
            # This is intentionally strict.  A back-of-head query must never
            # fall back to the front half merely because that face is closer.
            same_depth = [
                candidate
                for candidate in candidates
                if (candidate[0].y - center.y) * depth_delta >= 0.0
            ]
            if same_depth:
                candidates = same_depth

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
        if query_radial.length > 0.05:
            query_radial.normalize()
            same_sector = []
            for candidate in candidates:
                candidate_radial = radial(candidate[0])
                if candidate_radial.length <= 0.05:
                    continue
                candidate_radial.normalize()
                if query_radial.dot(candidate_radial) >= 0.25:
                    same_sector.append(candidate)
            if same_sector:
                candidates = same_sector

    aligned = [candidate for candidate in candidates if normal.dot(candidate[1]) >= 0.0]
    if aligned:
        candidates = aligned

    def score(
        candidate: tuple[
            Vector, Vector, int, float, Vector, bpy.types.MeshLoopTriangle
        ]
    ) -> tuple[float, float]:
        location, candidate_normal, _, distance, normalized_delta, triangle = candidate
        spatial_error = float(normalized_delta.length_squared)
        normal_error = max(0.0, 1.0 - float(normal.dot(candidate_normal)))
        color_error = 0.0
        if target_color is not None and materials is not None:
            source_uv = triangle_uv_at(mesh, triangle, location)
            source_color = sample_image(
                material_image(materials[triangle.material_index]), source_uv
            )
            color_error = float((source_color - target_color).length_squared)
        return (
            spatial_error + normal_error * 0.10 + color_error * 4.00,
            distance,
        )

    best = min(candidates, key=score)
    return best[0], best[1], best[2], best[3]


def ray_surface_hit(
    bvh: BVHTree,
    point: Vector,
    normal: Vector,
    bounds: tuple[Vector, Vector] | None,
) -> tuple[Vector, Vector, int, float] | None:
    """Ray inward from both sides and keep the source's matching outward face."""
    direction = normal.normalized()
    center = extents = None
    principal_axis = None
    cross_axes: list[int] = []
    if bounds is not None:
        center = (bounds[0] + bounds[1]) * 0.5
        extents = bounds[1] - bounds[0]
        principal_axis = max(range(3), key=lambda axis: abs(extents[axis]))
        cross_axes = [axis for axis in range(3) if axis != principal_axis]
        # Imported shading normals are not consistently outward on every
        # mirrored rigid segment.  The gradient of the part's cross-section is
        # a stable anatomical outward direction for heads, limbs, and feet.
        anatomical = Vector((0.0, 0.0, 0.0))
        for axis in cross_axes:
            anatomical[axis] = (point[axis] - center[axis]) / max(
                abs(extents[axis]) ** 2, 1e-6
            )
        normalized_depth = (point.y - center.y) / max(abs(extents.y), 1e-6)
        if abs(normalized_depth) >= 0.18:
            # Front and rear costume art is authored as a depth projection.
            # A diagonal ellipsoid ray at the rear-right skull can otherwise
            # graze the side eye and magnify it across a rear DC polygon.
            direction = Vector((0.0, 1.0 if normalized_depth > 0.0 else -1.0, 0.0))
        elif anatomical.length > 0.02:
            direction = anatomical.normalized()
    if direction.length <= 1e-6:
        return None
    if bounds is None:
        ray_length = 100.0
    else:
        ray_length = max((bounds[1] - bounds[0]).length * 2.0, 4.0)

    hits: list[tuple[Vector, Vector, int, float]] = []
    for outward_direction in (direction, -direction):
        origin = point + outward_direction * ray_length
        hit = bvh.ray_cast(origin, -outward_direction, ray_length * 2.0)
        if hit[0] is None or hit[1] is None or hit[2] is None:
            continue
        if center is not None and extents is not None:
            depth_delta = point.y - center.y
            if (
                abs(depth_delta) > max(abs(extents.y) * 0.03, 1e-4)
                and (hit[0].y - center.y) * depth_delta < 0.0
            ):
                continue
            query_radial = Vector(
                tuple(
                    (point[axis] - center[axis])
                    / max(abs(extents[axis]), 1e-6)
                    for axis in cross_axes
                )
            )
            hit_radial = Vector(
                tuple(
                    (hit[0][axis] - center[axis])
                    / max(abs(extents[axis]), 1e-6)
                    for axis in cross_axes
                )
            )
            if (
                query_radial.length > 0.05
                and hit_radial.length > 0.05
                and query_radial.normalized().dot(hit_radial.normalized()) < 0.25
            ):
                continue
        hits.append((hit[0], hit[1], hit[2], float((hit[0] - point).length)))
    if not hits:
        return None
    aligned = [hit for hit in hits if direction.dot(hit[1]) >= 0.1]
    if aligned:
        hits = aligned
    return min(hits, key=lambda hit: (hit[3], -direction.dot(hit[1])))


def oracle_hit_color_error(
    hit: tuple[Vector, Vector, int, float] | None,
    triangles: list[bpy.types.MeshLoopTriangle],
    mesh: bpy.types.Mesh,
    materials: list[bpy.types.Material],
    target_color: Vector,
) -> float:
    if hit is None or hit[2] is None:
        return float("inf")
    triangle = triangles[hit[2]]
    source_uv = triangle_uv_at(mesh, triangle, hit[0])
    source_color = sample_image(
        material_image(materials[triangle.material_index]), source_uv
    )
    return float((source_color - target_color).length_squared)


def parametric_surface_hit(
    triangles: list[bpy.types.MeshLoopTriangle],
    mesh: bpy.types.Mesh,
    point: Vector,
    bounds: tuple[Vector, Vector] | None,
    target_color: Vector | None = None,
    materials: list[bpy.types.Material] | None = None,
) -> tuple[Vector, Vector, int, float] | None:
    """Match a rigid part in longitudinal/around-the-body coordinates.

    Bone-segment surfaces are topological tubes.  Comparing height along the
    segment and angle around its cross-section is invariant to the different
    Dreamcast/PS1 silhouettes, and cannot jump through a head or calf to the
    opposite texture strip.
    """
    if not triangles or bounds is None:
        return None
    minimum, maximum = bounds
    center = (minimum + maximum) * 0.5
    extents = maximum - minimum
    principal_axis = max(range(3), key=lambda axis: abs(extents[axis]))
    cross_axes = [axis for axis in range(3) if axis != principal_axis]

    def parameters(value: Vector) -> tuple[float, float]:
        longitudinal = (value[principal_axis] - minimum[principal_axis]) / max(
            abs(extents[principal_axis]), 1e-6
        )
        first = (value[cross_axes[0]] - center[cross_axes[0]]) / max(
            abs(extents[cross_axes[0]]), 1e-6
        )
        second = (value[cross_axes[1]] - center[cross_axes[1]]) / max(
            abs(extents[cross_axes[1]]), 1e-6
        )
        return longitudinal, math.atan2(second, first) / math.pi

    query_longitudinal, query_angle = parameters(point)

    def unwrap(angle: float) -> float:
        while angle - query_angle > 1.0:
            angle -= 2.0
        while angle - query_angle < -1.0:
            angle += 2.0
        return angle

    best: tuple[float, float, Vector, Vector, int] | None = None
    for local_index, triangle in enumerate(triangles):
        source_vertices = [mesh.vertices[index].co for index in triangle.vertices]
        source_parameters = [parameters(vertex) for vertex in source_vertices]
        parameter_vertices = [
            Vector((longitudinal, unwrap(angle), 0.0))
            for longitudinal, angle in source_parameters
        ]
        parameter_area = (
            parameter_vertices[1] - parameter_vertices[0]
        ).cross(parameter_vertices[2] - parameter_vertices[0]).length
        if parameter_area <= 1e-8:
            continue
        query = Vector((query_longitudinal, query_angle, 0.0))
        closest = closest_point_on_tri(query, *parameter_vertices)
        if not all(math.isfinite(float(value)) for value in closest):
            continue
        parameter_error = float((closest - query).length_squared)
        location = barycentric_transform(
            closest,
            *parameter_vertices,
            *source_vertices,
        )
        color_error = 0.0
        if target_color is not None and materials is not None:
            uv = triangle_uv_at(mesh, triangle, location)
            color = sample_image(
                material_image(materials[triangle.material_index]), uv
            )
            color_error = float((color - target_color).length_squared)
        score = parameter_error + color_error * 0.20
        candidate = (
            score,
            parameter_error,
            location,
            triangle.normal.copy(),
            local_index,
        )
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None
    return best[2], best[3], best[4], math.sqrt(best[1])


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
    oracle_source: bpy.types.Object | None = None,
) -> tuple[dict[str, int], list[dict[str, object]]]:
    mapping_source = oracle_source or source
    source_mesh = mapping_source.data
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

    # A Dreamcast polygon is usually larger than the closest SM2 source triangle.
    # Projecting all of its corners through only the centre triangle clamps the
    # outlying corners to that triangle's edges.  The resulting UV plateaus are
    # especially visible as foreign triangular patches on the crown and calves.
    # Keep the centre lookup for the polygon's material, then project every loop
    # through its own nearest triangle within that same material surface.
    triangles_by_material: dict[int, list[bpy.types.MeshLoopTriangle]] = {}
    triangles_by_group: dict[str, list[bpy.types.MeshLoopTriangle]] = {}
    triangles_by_surface: dict[tuple[int, str], list[bpy.types.MeshLoopTriangle]] = {}
    for triangle in triangles:
        triangles_by_material.setdefault(triangle.material_index, []).append(triangle)
        group_totals: dict[str, float] = {}
        for vertex_index in triangle.vertices:
            for membership in source_mesh.vertices[vertex_index].groups:
                name = mapping_source.vertex_groups[membership.group].name
                group_totals[name] = group_totals.get(name, 0.0) + membership.weight
        if group_totals:
            group_name = max(group_totals, key=group_totals.get)
            triangles_by_group.setdefault(group_name, []).append(triangle)
            triangles_by_surface.setdefault(
                (triangle.material_index, group_name), []
            ).append(triangle)
    bvh_by_material = {
        material_index: BVHTree.FromPolygons(
            vertices,
            [tuple(triangle.vertices) for triangle in material_triangles],
            all_triangles=True,
        )
        for material_index, material_triangles in triangles_by_material.items()
    }
    bvh_by_group = {
        group_name: BVHTree.FromPolygons(
            vertices,
            [tuple(triangle.vertices) for triangle in group_triangles],
            all_triangles=True,
        )
        for group_name, group_triangles in triangles_by_group.items()
    }
    bvh_by_surface = {
        surface: BVHTree.FromPolygons(
            vertices,
            [tuple(triangle.vertices) for triangle in surface_triangles],
            all_triangles=True,
        )
        for surface, surface_triangles in triangles_by_surface.items()
    }
    # Split each material/body-part surface at true mesh/UV seams.  Blender's
    # glTF import duplicates vertices at UV seams, so triangles connected by a
    # shared vertex necessarily belong to one continuous source UV island.
    # Keeping all three target corners inside the centre triangle's component
    # prevents interpolation through an unrelated island while still allowing
    # smooth transfer across adjacent source triangles.
    triangles_by_component: dict[
        tuple[int, str, int], list[bpy.types.MeshLoopTriangle]
    ] = {}
    component_by_triangle: dict[int, tuple[int, str, int]] = {}
    for (material_index, group_name), surface_triangles in triangles_by_surface.items():
        parents = list(range(len(surface_triangles)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        triangles_at_vertex: dict[int, list[int]] = {}
        for local_index, triangle in enumerate(surface_triangles):
            for vertex_index in triangle.vertices:
                triangles_at_vertex.setdefault(vertex_index, []).append(local_index)
        for local_indices in triangles_at_vertex.values():
            for other in local_indices[1:]:
                union(local_indices[0], other)

        roots: dict[int, list[bpy.types.MeshLoopTriangle]] = {}
        for local_index, triangle in enumerate(surface_triangles):
            roots.setdefault(find(local_index), []).append(triangle)
        for component_index, component_triangles in enumerate(roots.values()):
            key = (material_index, group_name, component_index)
            triangles_by_component[key] = component_triangles
            for triangle in component_triangles:
                component_by_triangle[triangle.index] = key
    bvh_by_component = {
        key: BVHTree.FromPolygons(
            vertices,
            [tuple(triangle.vertices) for triangle in component_triangles],
            all_triangles=True,
        )
        for key, component_triangles in triangles_by_component.items()
    }
    target_group_bounds = group_bounds(target)
    source_group_bounds = group_bounds(mapping_source)

    source_materials = [slot.material for slot in source.material_slots]
    if any(material is None for material in source_materials):
        raise RuntimeError("source contains an empty material slot")
    mapping_materials = [slot.material for slot in mapping_source.material_slots]
    if any(material is None for material in mapping_materials):
        raise RuntimeError("mapping source contains an empty material slot")
    if len(mapping_materials) != len(source_materials):
        raise RuntimeError("oracle and costume source material slots differ")
    source_wing_index = next(
        (
            index
            for index, material in enumerate(source_materials)
            if material.name.casefold().startswith(SOURCE_WING_MATERIAL)
        ),
        None,
    )
    target_wing_indices = {
        index
        for index, slot in enumerate(target.material_slots)
        if slot.material is not None
        and slot.material.name.casefold().startswith(TARGET_WING_MATERIAL)
    }
    if source_wing_index is None or not target_wing_indices:
        raise RuntimeError(
            "source lacks SM2 CEB60740 wing material or target lacks "
            "Dreamcast DC38D248 wing geometry"
        )
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

        polygon_group = polygon_group_name(target, polygon)
        mapped_center = map_group_point(
            polygon.center,
            polygon_group,
            target_group_bounds,
            source_group_bounds,
        )
        center_triangles = triangles
        center_bvh = bvh
        if polygon_group is not None and polygon_group in bvh_by_group:
            center_triangles = triangles_by_group[polygon_group]
            center_bvh = bvh_by_group[polygon_group]
        original_material = original_target_materials[
            mappings[polygon.index]["original"]["materialIndex"]
        ]
        center_uv = sum(
            (target_uv.data[index].uv for index in polygon.loop_indices),
            Vector((0.0, 0.0)),
        ) / len(polygon.loop_indices)
        center_color = sample_image(material_image(original_material), center_uv)
        center_bounds = source_group_bounds.get(polygon_group)
        center_parametric_hit = parametric_surface_hit(
            center_triangles,
            source_mesh,
            mapped_center,
            center_bounds,
            center_color if oracle_source is not None else None,
            mapping_materials if oracle_source is not None else None,
        )
        center_ray_hit = center_parametric_hit or ray_surface_hit(
            center_bvh,
            mapped_center,
            polygon.normal,
            center_bounds,
        )
        if (
            oracle_source is not None
            and oracle_hit_color_error(
                center_ray_hit,
                center_triangles,
                source_mesh,
                mapping_materials,
                center_color,
            )
            > 0.35
        ):
            center_ray_hit = None
        center_hit = center_ray_hit or exhaustive_surface_hit(
            center_triangles,
            source_mesh,
            mapped_center,
            polygon.normal,
            center_bounds,
            center_color if oracle_source is not None else None,
            mapping_materials if oracle_source is not None else None,
        )
        if center_hit is None or center_hit[2] is None:
            misses += 1
            continue
        center_triangle = center_triangles[center_hit[2]]
        polygon.material_index = center_triangle.material_index
        transferred_polygons += 1
        component_key = component_by_triangle.get(center_triangle.index)
        if component_key is None:
            raise RuntimeError(
                f"source triangle {center_triangle.index} has no UV component"
            )
        component_triangles = triangles_by_component[component_key]
        component_bvh = bvh_by_component[component_key]
        diagnostic = {
            "group": polygon_group,
            "targetCenter": [float(value) for value in polygon.center],
            "mappedCenter": [float(value) for value in mapped_center],
            "sourceCenterHit": [float(value) for value in center_hit[0]],
            "sourceCenterTriangle": int(center_triangle.index),
            "sourceCenterMaterial": int(center_triangle.material_index),
            "component": [
                int(component_key[0]),
                component_key[1],
                int(component_key[2]),
            ],
            "loops": [],
        }
        mappings[polygon.index]["diagnostic"] = diagnostic
        for loop_index in polygon.loop_indices:
            vertex_index = target_mesh.loops[loop_index].vertex_index
            point = target_mesh.vertices[vertex_index].co
            loop_group = dominant_group_name(target, vertex_index) or polygon_group
            mapped_point = map_group_point(
                point,
                loop_group,
                target_group_bounds,
                source_group_bounds,
            )
            target_color = sample_image(
                material_image(original_material),
                target_uv.data[loop_index].uv,
            )
            loop_bounds = source_group_bounds.get(loop_group)
            loop_normal = target_mesh.vertices[vertex_index].normal
            loop_parametric_hit = parametric_surface_hit(
                component_triangles,
                source_mesh,
                mapped_point,
                loop_bounds,
                target_color if oracle_source is not None else None,
                mapping_materials if oracle_source is not None else None,
            )
            loop_ray_hit = loop_parametric_hit or ray_surface_hit(
                component_bvh,
                mapped_point,
                loop_normal,
                loop_bounds,
            )
            if (
                oracle_source is not None
                and oracle_hit_color_error(
                    loop_ray_hit,
                    component_triangles,
                    source_mesh,
                    mapping_materials,
                    target_color,
                )
                > 0.35
            ):
                loop_ray_hit = None
            loop_hit = loop_ray_hit or exhaustive_surface_hit(
                component_triangles,
                source_mesh,
                mapped_point,
                loop_normal,
                loop_bounds,
                target_color if oracle_source is not None else None,
                mapping_materials if oracle_source is not None else None,
            )
            if loop_hit is None or loop_hit[2] is None:
                misses += 1
                continue
            loop_triangle = component_triangles[loop_hit[2]]
            target_uv.data[loop_index].uv = triangle_uv_at(
                source_mesh,
                loop_triangle,
                loop_hit[0],
            )
            diagnostic["loops"].append(
                {
                    "loopIndex": int(loop_index),
                    "sourceTriangle": int(loop_triangle.index),
                    "sourceHit": [float(value) for value in loop_hit[0]],
                    "uv": [
                        float(value)
                        for value in target_uv.data[loop_index].uv
                    ],
                }
            )
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
        oracle_group: set[bpy.types.Object] = set()
        oracle_mesh = None
        if args.oracle_source:
            oracle_path = blender_compatible_glb(
                os.path.abspath(args.oracle_source),
                temporary_root,
            )
            _, oracle_mesh, oracle_group = import_group(oracle_path)

        save_source_images(source_mesh, args.textures_output)
        counts, mappings = transfer_surface(source_mesh, target_mesh, oracle_mesh)
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
        for obj in oracle_group:
            bpy.data.objects.remove(obj, do_unlink=True)
        pose_arms(target_armature)
        baked = bake_pose(target_armature)
        if not baked:
            raise RuntimeError("target had no skinned mesh to bake into the T-pose")
        export_glb(args.output, baked)
        if args.blend_output:
            blend_path = Path(args.blend_output).resolve()
            blend_path.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.file.pack_all()
            bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    print(
        f"wrote {args.name} nearest-surface DC transfer: {os.path.abspath(args.output)}; "
        f"polygons={counts['transferredPolygons']}, loops={counts['transferredLoops']}, "
        f"wingPolygons={counts['preservedWingPolygons']}"
    )


if __name__ == "__main__":
    main()
