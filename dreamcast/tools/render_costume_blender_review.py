"""Render repeatable body-region close-ups from a costume .blend file.

Run with Blender in background mode.  The camera operates only inside Blender;
no desktop input or window automation is used.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--shot",
        action="append",
        help="render only this named shot; repeat for multiple shots",
    )
    parser.add_argument(
        "--probe",
        action="append",
        help="report the mesh polygon under an output pixel formatted as X,Y",
    )
    return parser.parse_args(argv)


def point_camera(camera: bpy.types.Object, target: Vector) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def main() -> None:
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input.resolve()))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    scene = bpy.context.scene
    # The exporter wires vertex-lit texture color into Emission.  Eevee renders
    # that exact material graph; Workbench's texture mode incorrectly applies
    # palette alpha to opaque body pixels and creates false holes.
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.film_transparent = False
    scene.world.color = (0.18, 0.18, 0.18)
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1400
    scene.render.resolution_percentage = 100

    camera_data = bpy.data.cameras.new("CostumeReviewCamera")
    camera_data.type = "ORTHO"
    camera = bpy.data.objects.new("CostumeReviewCamera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera

    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("review blend contains no mesh")
    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in meshes
        for corner in obj.bound_box
    ]
    minimum = Vector(tuple(min(point[index] for point in corners) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in corners) for index in range(3)))
    center = (minimum + maximum) * 0.5
    width = maximum.x - minimum.x
    height = maximum.z - minimum.z
    camera_distance = max(width, height) * 2.0

    def z_at(fraction: float) -> float:
        return minimum.z + height * fraction

    # The PSX actor exporter uses Z-up, X left/right, and -Y as the character's
    # front. Fractions of the actual bounds keep the same anatomical framing
    # whether the source blend retains its import scale or has transforms baked.
    shots = (
        ("full_front", (center.x, center.y - camera_distance, center.z), center, max(width, height) * 1.08),
        ("full_rear", (center.x, center.y + camera_distance, center.z), center, max(width, height) * 1.08),
        ("head_front", (center.x, center.y - camera_distance, z_at(0.90)), (center.x, center.y, z_at(0.90)), height * 0.25),
        ("head_rear", (center.x, center.y + camera_distance, z_at(0.90)), (center.x, center.y, z_at(0.90)), height * 0.25),
        ("head_rear_left", (center.x - camera_distance, center.y + camera_distance, z_at(0.90)), (center.x, center.y, z_at(0.90)), height * 0.28),
        ("head_rear_right", (center.x + camera_distance, center.y + camera_distance, z_at(0.90)), (center.x, center.y, z_at(0.90)), height * 0.28),
        ("shoulders_front", (center.x, center.y - camera_distance, z_at(0.70)), (center.x, center.y, z_at(0.70)), height * 0.58),
        ("shoulders_rear", (center.x, center.y + camera_distance, z_at(0.70)), (center.x, center.y, z_at(0.70)), height * 0.58),
        ("legs_front", (center.x, center.y - camera_distance, z_at(0.37)), (center.x, center.y, z_at(0.37)), height * 0.58),
        ("legs_rear", (center.x, center.y + camera_distance, z_at(0.37)), (center.x, center.y, z_at(0.37)), height * 0.58),
        ("calves_front", (center.x, center.y - camera_distance, z_at(0.19)), (center.x, center.y, z_at(0.19)), height * 0.40),
        ("calves_rear", (center.x, center.y + camera_distance, z_at(0.19)), (center.x, center.y, z_at(0.19)), height * 0.40),
        ("calves_rear_left", (center.x - camera_distance, center.y + camera_distance, z_at(0.19)), (center.x, center.y, z_at(0.19)), height * 0.44),
        ("calves_rear_right", (center.x + camera_distance, center.y + camera_distance, z_at(0.19)), (center.x, center.y, z_at(0.19)), height * 0.44),
        ("feet_front", (center.x, center.y - camera_distance, z_at(0.04)), (center.x, center.y, z_at(0.04)), height * 0.30),
        ("feet_rear", (center.x, center.y + camera_distance, z_at(0.04)), (center.x, center.y, z_at(0.04)), height * 0.30),
    )
    for name, location, target, scale in shots:
        if args.shot and name not in args.shot:
            continue
        camera.location = location
        camera_data.ortho_scale = scale
        point_camera(camera, Vector(target))
        for probe in args.probe or ():
            pixel_x, pixel_y = (float(value) for value in probe.split(",", 1))
            local_x = (pixel_x / scene.render.resolution_x - 0.5) * scale
            local_y = (0.5 - pixel_y / scene.render.resolution_y) * scale
            origin = camera.matrix_world @ Vector((local_x, local_y, 0.0))
            direction = camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
            hits = []
            for obj in meshes:
                inverse = obj.matrix_world.inverted()
                local_origin = inverse @ origin
                local_direction = (inverse.to_3x3() @ direction).normalized()
                hit, hit_location, _, polygon_index = obj.ray_cast(
                    local_origin,
                    local_direction,
                )
                if hit:
                    world_location = obj.matrix_world @ hit_location
                    hits.append(
                        (
                            (world_location - origin).length,
                            obj.name,
                            polygon_index,
                            [float(value) for value in world_location],
                        )
                    )
            print(f"probe {name} {probe}: {min(hits) if hits else None}")
        scene.render.filepath = str(output / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print(f"rendered {name}: {scene.render.filepath}")


if __name__ == "__main__":
    main()
