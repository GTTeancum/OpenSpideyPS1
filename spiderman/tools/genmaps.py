"""Linear-sweep function maps for Spider-Man's main executable and every overlay.

A sweep decodes every word as a possible instruction, so anything in the data that
happens to look like a `jal` invents a function start inside a real function. The
output is raw material: keep it as `*_sweep.json`, never edit it, and let fixmaps.py
derive the refined maps from it.

Overlays are swept from the pre-relocated images under config/overlays rather than
from the disc, because the bytes on the disc are not the bytes that execute -- see
tools/overlays.py.

Usage:
    python tools/genmaps.py [--force] [name ...]
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RECOMP = os.path.join(ROOT, '..', 'tools', 'RecompOne', 'RecompOne.Recompiler')
GAME_DATA = os.path.join(ROOT, 'extracted')
OUT = os.path.join(ROOT, 'config', 'funcmaps')

MAIN_BASE = '0x80010000'
MAIN_FILE = 'SLUS_008.75'
MAIN_SKIP = '800'        # PS-X EXE header, hex
MAIN_SIZE = 'B6800'      # t_size from the header, hex


def run(args):
    cmd = ['dotnet', 'run', '--project', RECOMP, '-c', 'Release', '--no-build', '--'] + args
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    tail = (p.stdout + p.stderr).strip().splitlines()
    return p.returncode, tail[-1] if tail else '(no output)'


def main():
    force = '--force' in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith('--')]
    os.makedirs(OUT, exist_ok=True)
    manifest = json.load(open(os.path.join(ROOT, 'config', 'overlays', 'manifest.json')))

    jobs = [('main', ['-disc', GAME_DATA, '-base', MAIN_BASE, '-file', MAIN_FILE,
                      '-skip', MAIN_SKIP, '-size', MAIN_SIZE])]
    for name, v in manifest.items():
        jobs.append((name, ['-base', v['base'], '-path',
                            os.path.join('config', 'overlays', name + '.bin')]))

    failed = []
    for name, args in jobs:
        if only and name not in only:
            continue
        dst = os.path.join(OUT, f'{name}_sweep.json')
        if os.path.exists(dst) and not force:
            print(f'skip {name} (exists)')
            continue
        rc, last = run(['--generate-function-file', '-linear-sweep'] + args + ['-out', dst])
        status = 'ok ' if rc == 0 else 'FAIL'
        print(f'{status} {name:12s} {last}')
        if rc != 0:
            failed.append(name)

    if failed:
        print(f'\n{len(failed)} failed: {" ".join(failed)}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
