#!/usr/bin/env python3
"""One process, private saves/settings, process-local input, native game captures only."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--mode', choices=['viewer', 'selection', 'gameplay'], default='viewer')
    p.add_argument('--profile', default='spiderman')
    p.add_argument('--exe', type=Path, help='optional published SM1 executable to copy into the private runtime')
    p.add_argument('--mod-dir', type=Path, help='optional suit folder to copy instead of the sample')
    p.add_argument('--mods-root', type=Path, help='optional suits root to copy for in-process selection cycling')
    p.add_argument('--no-mods', action='store_true', help='run with stock game content only')
    p.add_argument('--selected-suit', help='seed selected-suit.txt without forcing a per-frame costume override')
    p.add_argument('--no-costume-override', action='store_true', help='allow the live costume viewer to change the selected suit')
    p.add_argument('--data', type=Path, help='optional loose-disc directory')
    p.add_argument('--assets', type=Path, help='optional built-in asset directory')
    p.add_argument('--shots', help='optional absolute comma-separated capture frames')
    p.add_argument('--exit-frame', type=int, help='optional absolute exit frame')
    p.add_argument('--sdk-trace', action='store_true', help='trace CD/XA SDK calls')
    p.add_argument('--trace-texture-registry', action='store_true', help='trace external texture registry changes')
    p.add_argument('--no-stall-exit', action='store_true', help='leave the diagnostic watchdog disabled')
    p.add_argument('--timeout', type=int, default=150, help='process timeout in seconds')
    p.add_argument('--render-scale', type=int, default=4, help='modern-renderer integer scale')
    p.add_argument('--hz', type=int, choices=range(10, 61), help='override presentation/GPU cadence')
    p.add_argument('--vblank-step', type=int, choices=range(1, 5), help='override emulated vblanks delivered per frame')
    p.add_argument('--no-perspective-trace', action='store_true', help='disable verbose perspective counters')
    p.add_argument('--snap-projected-vertices', action='store_true', help='A/B integer-snapped projected positions while retaining depth-correct UVs')
    p.add_argument('--sample-memory', action='store_true', help='write one-second process memory samples')
    p.add_argument('--script', help='optional process-local input script')
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
    if args.exe:
        shutil.copy2(args.exe.resolve(), exe_dir / 'SpiderMan.exe')
    else:
        build = ROOT / 'spiderman/port/bin/Release/net10.0'
        for item in build.iterdir():
            if item.is_file() and (item.suffix in ['.exe', '.dll'] or item.name.endswith(('.deps.json', '.runtimeconfig.json'))):
                shutil.copy2(item, exe_dir / item.name)
        if (build / 'runtimes').exists():
            shutil.copytree(build / 'runtimes', exe_dir / 'runtimes')
    suits = exe_dir / 'mods/suits'
    source_mod = args.mod_dir.resolve() if args.mod_dir else ROOT / 'mods/samples/magenta-man'
    mod_id = None
    if args.no_mods:
        if args.mod_dir or args.mods_root or args.selected_suit:
            raise RuntimeError('--no-mods cannot be combined with mod selection arguments')
    elif args.mods_root:
        copied_ids = []
        for candidate in sorted(args.mods_root.resolve().iterdir()):
            manifest_path = candidate / 'suit.json'
            if not candidate.is_dir() or not manifest_path.is_file():
                continue
            candidate_id = json.loads('\n'.join(
                line for line in manifest_path.read_text().splitlines()
                if not line.lstrip().startswith('//')
            ))['id']
            shutil.copytree(candidate, suits / candidate_id)
            copied_ids.append(candidate_id)
        if not copied_ids:
            raise RuntimeError(f'no suit manifests found under {args.mods_root}')
        mod_id = args.selected_suit or copied_ids[0]
        if mod_id not in copied_ids:
            raise RuntimeError(f'selected suit {mod_id!r} was not copied from {args.mods_root}')
    else:
        mod_id = json.loads('\n'.join(
            line for line in (source_mod / 'suit.json').read_text().splitlines()
            if not line.lstrip().startswith('//')
        ))['id']
        sample = suits / mod_id
        shutil.copytree(source_mod, sample)
    if not args.no_mods and not args.mod_dir and not args.mods_root:
        # Test fixture only: the shipped sample manifest is left unchanged.
        manifest = (sample / 'suit.json').read_text()
        (sample / 'suit.json').write_text(manifest.replace('"profile": "spiderman"', f'"profile": "{args.profile}"'))
    if args.selected_suit:
        suits.mkdir(parents=True, exist_ok=True)
        (suits / 'selected-suit.txt').write_text(args.selected_suit + '\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('SPIDEY_', 'RECOMP_'))}
    env.update(RECOMP_RENDER_SCALE=str(args.render_scale), RECOMP_FXAA='1', SPIDEY_WIDE='1',
               SPIDEY_DATA=str(args.data.resolve() if args.data else ROOT / 'proof_render/first-run-installer/valid-sm1/game'),
               SPIDEY_ASSET_DIR=str(args.assets.resolve() if args.assets else ROOT / 'proof_render/first-run-installer/valid-sm1/assets/builtin'),
               SPIDEY_CAPTURE_PRESENTED='1', SPIDEY_SCRIPT_EXCLUSIVE='1', SPIDEY_BOOT_SKIP_UNTIL='title.bmr',
               SPIDEY_SHOT_DIR=str(out), SPIDEY_LOG_DIR=str(out),
               SPIDEY_TRACE_WAD='1')
    if not args.no_stall_exit:
        env['SPIDEY_STALL_EXIT'] = '1'
    if not args.no_perspective_trace:
        env['RECOMP_PERSPECTIVE_TRACE'] = '1'
    if args.snap_projected_vertices:
        env['RECOMP_SNAP_PROJECTED_VERTICES'] = '1'
    if args.hz:
        env['SPIDEY_HZ'] = str(args.hz)
    if args.vblank_step:
        env['SPIDEY_VBLANK'] = str(args.vblank_step)
    env['SPIDEY_MOD_TRACE'] = '1'
    if args.trace_texture_registry:
        env['RECOMP_TRACE_TEXTURE_REGISTRY'] = '1'
    if args.sdk_trace:
        env['SPIDEY_LOG'] = 'sdk'
    if args.mode == 'gameplay':
        if not args.no_mods and not args.no_costume_override:
            env['SPIDEY_COSTUME'] = mod_id
        env['SPIDEY_SCRIPT'] = 'title.bmr+120:start:12;title.bmr+420:cross:12;title.bmr+720:cross:12;title.bmr+1100:cross:12;title.bmr+1500:cross:12;title.bmr+1900:cross:12'
        env['SPIDEY_SHOTS'] = '4300,4400'
        env['SPIDEY_EXIT'] = '4450'
    else:
        env['SPIDEY_CHEATS'] = 'everything,viewers'
        env['SPIDEY_SCRIPT'] = ';'.join(['title.bmr+120:start:12', 'title.bmr+300:right:12',
            'title.bmr+500:down:12', 'title.bmr+700:down:12', 'title.bmr+900:cross:12', 'title.bmr+1200:cross:12'])
        if args.mode == 'viewer':
            env['SPIDEY_COSTUME'] = mod_id
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
    if args.shots:
        env['SPIDEY_SHOTS'] = args.shots
    if args.exit_frame:
        env['SPIDEY_EXIT'] = str(args.exit_frame)
    if args.script:
        env['SPIDEY_SCRIPT'] = args.script
    (out / 'test-environment.json').write_text(json.dumps({k:v for k,v in env.items() if k.startswith(('SPIDEY_', 'RECOMP_'))}, indent=2))
    with (out / 'console.log').open('w') as log:
        proc = subprocess.Popen([str(exe_dir / 'SpiderMan.exe')], cwd=exe_dir, env=env, stdout=log, stderr=subprocess.STDOUT)
        print(f'PID {proc.pid}, {args.mode}, {out}', flush=True)
        if args.sample_memory:
            import psutil
            monitored = psutil.Process(proc.pid)
            deadline = time.monotonic() + args.timeout
            started = time.monotonic()
            samples = []
            while proc.poll() is None and time.monotonic() < deadline:
                try:
                    memory = monitored.memory_info()
                    samples.append((time.monotonic() - started, memory.rss, memory.vms))
                except psutil.Error:
                    pass
                time.sleep(1)
            if proc.poll() is None:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(proc.args, args.timeout)
            code = proc.returncode
            with (out / 'memory.csv').open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(('elapsed_seconds', 'working_set_bytes', 'virtual_bytes'))
                writer.writerows(samples)
        else:
            try:
                code = proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
    print(f'exit {code}; {len(list(out.glob("frame_*.png")))} native captures', flush=True)
    if code:
        raise SystemExit(code)


if __name__ == '__main__':
    main()
