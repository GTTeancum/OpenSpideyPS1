"""Exercise import/export against all bundled actor templates, in background Blender."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import zipfile

import bpy

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--census', type=Path, required=True)
p.add_argument('--report', type=Path, required=True)
p.add_argument('--python', required=True)
p.add_argument('--multitool', required=True)
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
sys.path.insert(0, str(a.repo/'tools'))
import blender_spidey as addon

results = []
with zipfile.ZipFile(a.repo/'spiderman/port/bundled/runtime-assets.zip') as archive:
    for row in json.loads(a.census.read_text()):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        with tempfile.TemporaryDirectory(prefix='spidey-template-test-') as td:
            folder = Path(td)
            path = folder/row['name']
            path.write_bytes(archive.read(row['name']))
            try:
                template, rig = addon.import_template(path, a.multitool)
                target = template.copy()
                target.data = template.data.copy()
                target.name = 'Editable replacement'
                del target['spidey_template']
                bpy.context.collection.objects.link(target)
                # Atlas baking is intentionally separate from template geometry
                # round-trip coverage; every polygon receives a known triangle.
                uv = target.data.uv_layers.active.data
                for polygon in target.data.polygons:
                    for loop, coord in zip(polygon.loop_indices, [(0,0),(1,0),(0,1)]):
                        uv[loop].uv = coord
                image = bpy.data.images.new('Test atlas', 64, 64)
                image.generated_color = (.5,.5,.5,1)
                report = addon.export_actor(template, target, image, folder/'export', a.repo,
                                            a.python, a.multitool)
                results.append(dict(name=row['name'], **report))
                # Report's status describes visual acceptance separately.
                results[-1]['status'] = 'structural-pass'
                print('TEMPLATE_PASS',row['name'],report['exportedMeshRecords'],flush=True)
            except Exception as error:
                results.append(dict(name=row['name'],status='failed',error=str(error)))
                print('TEMPLATE_FAIL',row['name'],str(error),flush=True)
            a.report.write_text(json.dumps(results,indent=2))
assert all(r['status']=='structural-pass' for r in results), 'See template test report'
