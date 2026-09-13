"""Sequential stock/all-Black-Cat L1A1 baseline, using only child-local input."""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import struct
import time
import psutil

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--game',type=Path,required=True)
p.add_argument('--assets',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--runs',nargs='+',choices=['stock','blackcats'],default=['stock','blackcats'])
p.add_argument('--crowd',action='store_true',help='Use the opt-in native crowd draw fixture')
p.add_argument('--full-roster',action='store_true',help='Activate all nine authored L1A1 character records and soak')
a=p.parse_args()
a.output=a.output.resolve()
a.output.mkdir(parents=True,exist_ok=False)
results=[]
for name in a.runs:
    folder=a.output/name
    runtime=folder/'runtime'
    runtime.mkdir(parents=True)
    shutil.copy2(a.game/'SpiderMan.exe',runtime/'SpiderMan.exe')
    settings=json.loads((a.game/'settings.json').read_text())
    settings.update(Muted=True,CardAEnabled=False,CardBEnabled=False,ActiveMods=[])
    (runtime/'settings.json').write_text(json.dumps(settings))
    env={k:v for k,v in os.environ.items() if not k.startswith('SPIDEY_')}
    env.update(SPIDEY_LEVEL='l1a1',SPIDEY_BOOT_SKIP_UNTIL='title.bmr',
        SPIDEY_SCRIPT_EXCLUSIVE='1',SPIDEY_WIDE='1',SPIDEY_TRACE_WAD='1',SPIDEY_TRACE_RENDER='1',SPIDEY_PACKET_TRACE='1',
        SPIDEY_SCRIPT='title.bmr+120:start:12;title.bmr+420:cross:12;title.bmr+720:cross:12;title.bmr+1100:cross:12;title.bmr+1500:cross:12',
        SPIDEY_SHOTS='l1a1.vab+1400,l1a1.vab+1900,l1a1.vab+2800',
        SPIDEY_SHOT_DIR=str(folder/'captures'),SPIDEY_EXIT='l1a1.vab+2900',
        SPIDEY_RAMDUMP='3300',SPIDEY_RAMDIR=str(folder/'ram'))
    if name=='blackcats':env['SPIDEY_ASSET_DIR']=str(a.assets.resolve())
    if a.crowd:
        env.update(SPIDEY_BASELINE_CROWD='1',SPIDEY_SHOTS='3600,3800,4000',
                   SPIDEY_EXIT='4100',SPIDEY_RAMDUMP='3300,3900,4080')
    if a.full_roster:
        env.pop('SPIDEY_BASELINE_CROWD',None)
        env.update(SPIDEY_BASELINE_ROSTER='1',SPIDEY_SHOTS='3900,4800,6600',
                   SPIDEY_EXIT='7200',SPIDEY_RAMDUMP='3300,3900,6600,7080')
    (folder/'route.json').write_text(json.dumps({k:v for k,v in env.items() if k.startswith('SPIDEY_')},indent=2))
    samples=[]
    start=time.monotonic()
    with (folder/'console.log').open('w') as log:
        process=subprocess.Popen([str(runtime/'SpiderMan.exe')],cwd=runtime,env=env,stdout=log,stderr=subprocess.STDOUT)
        probe=psutil.Process(process.pid)
        try:
            while process.poll() is None:
                if time.monotonic()-start>240:raise TimeoutError('Native route exceeded 240 seconds')
                try:
                    m=probe.memory_info()
                    samples.append(dict(seconds=time.monotonic()-start,private=m.private,workingSet=m.rss,cpuSeconds=sum(probe.cpu_times()[:2])))
                except psutil.NoSuchProcess:break
                time.sleep(.5)
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
    text=(folder/'console.log').read_text()
    result=dict(run=name,exitCode=process.returncode,seconds=time.monotonic()-start,
        peakPrivateBytes=max(x['private'] for x in samples),peakWorkingSetBytes=max(x['workingSet'] for x in samples),
        samples=samples)
    peaks=[int(x) for x in re.findall(r'\[frame-packets\] peak=(\d+)',text)]
    result['peakFramePacketBytes']=max(peaks,default=0)
    (folder/'metrics.json').write_text(json.dumps(result,indent=2))
    assert process.returncode==0 and '[capture] exit at frame' in text
    if a.full_roster:
        assert '[character-roster] COMPLETE records=9' in text
        assert 'drawing 5 existing henchmen' in text
        result['visitedCharacterRecords']=sorted(set(map(int,re.findall(r'\[character-roster\] visited record=(\d+)',text))))
        assert len(result['visitedCharacterRecords'])==9
    for failure in ('Out of VRAM','CORRUPTED','bad node','arena exhausted','Unhandled exception','FATAL HALT','unmapped address'):
        assert failure not in text,failure
    if name=='blackcats':
        for actor in ('spidey.psx','blackcat.psx','henchman.psx'):
            assert 'override '+actor in text,actor+' not replaced'
    blocks=[dict(name=n,size=int(s),address=int(addr,16)) for n,s,addr in
            re.findall(r'\[loose-wad\] arena (.*?): (\d+) bytes at 0x([0-9A-F]+)',text)]
    assert blocks and 'arena free' not in text,'This audit expects the opening level allocations to remain live'
    blocks.sort(key=lambda b:b['address'])
    for i,block in enumerate(blocks):
        assert 0x80300000<=block['address']<block['address']+block['size']<=0x80780000
        if i:assert blocks[i-1]['address']+blocks[i-1]['size']<=block['address']
    snapshots=[]
    for path in sorted((folder/'ram').glob('ram-*.bin')):
        ram=path.read_bytes()
        for block in blocks:
            match=re.search(r'override '+re.escape(block['name'])+r': (\d+) bytes',text)
            if not match:
                assert block['name']=='SM1 frame packets'
                end=(block['address']&0x7fffff)+block['size']
                assert not any(ram[end-256:end]),'Frame command safety margin was overwritten'
                continue
            length=int(match[1])
            begin=block['address']&0x7fffff
            assert not any(ram[begin+length:begin+block['size']]),'Actor allocation padding was overwritten'
        end=(blocks[-1]['address']&0x7fffff)+blocks[-1]['size']
        assert not any(ram[end:0x780000]),'Unused expanded arena was overwritten'
        node=struct.unpack_from('<I',ram,0xb5234)[0]
        actors=[]
        types=[]
        while node:
            assert node not in actors and 0x80000000<=node<0x80200000
            actors.append(node)
            types.append(struct.unpack_from('<H',ram,(node&0x7fffff)+0x34)[0])
            node=struct.unpack_from('<I',ram,(node&0x7fffff)+0x1c)[0]
        if a.full_roster:
            expected=4 if int(path.stem[4:])<3600 else 5
            assert types.count(0x138)==expected, 'Unexpected full-roster henchman count'
            assert all(t in (0x138,0x13f) for t in types)
        snapshots.append(dict(frame=int(path.stem[4:]),enemyCount=len(actors),
                              actorTypes=[f'{t:04x}' for t in types],
                              enemyPointers=[f'{x:08x}' for x in actors],
                              allocationPaddingClean=True,unusedArenaClean=True))
    result['nativeMemoryAudit']=dict(blocks=blocks,allocatedBytes=sum(b['size'] for b in blocks),snapshots=snapshots)
    (folder/'metrics.json').write_text(json.dumps(result,indent=2))
    results.append({k:v for k,v in result.items() if k!='samples'})
    (a.output/'summary.json').write_text(json.dumps(results,indent=2))
    print('BASELINE_PASS',name,json.dumps(results[-1]),flush=True)
