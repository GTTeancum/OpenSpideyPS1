"""Keep Quick Change's jacket/belt and ankle cuffs on consistent rigid owners."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'spiderman/tools'))
from port_dc_character import mesh_parts
from pack_sm2_costume_to_dc import container_layout, resolve_multitool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ROOT / 'spiderman/port/bundled/runtime-assets.zip') as archive:
        raw = archive.read('spquick.psx')
    donor = args.output / 'donor.psx'
    donor.write_bytes(raw)
    dump_path = args.output / 'donor-dump.json'
    tool = resolve_multitool(None)
    subprocess.run([str(tool), 'psx-mesh-dump', str(donor), '--json', str(dump_path)], check=True, stdout=subprocess.DEVNULL)
    dump = json.loads(dump_path.read_text())
    layout = container_layout(raw)
    parts = [mesh_parts(raw, p) for p in layout['meshPointers']]
    offsets = {o['ObjectIndex']: [round(p * 36) for p in o['Position'].values()] for o in dump['Objects']}
    points, owners = {}, {}
    keys = []
    changes = []
    for i, mesh in enumerate(dump['Meshes']):
        mesh_keys = []
        for v in mesh['Vertices']:
            key = (v['SourceMeshIndex'], v['SourceVertexIndex'])
            mesh_keys.append(key)
            if key in points:
                continue
            p = tuple(round(n * 36) for n in v['WorldPosition'].values())
            old = v['SourceObjectIndex']
            owner = old
            # Whole lower jacket band and belt/top trouser ring follow pelvis.
            if old in (0, 2, 13, 16) and -400 <= p[1] <= 140:
                owner = 0
            # Each entire cuff follows its foot, including shared shoe-rim points.
            if old in (12, 14) and p[1] >= 1340:
                owner = 14
            if old in (15, 17) and p[1] >= 1340:
                owner = 17
            points[key], owners[key] = p, owner
            if owner != old:
                changes.append(dict(source=list(key), position=p, before=old, after=owner))
        keys.append(mesh_keys)
    # Native attachments can only reference earlier parts. Move faces crossing
    # a reassigned cuff to the foot part, keeping raw UV/material/color records.
    faces = [[] for _ in parts]
    for i, mesh in enumerate(dump['Meshes']):
        for f, raw_face in zip(mesh['Faces'], parts[i][3]):
            ids = [keys[i][v] for v in f['Indices']]
            destination = max(i, *(owners[k] for k in ids))
            faces[destination].append((ids, raw_face, parts[i][2][f['NormalIndex']],
                                       [parts[i][2][v] for v in f['Indices']]))
    indices = []
    for i in range(len(parts)):
        indices.append(sorted({k for k in points if owners[k] == i} |
                              {k for ids, *_ in faces[i] for k in ids}))
    shared = {k for k in points if any(k in ids and owners[k] != i for i, ids in enumerate(indices))}
    references = {}
    for i, ids in enumerate(indices):
        for k in ids:
            if owners[k] == i and k in shared:
                references[k] = len(references)
    out = bytearray(raw[:min(layout['meshPointers'])])
    stats = []
    for i, ids in enumerate(indices):
        if len(ids) > 256:
            raise ValueError(f'Part {i} exceeds native vertex capacity')
        lookup = {k: n for n, k in enumerate(ids)}
        struct.pack_into('<I', out, layout['meshPointerTable'] + 4*i, len(out))
        header = bytearray(parts[i][0])
        struct.pack_into('<HHH', header, 2, len(ids), len(ids)+len(faces[i]), len(faces[i]))
        local = [[points[k][j]-offsets[i][j] for j in range(3)] for k in ids]
        struct.pack_into('<I', header, 8, math.ceil(max(math.dist(p, (0, 0, 0)) for p in local))*256)
        for j in range(3):
            struct.pack_into('<hh', header, 12+4*j, math.ceil(max(p[j] for p in local)/16), math.floor(min(p[j] for p in local)/16))
        out.extend(header)
        for k, p in zip(ids, local):
            if owners[k] == i:
                out.extend(struct.pack('<hhhH', *p, int(k in shared)))
            else:
                assert owners[k] < i
                out.extend(struct.pack('<hHHH', 0, references[k], 0, 2))
        # Preserve native normals while changing the rigid skin assignments.
        normals = {k: parts[k[0]][2][k[1]] for k in ids}
        for face_ids, _, _, face_normals in faces[i]:
            for k, n in zip(face_ids, face_normals):
                normals[k] = n
        for k in ids:
            out.extend(normals[k])
        for _, _, n, _ in faces[i]:
            out.extend(n)
        for n, (face_ids, raw_face, _, _) in enumerate(faces[i]):
            face = bytearray(raw_face)
            for corner, k in enumerate(face_ids):
                face[4+corner] = lookup[k]
            struct.pack_into('<H', face, 12, len(ids)+n)
            out.extend(face)
        stats.append(dict(mesh=i, vertices=len(ids), faces=len(faces[i])))
    oldmeta = struct.unpack_from('<I', raw, 4)[0]
    meta = len(out)
    out.extend(raw[oldmeta:])
    struct.pack_into('<I', out, 4, meta)
    delta = meta-oldmeta
    for i in range(layout['textureCount']):
        old = struct.unpack_from('<I', raw, layout['texturePointerTable']+4*i)[0]
        struct.pack_into('<I', out, layout['texturePointerTable']+delta+4*i, old+delta)
    actor = args.output / 'actor.psx'
    actor.write_bytes(out)
    result_path = args.output / 'native-dump.json'
    subprocess.run([str(tool), 'psx-mesh-dump', str(actor), '--json', str(result_path)], check=True, stdout=subprocess.DEVNULL)
    result = json.loads(result_path.read_text())
    assert sum(m['FaceCount'] for m in result['Meshes']) == sum(m['FaceCount'] for m in dump['Meshes'])
    assert not any(m['StitchFailureCount'] or any(f['RejectionReason'] for f in m['FaceReads']) for m in result['Meshes'])
    def signatures(data):
        return Counter((f['TextureHash'], tuple(tuple(round(x*36) for x in f['ResolvedWorldVertices'][v].values()) for v in corners),
                        tuple((f['TextureCoordinates'][v]['U'],f['TextureCoordinates'][v]['V']) for v in corners))
                       for m in data['Meshes'] for f in m['Faces']
                       for corners in (((0, 1, 2), (2, 1, 3)) if f['IsQuad'] else ((0, 1, 2),)))
    assert signatures(dump) == signatures(result), 'Bind geometry or UVs changed'
    for i, mesh in enumerate(result['Meshes']):
        for v in mesh['Vertices']:
            k = indices[i][v['VertexIndex']]
            assert v['SourceObjectIndex'] == owners[k]
    report = dict(changedVertices=changes, parts=stats, faceCount=sum(m['FaceCount'] for m in result['Meshes']),
                  bindGeometryAndUvsUnchanged=True, allOwnersVerified=True, stitchFailures=0)
    (args.output / 'rig-report.json').write_text(json.dumps(report, indent=2))
    print(f'{len(changes)} rigid-owner changes; geometry/UVs preserved; all attachments verified')


if __name__ == '__main__':
    main()
