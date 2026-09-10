"""Experimental FBX-to-native fitting; run with Blender in background mode."""
import bpy,json,sys,math,argparse
from pathlib import Path
from mathutils import Vector,Matrix,Quaternion
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--preview',action='store_true')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
P=args.output.resolve();source=args.source.resolve()
bpy.ops.wm.read_factory_settings(use_empty=True)
fbxs=list(source.glob('*.fbx'))
if len(fbxs)!=1:raise ValueError('Expected one FBX in the source directory')
bpy.ops.import_scene.fbx(filepath=str(fbxs[0]))
bpy.context.view_layer.update()
meshes=[x for x in bpy.data.objects if x.type=='MESH'];arms=[x for x in bpy.data.objects if x.type=='ARMATURE']
if len(meshes)!=1 or len(arms)!=1:raise ValueError('This prototype requires one mesh and one armature')
o=meshes[0];arm=arms[0]
src={b.name.split('Clown001')[-1]:arm.matrix_world@b.head_local for b in arm.data.bones if 'Clown001' in b.name}
donor=json.loads((P/'donor-dump.json').read_text())
tgt={b['ObjectIndex']:Vector(tuple(b['Position'].values()))*36 for b in donor['Objects']}
# Native mesh order differs from anatomical hierarchy order.
spec={0:('Spine1','Spine2',2),2:('Spine2','Spine3',1),1:('Spine3','Neck',7),7:('Head',None,None),4:('LArm1','LArm2',3),3:('LArm2','LArmPalm',5),5:('LArmPalm',None,None),9:('RArm1','RArm2',8),8:('RArm2','RArmPalm',10),10:('RArmPalm',None,None),16:('LLeg1','LLeg2',15),15:('LLeg2','LLegAnkle',17),17:('LLegAnkle',None,None),13:('RLeg1','RLeg2',12),12:('RLeg2','RLegAnkle',14),14:('RLegAnkle',None,None)}
# Normalize imported FBX axes and units from its anatomical landmarks.
def basis(left, up):
 x=left.normalized(); y=(up-x*up.dot(x)).normalized();z=x.cross(y)
 return Matrix((x,y,z)).transposed()
source_basis=basis(src['LArm1']-src['RArm1'],src['Head']-src['Spine1'])
target_basis=basis(tgt[4]-tgt[9],tgt[7]-tgt[0])
source_rotation=target_basis@source_basis.transposed()
src={name:source_rotation@p for name,p in src.items()}
scale=(tgt[7]-tgt[17]).length/(src['Head']-src['LLegAnkle']).length
trans={}
for i,(s,e,j) in spec.items():
 if e:
  a=src[e]-src[s]; b=tgt[j]-tgt[i]; r=a.normalized().rotation_difference(b.normalized()).to_matrix(); u=a.normalized(); stretch=Matrix.Identity(3)+(b.length/a.length/scale-1)*Matrix([[u[x]*u[y] for y in range(3)] for x in range(3)]); trans[i]=(r@stretch)*scale
 elif i in (5,10): trans[i]=trans[3 if i==5 else 8]
 else: trans[i]=Matrix.Identity(3)*scale

def group(n):
 n=n.split('Clown001')[-1]
 if n in ('Pelvis','Spine1'):return 0
 if n=='Spine2':return 2
 if n in ('Spine3','Ribcage') or 'Collarbone' in n:return 1
 if n in ('Head','Neck'):return 7
 for side,upper,lower,hand,thigh,shin,foot in [('L',4,3,5,16,15,17),('R',9,8,10,13,12,14)]:
  if n.startswith(side+'Arm1'):return upper
  if n.startswith(side+'Arm2'):return lower
  if n.startswith(side+'Arm'):return hand
  if n==side+'Leg1':return thigh
  if n==side+'Leg2':return shin
  if n.startswith(side+'Leg'):return foot
 raise ValueError(n)
# Pose the source's actual finger weights before collapsing to rigid native hands.
# Each hand gets aligned fingers, MCP/PIP flexion, and a thumb across the outside.
finger_pose={}
for side in ('L','R'):
 wrist=src[side+'ArmPalm']; knuckles=[src[side+'ArmDigit'+d+'1'] for d in ('2','3','5')]
 middle=sum(knuckles,Vector())/3
 forward=(middle-wrist).normalized();across=(knuckles[0]-knuckles[2]).normalized()
 palm=forward.cross(across).normalized()
 if palm.dot(Vector((-1 if side=='L' else 1,0,0)))<0:palm=-palm
 axis=forward.cross(palm).normalized()
 for digit in ('2','3','5'):
  name=side+'ArmDigit'+digit; b=src[name+'1'];c=src[name+'2']
  align=(c-b).normalized().rotation_difference(forward)
  first=(Quaternion(axis,math.radians(78))@align).to_matrix()*.82
  second=Quaternion(axis,math.radians(145)).to_matrix()
  finger_pose[name+'1']=(b,b,first)
  finger_pose[name+'2']=(c,b+first@(c-b),second@first)
 # The thumb lies across the curled fingers instead of inside the palm.
 name=side+'ArmDigit0';b=src[name+'1'];c=src[name+'2']
 length=(src[side+'ArmDigit32']-src[side+'ArmDigit31']).length
 target=(knuckles[0]+knuckles[1])/2+palm*length*.6+forward*length*.15
 first=(c-b).normalized().rotation_difference((target-b).normalized())
 posed_c=b+first@(c-b)
 direction=(-across+forward*1.5).normalized()
 second=(c-b).normalized().rotation_difference(direction)
 finger_pose[name+'1']=(b,b,first);finger_pose[name+'2']=(c,posed_c,second)
