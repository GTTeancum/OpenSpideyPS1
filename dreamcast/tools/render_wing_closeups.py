"""Render tight, repeatable wing views from a static Spider-Man proof GLB."""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Vector


sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_tpose_glb import blender_compatible_glb, clear_scene  # noqa: E402


WING_MATERIAL_PREFIXES = ("tex_dc38d248", "wing_magenta_key")
VIEWS = {
    "front": Vector((0.0, -1.0, 0.05)),
    "rear": Vector((0.0, 1.0, 0.05)),
    "front_underside": Vector((0.0, -1.0, -0.55)),
    "rear_underside": Vector((0.0, 1.0, -0.55)),
    "left_oblique": Vector((-0.75, -1.0, -0.2)),
    "right_oblique": Vector((0.75, -1.0, -0.2)),
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prefix", default="wing")
    parser.add_argument("--width", type=int, default=1800)
    parser.add_argument("--height", type=int, default=1200)
    return parser.parse_args(argv)


def wing_points() -> list[Vector]:
    points: list[Vector] = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        wing_slots = {
            index
            for index, slot in enumerate(obj.material_slots)
            if slot.material is not None
            and slot.material.name.casefold().startswith(WING_MATERIAL_PREFIXES)
        }
        for polygon in obj.data.polygons:
            if polygon.material_index not in wing_slots:
                continue
            points.extend(obj.matrix_world @ obj.data.vertices[index].co for index in polygon.vertices)
    if not points:
        raise RuntimeError("no polygons use the DC38D248 wing material")
    return points


def look_at(camera: bpy.types.Object, target: Vector) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def projected_scale(points: list[Vector], center: Vector, direction: Vector, aspect: float) -> float:
    forward = -direction.normalized()
    right = forward.cross(Vector((0.0, 0.0, 1.0)))
    if right.length < 1e-6:
        right = Vector((1.0, 0.0, 0.0))
    right.normalize()
    up = right.cross(forward).normalized()
    xs = [(point - center).dot(right) for point in points]
    ys = [(point - center).dot(up) for point in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    # Include a little shoulder context but keep the membranes large in frame.
    return max(height * 1.45, width / aspect * 1.35, 8.0)


def add_area_light(name: str, location: tuple[float, float, float], energy: float, size: float) -> None:
    data = bpy.data.lights.new(name=name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    light = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(light)
    light.location = location
    look_at(light, Vector((0.0, 0.0, 0.0)))


def make_materials_unlit() -> None:
    """Show authored pixels directly while retaining each material's alpha."""
    for material in bpy.data.materials:
        if not material.use_nodes or material.node_tree is None:
            continue
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        output = next((node for node in nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output), None)
        principled = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
        if output is None or principled is None:
            continue

        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Strength"].default_value = 1.0
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        mix = nodes.new("ShaderNodeMixShader")

        base_color = principled.inputs.get("Base Color")
        alpha = principled.inputs.get("Alpha")
        if base_color is not None and base_color.is_linked:
            links.new(base_color.links[0].from_socket, emission.inputs["Color"])
        elif base_color is not None:
            emission.inputs["Color"].default_value = base_color.default_value
        if alpha is not None and alpha.is_linked:
            links.new(alpha.links[0].from_socket, mix.inputs[0])
        elif alpha is not None:
            mix.inputs[0].default_value = alpha.default_value
        else:
            mix.inputs[0].default_value = 1.0

        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(emission.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs["Surface"])


def setup_scene(width: int, height: int, center: Vector) -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.world.color = (0.025, 0.025, 0.035)

    camera_data = bpy.data.cameras.new("wing_audit_camera")
    camera_data.type = "ORTHO"
    camera_data.lens = 55
    camera = bpy.data.objects.new("wing_audit_camera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera

    add_area_light("wing_key", tuple(center + Vector((-20.0, -30.0, 25.0))), 1100.0, 18.0)
    add_area_light("wing_fill", tuple(center + Vector((25.0, 18.0, 10.0))), 850.0, 15.0)
    add_area_light("wing_rim", tuple(center + Vector((0.0, 20.0, -15.0))), 700.0, 12.0)
    return camera


def main() -> None:
    args = parse_args()
    clear_scene()
    with tempfile.TemporaryDirectory(prefix="spidey-wing-render-") as temporary_root:
        import_path = blender_compatible_glb(os.path.abspath(args.input), temporary_root)
        bpy.ops.import_scene.gltf(filepath=import_path)
    make_materials_unlit()
    points = wing_points()
    center = sum(points, Vector()) / len(points)
    camera = setup_scene(args.width, args.height, center)
    aspect = args.width / args.height
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for view_name, direction in VIEWS.items():
        normalized = direction.normalized()
        camera.location = center + normalized * 100.0
        look_at(camera, center)
        camera.data.ortho_scale = projected_scale(points, center, normalized, aspect)
        output = output_dir / f"{args.prefix}_{view_name}.png"
        bpy.context.scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        print(f"rendered {output}")


if __name__ == "__main__":
    main()
