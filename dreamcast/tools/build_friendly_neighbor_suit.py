"""Convert WizByte's original GameBanana archive to an SM1/SM2 suit."""
import argparse
import hashlib
import io
import json
import shutil
from pathlib import Path
import zipfile
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]

# Dreamcast emulator PNG names -> native material hashes; see process notes.
MATERIALS = {
    'aef9fccb': '9D39C02B', 'b01f944a': '29AF154F',
    'e1e08580': '154B7D71', '29c42eb7': '42991273',
    '849133f4': 'D7669388', '4a842b4e': 'D8425644',
    '1ed2b960': 'F82D1471', 'f8030f8d': 'FBC5A5A0',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if hashlib.md5(args.archive.read_bytes()).hexdigest() != '0e2f2221d50382a0933cba7a4d8b834d':
        raise ValueError('Expected original spider-man_john_romita_sr_.zip, GameBanana file 1663238')
    if args.output.exists():
        raise ValueError('Use a fresh output directory')
    (args.output / 'textures').mkdir(parents=True)
    textures = {}
    with zipfile.ZipFile(args.archive) as archive:
        # Default Classic body only. Emulator replacements use opposite vertical UVs.
        for offset, material in MATERIALS.items():
            original = Image.open(io.BytesIO(archive.read(f'Classic/spidey/{offset}.png'))).convert('RGB').transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            relative = f'textures/{material}.png'
            original.save(args.output / relative)
            with Image.open(args.output / relative) as converted:
                if converted.size != original.size or converted.tobytes() != original.tobytes():
                    raise ValueError(f'Pixel mismatch: {offset}')
            textures[material] = relative
    manifest = dict(version=1, id='friendly-neighbor', name='Friendly Neighbor',
                    comments='By WizByte', model='spiderman',
                    abilities={'profile': 'spiderman'}, textures=textures)
    (args.output / 'suit.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copy2(ROOT / 'mods/suit-instructions.txt', args.output / 'instructions.txt')
    (args.output / 'README.md').write_text(
        '# Friendly Neighbor\n\nBy WizByte (creator / porter).\n\n'
        'Author: https://gamebanana.com/members/5278375\n'
        'Source: https://gamebanana.com/mods/665138 (Friendly Neighbor Costume).\n'
        'Eight 1024px Classic body textures vertically flipped for native UVs, without resizing\n'
        'or recoloring. Default mask and palette; bonus variants and HUD excluded.\nUses the wingless SM1 body in both games and standard\n'
        'Spider-Man powers. Install this folder in mods/suits.\n')
    print(f'{args.output}: eight textures; source RGB pixels verified')


if __name__ == '__main__':
    main()
