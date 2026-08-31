"""Bake a Spider-Man GLB into a static T-pose for inspection screenshots.

This deliberately produces a proof artifact, not the runtime character.  The
runtime GLB keeps its armature and bind pose; this script rotates the two bicep
bones, applies the armature modifiers, and exports the evaluated geometry.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile

import bpy


LEFT_BICEP_BONE = "spidey_spidey_left_bicep01"
RIGHT_BICEP_BONE = "spidey_spidey_right_bicep01"
WING_MATERIAL_PREFIXES = ("tex_dc38d248", "wing_magenta_key")


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--show-wings",
        action="store_true",
        help="replace the normally transparent wing texture with an opaque UV audit grid",
    )
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def blender_compatible_glb(path: str, temporary_root: str) -> str:
    """Drop only optional custom PSX attributes that trigger a Blender 4.5 bug.

    Neversoft Multitool emits `_PSX_COLOR_0`/`_PSX_FLAGS_0` diagnostics in
    addition to standard glTF attributes.  Their accessor widths can differ
    between primitives, and Blender incorrectly tries to concatenate them.
    Skin joints, weights, positions, UVs, normals and colors are untouched.
    """
    source = Path(path)
    if source.suffix.casefold() != ".glb":
        return str(source)
    data = source.read_bytes()
    if data[:4] != b"glTF":
        return str(source)

    chunks: list[tuple[int, bytes]] = []
    cursor = 12
    while cursor < len(data):
        length, chunk_type = struct.unpack_from("<II", data, cursor)
        cursor += 8
        chunks.append((chunk_type, data[cursor : cursor + length]))
        cursor += length

    changed = False
    rebuilt: list[tuple[int, bytes]] = []
    for chunk_type, payload in chunks:
        if chunk_type != 0x4E4F534A:
            rebuilt.append((chunk_type, payload))
            continue
        document = json.loads(payload.decode("utf-8"))
        for mesh in document.get("meshes", []):
            for primitive in mesh.get("primitives", []):
                attributes = primitive.get("attributes", {})
                for name in list(attributes):
                    if name.startswith("_PSX_"):
                        del attributes[name]
                        changed = True
        encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
        encoded += b" " * ((-len(encoded)) % 4)
        rebuilt.append((chunk_type, encoded))

    if not changed:
        return str(source)
    output = bytearray(b"glTF" + struct.pack("<II", 2, 0))
    for chunk_type, payload in rebuilt:
        output.extend(struct.pack("<II", len(payload), chunk_type))
        output.extend(payload)
    struct.pack_into("<I", output, 8, len(output))
    sanitized = Path(temporary_root) / source.name
    sanitized.write_bytes(output)
    return str(sanitized)


def pose_arms(armature: bpy.types.Object) -> None:
    # Imported glTF bones point along local Y.  Their local Z axes map to the
    # model's left/right shoulder swing axis, so Z (not Blender's displayed
    # global Y) raises the hanging arms into a T-pose.
    rotations = {
        LEFT_BICEP_BONE: math.pi / 2.0,
        RIGHT_BICEP_BONE: -math.pi / 2.0,
    }
    for name, angle in rotations.items():
        bone = armature.pose.bones.get(name)
        if bone is None:
            bone = next(
                (candidate for candidate in armature.pose.bones if candidate.name.casefold() == name.casefold()),
                None,
            )
        if bone is None:
            raise RuntimeError(f"armature lacks required T-pose bone {name}")
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, angle)
    bpy.context.view_layer.update()


def wing_materials(objects: list[bpy.types.Object] | None = None) -> list[bpy.types.Material]:
    candidates = (
        [slot.material for obj in objects for slot in obj.material_slots]
        if objects is not None
        else list(bpy.data.materials)
    )
    return list(
        {
            material.name: material
            for material in candidates
            if material is not None
            and material.name.casefold().startswith(WING_MATERIAL_PREFIXES)
        }.values()
    )


def material_image(material: bpy.types.Material) -> bpy.types.Image | None:
    if not material.use_nodes or material.node_tree is None:
        return None
    return next(
        (
            node.image
            for node in material.node_tree.nodes
            if node.type == "TEX_IMAGE" and node.image is not None
        ),
        None,
    )


def image_alpha_mode(image: bpy.types.Image | None) -> str:
    """Return the glTF alpha mode represented by an image's actual pixels."""
    if image is None or image.size[0] <= 0 or image.size[1] <= 0:
        return "OPAQUE"
    # Blender's ``bpy_prop_array`` accepts a plain slice but rejects a stepped
    # one, so materialize once before selecting alpha components.
    alphas = list(image.pixels)[3::4]
    if not alphas or min(alphas) >= 1.0 - 1e-6:
        return "OPAQUE"
    if all(alpha <= 1e-6 or alpha >= 1.0 - 1e-6 for alpha in alphas):
        return "MASK"
    return "BLEND"


