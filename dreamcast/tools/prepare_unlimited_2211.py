"""Prepare Unlimited 2211's helmet and rigid back attachments for native limits."""
import argparse
import json
import sys
from pathlib import Path
import bpy
import bmesh

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fbx', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
out = Path(args.output).resolve()
if out.exists():
    raise ValueError('Use a fresh output directory')
out.mkdir(parents=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=args.fbx)
obj = next(o for o in bpy.data.objects if o.type == 'MESH')
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
adj = [set() for _ in obj.data.vertices]
for edge in obj.data.edges:
    a, b = edge.vertices
    adj[a].add(b)
    adj[b].add(a)
seen, components = set(), []
for i in range(len(adj)):
    if i in seen:
        continue
    stack, component = [i], []
    seen.add(i)
    while stack:
        j = stack.pop()
        component.append(j)
        for k in adj[j]:
            if k not in seen:
                seen.add(k)
                stack.append(k)
    components.append(component)
helmets = [c for c in components if len(c) == 325 and all(
    obj.vertex_groups[max(obj.data.vertices[i].groups, key=lambda g: g.weight).group].name == 'Clown001Head' for i in c)]
attachments = [c for c in components if len(c) in (7, 14, 28, 30) and
               min(obj.data.vertices[i].co.z for i in c) > 1.0]
assert len(helmets) == 1 and len(attachments) == 16, 'Review changed 2211 topology'
# Mechanical pieces remain rigid: lower pair follows the waist; upper pair the
# middle torso. Do not independently round near-tied skin weights at each vertex.
for c in attachments:
    joint = 'Clown001Spine1' if min(obj.data.vertices[i].co.z for i in c) < 1.15 else 'Clown001Spine2'
    for group in obj.vertex_groups:
        group.remove(c)
    obj.vertex_groups[joint].add(c, 1.0, 'REPLACE')
parts, removed, report = [], set(), []
for c in helmets + attachments:
    ids = set(c)
    mesh = obj.data.copy()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in ids], context='VERTS')
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
    bm.to_mesh(mesh)
    bm.free()
    part = bpy.data.objects.new('Native 2211 part', mesh)
    bpy.context.collection.objects.link(part)
    part.matrix_world = obj.matrix_world.copy()
    for group in obj.vertex_groups:
        part.vertex_groups.new(name=group.name)
    before = len(mesh.vertices)
    bpy.ops.object.select_all(action='DESELECT')
    part.select_set(True)
    bpy.context.view_layer.objects.active = part
    modifier = part.modifiers.new('Native vertex budget', 'DECIMATE')
    modifier.ratio = .55 if c in helmets else .75
    modifier.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    report.append({'kind': 'helmet' if c in helmets else 'attachment', 'before': before, 'after': len(part.data.vertices)})
    parts.append(part)
    removed.update(ids)
bm = bmesh.new()
bm.from_mesh(obj.data)
bm.verts.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index in removed], context='VERTS')
bm.to_mesh(obj.data)
bm.free()
bpy.ops.object.select_all(action='DESELECT')
for part in parts + [obj]:
    part.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.join()
arm.select_set(True)
bpy.ops.export_scene.fbx(filepath=str(out / '2211.fbx'), use_selection=True, add_leaf_bones=False, bake_anim=False)
(out / 'preparation.json').write_text(json.dumps({'source': args.fbx, 'parts': report, 'body': 'unchanged', 'attachments': 'rigid lower waist and upper middle-torso groups', 'requiredPackingOption': '--opaque-diffuse'}, indent=2))
print(report)
