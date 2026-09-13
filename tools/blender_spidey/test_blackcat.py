"""Blender background integration test. Source collection stays outside the repository."""
import argparse
import json
from pathlib import Path
import sys
import math
import zipfile

import bpy
from mathutils import Vector, Matrix, Quaternion

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--collection', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--python', required=True)
p.add_argument('--multitool', required=True)
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
a.output.mkdir(parents=True, exist_ok=True)
if not (a.output/'blackcat.psx').exists():
    with zipfile.ZipFile(a.repo/'spiderman/port/bundled/runtime-assets.zip') as archive:
        (a.output/'blackcat.psx').write_bytes(archive.read('blackcat.psx'))
sys.path.insert(0, str(a.repo / 'tools'))
import blender_spidey as addon

bpy.ops.wm.read_factory_settings(use_empty=True)
addon.register()
template, rig = addon.import_template(a.output / 'blackcat.psx', a.multitool)
dump = json.loads(template['spidey_dump'])
# Spread the template arms and legs before transfer, just as an artist would.
# Otherwise the donor's fingers touch its thighs and nearest-surface transfer
# cannot distinguish a glove from a trouser leg.
for index, angle in [(8,-70),(11,70),(4,-12),(1,12)]:
    bone = rig.pose.bones[addon.bone_name(index)]
    bone.rotation_mode = 'QUATERNION'
    axis = bone.bone.matrix_local.to_3x3().inverted() @ Vector((0,1,0))
    bone.rotation_quaternion = Quaternion(axis, math.radians(angle))
bpy.context.view_layer.update()
target = {i: rig.matrix_world @ rig.pose.bones[addon.bone_name(i)].head
          for i in range(len(dump['Objects']))}
before = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=str(a.collection / 'costumes/blackcat/blackcat.fbx'))
new = set(bpy.data.objects)-before
body = next(o for o in new if o.type == 'MESH')
source_rig = next(o for o in new if o.type == 'ARMATURE')
source = {b.name: source_rig.matrix_world @ b.head_local for b in source_rig.data.bones}
# This fixture aligns the source rig's landmarks over the imported template.
# It replaces the artist's manual alignment step only; export weights below
# come from the add-on's nearest-surface transfer, not these source weights.
spec = {0: ('Pelvis', 'Spine2', 12), 12: ('Spine2', 'Head', 14),
        14: ('Head', None, None), 4: ('LLeg1', 'LLeg2', 5),
        5: ('LLeg2', 'LLegAnkle', 6), 6: ('LLegAnkle', None, None),
        1: ('RLeg1', 'RLeg2', 2), 2: ('RLeg2', 'RLegAnkle', 3),
        3: ('RLegAnkle', None, None), 8: ('LArm1', 'LArm2', 7),
        7: ('LArm2', 'LArmPalm', 9), 9: ('LArmPalm', None, None),
        11: ('RArm1', 'RArm2', 10), 10: ('RArm2', 'RArmPalm', 13),
        13: ('RArmPalm', None, None)}
scale = (target[14]-target[6]).length / (source['Clown001Head']-source['Clown001LLegAnkle']).length
transforms = {}
for i, (start, end, child) in spec.items():
    if end:
        s = source['Clown001'+end]-source['Clown001'+start]
        t = target[child]-target[i]
        axis = s.normalized()
        stretch = Matrix.Identity(3) + (t.length/s.length/scale-1)*Matrix([[axis[x]*axis[y] for y in range(3)] for x in range(3)])
        transforms[i] = (axis.rotation_difference(t.normalized()).to_matrix() @ stretch)*scale
    else:
        transforms[i] = Matrix.Identity(3)*scale
for hand, forearm in [(9, 7), (13, 10)]:
    transforms[hand] = transforms[forearm]

def part(name):
    n = name.removeprefix('Clown001')
    if n == 'Pelvis': return 0
    if n in ('Neck', 'Head'): return 14
    for side, thigh, shin, foot, upper, lower, hand in [('L',4,5,6,8,7,9),('R',1,2,3,11,10,13)]:
        if n == side+'Leg1': return thigh
        if n == side+'Leg2': return shin
        if n.startswith(side+'Leg'): return foot
        if n.startswith(side+'Arm1'): return upper
        if n.startswith(side+'Arm2'): return lower
        if n.startswith(side+'Arm') and 'Collarbone' not in n: return hand
    return 12

for v in body.data.vertices:
    point = body.matrix_world @ v.co
    value, total = Vector(), 0
    for g in v.groups:
        i = part(body.vertex_groups[g.group].name)
        value += (transforms[i] @ (point-source['Clown001'+spec[i][0]])+target[i])*g.weight
        total += g.weight
    v.co = value/total
body.matrix_world = Matrix.Identity(4)
body.modifiers.clear()
bpy.data.objects.remove(source_rig, do_unlink=True)
bpy.context.view_layer.update()
aligned = [body.matrix_world @ v.co for v in body.data.vertices]
addon.transfer_weights(template, body)
bpy.context.view_layer.update()
evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
alignment_error = max((body.matrix_world @ v.co - aligned[v.index]).length for v in evaluated.vertices)
body.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
assert alignment_error < 1e-4, f'Transfer changed the artist alignment: {alignment_error}'
image = bpy.data.images.load(str(a.collection / 'textures-png/BlackCat_D.png'))
mat = bpy.data.materials.new('Gameloft Black Cat diffuse')
mat.use_nodes = True
node = mat.node_tree.nodes.new('ShaderNodeTexImage')
node.image = image
mat.node_tree.links.new(node.outputs['Color'], mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
body.data.materials.clear()
body.data.materials.append(mat)
bpy.context.view_layer.objects.active = body
report = addon.export_actor(template, body, image, a.output/'export', a.repo, a.python, a.multitool)
assert report['hierarchyPreserved'] and max(report['partVertices']) <= 256
report['alignmentRoundTripMaxError'] = alignment_error
(a.output/'integration-report.json').write_text(json.dumps(report,indent=2))
template.hide_render = True
template.hide_set(True)
image.pack()
bpy.ops.wm.save_as_mainfile(filepath=str(a.output/'blackcat-authoring.blend'))
print('BLACKCAT_ADDON_PASS', json.dumps(report))
addon.unregister()
