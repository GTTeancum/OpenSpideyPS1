"""Temporary L1A1 replacement set: Black Cat geometry on each native actor rig.

Run with background Blender. This fixture maps the reviewed Black Cat weights
to the opening level's humanoid rigs; it is not a general auto-retargeter.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile
import bpy
from mathutils import Vector

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--authoring', type=Path, required=True)
p.add_argument('--blackcat-assets', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--python', required=True)
p.add_argument('--multitool', required=True)
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
sys.path.insert(0, str(a.repo/'tools'))
import blender_spidey as addon

a.output.mkdir(parents=True, exist_ok=False)
shutil.copytree(a.blackcat_assets, a.output/'assets')
# Source Black Cat part -> target positional joint, not Objects[].MeshIndex.
maps = {
    'blackcat.psx': {i:i for i in range(18)},
    'spidey.psx': {0:0,1:13,2:12,3:14,4:16,5:15,6:17,7:3,8:4,
                  9:5,10:8,11:9,12:2,13:10,14:7,15:7,16:7,17:2},
    'henchman.psx': {0:0,1:4,2:5,3:6,4:1,5:2,6:3,7:7,8:8,
                    9:9,10:10,11:11,12:12,13:14,14:13,15:13,16:13,17:12},
}
reports = []
for filename, mapping in maps.items():
    bpy.ops.wm.open_mainfile(filepath=str(a.authoring))
    source = next(o for o in bpy.data.objects if o.get('spidey_template'))
    body = next(o for o in bpy.data.objects if o.type == 'MESH' and not o.get('spidey_template'))
    source_data = json.loads(source['spidey_dump'])
    names = [g.name for g in body.vertex_groups]
    weights = [{int(names[g.group][5:]): g.weight for g in v.groups if g.weight > 0}
               for v in body.data.vertices]
    with zipfile.ZipFile(a.repo/'spiderman/port/bundled/runtime-assets.zip') as archive:
        donor = a.output/filename
        donor.write_bytes(archive.read(filename))
    template, rig = addon.import_template(donor, a.multitool)
    dest = json.loads(template['spidey_dump'])
    origins = [addon.to_blender([x*source_data['ScaleDivisor'] for x in o['Position'].values()])
               for o in source_data['Objects']]
    targets = [addon.to_blender([x*dest['ScaleDivisor'] for x in o['Position'].values()])
               for o in dest['Objects']]
    scale = (targets[mapping[14]]-targets[mapping[6]]).length/(origins[14]-origins[6]).length
    body.modifiers.clear()
    body.vertex_groups.clear()
    for i in range(len(targets)):
        body.vertex_groups.new(name=addon.bone_name(i))
    for v, groups in zip(body.data.vertices, weights):
        total = sum(groups.values())
        v.co = sum((((v.co-origins[i])*scale+targets[mapping[i]])*w/total
                    for i,w in groups.items()), Vector())
        combined = {}
        for i,w in groups.items():
            combined[mapping[i]] = combined.get(mapping[i],0)+w/total
        for i,w in combined.items():
            body.vertex_groups[i].add([v.index],w,'REPLACE')
    image = next(n.image for s in body.material_slots for n in s.material.node_tree.nodes
                 if n.type == 'TEX_IMAGE' and n.image)
    report = addon.export_actor(template,body,image,a.output/filename.replace('.psx',''),
                                a.repo,a.python,a.multitool)
    exported = a.output/filename.replace('.psx','')/'assets'
    shutil.copytree(exported,a.output/'assets',dirs_exist_ok=True)
    reports.append(dict(actor=filename,mapping=mapping,**report))
    print('LEVEL_ACTOR_PASS',filename,report['exportedTriangles'],flush=True)
(a.output/'report.json').write_text(json.dumps(reports,indent=2))
