"""Make the original wingless SM1 appearance selectable through SM2's suit menu."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from pack_sm2_costume_to_dc import container_layout

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-manifest', type=Path, default=ROOT / 'dreamcast/converted/all-characters/packs/dreamcast-sm1-actors/texture-manifest.json')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Use a fresh output directory')
    with zipfile.ZipFile(ROOT / 'spiderman/port/bundled/runtime-assets.zip') as archive:
        hashes = container_layout(archive.read('spidey.psx'))['textureHashes']
    entries = [e for e in json.loads(args.source_manifest.read_text())['entries'] if e['actor'] == 'SPIDEY']
    if len(entries) != 8:
        raise ValueError('Expected eight original SM1 body materials')
    (output / 'textures').mkdir(parents=True)
    textures = {}
    for entry in entries:
        source = Path(entry['source'])
        relative = f"textures/{hashes[entry['textureIndex']]:08X}.png"
        shutil.copy2(source, output / relative)
        assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256((output / relative).read_bytes()).digest()
        textures[f"{hashes[entry['textureIndex']]:08X}"] = relative
    manifest = dict(version=1, id='spiderman-sm1', name='Spider-Man (SM1)',
                    comments='Neversoft / Treyarch', model='spiderman',
                    abilities=dict(profile='spiderman'), textures=textures)
    (output / 'suit.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'README.md').write_text(
        '# Spider-Man (SM1) for SM2\n\n'
        'Original SM1 Dreamcast appearance, using the wingless SM1 actor bundled with SM2.\n'
        'The eight original body textures are copied without recoloring or resizing.\n'
        'Uses standard SM2 Spider-Man powers and animations. Select Spider-Man (SM1)\n'
        'in the costume menu. The original SM2 Spider-Man remains available.\n')
    print(output)


if __name__ == '__main__':
    main()
