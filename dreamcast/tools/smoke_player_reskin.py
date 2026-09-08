#!/usr/bin/env python3
"""Player-layout smoke: published EXE, real installer, drop-in mod, no asset overrides.

Run phases sequentially. The target must be outside the repository. Scripted input
is confined to the game's native harness, never host OS input. No desktop capture.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--install', type=Path, required=True)
    p.add_argument('--phase', choices=['setup', 'navigation', 'selection', 'gameplay', 'stock'], required=True)
    p.add_argument('--attempt', default='')
    p.add_argument('--game', choices=['sm1', 'sm2'], default='sm1')
    p.add_argument('--exe', type=Path)
    p.add_argument('--cue', type=Path)
    args = p.parse_args()
    exe_name = 'SpiderMan2.exe' if args.game == 'sm2' else 'SpiderMan.exe'
    target = args.install.resolve()
    if target.is_relative_to(ROOT):
        raise ValueError('Install outside the repository to exclude parent-directory asset discovery')
    for name in ['SpiderMan.exe', 'SpiderMan2.exe']:
        result = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {name}', '/FO', 'CSV', '/NH'],
                                capture_output=True, text=True, check=True)
        if f'"{name}"'.lower() in result.stdout.lower():
            raise RuntimeError('A game is already running; refusing to launch another')
    if args.phase == 'setup':
        if target.exists() or not args.exe or not args.cue:
            raise ValueError('Setup requires a fresh folder, --exe and --cue')
        target.mkdir(parents=True)
        shutil.copy2(args.exe, target / exe_name)
    elif not (target / 'game/recompone-disc.json').is_file():
        raise ValueError('Complete setup first')
    evidence = target / 'proof' / (args.phase + args.attempt)
    evidence.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('SPIDEY_', 'RECOMP_'))}
    command = [str(target / exe_name)]
    if args.phase == 'setup':
        # A CUE argument starts the actual windowed installer; no headless bypass.
        command.append(str(args.cue.resolve()))
        env['RECOMP_INSTALL_ONLY'] = '1'
    else:
        sample = target / 'mods/suits/magenta-man'
        if args.phase == 'selection':
            source = 'magenta-man-sm2' if args.game == 'sm2' else 'magenta-man'
            shutil.copytree(ROOT / 'mods/samples' / source, sample, dirs_exist_ok=True)
        elif args.phase == 'stock':
            # Reversible uninstall of only this smoke fixture.
            sample.rename(target / 'proof/removed-magenta-man')
        env.update(SPIDEY_SCRIPT_EXCLUSIVE='1', SPIDEY_CAPTURE_PRESENTED='1',
                   SPIDEY_SHOT_DIR=str(evidence), SPIDEY_LOG_DIR=str(evidence),
                   SPIDEY_TRACE_WAD='1', SPIDEY_MOD_TRACE='1',
                   RECOMP_RENDER_SCALE='4', SPIDEY_WIDE='1')
        if args.phase in ['navigation', 'selection']:
            script = ['title.bmr+120:start:12', 'title.bmr+300:right:12',
                      'title.bmr+500:down:12',
                      'title.bmr+900:cross:12', 'title.bmr+1200:cross:12']
            script += [f'title.bmr+{1600+i*30}:down:6' for i in range(20)]
            script += ['title.bmr+2300:cross:12']
            env.update(SPIDEY_SCRIPT=';'.join(script),
                       SPIDEY_SHOTS='title.bmr+1450,title.bmr+2250,title.bmr+2500',
                       SPIDEY_EXIT='title.bmr+2600')
            if args.phase == 'navigation':
                env.update(SPIDEY_SHOTS='title.bmr+350,title.bmr+800,title.bmr+1050',
                           SPIDEY_EXIT='title.bmr+1120')
        else:
            # Selection is restored from the file written by the real viewer.
            env.update(SPIDEY_SCRIPT=';'.join([
                'title.bmr+120:start:12', 'title.bmr+420:cross:12',
                'title.bmr+720:cross:12', 'title.bmr+1100:cross:12',
                'title.bmr+1500:cross:12', 'title.bmr+1900:cross:12']),
                SPIDEY_SHOTS='title.bmr+4000,title.bmr+4200',
                SPIDEY_EXIT='title.bmr+4300')
    if args.game == 'sm2' and args.phase != 'setup':
        # SM2 loads title.bmr before its intro movie. Normal Start/Cross presses
        # advance it; charlite.dat anchors navigation to the actual main menu.
        for key in ['SPIDEY_SCRIPT', 'SPIDEY_SHOTS', 'SPIDEY_EXIT']:
            env[key] = env[key].replace('title.bmr+', 'charlite.dat+')
        env['SPIDEY_SCRIPT'] = env['SPIDEY_SCRIPT'].replace('charlite.dat+120:start:12;', '')
        env['SPIDEY_SCRIPT'] = 'title.bmr+120:start:12;title.bmr+900:cross:12;' + env['SPIDEY_SCRIPT']
    trace = {k: v for k, v in env.items() if k.startswith(('SPIDEY_', 'RECOMP_'))}
    for forbidden in ['SPIDEY_DATA', 'SPIDEY_ASSET_DIR', 'RECOMP_ASSET_PACK_DIR',
                      'SPIDEY_SUIT_MOD_DIR', 'SPIDEY_COSTUME', 'SPIDEY_CHEATS',
                      'SPIDEY_BOOT_SKIP_UNTIL', 'RECOMP_INSTALL_HEADLESS']:
        assert forbidden not in env, forbidden
    (evidence / 'launch.json').write_text(json.dumps(dict(command=command, environment=trace,
        exe_sha256=hashlib.sha256((target / exe_name).read_bytes()).hexdigest()), indent=2))
    started = time.monotonic()
    with (evidence / 'console.log').open('w') as log:
        process = subprocess.Popen(command, cwd=target, env=env, stdout=log, stderr=subprocess.STDOUT)
        print(f'{args.phase}: PID {process.pid}; {target}', flush=True)
        try:
            code = process.wait(timeout=480)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
    report = dict(phase=args.phase, exit_code=code, seconds=round(time.monotonic()-started, 2),
                  frames=[f.name for f in sorted(evidence.glob('frame_*.png'))])
    (evidence / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    if code:
        raise SystemExit(code)
    if args.phase == 'setup':
        assert (target / 'game/recompone-disc.json').is_file()
        assert (target / 'assets/builtin/spidey.psx').is_file()
        assert Path(json.loads((target / 'settings.json').read_text())['CdPath']).resolve() == target / 'game'
    elif args.phase == 'selection':
        assert (target / 'mods/suits/selected-suit.txt').read_text().strip() == 'magenta-man'
    elif args.phase in ['gameplay', 'stock']:
        log = (evidence / 'console.log').read_text()
        assert '[suit-mod] active magenta-man' in log if args.phase == 'gameplay' else '[suit-mod] active magenta-man' not in log
    print('Structural checks passed; screenshots still require visual review.', flush=True)


if __name__ == '__main__':
    main()
