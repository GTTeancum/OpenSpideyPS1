"""Package Dat Mental Gamer's red Quick Change textures for both games."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import zipfile
from PIL import Image
from pack_sm2_costume_to_dc import container_layout

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES = {6: '0005B2C4', 5: '00061F78'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if hashlib.md5(args.archive.read_bytes()).hexdigest() != 'a3fae3c9c17f7b9a709bb02e98d90f18':
        raise ValueError('Expected improved_quick_change.zip, GameBanana file 521501')
    if args.output.exists():
        raise ValueError('Use a fresh output directory')
    manifest_path = ROOT / 'dreamcast/converted/all-characters/packs/dreamcast-sm1-actors/texture-manifest.json'
    entries = [e for e in json.loads(manifest_path.read_text())['entries'] if e['actor'] == 'SPQUICK']
    if len(entries) != 9:
        raise ValueError('Expected nine Quick Change materials')
    with zipfile.ZipFile(ROOT / 'spiderman/port/bundled/runtime-assets.zip') as bundle:
        hashes = container_layout(bundle.read('spquick.psx'))['textureHashes']
    (args.output / 'textures').mkdir(parents=True)
    textures = {}
    with zipfile.ZipFile(args.archive) as archive:
        for entry in entries:
            index = entry['textureIndex']
            material = f'{hashes[index]:08X}'
            relative = f'textures/{material}.png'
            destination = args.output / relative
            if index in OVERRIDES:
                original = Image.open(io.BytesIO(archive.read(f'SpQuick/{OVERRIDES[index]}.bmp'))).convert('RGB')
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
    suit = dict(version=1, id='quick-change-red', name='Quick Change (red)',
                comments='By Dat Mental Gamer', model='quick-change',
                abilities={'profile': 'spiderman'}, textures=textures)
    (args.output / 'suit.json').write_text(json.dumps(suit, indent=2) + '\n')
    (args.output / 'README.md').write_text(
        '# Quick Change (red)\n\nBy Dat Mental Gamer.\n\n'
        'Source: https://gamebanana.com/mods/249032 (Improved Quick Change Costume).\n'
        'Original red mask and glove BMPs converted to PNG without pixel changes.\n'
        'Remaining seven textures and body come from SM1 Quick Change.\n'
        'Uses standard Spider-Man powers in both games. Install in mods/suits.\n')
    print('Verified two original mod textures and seven unchanged base textures.')


if __name__ == '__main__':
    main()
