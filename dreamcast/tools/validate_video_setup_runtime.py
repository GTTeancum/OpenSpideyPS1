#!/usr/bin/env python3
"""Test native Video Setup with process-local input and native GPU captures only.

Run wide then minimum, or fullscreen-on then fullscreen-off: the second scenario
restarts with the settings saved by the first.
The executable's settings are backed up and restored; saves/cards are disabled.
No desktop input or desktop capture is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', choices=['sm1', 'sm2'], required=True)
    parser.add_argument('--scenario', choices=['wide', 'minimum', 'fullscreen-on', 'fullscreen-off'], required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'proof_render/video-setup-final')
    args = parser.parse_args()
    project, name = ('spiderman', 'SpiderMan') if args.game == 'sm1' else ('spiderman2', 'SpiderMan2')
    exe = (args.exe or ROOT / project / 'port/dist' / f'{name}.exe').resolve()
    home = exe.parent
    state = args.output.resolve() / args.game
    output = state / args.scenario
    output.mkdir(parents=True, exist_ok=True)
    files = ['settings.json', 'interface.ini']
    original = {f: (home / f).read_bytes() if (home / f).exists() else None for f in files}
    if args.scenario in ('wide', 'fullscreen-on'):
        source = original['settings.json'] or (ROOT / project / 'port/bin/Release/net10.0/settings.json').read_bytes()
        settings = json.loads(source)
        settings.update(Muted=True, CardAEnabled=False, CardBEnabled=False, ActiveMods=[], Widescreen=False)
        (state / 'settings.json').write_text(json.dumps(settings, indent=2))
        (state / 'interface.ini').write_text('[RecompOne]\nWindowWidth=664\nWindowHeight=524\n'
            'VideoWidth=640\nVideoHeight=480\nRenderScale=4\nFullscreen=False\n')
    elif not all((state / f).exists() for f in files):
        parser.error('Run wide or fullscreen-on first to create persisted settings.')

    events = [(120, 'start'), (420, 'down'), (500, 'down'), (580, 'cross'),
              (900, 'down'), (980, 'down'), (1060, 'cross')]
    entry = 1060
    if args.game == 'sm2':
        events += [(1500, 'down'), (1700, 'down'), (1800, 'cross')]
        entry = 1800
    events += [(entry + 340, 'right'), (entry + 440, 'down'),
               (entry + 540, 'right' if args.scenario == 'wide' else 'left'),
               (entry + 640, 'down'), (entry + 740, 'cross'),
               (entry + 940, 'triangle'), (entry + 1180, 'cross')]
    if args.scenario == 'minimum':
        # 720p maps to the nearest 4:3 height, 768; step through 600 to 480.
        events.append((entry + 590, 'left'))
        events.sort()
    if args.scenario.startswith('fullscreen-'):
        events = [(f, button) for f, button in events if f <= entry]
        events += [(entry + 340, 'down'), (entry + 440, 'down'),
                   (entry + 540, 'right'), (entry + 640, 'down'),
                   (entry + 740, 'cross'), (entry + 940, 'triangle'), (entry + 1180, 'cross')]
    else:
        events.append((entry + 690, 'down'))  # fullscreen is now row 2; Apply is row 3
        events.sort()
    shots = [entry + 220, entry + 850, entry + 1080, entry + 1400]
    if args.scenario in ('wide', 'fullscreen-on'):
        if args.scenario == 'fullscreen-on':
            events += [(entry + 1300, 'down'), (entry + 1380, 'down')]
        events += [(entry + 1460, 'right'), (entry + 1590, 'triangle'),
                   (entry + 1820, 'cross'), (entry + 2180, 'triangle')]
        shots += [entry + 2050]
        end = entry + 2750
    else:
        events += [(entry + 1520, 'triangle')]
        end = entry + 2100
    env = {k: v for k, v in os.environ.items() if not k.startswith('SPIDEY_')}
    env.pop('RECOMP_ASSET_PACK_DIR', None)
    env.update(SPIDEY_BOOT_SKIP_UNTIL='title.bmr', SPIDEY_SCRIPT_EXCLUSIVE='1',
        SPIDEY_SCRIPT=';'.join(f'title.bmr+{f}:{button}:8' for f, button in events),
        SPIDEY_SHOTS=','.join(f'title.bmr+{f}' for f in shots),
        SPIDEY_SHOT_DIR=str(output), SPIDEY_EXIT=str(end))
    try:
        for f in files:
            (home / f).write_bytes((state / f).read_bytes())
        with (output / 'run.log').open('w') as log:
            process = subprocess.Popen([str(exe)], cwd=home, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=190)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise
        assert code == 0, f'Game exit {code}'
        for f in files:
            (state / f).write_bytes((home / f).read_bytes())
    finally:
        for f, data in original.items():
            if data is not None:
                (home / f).write_bytes(data)
            else:
                (home / f).unlink(missing_ok=True)

    log = (output / 'run.log').read_text()
    wide = args.scenario == 'wide'
    fullscreen = args.scenario == 'fullscreen-on'
    triple = wide or fullscreen
    width, height = (1280, 720) if wide else (640, 480)
    expected = f'{width}x{height}'
    assert f'apply {expected} wide={wide} fullscreen={fullscreen}' in log
    if not fullscreen:
        assert f'output area {expected}; selected {expected}' in log
    assert f'[Host] fullscreen={fullscreen}; window state={"Fullscreen" if fullscreen else "Normal"}' in log
    saved = json.loads((state / 'settings.json').read_text())
    ini = (state / 'interface.ini').read_text()
    assert saved['Widescreen'] == wide
    assert f'VideoWidth={width}\n' in ini and f'VideoHeight={height}\n' in ini
    assert f'Fullscreen={fullscreen}\n' in ini
    assert log.count('[video-menu] opened') == (3 if triple else 2)
    assert log.count('[video-menu] closed; native OPTIONS restored') == (3 if triple else 2)
    assert log.count(f'opened {expected} wide={wide} fullscreen={fullscreen}') == (2 if triple else 1)
    if args.scenario == 'minimum':
        assert 'opened 1280x720 wide=True' in log, 'Applied settings failed to survive restart'
    if args.scenario == 'fullscreen-off':
        assert 'opened 640x480 wide=False fullscreen=True' in log, 'Fullscreen failed to survive restart'
    assert len(list(output.glob('frame_*.png'))) == len(shots)
    report = dict(game=args.game, scenario=args.scenario, executableSha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        selected=expected, widescreen=wide, fullscreen=fullscreen, nativeMenuOpens=3 if triple else 2,
        nativeMenuAllocationsFreed=log.count('arena free native video menu labels'),
        outputAreaVerified=not fullscreen, fullscreenStateVerified=True, settingsVerified=True,
        captures=[str(p) for p in sorted(output.glob('frame_*.png'))])
    assert report['nativeMenuAllocationsFreed'] == report['nativeMenuOpens']
    (output / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