vertices=[];weights=[];owners=[]
for v in o.data.vertices:
 w={}
 for g in v.groups:
  if g.weight<=0:continue
  i=group(o.vertex_groups[g.group].name);w[i]=w.get(i,0)+g.weight
 total=sum(w.values());w={i:a/total for i,a in w.items()};original=source_rotation@(o.matrix_world@v.co)
 p=Vector()
 for g in v.groups:
  name=o.vertex_groups[g.group].name.split('Clown001')[-1]
  if name in finger_pose:
   origin,destination,rotation=finger_pose[name];point=destination+rotation@(original-origin)
  else:point=original
  p+=point*(g.weight/total)
 fitted=sum(( (trans[i]@(p-src[spec[i][0]])+tgt[i])*a for i,a in w.items()),Vector())
 vertices.append(list(fitted));weights.append(w);owners.append(max(w,key=w.get))
# Relax only finger-weighted vertices after posing to round low-poly joint corners.
# Topology and UVs stay fixed; wrist and body vertices are pinned.
# Native UVs live on face corners: weld FBX UV-split duplicates without losing UV seams.
canonical={};aliases=[];representatives=[]
for v,point in enumerate(vertices):
 key=(tuple(round(x,5) for x in point),tuple(sorted((i,round(w,6)) for i,w in weights[v].items())))
 if key not in canonical:canonical[key]=len(representatives);representatives.append(v)
 aliases.append(canonical[key])
vertices=[vertices[i] for i in representatives];weights=[weights[i] for i in representatives];owners=[owners[i] for i in representatives]
adj=[set() for _ in vertices]
for edge in o.data.edges:
 a,b=(aliases[v] for v in edge.vertices)
 if a!=b:adj[a].add(b);adj[b].add(a)
strength=[sum(g.weight for g in v.groups if 'ArmDigit' in o.vertex_groups[g.group].name) for v in (o.data.vertices[i] for i in representatives)]
for _ in range(4):
 previous=[Vector(p) for p in vertices]
 for i,neighbors in enumerate(adj):
  if strength[i] and neighbors:
   mean=sum((previous[j] for j in neighbors),Vector())/len(neighbors)
   vertices[i]=list(previous[i].lerp(mean,.3*strength[i]))
o.data.calc_loop_triangles();uv=o.data.uv_layers.active.data
faces=[{'v':[aliases[v] for v in t.vertices],'uv':[list(uv[l].uv) for l in t.loops]} for t in o.data.loop_triangles]
for f in faces:
 scores={i:sum(weights[v].get(i,0) for v in f['v']) for i in spec};f['mesh']=max(scores,key=scores.get)
report={'vertices':vertices,'owners':owners,'faces':faces,'offsets':{str(i):list(p) for i,p in tgt.items()},'sourceTriangles':len(faces),'sourceVertices':len(vertices),'handPose':'closed fingers and fists in both native hand variants','policy':'blended bind-pose fitting, dominant native bone, shared cross-part attachment vertices'}
report['dominantSourceGroups']=[o.vertex_groups[max(v.groups,key=lambda g:g.weight).group].name for v in (o.data.vertices[i] for i in representatives)]
(P/'fitted.json').write_text(json.dumps(report))
print('PARTS',[(i,sum(x==i for x in owners),len(set(v for f in faces if f['mesh']==i for v in f['v'])|set(v for v,x in enumerate(owners) if x==i))) for i in spec])
if not args.preview:sys.exit(0)
# Real source texture, no generated artwork. Keep full-resolution diffuse for review.
for x in list(bpy.data.objects):bpy.data.objects.remove(x,do_unlink=True)
mesh=bpy.data.meshes.new('LastStand fitted');mesh.from_pydata([(p[0]/36,p[2]/36,-p[1]/36) for p in vertices],[],[f['v'] for f in faces]);mesh.update()
obj=bpy.data.objects.new('LastStand fitted',mesh);bpy.context.collection.objects.link(obj)
uvlayer=mesh.uv_layers.new()
for poly,f in zip(mesh.polygons,faces):
 for l,u in zip(poly.loop_indices,f['uv']):uvlayer.data[l].uv=u
mat=bpy.data.materials.new('LastStand diffuse');mat.use_nodes=True
img=bpy.data.images.load(str(next(source.glob('*_D_rgb.tga'))));img.pack()
tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=img
bs=mat.node_tree.nodes.get('Principled BSDF');mat.node_tree.links.new(tex.outputs['Color'],bs.inputs['Base Color']);bs.inputs['Roughness'].default_value=.8
mesh.materials.append(mat)
for f in mesh.polygons:f.use_smooth=True
bpy.ops.object.camera_add(location=(115,-170,55));cam=bpy.context.object;target=Vector((0,0,2));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=115;bpy.context.scene.camera=cam
for loc,power,size in [((70,-100,100),160000,90),((-70,-20,20),70000,70),((0,70,60),100000,70)]:
 bpy.ops.object.light_add(type='AREA',location=loc);light=bpy.context.object;light.data.energy=power;light.data.shape='DISK';light.data.size=size;light.rotation_euler=(target-light.location).to_track_quat('-Z','Y').to_euler()
s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.samples=24;s.render.resolution_x=650;s.render.resolution_y=750;s.render.resolution_percentage=100;s.world=bpy.data.worlds.new('World');s.world.color=(.15,.15,.15);s.view_settings.view_transform='Standard';s.render.filepath=str((P/'fitted-preview.png').resolve())
bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str((P/'fitted.blend').resolve()));bpy.ops.render.render(write_still=True)
