"""Package DarthJak90's civilian Ben Reilly textures for both games."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
from PIL import Image
from pack_sm2_costume_to_dc import container_layout

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES = {22: '00062AF8', 8: '0006AFD0'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if hashlib.md5(args.archive.read_bytes()).hexdigest() != '40afa6d6d0b91d375c52165238835642':
        raise ValueError('Expected ben_reilly_5fae7.zip, GameBanana file 995237')
    if args.output.exists():
        raise ValueError('Use a fresh output directory')
    manifest_path = ROOT / 'dreamcast/converted/all-characters/packs/dreamcast-sm1-actors/texture-manifest.json'
    entries = [e for e in json.loads(manifest_path.read_text())['entries'] if e['actor'] == 'SPPARK']
    if len(entries) != 12 or {e['textureIndex'] for e in entries} != set(range(9)) | {22, 23, 24}:
        raise ValueError('Expected twelve Peter Parker materials')
    with zipfile.ZipFile(ROOT / 'spiderman/port/bundled/runtime-assets.zip') as bundle:
        hashes = container_layout(bundle.read('sppark.psx'))['textureHashes']
    # The converted texture manifest inserts thirteen player support slots at
    # index nine; the standalone actor's material table omits that window.
    material_indices = {entry['textureIndex']: index for index, entry in enumerate(sorted(entries, key=lambda e: e['textureIndex']))}
    (args.output / 'textures').mkdir(parents=True)
    textures = {}
    with zipfile.ZipFile(args.archive) as archive:
        for entry in entries:
            index = entry['textureIndex']
            material = f'{hashes[material_indices[index]]:08X}'
            relative = f'textures/{material}.png'
            destination = args.output / relative
            if index in OVERRIDES:
                original = Image.open(io.BytesIO(archive.read(f'spPark/{OVERRIDES[index]}.bmp'))).convert('RGB')
                original.save(destination)
                with Image.open(destination) as result:
                    if result.size != original.size or result.tobytes() != original.tobytes():
                        raise ValueError('Converted pixels differ')
            else:
                source = Path(entry['source'])
                shutil.copy2(source, destination)
                if source.read_bytes() != destination.read_bytes():
                    raise ValueError('Base texture differs')
            textures[material] = relative
    with tempfile.TemporaryDirectory(prefix='ben-reilly-rig-') as work:
        subprocess.run([sys.executable, str(ROOT / 'dreamcast/tools/rig_quick_change_red.py'),
                        '--output', work, '--donor', 'sppark.psx'], check=True)
        shutil.copy2(Path(work) / 'actor.psx', args.output / 'actor.psx')
        shutil.copy2(Path(work) / 'rig-report.json', args.output / 'rig-report.json')
    suit = dict(version=1, id='ben-reilly-street', name='Ben Reilly (Street)',
                comments='By DarthJak90', model='peter-parker',
                modelFile='actor.psx', abilities={'profile': 'spiderman'}, textures=textures)
    (args.output / 'suit.json').write_text(json.dumps(suit, indent=2) + '\n')
    (args.output / 'README.md').write_text(
        '# Ben Reilly (Street)\n\nBy DarthJak90.\n\n'
        'Source: https://gamebanana.com/mods/448036\n'
        'Author: https://gamebanana.com/members/2685073\n'
        'Both spPark costume BMPs converted without pixel changes; ten other\n'
        'body textures remain original SM1 Peter Parker. The separate parker NPC\n'
        'texture is not installed globally. Jacket/belt and ankle cuffs use the\n'
        'rigid boundary treatment. Standard Spider-Man powers in both games.\n'
        'Hidden waistband overlap removed and jacket hem tailored to the join.\n'
        'Install this folder in mods/suits. Requires the 19-character name update.\n')
    print('Verified two original mod textures and ten unchanged base textures.')


if __name__ == '__main__':
    main()
