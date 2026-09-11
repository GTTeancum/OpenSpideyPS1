"""Convert Dat Mental Gamer's original GameBanana archive to an SM1/SM2 suit."""
import argparse
import hashlib
import io
import json
import shutil
from pathlib import Path
import zipfile
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]

# Original Dreamcast texture payload offsets -> native material hashes.
MATERIALS = {
    '00059588': '9D39C02B', '0005DDAC': '29AF154F',
    '000625D0': '154B7D71', '00066DF4': '42991273',
    '00068618': 'D7669388', '00069E3C': 'D8425644',
    '0006E660': 'F82D1471', '0006FE84': 'FBC5A5A0',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if hashlib.md5(args.archive.read_bytes()).hexdigest() != '1ad64ed7645963dacbb303f4d9b0fe9d':
        raise ValueError('Expected original sm2000_tasm2012_redsuit_bb1fb.zip, GameBanana file 806768')
    if args.output.exists():
        raise ValueError('Use a fresh output directory')
    (args.output / 'textures').mkdir(parents=True)
    textures = {}
    with zipfile.ZipFile(args.archive) as archive:
        # Use the standard named texture; the withbelt BMP is an optional variant.
        for offset, material in MATERIALS.items():
            original = Image.open(io.BytesIO(archive.read(f'spidey/{offset}.bmp'))).convert('RGB')
            relative = f'textures/{material}.png'
            original.save(args.output / relative)
            with Image.open(args.output / relative) as converted:
                if converted.size != original.size or converted.tobytes() != original.tobytes():
                    raise ValueError(f'Pixel mismatch: {offset}')
            textures[material] = relative
    manifest = dict(version=1, id='amazing-tasm', name='Amazing (TASM)',
                    comments='By Dat Mental Gamer', model='spiderman',
                    abilities={'profile': 'spiderman'}, textures=textures)
    (args.output / 'suit.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copy2(ROOT / 'mods/suit-instructions.txt', args.output / 'instructions.txt')
    (args.output / 'README.md').write_text(
        '# Amazing (TASM)\n\nBy Dat Mental Gamer (creator / porter).\n\n'
        'Original game credits: Beenox and Neversoft (as listed by the author).\n'
        'Author: https://gamebanana.com/members/1614404\n'
        'Source: https://gamebanana.com/mods/380766 (Amazing (TASM) Costume).\n'
        'Original eight BMP textures converted losslessly to PNG, with no resizing\n'
        'or recoloring. Uses the wingless SM1 body in both games and standard\n'
        'Spider-Man powers. Install this folder in mods/suits.\n')
    print(f'{args.output}: eight textures; source RGB pixels verified')


if __name__ == '__main__':
    main()
