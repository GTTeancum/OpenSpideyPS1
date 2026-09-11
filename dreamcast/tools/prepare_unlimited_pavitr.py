"""Create coherent native joint boundaries for Unlimited Pavitr's loose clothing."""
import argparse,json,sys,shutil
from pathlib import Path
import bpy
p=argparse.ArgumentParser();p.add_argument('--fbx',required=True);p.add_argument('--output',required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(a.output).resolve()
if out.exists():raise ValueError('Use a fresh output directory')
out.mkdir(parents=True)
bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.fbx(filepath=a.fbx)
o=next(o for o in bpy.data.objects if o.type=='MESH');arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
assert len(o.data.vertices)==2034,'Review changed India source mesh'
owners={};counts={'legs':0,'shoulders':0}
for v in o.data.vertices:
 w={o.vertex_groups[g.group].name.removeprefix('Clown001'):g.weight for g in v.groups if g.weight>0}
 # Preserve the fitted position and UVs; only replace the final native owner.
 # A level knee boundary avoids alternating rigid bones through deep folds.
 if .32<v.co.z<.78 and sum(x for n,x in w.items() if 'Leg' in n)>.8:
  side='L' if v.co.x>0 else 'R';knee=arm.data.bones['Clown001'+side+'Leg2'].head_local.z
  owners[v.index]=(16 if side=='L' else 13) if v.co.z>=knee else (15 if side=='L' else 12)
  counts['legs']+=1
 if v.co.z>1.25 and .14<abs(v.co.x)<.29 and any('Arm1' in n or 'Collarbone' in n for n in w):
  # An oblique plane perpendicular to the sloping arm incorrectly includes
  # lower chest vertices. Keep the chest inside the lateral shoulder boundary.
  side='L' if v.co.x>0 else 'R'
  owners[v.index]=(4 if side=='L' else 9) if abs(v.co.x)>=.205 else 1
  counts['shoulders']+=1
shutil.copy2(a.fbx,out/'india.fbx')
(out/'native-owners.json').write_text(json.dumps({'sourceVertexCount':len(o.data.vertices),'owners':owners,'regionCounts':counts,'fitFootSoles':True,'proportionalFeet':True,'relaxedShoulders':True,'policy':'anatomical knee and shoulder boundaries; fit soles to donor ground plane; shorten shoes and restore instep/arch'},indent=2))
print(counts)
