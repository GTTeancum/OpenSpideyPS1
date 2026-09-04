#!/usr/bin/env python3
"""Reproducible data-only recolor fixture; never rebuilds or edits the donor PSX.

Preserves UV layout, shading, neutral eyes/web lines and alpha. Texture 0 is
deliberately enlarged to 2048x2048 to exercise host-side HD uploads, not to claim
new artistic detail. Other textures retain the original Dreamcast dimensions.
"""
import argparse
import json
import shutil
from pathlib import Path
from PIL import Image
from pack_sm2_costume_to_dc import container_layout
from build_reskin_uv_templates import build_templates

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
        if index == 0:
            image = image.resize((2048, 2048), Image.Resampling.NEAREST)
        material = f'{hashes[index]:08X}'
        relative = f'textures/{material}.png'
        image.save(output / relative)
        textures[material] = relative
    manifest = dict(version=1, id='magenta-man', name='Magenta Man',
                    comments='Your friendly magenta neighborhood!',
                    abilities={'profile': 'spiderman'}, textures=textures)
    content = json.dumps(manifest, indent=2)
    content = content.replace('  "abilities": {',
        '  // Choose whose powers your costume uses:\n'
        '  // spiderman, 2099, symbiote, captain-universe, unlimited, bagman,\n'
        '  // scarlet, ben-reilly, quick-change, peter-parker.\n'
        '  // See instructions.txt for what each choice does.\n'
        '  "abilities": {')
    (output / 'suit.json').write_text(content + '\n', encoding='utf-8')
    instructions = ROOT / 'mods/samples/magenta-man/instructions.txt'
    if output != instructions.parent:
        shutil.copy2(instructions, output / 'instructions.txt')
    build_templates(output)
    print(f'{output}: {len(textures)} external PNGs; donor unchanged; JSON profile spiderman')


if __name__ == '__main__':
    main()
