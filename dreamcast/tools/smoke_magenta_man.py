#!/usr/bin/env python3
"""One process, private saves/settings, process-local input, native game captures only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--mode', choices=['viewer', 'selection', 'gameplay'], default='viewer')
    p.add_argument('--profile', default='spiderman')
    args = p.parse_args()
    for process in ['SpiderMan.exe', 'SpiderMan2.exe']:
        result = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {process}', '/FO', 'CSV', '/NH'], capture_output=True, text=True)
        if f'"{process}"'.lower() in result.stdout.lower():
            raise RuntimeError('another game process is running; refusing to launch')
    out = args.output.resolve()
    if out.exists():
        raise RuntimeError('use a new proof directory to preserve earlier evidence')
    exe_dir = out / 'runtime'
    exe_dir.mkdir(parents=True)
    build = ROOT / 'spiderman/port/bin/Release/net10.0'
    for item in build.iterdir():
        if item.is_file() and (item.suffix in ['.exe', '.dll'] or item.name.endswith(('.deps.json', '.runtimeconfig.json'))):
            shutil.copy2(item, exe_dir / item.name)
    if (build / 'runtimes').exists():
        shutil.copytree(build / 'runtimes', exe_dir / 'runtimes')
    suits = exe_dir / 'mods/suits'
    sample = suits / 'magenta-man'
    shutil.copytree(ROOT / 'mods/samples/magenta-man', sample)
    # Test fixture only: the shipped sample manifest is left unchanged.
    manifest = (sample / 'suit.json').read_text()
    (sample / 'suit.json').write_text(manifest.replace('"profile": "spiderman"', f'"profile": "{args.profile}"'))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('SPIDEY_', 'RECOMP_'))}
    env.update(RECOMP_RENDER_SCALE='4', RECOMP_FXAA='1', SPIDEY_WIDE='1',
               SPIDEY_DATA=str(ROOT / 'proof_render/first-run-installer/valid-sm1/game'),
               SPIDEY_ASSET_DIR=str(ROOT / 'proof_render/first-run-installer/valid-sm1/assets/builtin'),
               SPIDEY_CAPTURE_PRESENTED='1', SPIDEY_SCRIPT_EXCLUSIVE='1', SPIDEY_BOOT_SKIP_UNTIL='title.bmr',
               SPIDEY_HZ='60', SPIDEY_SHOT_DIR=str(out), SPIDEY_LOG_DIR=str(out),
               SPIDEY_TRACE_WAD='1', SPIDEY_STALL_EXIT='1')
    env['SPIDEY_MOD_TRACE'] = '1'
    if args.mode == 'gameplay':
        env['SPIDEY_COSTUME'] = 'magenta-man'
        env['SPIDEY_SCRIPT'] = 'title.bmr+120:start:12;title.bmr+420:cross:12;title.bmr+720:cross:12;title.bmr+1100:cross:12;title.bmr+1500:cross:12;title.bmr+1900:cross:12'
        env['SPIDEY_SHOTS'] = '4300,4400'
        env['SPIDEY_EXIT'] = '4450'
    else:
        env['SPIDEY_CHEATS'] = 'everything,viewers'
        env['SPIDEY_SCRIPT'] = ';'.join(['title.bmr+120:start:12', 'title.bmr+300:right:12',
            'title.bmr+500:down:12', 'title.bmr+700:down:12', 'title.bmr+900:cross:12', 'title.bmr+1200:cross:12'])
        if args.mode == 'viewer':
            env['SPIDEY_COSTUME'] = 'magenta-man'
            env['SPIDEY_SHOTS'] = 'title.bmr+1500,title.bmr+1700'
            env['SPIDEY_EXIT'] = 'title.bmr+1800'
        else:
            # Actual menu selection, not a per-frame costume override. This list does not wrap.
            env['SPIDEY_SCRIPT'] += ''.join(f';title.bmr+{1600+i*30}:down:6' for i in range(20))
            env['SPIDEY_SCRIPT'] += ';title.bmr+2300:cross:12'
            env['SPIDEY_SCRIPT'] += ''.join(f';title.bmr+{2700+i*30}:up:6' for i in range(20))
            env['SPIDEY_SCRIPT'] += ';title.bmr+3400:cross:12'
            env['SPIDEY_SHOTS'] = 'title.bmr+1450,title.bmr+2500,title.bmr+3650'
            env['SPIDEY_EXIT'] = 'title.bmr+3800'
    (out / 'test-environment.json').write_text(json.dumps({k:v for k,v in env.items() if k.startswith(('SPIDEY_', 'RECOMP_'))}, indent=2))
    with (out / 'console.log').open('w') as log:
        proc = subprocess.Popen([str(exe_dir / 'SpiderMan.exe')], cwd=exe_dir, env=env, stdout=log, stderr=subprocess.STDOUT)
        print(f'PID {proc.pid}, {args.mode}, {out}', flush=True)
        try:
            code = proc.wait(timeout=150)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise
    print(f'exit {code}; {len(list(out.glob("frame_*.png")))} native captures', flush=True)
    if code:
        raise SystemExit(code)


if __name__ == '__main__':
    main()
