"""Experimental native actor writer; retains donor hierarchy/animations and support textures."""
import sys,struct,json,math,hashlib,argparse,zlib
from pathlib import Path
from collections import Counter
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'spiderman/tools'),str(ROOT/'dreamcast/tools')]
import port_dc_character as c
from pack_sm2_costume_to_dc import container_layout
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--id',default='unlimited-custom');parser.add_argument('--name',default='Unlimited Custom');parser.add_argument('--opaque-diffuse',action='store_true');parser.add_argument('--template-layout',action='store_true',help='Use donor mesh count without Spider-Man hand substitutions');parser.add_argument('--actor-file',default='spidey.psx');args=parser.parse_args()
TEX=64 if args.template_layout else 128
P=args.output.resolve();raw=(P/'donor.psx').read_bytes();layout=container_layout(raw);fit=json.loads((P/'fitted.json').read_text());verts=fit['vertices'];owner=fit['owners'];offsets=fit['offsets']
# Faces referencing another part are emitted after their attachment sources.
part_count=struct.unpack_from('<I',raw,8)[0] if args.template_layout else 18
faces=[[] for _ in range(part_count)]
for f in fit['faces']:faces[max(owner[v] for v in f['v'])].append(f)
indices=[sorted(set(v for f in faces[i] for v in f['v'])|{v for v,b in enumerate(owner) if b==i}) for i in range(part_count)]
if args.template_layout:
 # Native lighting reads its first normal before testing the loop count. An
 # empty joint still needs an inert vertex/normal pair; no faces are emitted.
 for i,ids in enumerate(indices):
  if not ids and str(i) not in fit.get('alternateParts',{}):
   ids.append(len(verts));verts.append(offsets[str(i)]);owner.append(i)
usedby={v:{i for i,ids in enumerate(indices) if v in ids} for v in range(len(verts))}
shared={v for v,s in usedby.items() if len(s)>1};references={};n=0
for i,ids in enumerate(indices):
 for v in ids:
  if owner[v]==i and v in shared:references[v]=n;n+=1
# Preserve smooth vertex normals through every repeated attachment record.
normals=[[0.,0.,0.] for _ in verts]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def norm(a):
 length=math.sqrt(sum(x*x for x in a));return [round(x/length*4096) for x in a] if length>1e-10 else [0,-4096,0]
def face_normal(f):
 a,b,d=[verts[v] for v in f['v']];return cross([b[j]-a[j] for j in range(3)],[d[j]-a[j] for j in range(3)])
for f in fit['faces']:
 a=face_normal(f)
 for v in f['v']:
  for j in range(3):normals[v][j]+=a[j]
out=bytearray(raw[:layout['meshPointerTable']+part_count*4] if args.template_layout else raw[:min(layout['meshPointers'])]); stats=[]
if args.template_layout:struct.pack_into('<I',out,layout['meshPointerTable']-4,part_count)
for i in range(part_count):
 actual=int(fit.get('alternateParts',{}).get(str(i),i)) if args.template_layout else {6:5,11:10}.get(i,i);ids=indices[actual];fs=faces[actual];assert len(ids)<=256,(i,len(ids));lookup={v:j for j,v in enumerate(ids)}
 struct.pack_into('<I',out,layout['meshPointerTable']+4*i,len(out))
 head=bytearray(raw[layout['meshPointers'][i]:layout['meshPointers'][i]+28]);struct.pack_into('<HHH',head,2,len(ids),len(ids)+len(fs),len(fs))
 if args.template_layout:struct.pack_into('<HH',head,24,32767,0xFFFF)
 # Conservative local bounds; copied donor LOD and flags remain intact.
 local=[[round(verts[v][j]-offsets[str(i)][j]) for j in range(3)] for v in ids if owner[v]==actual]
 radius=math.ceil(max((math.sqrt(sum(x*x for x in p)) for p in local),default=0))*256
 struct.pack_into('<I',head,8,radius)
 for j in range(3):
  struct.pack_into('<hh',head,12+4*j,math.ceil(max((p[j] for p in local),default=0)/16),math.floor(min((p[j] for p in local),default=0)/16))
 out.extend(head)
 for v in ids:
  if owner[v]!=actual:
   assert owner[v]<actual
   out.extend(struct.pack('<hHHH',0,references[v],0,2))
  else:
   p=[round(verts[v][j]-offsets[str(i)][j]) for j in range(3)];out.extend(struct.pack('<hhhH',*p,1 if v in shared and i==actual else 0))
 for v in ids:out.extend(struct.pack('<hhhH',*norm(normals[v]),0))
 for f in fs:out.extend(struct.pack('<hhhH',*norm(face_normal(f)),0))
 for k,f in enumerate(fs):
  face=bytearray(36);struct.pack_into('<HH',face,0,0x1f,36)
  for slot,corner in enumerate((0,2,1)):
   face[4+slot]=lookup[f['v'][corner]];u,v=f['uv'][corner];face[20+slot*2]=max(0,min(255,round(u*(TEX-1))));face[21+slot*2]=max(0,min(255,round((1-v)*(TEX-1))))
  face[8:12]=bytes([210,210,210,36]);struct.pack_into('<H',face,12,len(ids)+k);out.extend(face)
 stats.append({'mesh':i,'vertices':len(ids),'triangles':len(fs)})
meta=len(out);oldmeta=struct.unpack_from('<I',raw,4)[0]
if args.template_layout:
 cursor=oldmeta
 while struct.unpack_from('<I',raw,cursor)[0]!=0xFFFFFFFF:
  cursor+=8+struct.unpack_from('<I',raw,cursor+4)[0]
 cursor+=4
 out.extend(raw[oldmeta:cursor]);out.extend(raw[cursor:cursor+part_count*4])
 out.extend(struct.pack('<IIIII',1,layout['textureHashes'][0] if layout['textureHashes'] else 0,0,0,0))
