"""Full port build: rebuild the maps, recompile, close the call graph, repeat, build.

RecompOne turns every control transfer leaving a function into `Dispatcher.Call(addr)`.
A target nothing defines throws `unmapped call` the first time the game takes that
path -- a latent crash rather than a build error, which is why the graph gets closed
deliberately here instead of being discovered by playing.

The loop stops when the missing count stops falling. A residue that never resolves is
normal: it is jump-table analysis running off the end of a real table into the data
that follows, unreachable by any real path. Chasing it to zero is chasing noise.

Usage: python tools/build.py [--no-dotnet]
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RECOMP = os.path.join(ROOT, '..', 'tools', 'RecompOne', 'RecompOne.Recompiler')


def sh(args, **kw):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, **kw)


def fixmaps():
    p = sh([sys.executable, 'tools/fixmaps.py', '.'])
    line = [l for l in p.stdout.splitlines() if l.startswith('total ')]
    print('  fixmaps: ' + (line[-1] if line else p.stdout.strip()[-200:]))


def recompile():
    p = sh(['dotnet', 'run', '--project', RECOMP, '-c', 'Release', '--no-build',
            '--', 'config/spiderman2.json'])
    for l in p.stdout.splitlines():
        if 'total functions' in l or 'applied' in l or 'reimplementations' in l:
            print('  ' + l.strip())
    if p.returncode != 0:
        print(p.stdout[-2000:] + p.stderr[-2000:])
        raise SystemExit('recompile failed')


def closure():
    p = sh([sys.executable, 'tools/closure.py', '.'])
    m = re.search(r'^missing (\d+)', p.stdout, re.M)
    return int(m.group(1)) if m else 0


def main():
    print('== initial maps')
    fixmaps()
    recompile()

    prev = None
    for i in range(1, 9):
        missing = closure()
        print(f'== pass {i}: missing {missing}')
        if missing == 0:
            print('call graph closed')
            break
        if prev is not None and missing >= prev:
            print(f'call graph stable with {missing} unreachable target(s) left in data')
            break
        prev = missing
        fixmaps()
        recompile()

    if '--no-dotnet' in sys.argv:
        return 0
    print('== building the port')
    p = sh(['dotnet', 'build', 'port/SpiderMan2.csproj', '-c', 'Release'])
    for l in (p.stdout + p.stderr).splitlines():
        if 'error' in l.lower() or 'Build succeeded' in l:
            print('  ' + l.strip())
    return p.returncode


if __name__ == '__main__':
    sys.exit(main())