def configure_wing_materials(objects: list[bpy.types.Object]) -> dict[str, str]:
    """Make collapsed PS1 reverse faces two-sided and retain alpha semantics."""
    semantics: dict[str, str] = {}
    for material in wing_materials(objects):
        material.use_backface_culling = False
        semantics[material.name] = image_alpha_mode(material_image(material))
    return semantics


def patch_glb_wing_materials(path: str, semantics: dict[str, str]) -> None:
    """Force exact glTF flags that Blender 4.5 cannot express for MASK cleanly."""
    if not semantics:
        return
    output_path = Path(path)
    data = output_path.read_bytes()
    if data[:4] != b"glTF":
        raise RuntimeError(f"expected GLB output at {output_path}")

    chunks: list[tuple[int, bytes]] = []
    cursor = 12
    while cursor < len(data):
        length, chunk_type = struct.unpack_from("<II", data, cursor)
        cursor += 8
        chunks.append((chunk_type, data[cursor : cursor + length]))
        cursor += length

    rebuilt: list[tuple[int, bytes]] = []
    matched: set[str] = set()
    for chunk_type, payload in chunks:
        if chunk_type != 0x4E4F534A:
            rebuilt.append((chunk_type, payload))
            continue
        document = json.loads(payload.decode("utf-8"))
        for material in document.get("materials", []):
            exported_name = material.get("name", "")
            source_name = next(
                (
                    name
                    for name in semantics
                    if exported_name.casefold().startswith(name.casefold())
                ),
                None,
            )
            if source_name is None:
                continue
            matched.add(source_name)
            material["doubleSided"] = True
            alpha_mode = semantics[source_name]
            material["alphaMode"] = alpha_mode
            if alpha_mode == "MASK":
                material["alphaCutoff"] = 0.5
            else:
                material.pop("alphaCutoff", None)
        encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
        encoded += b" " * ((-len(encoded)) % 4)
        rebuilt.append((chunk_type, encoded))

    missing = set(semantics).difference(matched)
    if missing:
        raise RuntimeError(f"exported GLB lacks wing material(s): {sorted(missing)}")
    output = bytearray(b"glTF" + struct.pack("<II", 2, 0))
    for chunk_type, payload in rebuilt:
        output.extend(struct.pack("<II", len(payload), chunk_type))
        output.extend(payload)
    struct.pack_into("<I", output, 8, len(output))
    output_path.write_bytes(output)


def reveal_wings() -> None:
    material = bpy.data.materials.get("tex_DC38D248")
    if material is None:
        material = bpy.data.materials.get("wing_magenta_key")
    if material is None:
        raise RuntimeError(
            "--show-wings requested but neither the native DC38D248 wing material "
            "nor the legacy debug material is present"
        )
    material.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None:
            size = 64
            node.image.scale(size, size)
            pixels: list[float] = []
            for y in range(size):
                for x in range(size):
                    checker = ((x // 8) + (y // 8)) % 2
                    color = (0.05, 0.75, 1.0) if checker else (1.0, 0.8, 0.05)
                    if x < 2 or y < 2:
                        color = (1.0, 0.05, 0.05)
                    elif x >= size - 2 or y >= size - 2:
                        color = (0.05, 1.0, 0.1)
                    elif abs(x - y) < 2:
                        color = (1.0, 1.0, 1.0)
                    pixels.extend((*color, 1.0))
            node.image.pixels = pixels
            node.image.update()


def bake_pose(armature: bpy.types.Object) -> list[bpy.types.Object]:
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    baked: list[bpy.types.Object] = []
    for obj in meshes:
        armature_modifiers = [mod for mod in obj.modifiers if mod.type == "ARMATURE"]
        if not armature_modifiers:
            continue
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        for modifier in armature_modifiers:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        matrix_world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = matrix_world
        baked.append(obj)
        obj.select_set(False)

    for obj in list(bpy.context.scene.objects):
        if obj not in baked:
            bpy.data.objects.remove(obj, do_unlink=True)
    return baked


def export_glb(path: str, objects: list[bpy.types.Object]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wing_semantics = configure_wing_materials(objects)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.gltf(
        filepath=os.path.abspath(path),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
    )
    patch_glb_wing_materials(path, wing_semantics)


def main() -> None:
    args = parse_args()
    clear_scene()
    with tempfile.TemporaryDirectory(prefix="spidey-tpose-") as temporary_root:
        import_path = blender_compatible_glb(os.path.abspath(args.input), temporary_root)
        bpy.ops.import_scene.gltf(filepath=import_path)
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(f"expected one armature, found {len(armatures)}")
    if args.show_wings:
        reveal_wings()
    pose_arms(armatures[0])
    meshes = bake_pose(armatures[0])
    if not meshes:
        raise RuntimeError("no skinned meshes were available to bake")
    export_glb(args.output, meshes)
    print(f"wrote static T-pose proof GLB: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
