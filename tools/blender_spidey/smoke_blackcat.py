"""Run the opening Black Cat scene with process-local input and native captures."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--game', type=Path, required=True, help='Directory containing SpiderMan.exe and settings.json')
p.add_argument('--assets', type=Path, required=True, help='Exported assets directory')
p.add_argument('--output', type=Path, required=True, help='Fresh private test directory')
a = p.parse_args()
a.output = a.output.resolve()
a.output.mkdir(parents=True, exist_ok=False)
runtime = a.output/'runtime'
runtime.mkdir()
shutil.copy2(a.game/'SpiderMan.exe', runtime/'SpiderMan.exe')
settings = json.loads((a.game/'settings.json').read_text())
settings.update(Muted=True, CardAEnabled=False, CardBEnabled=False, ActiveMods=[])
(runtime/'settings.json').write_text(json.dumps(settings))
env = os.environ.copy()
env.update(SPIDEY_ASSET_DIR=str(a.assets.resolve()), SPIDEY_LEVEL='l1a1',
           SPIDEY_BOOT_SKIP_UNTIL='title.bmr', SPIDEY_SCRIPT_EXCLUSIVE='1', SPIDEY_WIDE='1',
           SPIDEY_SCRIPT='title.bmr+120:start:12;title.bmr+420:cross:12;title.bmr+720:cross:12;title.bmr+1100:cross:12;title.bmr+1500:cross:12',
           SPIDEY_SHOTS=','.join('l1a1.vab+'+str(n) for n in [1000,1200,1400,1600,1900,2200]),
           SPIDEY_SHOT_DIR=str(a.output/'captures'), SPIDEY_EXIT='l1a1.vab+2250', SPIDEY_TRACE_WAD='1')
(a.output/'route.json').write_text(json.dumps({k:v for k,v in env.items() if k.startswith('SPIDEY_')},indent=2))
with (a.output/'console.log').open('w') as log:
    subprocess.run([str(runtime/'SpiderMan.exe')], cwd=runtime, env=env,
                   stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
text = (a.output/'console.log').read_text()
assert 'override blackcat.psx' in text and '[capture] exit at frame' in text
assert 'Out of VRAM' not in text
assert len(list((a.output/'captures').glob('frame_*.png'))) == 6
print('Native run complete. Review each capture before installing the actor.')
