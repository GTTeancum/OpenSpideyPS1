#!/usr/bin/env python3
"""Export the original DC model's UV layouts with Blender, then stamp using Sharp.

No UV decoding, unwrapping, edge detection, or coordinate adjustment is done here.
Blender owns the GLB import and UV Layout SVG export; Sharp rasterizes that SVG.
Requires Blender, Node.js and Sharp (NODE_EXE / SHARP_MODULE may select installs).
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def blender_export(source, mod):
    import bpy
    import addon_utils

    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable('io_mesh_uv_layout', default_set=False)
    bpy.ops.import_scene.gltf(filepath=str(source.resolve()))
    meshes = [o for o in bpy.context.scene.objects
              if o.type == 'MESH' and o.data.uv_layers.active and o.data.materials]
    if not meshes:
        raise ValueError('Original DC GLB has no UV-mapped meshes')
    output = mod / 'TEMPLATE' / 'UV'
    output.mkdir(parents=True, exist_ok=True)
    for texture in sorted((mod / 'textures').glob('*.png')):
        material_name = 'tex_' + texture.stem
        image = bpy.data.images.load(str(texture.resolve()), check_existing=True)
        size = tuple(image.size)
        bpy.ops.object.select_all(action='DESELECT')
        count = 0
        for obj in meshes:
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            for face in obj.data.polygons:
                material = obj.data.materials[face.material_index]
                face.select = material is not None and material.name == material_name
                count += face.select
        if not count:
            raise ValueError(f'No source faces for {material_name}')
        # Export selected material faces at the EXACT paint texture dimensions.
        # PNG export needs an interactive GPU context; SVG works headlessly.
        bpy.ops.uv.export_layout(filepath=str((output / (texture.stem + '.svg')).resolve()),
                                 mode='SVG', size=size, opacity=0,
                                 export_all=False, export_tiles='NONE', modified=False)
        print(f'Blender UV Layout: {texture.stem}, {count} faces, {size}', flush=True)


def build_templates(mod, source=None, blender=None, node=None, sharp=None):
    source = source or ROOT / 'dreamcast/decoded/meshes/SPIDEY.glb'
    blender = (blender or os.environ.get('BLENDER') or shutil.which('blender')
               or 'C:/Program Files/Blender Foundation/Blender 4.5/blender.exe')
    node = node or os.environ.get('NODE_EXE') or shutil.which('node')
    sharp = sharp or os.environ.get('SHARP_MODULE') or 'sharp'
    if not node:
        raise FileNotFoundError('Node.js required; set NODE_EXE or pass --node')
    sources = sorted((mod / 'textures').glob('*.png'))
    if not source.is_file() or not sources:
        raise FileNotFoundError('Original DC SPIDEY.glb and mod textures are required')
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    subprocess.run([str(blender), '--background', '--factory-startup', '--python-exit-code', '1',
                    '--python', str(Path(__file__).resolve()), '--', '--blender-worker',
                    '--source', str(source.resolve()), '--mod', str(mod.resolve())], check=True)
    subprocess.run([str(node), str(Path(__file__).with_name('stamp_reskin_uv_templates.cjs')),
                    str(mod.resolve()), str(sharp)], check=True)
    if before != {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}:
        raise AssertionError('Playable textures changed')
    print(f'{mod / "TEMPLATE"}: {len(sources)} Blender guides; playable textures unchanged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT / 'dreamcast/decoded/meshes/SPIDEY.glb')
    parser.add_argument('--mod', type=Path, default=ROOT / 'mods/samples/magenta-man')
    parser.add_argument('--blender')
    parser.add_argument('--node')
    parser.add_argument('--sharp')
    parser.add_argument('--blender-worker', action='store_true', help=argparse.SUPPRESS)
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    if args.blender_worker:
        blender_export(args.source, args.mod)
    else:
        build_templates(args.mod, args.source, args.blender, args.node, args.sharp)
