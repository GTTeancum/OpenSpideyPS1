"""Prepare selected Unlimited roster meshes for native part budgets; Blender only."""
import bpy, bmesh, json, argparse, sys, math
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--fbx', required=True)
p.add_argument('--output', required=True)
p.add_argument('--head-ratio', type=float, default=0.45)
p.add_argument('--torso-ratio', type=float, default=1.0)
p.add_argument('--head-min', type=int, default=80)
p.add_argument('--torso-min', type=int, default=70)
p.add_argument('--amazing-cape', action='store_true')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
if not (0 < a.head_ratio <= 1 and 0 < a.torso_ratio <= 1):
    raise ValueError('Reduction ratios must be in (0, 1]')
out = Path(a.output)
out.mkdir(parents=True, exist_ok=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=a.fbx)
meshes = [x for x in bpy.data.objects if x.type == 'MESH']
armatures = [x for x in bpy.data.objects if x.type == 'ARMATURE']
if len(meshes) != 1 or len(armatures) != 1:
    raise ValueError('Expected one Clown001 mesh and armature')
o, arm = meshes[0], armatures[0]
wrapped_uv_loops = 0
if a.amazing_cape:
    # Gameloft repeats the atlas for the inner cape and cuffs. Native UV bytes
    # address one texture page, so translate each repeated polygon as a unit.
    uv = o.data.uv_layers.active.data
    for polygon in o.data.polygons:
        for axis in (0, 1):
            values = [uv[i].uv[axis] for i in polygon.loop_indices]
            offset = math.floor(min(values))
            if offset:
                if max(values) - offset > 1.000001:
                    raise ValueError('UV polygon crosses a tile boundary; needs splitting')
                for i in polygon.loop_indices:
                    uv[i].uv[axis] -= offset
                    wrapped_uv_loops += 1
adj = [set() for v in o.data.vertices]
for e in o.data.edges:
    i, j = e.vertices
    adj[i].add(j)
    adj[j].add(i)
seen = set()
selections = []
cape_report = []
for i in range(len(adj)):
    if i in seen:
        continue
    stack = [i]
    seen.add(i)
    ids = []
    while stack:
        j = stack.pop()
        ids.append(j)
        for k in adj[j]:
            if k not in seen:
                seen.add(k)
                stack.append(k)
    # Source-specific cape shells: keep their topology and move arm influence
    # onto the upper spine so crouching shoulders do not pull through the cloth.
    is_cape = a.amazing_cape and min((o.data.vertices[j].co.y for j in ids)) > 0.08 and (max((o.data.vertices[j].co.z for j in ids)) < 0.58) and (len(ids) in (110, 107, 4))
    if is_cape:
        for j in ids:
            v = o.data.vertices[j]
            moved = 0.0
            for g in list(v.groups):
                if 'Arm' in o.vertex_groups[g.group].name:
                    moved += g.weight
                    o.vertex_groups[g.group].remove([j])
            if moved:
                o.vertex_groups['Clown001Spine3'].add([j], moved, 'ADD')
            v.co.y += 0.025
            # Separate inside/outside shells before fitting to avoid overlap.
            v.co += v.normal * 0.004
        cape_report.append(dict(vertices=len(ids), rearOffset=0.025, surfaceOffset=0.004))
    names = [o.vertex_groups[max(o.data.vertices[j].groups, key=lambda g: g.weight).group].name for j in ids]
    head = sum((n.endswith(('Head', 'Neck')) for n in names)) / len(ids)
    torso = sum((any((s in n for s in ('Spine', 'Pelvis', 'Ribcage', 'Collarbone'))) for n in names)) / len(ids)
    ratio = a.head_ratio if head > 0.5 and len(ids) > a.head_min else a.torso_ratio if torso > 0.6 and len(ids) > a.torso_min else 1.0
    if is_cape:
        # Preserve the matching inner and outer cape topology.
        ratio = 1.0
    if ratio < 1:
        selections.append((set(ids), ratio, 'head' if head > 0.5 else 'torso'))
if a.amazing_cape and not cape_report:
    raise ValueError('The Amazing Spider cape shells were not found')
parts = []
report = []
for ids, ratio, label in selections:
    m = o.data.copy()
    bm = bmesh.new()
    bm.from_mesh(m)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in ids], context='VERTS')
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-06)
    bm.to_mesh(m)
    bm.free()
    part = bpy.data.objects.new('Prepared ' + label, m)
    bpy.context.collection.objects.link(part)
    part.matrix_world = o.matrix_world.copy()
    for g in o.vertex_groups:
        part.vertex_groups.new(name=g.name)
    bpy.ops.object.select_all(action='DESELECT')
    part.select_set(True)
    bpy.context.view_layer.objects.active = part
    before = len(m.vertices)
    mod = part.modifiers.new('Native part budget', 'DECIMATE')
    mod.ratio = ratio
    mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    report.append(dict(region=label, sourceVertices=len(ids), weldedBefore=before, after=len(part.data.vertices), ratio=ratio))
    parts.append(part)
remove = set().union(*(ids for ids, _, _ in selections))
bm = bmesh.new()
bm.from_mesh(o.data)
bm.verts.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index in remove], context='VERTS')
bm.to_mesh(o.data)
bm.free()
bpy.ops.object.select_all(action='DESELECT')
o.select_set(True)
for part in parts:
    part.select_set(True)
bpy.context.view_layer.objects.active = o
bpy.ops.object.join()
arm.select_set(True)
bpy.ops.export_scene.fbx(filepath=str(out / 'prepared.fbx'), use_selection=True, add_leaf_bones=False, bake_anim=False)
(out / 'preparation.json').write_text(json.dumps(dict(regions=report, cape=cape_report, wrappedUvLoops=wrapped_uv_loops), indent=2))
print(report)
