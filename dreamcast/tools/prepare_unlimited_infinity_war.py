# Character-specific preparation: preserve body topology, reduce the four rigid
# mechanical arms to the native torso budget, omit layered light/glow decals.
import bpy,bmesh,json,argparse,sys
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--fbx',required=True);parser.add_argument('--output',required=True);parser.add_argument('--arm-vertices',type=int,default=22)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
out=Path(args.output).resolve()
if out.exists():raise ValueError('Use a fresh output directory; source files are never overwritten')
if not 4<=args.arm_vertices<=256:raise ValueError('Arm vertex target must be 4..256')
out.mkdir(parents=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=args.fbx)
o=next(o for o in bpy.data.objects if o.type=='MESH');arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
adj=[set() for v in o.data.vertices]
for e in o.data.edges:a,b=e.vertices;adj[a].add(b);adj[b].add(a)
seen=set();components=[]
for v in range(len(adj)):
 if v in seen:continue
 stack=[v];seen.add(v);c=[]
 while stack:
  i=stack.pop();c.append(i)
  for j in adj[i]:
   if j not in seen:seen.add(j);stack.append(j)
 components.append(c)
rigid=[c for c in components if all(all(o.vertex_groups[g.group].name=='Clown001Spine3' for g in o.data.vertices[i].groups if g.weight>0) for i in c)]
claws=[c for c in rigid if len(c)>100]
assert len(claws)==4, 'Expected exactly four rigid mechanical arms'
parts=[];counts=[]
for n,c in enumerate(claws):
 ids=set(c);m=o.data.copy();bm=bmesh.new();bm.from_mesh(m);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.index not in ids],context='VERTS');bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=0.00001);bm.to_mesh(m);bm.free()
 p=bpy.data.objects.new('Static claw '+str(n+1),m);bpy.context.collection.objects.link(p);p.matrix_world=o.matrix_world.copy();bpy.context.view_layer.objects.active=p;p.select_set(True);o.select_set(False);arm.select_set(False)
 # Collapse only this disconnected rigid accessory. UVs remain on face corners.
 mod=p.modifiers.new('Native torso budget','DECIMATE');mod.ratio=max(.01,(2*args.arm_vertices-4)/max(1,len(m.polygons)));mod.use_collapse_triangulate=True
 bpy.ops.object.modifier_apply(modifier=mod.name)
 g=p.vertex_groups.new(name='Clown001Spine3');g.add(list(range(len(p.data.vertices))),1,'REPLACE')
 counts.append(len(p.data.vertices));parts.append(p);p.select_set(False)
# Keep the original body, hands, and face. The second material is a separate
# transparent light-card effect; its eyes already exist in the body diffuse.
remove=set(i for c in rigid for i in c)
bm=bmesh.new();bm.from_mesh(o.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.index in remove],context='VERTS');bmesh.ops.delete(bm,geom=[f for f in bm.faces if f.material_index==1],context='FACES');bm.to_mesh(o.data);bm.free()
bpy.context.view_layer.objects.active=o;o.select_set(True)
for p in parts:p.select_set(True)
bpy.ops.object.join();arm.select_set(True)
bpy.ops.export_scene.fbx(filepath=str(out/'InfinityWar.fbx'),use_selection=True,add_leaf_bones=False,bake_anim=False,path_mode='AUTO')
(out/'preparation.json').write_text(json.dumps({'source':args.fbx,'staticArms':4,'armVertices':counts,'bodyTopology':'retained','omitted':'layered back decals and transparent light cards'},indent=2))
print('STATIC ARMS',counts)
