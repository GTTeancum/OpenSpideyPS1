#!/usr/bin/env python3
"""Verify blank published launch and wrong-game rejection without desktop automation."""
import json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
for game,project,exe,other in [('sm1','spiderman','SpiderMan.exe','Spider-Man 2'),('sm2','spiderman2','SpiderMan2.exe','Spider-Man')]:
    proof=ROOT/'proof_render/standalone-release'/game/'first-launch';home=proof/'blank';home.mkdir(parents=True,exist_ok=True)
    target=home/exe
    if not target.exists(): os.link(ROOT/project/'port/dist'/exe,target)
    assert not (home/'game').exists()
    env={k:v for k,v in os.environ.items() if not k.startswith(('SPIDEY_','RECOMP_','DOTNET_BUNDLE_'))}
    env.update(RECOMP_HOST_PROOF=str(proof/'choose-disc.png'),RECOMP_HOST_PROOF_DELAY_MS='500')
    with (proof/'prompt.log').open('w') as log:
        process=subprocess.Popen([str(target)],cwd=home,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+20
            while not (proof/'choose-disc.png').exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.2)
            assert process.poll() is None, 'First launch exited instead of prompting'
            assert (proof/'choose-disc.png').exists(), 'No native prompt proof'
            assert not (home/'game').exists(), 'Published build borrowed developer data'
        finally:
            if process.poll() is None:process.terminate()
            process.wait(timeout=10)
    env.pop('RECOMP_HOST_PROOF');env.update(RECOMP_INSTALL_HEADLESS='1',RECOMP_INSTALL_ONLY='1')
    disc=next((ROOT/'proof_render/user-facing-stage/ready'/other).glob('*.cue'))
    result=subprocess.run([str(target),str(disc)],cwd=home,env=env,capture_output=True,text=True,timeout=20)
    (proof/'wrong-game.log').write_text(result.stdout+result.stderr)
    assert result.returncode==2 and 'does not identify' in result.stderr, result
    assert not (home/'game').exists()
    (proof/'result.json').write_text(json.dumps({'promptWithoutArguments':True,'noAncestorReuse':True,'wrongGameExitCode':result.returncode,'noExtractionOnRejection':True},indent=2))
    print(game, 'PASS prompt and wrong-game rejection')
