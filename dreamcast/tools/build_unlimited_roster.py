"""Reproduce the September 2026 Unlimited roster conversions in a fresh directory."""
import argparse, csv, hashlib, json, shutil, subprocess, sys
from pathlib import Path
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]
# Source costume, stable mod ID, display name, optional preparation arguments.
ROSTER = [('milesmorales', 'miles-morales', 'Miles Morales', None),
 ('amazing_spider', 'the-amazing-spider', 'The Amazing Spider', ['--amazing-cape', '--torso-ratio', '.55']),
 ('1602', '1602', '1602', ['--head-ratio', '.30', '--head-min', '5', '--torso-min', '5']),
 ('homemade', 'mcu-homemade', 'MCU Homemade', ['--head-ratio', '.30', '--head-min', '5', '--torso-min', '5']),
 ('endofearth', 'ends-of-the-earth', 'Ends of the Earth', None),
 ('bulletpoints', 'bullet-points', 'Bullet Points', None),
 ('spiderman_newdesign', 'all-new', 'All-New', None),
 ('secretwar', 'secret-war', 'Secret-War', None),
 ('ghost', 'ghost-spider', 'Ghost Spider', []),
 ('prodigy', 'prodigy', 'Prodigy', []),
 ('spdr',
  'sp-dr',
  'SP//DR',
  ['--head-ratio', '.40', '--torso-ratio', '.35', '--head-min', '5', '--torso-min', '5']),
 ('hornet', 'hornet', 'Hornet', []),
 ('buzz',
  'buzz',
  'Buzz',
  ['--head-ratio', '.45', '--torso-ratio', '.40', '--head-min', '5', '--torso-min', '5'])]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--collection', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--blender', type=Path, required=True)
    p.add_argument('--only', choices=[r[1] for r in ROSTER])
    a = p.parse_args()
    a.output = a.output.resolve()
    a.collection = a.collection.resolve()
    if a.output.exists() or a.output.is_relative_to(a.collection):
        raise ValueError('Use fresh output outside the source collection')
    a.output.mkdir(parents=True)
    rows = {r['Costume']: r for r in csv.DictReader((a.collection / 'costume-catalogue.csv').open(encoding='utf-8-sig'))}
    for source, slug, name, prep in ROSTER:
        if a.only and slug != a.only:
            continue
        row = rows[source]
        folder = a.output / (slug + '-source')
        original = a.collection / row['FBX']
        diffuse = a.collection / 'textures-png' / (Path(row['Diffuse textures']).stem + '.png')
        provenance = dict(sourceCostume=source, author='Gameloft', game='Spider-Man Unlimited', preparationArguments=prep, fbxSha256=hashlib.sha256(original.read_bytes()).hexdigest(), diffuseSha256=hashlib.sha256(diffuse.read_bytes()).hexdigest())
        if prep is not None:
            cmd = [a.blender, '--background', '--factory-startup', '--disable-autoexec', '-t', '2', '--python', ROOT / 'dreamcast/tools/prepare_unlimited_roster.py', '--', '--fbx', a.collection / row['FBX'], '--output', folder] + prep
            subprocess.run([str(x) for x in cmd], check=True)
            if not (folder / 'prepared.fbx').exists():
                raise RuntimeError('Blender preparation failed')
        else:
            folder.mkdir()
            shutil.copy2(a.collection / row['FBX'], folder / (source + '.fbx'))
        # Body diffuse alpha is a shader mask; preserve RGB and make it opaque.
        with Image.open(a.collection / 'textures-png' / (Path(row['Diffuse textures']).stem + '.png')) as im:
            im.convert('RGB').save(folder / 'Body_D_rgb.tga')
        build = a.output / slug
        subprocess.run([sys.executable, str(ROOT / 'dreamcast/tools/build_unlimited_actor.py'), '--source', str(folder), '--output', str(build), '--id', slug, '--name', name, '--blender', str(a.blender), '--opaque-diffuse'], check=True)
        mod = build / 'mods/suits' / slug
        shutil.copy2(ROOT / 'mods/suit-instructions.txt', mod / 'instructions.txt')
        (mod / 'README.md').write_text(f'# {name}\n\nBy Gameloft. Source: Spider-Man Unlimited.\nCustom native actor with standard Spider-Man powers in both games.\nOriginal diffuse RGB; native rigid joints and closed fists.\n' + ('Cape follows body joints; no independent cloth simulation.\n' if slug == 'the-amazing-spider' else ''))
        (build / 'source-provenance.json').write_text(json.dumps(provenance, indent=2))
        print(slug, 'structural pass; native visual review required', flush=True)
if __name__ == '__main__':
    main()
