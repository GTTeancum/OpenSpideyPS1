"""Reduce Noir's head surface to the native vertex budget."""
import bpy,bmesh,json,argparse,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--fbx',required=True);p.add_argument('--output',required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(a.output).resolve()
if out.exists():raise ValueError('Use a fresh output directory')
out.mkdir(parents=True)
bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.fbx(filepath=a.fbx)
o=next(o for o in bpy.data.objects if o.type=='MESH');arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
adj=[set() for v in o.data.vertices]
for e in o.data.edges:i,j=e.vertices;adj[i].add(j);adj[j].add(i)
seen=set();components=[]
for i in range(len(adj)):
 if i in seen:continue
 stack=[i];seen.add(i);component=[]
 while stack:
  j=stack.pop();component.append(j)
  for k in adj[j]:
   if k not in seen:seen.add(k);stack.append(k)
 components.append(component)
heads=[c for c in components if len(c)>80 and sum(o.vertex_groups[max(o.data.vertices[i].groups,key=lambda g:g.weight).group].name in ('Clown001Head','Clown001Neck') for i in c)>len(c)*.8]
assert len(heads)==1 and len(heads[0])==371,'Expected original Noir head/collar surface; review other variants'
ids=set(heads[0]);m=o.data.copy();bm=bmesh.new();bm.from_mesh(m);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.index not in ids],context='VERTS');bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.000001)
bm.to_mesh(m);bm.free()
head=bpy.data.objects.new('Native head',m);bpy.context.collection.objects.link(head);head.matrix_world=o.matrix_world.copy()
for group in o.vertex_groups:head.vertex_groups.new(name=group.name)
bpy.ops.object.select_all(action='DESELECT');head.select_set(True);bpy.context.view_layer.objects.active=head
before=len(m.vertices);mod=head.modifiers.new('Native head budget','DECIMATE');mod.ratio=.60;mod.use_collapse_triangulate=True;bpy.ops.object.modifier_apply(modifier=mod.name)
after=len(head.data.vertices)
bm=bmesh.new();bm.from_mesh(o.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.index in ids],context='VERTS');bm.to_mesh(o.data);bm.free()
o.select_set(True);bpy.context.view_layer.objects.active=o;bpy.ops.object.join();arm.select_set(True)
bpy.ops.export_scene.fbx(filepath=str(out/'Noir.fbx'),use_selection=True,add_leaf_bones=False,bake_anim=False)
(out/'preparation.json').write_text(json.dumps({'source':a.fbx,'headSurfaceVerticesBefore':before,'headSurfaceVerticesAfter':after,'body':'original topology and weights retained','head':'reduced connected head and collar surface; detached accessory retained','requiredPackingOption':'--opaque-diffuse'},indent=2))
print('HEAD',before,'->',after)
