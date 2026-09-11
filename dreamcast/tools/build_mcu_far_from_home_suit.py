"""Convert Spider-Wuss's original GameBanana archive to an SM1/SM2 suit."""
import argparse
import hashlib
import io
import json
import shutil
from pathlib import Path
import subprocess
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
    parser.add_argument('--sevenzip', type=Path, default=Path('C:/Program Files/7-Zip/7z.exe'))
    args = parser.parse_args()
    if hashlib.md5(args.archive.read_bytes()).hexdigest() != '0ae61beaf26411a4115c0097b0c85283':
        raise ValueError('Expected original far_from_home.rar, GameBanana file 506819')
    if args.output.exists():
        raise ValueError('Use a fresh output directory')
    (args.output / 'textures').mkdir(parents=True)
    textures = {}
    for offset, material in MATERIALS.items():
        original = Image.open(io.BytesIO(subprocess.check_output([str(args.sevenzip), 'e', '-so', str(args.archive), f'spidey/{offset}.bmp']))).convert('RGB')
        relative = f'textures/{material}.png'
        original.save(args.output / relative)
        with Image.open(args.output / relative) as converted:
            if converted.size != original.size or converted.tobytes() != original.tobytes():
                raise ValueError(f'Pixel mismatch: {offset}')
        textures[material] = relative
    manifest = dict(version=1, id='mcu-far-from-home', name='MCU Far From Home',
                    comments='By Spider-Wuss', model='spiderman',
                    abilities={'profile': 'spiderman'}, textures=textures)
    (args.output / 'suit.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copy2(ROOT / 'mods/suit-instructions.txt', args.output / 'instructions.txt')
    (args.output / 'README.md').write_text(
        '# MCU Far From Home\n\nBy Spider-Wuss (credited modeler).\n\n'
        'Author: https://gamebanana.com/members/1767938\n'
        'Source: https://gamebanana.com/mods/249041 (MCU Far From Home Costume).\n'
        'Original eight BMP textures converted losslessly to PNG, with no resizing\n'
        'or recoloring. Uses the wingless SM1 body in both games and standard\n'
        'Spider-Man powers. Install this folder in mods/suits.\n')
    print(f'{args.output}: eight textures; source RGB pixels verified')


if __name__ == '__main__':
    main()