else:out.extend(raw[oldmeta:])
struct.pack_into('<I',out,4,meta)
# Relocate embedded texture record pointers after changed geometry.
delta=meta-oldmeta
for i in range(0 if args.template_layout else layout['textureCount']):
 p=struct.unpack_from('<I',raw,layout['texturePointerTable']+4*i)[0];struct.pack_into('<I',out,layout['texturePointerTable']+delta+4*i,p+delta)
l=container_layout(out);material=zlib.crc32(('suit-material:'+args.id).encode());palette_id=zlib.crc32(('suit-palette:'+args.id).encode())
struct.pack_into('<I',out,l['hashCountOffset']+4,material)
image=Image.open(next(args.source.glob('*_D_rgb.tga'))).convert('RGBA')
if args.opaque_diffuse:image.putalpha(255)
palette,pixels=c.quantize_image(image,args.name,*image.size,TEX,TEX)
# FBX UVs address the original image, not the multitool's corrected DC image.
rows=[list(reversed(pixels[y*TEX:(y+1)*TEX])) for y in range(TEX)]
rows=[r[-1:]+r[:-1] for r in rows]
rows=rows[-1:]+rows[:-1]
column=[r[0] for r in rows]
for y in range(TEX):rows[y][0]=column[(y+1)%TEX]
pixels=bytes(x for row in rows for x in row)
# Append a private palette, retain all original support records, and replace body page zero.
palstart=l['textureSection'];c4=struct.unpack_from('<I',out,palstart)[0];p8=palstart+4+c4*36;c8=struct.unpack_from('<I',out,p8)[0];end8=p8+4+c8*516
new=bytearray(out[:end8]);struct.pack_into('<I',new,p8,c8+1);new.extend(struct.pack('<I256H',palette_id,*palette));new.extend(out[end8:l['texturePointerTable']]);table=len(new);new.extend(bytes(l['textureCount']*4))
for i in range(l['textureCount']):
 ptr=struct.unpack_from('<I',out,l['texturePointerTable']+i*4)[0];end=struct.unpack_from('<I',out,l['texturePointerTable']+(i+1)*4)[0] if i+1<l['textureCount'] else len(out);record=out[ptr:end]
 if struct.unpack_from('<I',record,12)[0]==0:record=struct.pack('<IIIIHH',0,256,palette_id,0,TEX,TEX)+pixels
 struct.pack_into('<I',new,table+i*4,len(new));new.extend(record)
if args.template_layout:
 # Every new face uses the single exported atlas. Keeping the donor's unused
 # pages wastes the game's fixed VRAM allocator and can corrupt actor textures.
 used=set(fit.get('usedTemplateTextureHashes',layout['textureHashes']))
 support=[]
 for i in range(layout['textureCount']):
  ptr=struct.unpack_from('<I',raw,layout['texturePointerTable']+i*4)[0]
  end=struct.unpack_from('<I',raw,layout['texturePointerTable']+(i+1)*4)[0] if i+1<layout['textureCount'] else len(raw)
  slot=struct.unpack_from('<I',raw,ptr+12)[0]
  if layout['textureHashes'][slot] not in used:
   record=bytearray(raw[ptr:end]);struct.pack_into('<I',record,12,slot+1);support.append(record)
 new=bytearray(out[:l['hashCountOffset']])
 hashes=(material,)+layout['textureHashes'] if support else (material,)
 new.extend(struct.pack('<I',len(hashes)));new.extend(struct.pack('<'+'I'*len(hashes),*hashes))
 if support:
  palstart=layout['textureSection'];c4=struct.unpack_from('<I',raw,palstart)[0];p8=palstart+4+c4*36;c8=struct.unpack_from('<I',raw,p8)[0]
  new.extend(raw[palstart:p8]);new.extend(struct.pack('<I',c8+1));new.extend(raw[p8+4:p8+4+c8*516])
 else:new.extend(struct.pack('<II',0,1))
 new.extend(struct.pack('<I256H',palette_id,*palette))
 records=[struct.pack('<IIIIHH',0,256,palette_id,0,TEX,TEX)+pixels]+support
 new.extend(struct.pack('<I',len(records)));table=len(new);new.extend(bytes(4*len(records)))
 for i,record in enumerate(records):
  struct.pack_into('<I',new,table+i*4,len(new));new.extend(record)
assets=P/'assets';assets.mkdir(exist_ok=True);(assets/args.actor_file).write_bytes(new)
(P/'native-report.json').write_text(json.dumps({'parts':stats,'stitchSources':n,'sourceTriangles':len(fit['faces']),'storedTrianglesWithAlternateHands':sum(x['triangles'] for x in stats),'actorBytes':len(new),'materialId':f'{material:08X}','sha256':hashlib.sha256(new).hexdigest()},indent=2))
print(json.dumps(stats));print('stitches',n,'bytes',len(new))
from port_all_characters import replacement_key
pack=assets/'packs'/args.id;(pack/'textures').mkdir(parents=True,exist_ok=True)
key=replacement_key(TEX,TEX,palette,pixels)
image.save(pack/'textures'/'diffuse.png')
(pack/'pack.json').write_text(json.dumps({'id':args.id,'name':args.name+' original diffuse','version':'0.1','textures':[{'file':'textures/diffuse.png','index':key.split('_')[0],'clut':key.split('_')[1]}],'priority':200,'game':{'id':'SLUS-00875','strict':True}},indent=2))
print('Full-resolution texture:',image.size,key)
