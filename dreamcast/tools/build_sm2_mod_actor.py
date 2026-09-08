"""Package the SM1 mod actor for SM2 without colliding with SM2's visible wings."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import struct
import zipfile
from pack_sm2_costume_to_dc import container_layout, HIDDEN_WING_HASH, DC_WING_HASH

ROOT = Path(__file__).resolve().parents[2]

def isolate_cutout(data: bytes) -> bytes:
    layout = container_layout(data)
    hashes = layout['textureHashes']
    if DC_WING_HASH not in hashes or HIDDEN_WING_HASH in hashes:
        raise ValueError('Expected the original SM1 wing-cutout material exactly once')
    if hashes.count(DC_WING_HASH) != 1:
        raise ValueError('Ambiguous wing material')
    # Prove the selected embedded texture is the SM1 transparent cutout before
    # changing its lookup identity. Geometry, UVs, palettes and pixels stay intact.
    index = hashes.index(DC_WING_HASH)
    palette_start = layout['textureSection']
    count4 = struct.unpack_from('<I', data, palette_start)[0]
    cursor = palette_start + 4 + count4 * 36
    count8 = struct.unpack_from('<I', data, cursor)[0]
    cursor += 4
    palettes = {}
    for _ in range(count8):
        identity = struct.unpack_from('<I', data, cursor)[0]
        palettes[identity] = struct.unpack_from('<256H', data, cursor+4)
        cursor += 516
    found = 0
    for n in range(layout['textureCount']):
        ptr = struct.unpack_from('<I', data, layout['texturePointerTable']+4*n)[0]
        flags, size, identity, material, width, height = struct.unpack_from('<IIIIHH', data, ptr)
        if material != index:
            continue
        found += 1
        if size != 256 or flags != 0 or identity not in palettes:
            raise ValueError('Unexpected SM1 cutout texture format')
        pixels = data[ptr+20:ptr+20+width*height]
        if len(pixels) != width*height or any(palettes[identity][p] != 0x7C1F for p in pixels):
            raise ValueError('Refusing to hide a visible wing texture')
    if found != 1:
        raise ValueError('Missing or repeated cutout texture')
    output = bytearray(data)
    struct.pack_into('<I', output, layout['hashCountOffset']+4+4*index, HIDDEN_WING_HASH)
    return bytes(output)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-bundle', type=Path, default=ROOT/'spiderman/port/bundled/runtime-assets.zip')
    parser.add_argument('--bundle', type=Path, default=ROOT/'spiderman2/port/bundled/runtime-assets.zip')
    args = parser.parse_args()
    with zipfile.ZipFile(args.source_bundle) as archive:
        actor = isolate_cutout(archive.read('spidey.psx'))
    name = 'spidey-mod-sm1.psx'
    with zipfile.ZipFile(args.bundle) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    manifest = json.loads(next(data for info,data in entries if info.filename == 'bundle.json'))
    record = next((item for item in manifest['files'] if item['path'] == name), None)
    if record is None:
        record = {'path': name}
        manifest['files'].append(record)
    record.update(bytes=len(actor), sha256=hashlib.sha256(actor).hexdigest().upper())
    replacements = {name:actor, 'bundle.json':(json.dumps(manifest,indent=2)+'\n').encode()}
    result = io.BytesIO()
    with zipfile.ZipFile(result,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for info,data in entries:
            archive.writestr(info,replacements.get(info.filename,data))
        if not any(info.filename == name for info,_ in entries):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, actor)
    temporary = args.bundle.with_suffix('.zip.tmp')
    temporary.write_bytes(result.getvalue())
    temporary.replace(args.bundle)
    print(f'{name}: {record["sha256"]}; only the cutout material identity changed')

if __name__ == '__main__':
    main()
