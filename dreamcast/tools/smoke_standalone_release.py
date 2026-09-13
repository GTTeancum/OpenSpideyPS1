#!/usr/bin/env python3
"""Fresh EXE+mods installation smoke. Only the game's process-local input/capture harness is used."""
import argparse, json, os, shutil, subprocess, time, zipfile
from pathlib import Path
import psutil
ROOT = Path(__file__).resolve().parents[2]
a=argparse.ArgumentParser(); a.add_argument('--game',choices=['sm1','sm2'],required=True); a.add_argument('--restart',action='store_true'); args=a.parse_args()
sm1=args.game=='sm1'; name='Spider-Man' if sm1 else 'Spider-Man 2'; exe='SpiderMan.exe' if sm1 else 'SpiderMan2.exe'
proof=ROOT/'proof_render/standalone-release'/args.game; package=proof/'package'; package.mkdir(parents=True,exist_ok=True)
ready=ROOT/'proof_render/user-facing-stage/ready'/name
if not args.restart:
    if (package/'game').exists(): raise SystemExit('Fresh test refuses an existing game directory')
    shutil.copy2(ROOT/('spiderman' if sm1 else 'spiderman2')/'port/dist'/exe,package/exe)
    for folder in sorted((ready/'mods/suits').iterdir()):
        if folder.is_dir() and (folder/'suit.json').exists(): shutil.copytree(folder,package/'mods/suits'/folder.name,dirs_exist_ok=True)
    for item in (ready/'mods').glob('*.md'): shutil.copy2(item,package/'mods'/item.name)
    for item in (ready/'mods/suits').glob('*.md'): shutil.copy2(item,package/'mods/suits'/item.name)
    (package/'START_HERE.txt').write_text(f'{name}\n\nExtract this archive to a writable folder, keeping mods beside the EXE.\nLaunch {exe} and select your USA BIN/CUE or ISO. Keep BIN files referenced by a CUE together.\nSetup extracts the assets once and starts the game. The source image is not needed afterward.\nNo separate .NET or Visual C++ installation is required. Windows and the graphics driver remain system requirements.\nOPTIONS > VIDEO SETUP controls resolution, aspect ratio and fullscreen.\nCostumes are available in the in-game suit selector. See the instructions inside mods.\nUse an original raw dump to retain XA audio/video; cooked ISOs cannot restore discarded data.\n')
    shutil.copy2(ROOT/'tools/RecompOne/native/win-x64/README.md',package/'NATIVE_RUNTIME_NOTICE.md')
    with zipfile.ZipFile(proof/(name+'.zip'),'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for item in sorted(package.rglob('*')):
            if item.is_file(): z.write(item,item.relative_to(package))
    (proof/'initial-inventory.json').write_text(json.dumps([str(p.relative_to(package)) for p in package.rglob('*') if p.is_file()],indent=2))
mode='restart-mod' if args.restart else 'fresh-stock'; output=proof/mode;output.mkdir(exist_ok=True)
env={k:v for k,v in os.environ.items() if not k.startswith(('SPIDEY_','RECOMP_','DOTNET_BUNDLE_'))}
env.update(SPIDEY_SCRIPT_EXCLUSIVE='1', SPIDEY_BOOT_SKIP_UNTIL='title.bmr',SPIDEY_SHOT_DIR=str(output),RECOMP_HOST_PROOF=str(output/'installer-or-window.png'),RECOMP_HOST_PROOF_DELAY_MS='500')
if sm1:
    env.update(SPIDEY_SCRIPT='title.bmr+120:start:12;title.bmr+420:cross:12;title.bmr+720:cross:12;title.bmr+1100:cross:12;title.bmr+1500:cross:12;title.bmr+1900:cross:12',SPIDEY_SHOTS='title.bmr+300,4300,4400',SPIDEY_EXIT='4450')
else:
    env.update(SPIDEY_SCRIPT='title.bmr+80:start:10;title.bmr+280:cross:10;title.bmr+480:cross:10;title.bmr+700:cross:10;e1m0_t.trg+1200:cross:8;e1m0_t.trg+1500:cross:8;e1m0_t.trg+1800:cross:8',SPIDEY_SHOTS='title.bmr+450,e1m0_t.trg+1968',SPIDEY_EXIT='6000')
command=[str(package/exe)]
if args.restart:
    mod=json.loads((package/'mods/suits/miles-morales/suit.json').read_text())
    (package/'mods/suits/selected-suit.txt').write_text(mod['id'])
else:
    command.append(str(next(ready.glob('*.cue'))))
start=time.monotonic(); modules={}
with (output/'stdout.log').open('w') as out,(output/'stderr.log').open('w') as err:
    proc=subprocess.Popen(command,cwd=package,env=env,stdout=out,stderr=err)
    while proc.poll() is None:
        if time.monotonic()-start>330: proc.terminate();raise SystemExit('Smoke timed out')
        try:
            for mod in psutil.Process(proc.pid).memory_maps():
                if Path(mod.path).name.lower() in ['vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll','glfw3.dll','soft_oal.dll','nfd.dll']: modules[Path(mod.path).name.lower()]=mod.path
        except (psutil.NoSuchProcess,psutil.AccessDenied): pass
        time.sleep(3)
result={'exitCode':proc.returncode,'elapsedSeconds':round(time.monotonic()-start,1),'modules':modules,'screens':[p.name for p in output.glob('*.png')],'imageArgument':command[1:]}
(output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
assert proc.returncode==0,result
for dll in ['vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll']: assert '.net' in modules.get(dll,''), (dll,modules)
assert (package/'game/recompone-disc.json').exists()
assert len(list(output.glob('frame_*.png'))) >= 2
