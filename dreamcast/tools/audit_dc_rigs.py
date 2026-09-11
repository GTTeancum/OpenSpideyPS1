"""Audit Dreamcast source ownership and animation chunks against shipped actors."""
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def read(raw):
    u = lambda p: struct.unpack_from('<I', raw, p)[0]
    n = u(8)
    table = 12 + 36*n
    count = u(table)
    pointers = [u(table+4+4*i) for i in range(count)]
    p = u(4)
    tags = {}
    while u(p) != 0xffffffff:
        tag, size = u(p), u(p+4)
        tags[tag] = raw[p+8:p+8+size]
        p += 8+size
    names = [u(p+4+4*i) for i in range(count)]
    streams, signatures, attachments = [], [], []
    for name, ptr in zip(names, pointers):
        nv = struct.unpack_from('<H', raw, ptr+2)[0]
        stream = raw[ptr+28:ptr+28+8*nv]
        streams.append(stream)
        resolved = []
        for off in range(0, len(stream), 8):
            x,y,z,kind = struct.unpack_from('<hhhH', stream, off)
            if kind == 2:
                value = attachments[y & 0xffff]
            else:
                value = (name,x,y,z)
                if kind == 1:
                    attachments.append(value)
            resolved.append(value)
        signatures.append(Counter(resolved))
    return dict(objects=raw[12:table], count=n, names=names, streams=streams,
                signatures=signatures, tags=tags)


def compare(source, output):
    # Compare each authored full-detail part by name, resolving stitch indices
    # to their source owner. Added wing vertices and compatibility LOD copies
    # do not count as reassignment of original Dreamcast vertices.
    primary = dict(zip(output['names'][:output['count']], output['signatures'][:output['count']]))
    missing = {}
    for name, vertices in zip(source['names'][:source['count']],source['signatures'][:source['count']]):
        delta = vertices - primary.get(name, Counter())
        if delta:
            missing[f'{name:08X}'] = sum(delta.values())
    return dict(originalFullDetailOwnersAndPositionsPreserved=not missing,
                missingOriginalVerticesByPart=missing,
                objectTableEqual=source['objects']==output['objects'],
                rawVertexStreamsEqual=source['streams']==output['streams'],
                hierarchyEqual=source['tags'].get(0x52454948)==output['tags'].get(0x52454948),
                animationChunksEqual={hex(t):source['tags'].get(t)==output['tags'].get(t)
                    for t in (42,44) if t in source['tags'] or t in output['tags']})


def main():
    sources = {}
    for path in sorted((ROOT/'dreamcast/extracted').glob('*.PSX')):
        try:
            data=read(path.read_bytes())
        except (ValueError,IndexError,struct.error):
            continue
        if set(data['tags']) & {42,44} and 0x52454948 in data['tags']:
            sources[path.stem]=data
    report={'bundles':{},'mods':{}}
    for game in ('spiderman','spiderman2'):
        records={}
        with zipfile.ZipFile(ROOT/game/'port/bundled/runtime-assets.zip') as z:
            for name in z.namelist():
                if '/' in name or not name.endswith('.psx'):continue
                stem=Path(name).stem.upper()
                alias={'SPIDEY-MOD-SM1':'SPIDEY','SPIDEY-MOD-QUICK':'SPQUICK',
                       'SPIDEY-SLOT13':'SPBAGMAN','SPIDEY-SLOT17':'SPPARK'}
                source=sources.get(alias.get(stem,stem))
                if source is None and stem.startswith('SP2') and 'TEX' not in stem:
                    source=sources['SPIDEY']
                if source is None:continue
                records[name]=compare(source,read(z.read(name)))
        report['bundles'][game]=records
    for game in ('Spider-Man','Spider-Man 2'):
        records={}
        for path in sorted((ROOT/'proof_render/user-facing-stage/ready'/game/'mods/suits').glob('*/suit.json')):
            suit=json.loads(re.sub(r'^\s*//.*$', '', path.read_text(encoding='utf-8-sig'), flags=re.M))
            if suit['id'] in ('quick-change-red','ben-reilly-street'):
                source=sources['SPQUICK' if suit['id']=='quick-change-red' else 'SPPARK']
                records[suit['id']]=compare(source,read((path.parent/suit['modelFile']).read_bytes()))
            else:
                records[suit['id']]={'classification':'custom non-Dreamcast mesh' if suit.get('modelFile') else 'texture-only; inherits bundled rig'}
        report['mods'][game]=records
    out=ROOT/'proof_render/dreamcast-rig-audit';out.mkdir(exist_ok=True)
    (out/'rig-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    for game,records in report['bundles'].items():
        print(game,len(records),'actors')
        for name,r in records.items():
            if not r['originalFullDetailOwnersAndPositionsPreserved']:print(name,r['missingOriginalVerticesByPart'])
    for game,records in report['mods'].items():
        for name,r in records.items():
            if 'originalFullDetailOwnersAndPositionsPreserved' in r:print(game,name,r['originalFullDetailOwnersAndPositionsPreserved'])


if __name__=='__main__':main()
