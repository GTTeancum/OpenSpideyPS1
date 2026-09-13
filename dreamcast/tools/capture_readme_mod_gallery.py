#!/usr/bin/env python3
"""Capture README mod portraits and gameplay using hidden, windowed native rendering.
Uses existing extracted game data; never sends host input or shows a window.
Build the capture executables with RECOMP_CAPTURE_HIDDEN support before running.
"""
import json, os, shutil, subprocess, argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
ROSTER={'sm1':['last-stand-spiderman','spider-punk','noir'],'sm2':['infinity-war','hornet','ghost-spider']}
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--game',choices=['sm1','sm2','both'],default='both');args=parser.parse_args()
for game in (ROSTER if args.game=='both' else [args.game]):
    sm1=game=='sm1';proof=ROOT/'proof_render/readme-mod-gallery';package=ROOT/'proof_render/standalone-release'/game/'package'
    app=proof/'sm1-app' if sm1 else ROOT/'proof_render/readme-spdr/app'
    exe=app/('SpiderMan.exe' if sm1 else 'SpiderMan2.exe')
    settings=json.loads((package/'settings.json').read_text(encoding='utf-8'));settings.update(Muted=True,CardAEnabled=False,CardBEnabled=False,Widescreen=True)
    (app/'settings.json').write_text(json.dumps(settings,indent=2),encoding='utf-8')
    (app/'interface.ini').write_text('[RecompOne]\nWindowWidth=960\nWindowHeight=540\nVideoWidth=960\nVideoHeight=540\nRenderScale=4\nFullscreen=False\n')
    for suit in ROSTER[game]:
        output=proof/game/suit;output.mkdir(parents=True,exist_ok=True);suits=output/'suits';suits.mkdir(exist_ok=True)
        shutil.copytree(package/'mods/suits'/suit,suits/suit,dirs_exist_ok=True);(suits/'selected-suit.txt').write_text(suit)
        env={k:v for k,v in os.environ.items() if not k.startswith(('SPIDEY_','RECOMP_'))}
        env.update(RECOMP_CAPTURE_HIDDEN='1',SPIDEY_DATA=str(package/'game'),SPIDEY_ASSET_DIR=str(package/'assets/builtin'),SPIDEY_SUIT_MOD_DIR=str(suits),SPIDEY_BOOT_SKIP_UNTIL='title.bmr',SPIDEY_SCRIPT_EXCLUSIVE='1',SPIDEY_SHOT_DIR=str(output/'captures'))
        if sm1:
            env.update(SPIDEY_SCRIPT='title.bmr+120:start:12;title.bmr+420:cross:12;title.bmr+720:cross:12;title.bmr+1100:cross:12;title.bmr+1500:cross:12;title.bmr+1900:cross:12',SPIDEY_SHOTS='title.bmr+300,4300',SPIDEY_EXIT='4320')
        else:
            env.update(SPIDEY_SCRIPT='title.bmr+80:start:10;title.bmr+280:cross:10;title.bmr+480:cross:10;title.bmr+700:cross:10;e1m0_t.trg+1200:cross:8;e1m0_t.trg+1500:cross:8;e1m0_t.trg+1800:cross:8',SPIDEY_SHOTS='title.bmr+450,e1m0_t.trg+1968',SPIDEY_EXIT='3400')
        with (output/'run.log').open('w',encoding='utf-8') as log:
            result=subprocess.run([str(exe)],cwd=app,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
        captures=sorted((output/'captures').glob('frame_*.png'))
        assert result.returncode==0 and len(captures)==2,(game,suit,result.returncode,captures)
        assert '[suit-mod] active '+suit+':' in (output/'run.log').read_text(encoding='utf-8',errors='replace')
        (output/'result.json').write_text(json.dumps({'game':game,'suit':suit,'hidden':True,'fullscreen':False,'exitCode':result.returncode,'captures':[str(p.relative_to(ROOT)) for p in captures]},indent=2))
        print(game,suit,'captured',flush=True)
