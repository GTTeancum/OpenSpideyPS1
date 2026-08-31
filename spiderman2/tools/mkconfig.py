"""Generate config/spiderman2.json for RecompOne.

The overlay list is derived from the relocation manifest so the two can never drift:
every overlay is recompiled at exactly the base tools/overlays.py relocated it to, and
the runtime patch that redirects the game's own allocation uses the same manifest.

Patches fall into the two categories the playbook describes. Whole libgpu subsystems
have to be replaced as a set -- the runtime takes over DrawOTag/DrawSync/PutDrawEnv/
PutDispEnv, which bypasses libgpu's internal DMA command queue, so any *other* libgpu
call left recompiled walks a queue nothing fills. And entry points the game uses that
the runtime does not implement get their own shims under patches/.

Only patches whose symbol was actually recovered are emitted, so a name PsyQ matching
missed cannot silently turn into a no-op patch.

Usage: python tools/mkconfig.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FM = os.path.join(ROOT, 'config', 'funcmaps')

# libgpu entry points that reach hardware through the queue the runtime replaces.
# Half-replacing this subsystem is worse than not replacing it at all.
GPU_RUNTIME = ['ClearImage', 'LoadImage', 'MoveImage', 'StoreImage']
GPU_SHIM = ['SetDispMask', 'DrawPrim', 'DrawOTagEnv', 'ClearOTagR',
            'DrawSyncCallback', 'GetODE', 'SetGraphDebug', 'ClearOTag']

# ResetGraph must NOT be replaced -- it initialises libgpu's own state, including the
# coordinate clamp limits every other libgpu helper reads. See patches/GpuPatches.cs.
GPU_PRE = ['ResetGraph']


def known_names():
    out = {}
    for f in json.load(open(os.path.join(FM, 'main.json')))['functions']:
        out[f['name']] = f['address']
    return out


def main():
    manifest = json.load(open(os.path.join(ROOT, 'config', 'overlays', 'manifest.json')))
    names = known_names()

    overlays = []
    for name, v in sorted(manifest.items()):
        overlays.append({
            'name': name,
            'path': f'overlays/{name}.bin',
            'base': v['base'],
            'funcMap': f'funcmaps/{name}.json',
        })

    patches = []
    skipped = []

    # Overlay loading: give every overlay a fixed base. See patches/OverlayPatches.cs.
    for fn, mode, target in (
            ('CdWadFind', 'pre',  'Recompiled.OverlayPatches.CdWadFind'),
            ('CdWadFind', 'post', 'Recompiled.OverlayPatches.CdWadFindExit'),
            ('CdWadRead', 'pre',  'RecompOne.Runtime.Assets.LooseWadOverrides.Read'),
            ('HeapAlloc', 'pre',  'Recompiled.OverlayPatches.HeapAlloc'),
            ('HeapFree',  'pre',  'Recompiled.OverlayPatches.HeapFree')):
        if fn in names:
            patches.append({'overlay': 'main', 'function': fn, 'mode': mode, 'target': target})
        else:
            skipped.append(f'{fn}({mode})')

    # No game-internals instrumentation yet. Spider-Man's port hooks LoadLevel,
    # RunFrame, SpawnActor and the rest by name, but every one of those is a global or
    # a structure layout that has to be found in *this* executable first, and a hook
    # pointed at a plausible-looking wrong address reports confident nonsense. The
    # names in funcmaps/manual.json are the ones read and confirmed; hooks get added
    # as more are.

    # The movie player, so its wait can be watched. See patches/MovieTrace.cs.
    if 'MovieNextFrame' in names:
        patches.append({'overlay': 'main', 'function': 'MovieNextFrame', 'mode': 'post',
                        'target': 'Recompiled.MovieTrace.NextFrameExit'})
    else:
        skipped.append('MovieNextFrame')

    # libpad: the game inits input through PadInitMtap, which the runtime does not
    # implement. The original has to keep running -- it installs the multitap handler
    # table the game calls through -- so the runtime's direct-mode init is layered on
    # top rather than replacing it. See patches/PadPatches.cs.
    if 'PadInitMtap' in names:
        patches.append({'overlay': 'main', 'function': 'PadInitMtap', 'mode': 'pre',
                        'target': 'Recompiled.PadPatches.PadInitMtapEnter'})
        patches.append({'overlay': 'main', 'function': 'PadInitMtap', 'mode': 'post',
                        'target': 'Recompiled.PadPatches.PadInitMtapExit'})
    else:
        skipped.append('PadInitMtap')
    for fn in GPU_RUNTIME:
        if fn in names:
            patches.append({'overlay': '*', 'function': fn, 'mode': 'replace',
                            'target': f'RecompOne.Runtime.Sdk.LibGpu.{fn}'})
        else:
            skipped.append(fn)
    for fn in GPU_SHIM:
        if fn in names:
            patches.append({'overlay': '*', 'function': fn, 'mode': 'replace',
                            'target': f'Recompiled.GpuPatches.{fn}'})
        else:
            skipped.append(fn)
    for fn in GPU_PRE:
        if fn in names:
            patches.append({'overlay': '*', 'function': fn, 'mode': 'pre',
                            'target': f'Recompiled.GpuPatches.{fn}'})
        else:
            skipped.append(fn)

    cfg = {
        'game': {'id': 'SLUS-01378', 'name': 'SpiderMan2', 'output': '../generated'},
        'cue': '../extracted',
        'funcMap': 'funcmaps/main.json',
        'overlays': overlays,
        'patches': patches,
        'callRing': True,
    }
    dst = os.path.join(ROOT, 'config', 'spiderman2.json')
    with open(dst, 'w') as fh:
        json.dump(cfg, fh, indent=2)
    print(f'wrote {dst}: {len(overlays)} overlays, {len(patches)} patches')
    if skipped:
        print('no symbol recovered for: ' + ', '.join(skipped))


if __name__ == '__main__':
    main()
