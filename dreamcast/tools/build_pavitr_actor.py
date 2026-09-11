"""Build a native suit mod from an Unlimited FBX using the Clown001 rig.

The output includes an installable mods/suits package with its custom native actor.
Source files are read-only. No game is launched and no installed bundle is changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
import re
import shutil

from pack_sm2_costume_to_dc import resolve_multitool

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--blender', type=Path, required=True)
    parser.add_argument('--multitool', type=Path)
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--opaque-diffuse', action='store_true', help='Treat body diffuse alpha as a shader mask, not transparency')
    parser.add_argument('--id', default='pavitr-prabhakar')
    parser.add_argument('--name', default='Pavitr Prabhakar')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]{1,48}', args.id) or not 1 <= len(args.name) <= 18:
        raise ValueError('Use a lowercase mod id and a display name of at most 18 characters')
    source, output = args.source.resolve(), args.output.resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError('Keep generated files outside the source directory')
    if output.exists():
        raise ValueError('Use a fresh output directory to avoid stale proof artifacts')
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in source.iterdir() if p.is_file()}
    multitool = resolve_multitool(args.multitool)
    output.mkdir(parents=True)

    def run(name, command):
        with (output / (name + '.log')).open('w', encoding='utf-8') as log:
            subprocess.run([str(p) for p in command], cwd=ROOT, stdout=log,
                           stderr=subprocess.STDOUT, check=True)

    with zipfile.ZipFile(ROOT / 'spiderman/port/bundled/runtime-assets.zip') as archive:
        (output / 'donor.psx').write_bytes(archive.read('spidey.psx'))
    run('donor-dump', [multitool, 'psx-mesh-dump', output / 'donor.psx',
                       '--json', output / 'donor-dump.json'])
    command = [args.blender, '--background', '--factory-startup', '--disable-autoexec',
               '-t', '2', '--python', ROOT / 'dreamcast/tools/fit_pavitr_actor.py',
               '--', '--source', source, '--output', output]
    if args.preview:
        command.append('--preview')
    run('fit', command)
    # Blender may return zero after a Python exception; require the actual output.
    if not (output / 'fitted.json').is_file():
        raise RuntimeError('Blender did not produce fitted geometry; see fit.log')
    run('pack', [sys.executable, ROOT / 'dreamcast/tools/pack_pavitr_actor.py',
                 '--source', source, '--output', output, '--id', args.id, '--name', args.name]
                 + (['--opaque-diffuse'] if args.opaque_diffuse else []))
    run('native-dump', [multitool, 'psx-mesh-dump', output / 'assets/spidey.psx',
                        '--json', output / 'native-dump.json'])
    dump = json.loads((output / 'native-dump.json').read_text())
    report = json.loads((output / 'native-report.json').read_text())
    if any(m['StitchFailureCount'] or m['VertexCount'] > 256 or
           any(f.get('RejectionReason') for f in m['FaceReads']) for m in dump['Meshes']):
        raise RuntimeError('Native parse, vertex capacity, or attachment validation failed')
    if sum(m['FaceCount'] for m in dump['Meshes']) != report['storedTrianglesWithAlternateHands']:
        raise RuntimeError('Native parser did not retain every emitted triangle')
    if sources != {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in source.iterdir() if p.is_file()}:
        raise RuntimeError('Source files changed during conversion')
    mod = output / 'mods' / 'suits' / args.id
    (mod / 'textures').mkdir(parents=True)
    shutil.copy2(output / 'assets/spidey.psx', mod / 'actor.psx')
    shutil.copy2(output / 'assets/packs' / args.id / 'textures/diffuse.png', mod / 'textures/diffuse.png')
    (mod / 'suit.json').write_text(json.dumps({'version': 1, 'id': args.id, 'name': args.name,
        'comments': 'Spider-Man Unlimited', 'model': 'spiderman', 'modelFile': 'actor.psx',
        'abilities': {'profile': 'spiderman'}, 'textures': {report['materialId']: 'textures/diffuse.png'}}, indent=2)+'\n')
    report.update(opaqueDiffuse=args.opaque_diffuse, sourceFiles=sources, modId=args.id, modDirectory=str(mod), status='structural-pass-native-visual-review-required',
                  limitations=['Clown001 rig only; other rigs need mapping review',
                               'Dominant-bone animation, not blended runtime skinning',
                               'Both native hand variants use fists; separate web-shooting hand poses are not yet authored',
                               'Normal and specular maps are not used by the native shader'])
    (output / 'native-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Structural pass: {report["sourceTriangles"]} source triangles; {output}')


if __name__ == '__main__':
    main()
