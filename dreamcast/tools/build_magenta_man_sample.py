#!/usr/bin/env python3
"""Reproducible data-only recolor fixture; never rebuilds or edits the donor PSX.

Preserves UV layout, shading, neutral eyes/web lines and alpha. Texture 0 is
deliberately enlarged to 2048x2048 to exercise host-side HD uploads, not to claim
new artistic detail. Other textures retain the original Dreamcast dimensions.
"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image
from pack_sm2_costume_to_dc import container_layout

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--donor', type=Path, default=ROOT / 'proof_render/first-run-installer/valid-sm1/assets/builtin/spidey.psx')
    parser.add_argument('--source-manifest', type=Path, default=ROOT / 'dreamcast/converted/all-characters/packs/dreamcast-sm1-actors/texture-manifest.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'mods/samples/magenta-man')
    args = parser.parse_args()
    donor = args.donor.read_bytes()
    hashes = container_layout(donor)['textureHashes']
    entries = [e for e in json.loads(args.source_manifest.read_text())['entries'] if e['actor'] == 'SPIDEY']
    output = args.output.resolve()
    (output / 'textures').mkdir(parents=True, exist_ok=True)
    textures = {}
    evidence = []
    for entry in sorted(entries, key=lambda e: e['textureIndex']):
        index = entry['textureIndex']
        source = Path(entry['source'])
        with Image.open(source) as opened:
            image = opened.convert('RGBA')
        recolored = []
        for r, g, b, a in image.getdata():
            maximum, minimum = max(r, g, b), min(r, g, b)
            # Neutral white/black remains neutral; colored fabric becomes magenta.
            chroma = maximum - minimum
            recolored.append((maximum, minimum, maximum, a) if chroma > 12 else (r, g, b, a))
        image.putdata(recolored)
        original_size = image.size
        if index == 0:
            image = image.resize((2048, 2048), Image.Resampling.NEAREST)
        material = f'{hashes[index]:08X}'
        relative = f'textures/{material}.png'
        image.save(output / relative)
        textures[material] = relative
        evidence.append({'material': material, 'source': str(source.relative_to(ROOT)),
                         'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                         'sourceSize': original_size, 'outputSize': image.size,
                         'sha256': hashlib.sha256((output / relative).read_bytes()).hexdigest()})
    manifest = dict(version=1, id='magenta-man', name='Magenta Man',
                    description='Magenta DC reskin. External PNGs, original web detail and white eyes.',
                    donor='dc-spiderman', abilities={'profile': 'spiderman'}, textures=textures)
    content = json.dumps(manifest, indent=2)
    content = content.replace('  "abilities": {',
        '  // Assign one SM1 ability profile (appearance stays DC Spider-Man):\n'
        '  // spiderman, 2099, symbiote, captain-universe, unlimited, bagman,\n'
        '  // scarlet, ben-reilly, quick-change, peter-parker. See README for effects.\n'
        '  // These are complete retail profiles, not SM2 abilities or arbitrary code.\n'
        '  "abilities": {')
    (output / 'suit.json').write_text(content + '\n', encoding='utf-8')
    (output / 'provenance.json').write_text(json.dumps({
        'donorSha256': hashlib.sha256(donor).hexdigest(),
        'donorUnmodified': True, 'textures': evidence,
        'note': '2048 texture is a nearest-neighbor HD-path test, not newly authored detail.'
    }, indent=2) + '\n', encoding='utf-8')
    print(f'{output}: {len(textures)} external PNGs; donor unchanged; JSON profile spiderman')


if __name__ == '__main__':
    main()
