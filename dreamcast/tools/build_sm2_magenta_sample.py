"""Build the SM2 example from the established multitool's approved-model GLB export."""
import argparse
import io
import json
from pathlib import Path
import struct
from PIL import Image
from build_reskin_uv_templates import build_templates

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, default=ROOT / 'mods/samples/magenta-man-sm2')
    args = p.parse_args()
    data = args.source.read_bytes()
    assert data[:4] == b'glTF'
    length, kind = struct.unpack_from('<II', data, 12)
    assert kind == 0x4E4F534A
    doc = json.loads(data[20:20+length])
    binary = data[28+length:]
    out = args.output.resolve()
    (out / 'textures').mkdir(parents=True, exist_ok=True)
    textures = {}
    for mat in doc['materials']:
        if not mat['name'].startswith('tex_'):
            continue
        material = mat['name'][4:]
        tex = doc['textures'][mat['pbrMetallicRoughness']['baseColorTexture']['index']]
        view = doc['bufferViews'][doc['images'][tex['source']]['bufferView']]
        start = view.get('byteOffset', 0)
        image = Image.open(io.BytesIO(binary[start:start+view['byteLength']])).convert('RGBA')
        image.putdata([(max(r,g,b), min(r,g,b), max(r,g,b), a) if max(r,g,b)-min(r,g,b)>12
                       else (r,g,b,a) for r,g,b,a in image.getdata()])
        if material == 'E9587C6D':
            image = image.resize((2048, 2048), Image.Resampling.NEAREST)
        relative = f'textures/{material}.png'
        image.save(out / relative)
        textures[material] = relative
    assert len(textures) == 14, textures.keys()
    manifest = dict(version=1, id='magenta-man', name='Magenta Man',
                    comments='Your friendly magenta neighborhood!',
                    abilities=dict(profile='spiderman'), textures=textures)
    text = json.dumps(manifest, indent=2).replace('  "abilities": {',
        '  // Choose powers from: spiderman, spider-phoenix, prodigy, dusk, insulated,\n'
        '  // alex-ross-red, alex-ross-white, venom-earth-x, negative-zone, symbiote,\n'
        '  // 2099, captain-universe, unlimited, bagman, scarlet, ben-reilly,\n'
        '  // quick-change, peter-parker, battle-damaged. See instructions.txt.\n'
        '  "abilities": {')
    (out / 'suit.json').write_text(text + '\n', encoding='utf-8')
    build_templates(out, source=args.source)


if __name__ == '__main__':
    main()
