"""Package Dat Mental Gamer's Spider-Man 3 Wii texture reskins for both games."""
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
SUITS = (
    ('raimi-red-blue', 'Raimi (red & blue)', 'SPIDEY', 'spiderman', 'spiderman',
     'Spider-Man 3 Default Costume/spidey'),
    ('raimi-symbiote', 'Raimi (symbiote)', 'SPSYMBI', 'symbiote', 'symbiote',
     'Spider-Man 3 Black Suit/spsymbi'),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if hashlib.md5(args.archive.read_bytes()).hexdigest() != 'e5ddf243f8501698b72eb66824290287':
        raise ValueError('Expected original GameBanana file 593969')
    if args.output.exists():
        raise ValueError('Use a fresh output directory')
    entries = json.loads((ROOT/'dreamcast/converted/all-characters/packs/dreamcast-sm1-actors/texture-manifest.json').read_text())['entries']
    with zipfile.ZipFile(args.archive) as archive, zipfile.ZipFile(ROOT/'spiderman/port/bundled/runtime-assets.zip') as bundle:
        for slug, name, actor, model, profile, prefix in SUITS:
            materials = container_layout(bundle.read(actor.lower()+'.psx'))['textureHashes']
            source_entries = [e for e in entries if e['actor'] == actor]
            # SPIDEY includes an unpainted hidden-wing material; only eight
            # original body BMPs are present in this author's archive.
            mappings = {}
            for entry in source_entries:
                offset = int(Path(entry['source']).stem.rsplit('_', 1)[1], 16) + 28
                filename = f'{prefix}/{offset:08X}.bmp'
                if filename in archive.namelist():
                    mappings[filename] = materials[entry['textureIndex']]
            expected = {n for n in archive.namelist() if n.startswith(prefix+'/') and n.endswith('.bmp')}
            if len(mappings) != 8 or set(mappings) != expected:
                raise ValueError(f'Incomplete source material mapping for {actor}')
            out = args.output/slug
            (out/'textures').mkdir(parents=True)
            textures = {}
            for filename, material in sorted(mappings.items()):
                original = Image.open(io.BytesIO(archive.read(filename))).convert('RGB')
                relative = f'textures/{material:08X}.png'
                original.save(out/relative)
                with Image.open(out/relative) as converted:
                    if converted.size != original.size or converted.tobytes() != original.tobytes():
                        raise ValueError(f'Pixel mismatch: {filename}')
                textures[f'{material:08X}'] = relative
            manifest = dict(version=1, id=slug, name=name, comments='By Dat Mental Gamer',
                            model=model, abilities={'profile':profile}, textures=textures)
            if actor == 'SPSYMBI':
                # SM2's built-in Symbiote power profile still uses its shared
                # actor. Carry the unchanged SM1 donor so these hashes match.
                donor = bundle.read('spsymbi.psx')
                (out/'actor.psx').write_bytes(donor)
                assert (out/'actor.psx').read_bytes() == donor
                manifest['modelFile'] = 'actor.psx'
            (out/'suit.json').write_text(json.dumps(manifest, indent=2)+'\n')
            shutil.copy2(ROOT/'mods/suit-instructions.txt', out/'instructions.txt')
            (out/'README.md').write_text(
                f'# {name}\n\nBy Dat Mental Gamer (creator / porter).\n\n'
                'Source: https://gamebanana.com/mods/296326\n'
                'Author: https://gamebanana.com/members/1614404\n'
                'Original Spider-Man 3 Wii texture credits, as listed by the author:\n'
                'Beenox, Vicarious Visions and Treyarch.\n\n'
                'Eight original BMPs converted to PNG without resizing or pixel changes.\n'
                f'Uses the original {model} Dreamcast body and {profile} powers.\n'
                'Geometry, vertex ownership and animations are inherited unchanged.\n'
                'Install the complete folder in mods/suits in SM1 or SM2.\n')
            print(f'{name}: eight source textures mapped and pixel-verified')


if __name__ == '__main__':
    main()
