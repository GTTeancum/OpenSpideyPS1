"""Surface-bake an SM2 PS1 costume onto donor-exact winged DC Spider-Man.

Run with Blender. Both inputs are loose-file-derived GLBs. The source is the
SM2 low-detail model carrying one ``sp_texNN`` library; the target is the
high-detail DC model reconstructed from the donor-exact winged PSX binary.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

import bpy


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
    parser.add_argument("--cage-extrusion", type=float, default=1.5)
    parser.add_argument("--max-ray-distance", type=float, default=3.0)
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
) -> dict[str, tuple[bpy.types.Image, bpy.types.ShaderNodeTexImage]]:
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
            width=max(int(width), 1),
            height=max(int(height), 1),
            alpha=True,
        )
        image.generated_color = (0.0, 0.0, 0.0, 1.0)
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.name = f"{costume_name} surface bake"
        node.image = image
        node.interpolation = "Closest"
        material.node_tree.nodes.active = node
        images[material.name] = (image, node)
    return images


def bake_body(
    source: bpy.types.Object,
    target: bpy.types.Object,
    cage_extrusion: float,
    max_ray_distance: float,
) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.cage_extrusion = cage_extrusion
    scene.render.bake.max_ray_distance = max_ray_distance
    scene.render.bake.margin = 8
    bpy.ops.object.bake(type="EMIT", target="IMAGE_TEXTURES")


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
            and slot.material.name.casefold().startswith(WING_MATERIAL)
        ),
        None,
    )
    target_material = next(
        (
            slot.material
            for slot in target.material_slots
            if slot.material is not None
            and slot.material.name.casefold().startswith(WING_MATERIAL)
        ),
        None,
    )
    if source_material is None or target_material is None:
        raise RuntimeError("source or target lacks native DC38D248 wing material")
    source_image = image_node(source_material).image
    target_image = images[target_material.name][0]
    if source_image is None:
        raise RuntimeError("SM2 wing material has no source image")
    old_width, old_height = int(target_image.size[0]), int(target_image.size[1])
    new_width, new_height = int(source_image.size[0]), int(source_image.size[1])
    if new_width <= 0 or new_height <= 0:
        raise RuntimeError("SM2 wing texture has invalid dimensions")

    # Neversoft UV bytes are pixel coordinates.  The Multitool GLB normalizes
    # them by each texture's dimensions, so replacing a 64x64 target image with
    # Dusk's 32x32 image also requires doubling the normalized UVs.  Without
    # this adjustment, only half of the intended source texture is sampled.
    wing_slot_indices = {
        index
        for index, slot in enumerate(target.material_slots)
        if slot.material is target_material
    }
    uv_layer = target.data.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("target wing mesh has no active UV layer")
    u_scale = old_width / new_width
    v_scale = old_height / new_height
    for polygon in target.data.polygons:
        if polygon.material_index not in wing_slot_indices:
            continue
        for loop_index in polygon.loop_indices:
            uv_layer.data[loop_index].uv.x *= u_scale
            # Blender imports glTF V as 1-V.  Scaling that stored value around zero
            # makes the exported V become ``source_v * scale - (scale - 1)``; Dusk's
            # 2x case therefore landed exactly one full texture repeat too low.  Scale
            # around the import/export pivot at V=1 so the emitted glTF coordinate is
            # the donor's original pixel-coordinate normalization.
            uv_layer.data[loop_index].uv.y = 1.0 + (
                uv_layer.data[loop_index].uv.y - 1.0
            ) * v_scale

    target_image.scale(source_image.size[0], source_image.size[1])
    target_image.pixels = list(source_image.pixels)
    target_image.update()
    # The native PS1 model draws reverse-winding copies.  Static GLB proofs
    # collapse those copies, so the surviving membrane must be two-sided.
    target_material.use_backface_culling = False


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
        node.interpolation = "Closest"
        tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
        tree.links.new(node.outputs["Color"], principled.inputs["Base Color"])
        tree.links.new(node.outputs["Alpha"], principled.inputs["Alpha"])
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


def main() -> None:
    args = parse_args()
    clear_scene()
    with tempfile.TemporaryDirectory(prefix="spidey-costume-bake-") as temporary_root:
        target_path = blender_compatible_glb(os.path.abspath(args.target), temporary_root)
        source_path = blender_compatible_glb(os.path.abspath(args.source), temporary_root)
        target_armature, target_mesh, target_group = import_group(target_path)
        source_armature, source_mesh, source_group = import_group(source_path)

        images = prepare_bake_images(target_mesh, args.name)
        bake_body(
            source_mesh,
            target_mesh,
            args.cage_extrusion,
            args.max_ray_distance,
        )
        copy_source_wing(source_mesh, target_mesh, images)
        connect_baked_images(target_mesh, images)
        save_images(images, args.textures_output)

        for obj in source_group:
            bpy.data.objects.remove(obj, do_unlink=True)
        pose_arms(target_armature)
        baked = bake_pose(target_armature)
        if not baked:
            raise RuntimeError("target had no skinned mesh to bake into the T-pose")
        export_glb(args.output, baked)
    print(f"wrote {args.name} DC surface bake in a static T-pose: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
