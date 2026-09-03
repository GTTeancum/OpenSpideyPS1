"""Generate config/spiderman.json for RecompOne.

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
            ('CdWadRead', 'pre',  'Recompiled.AssetOverrides.CdWadRead'),
            ('HeapAlloc', 'pre',  'Recompiled.OverlayPatches.HeapAlloc'),
            ('HeapFree',  'pre',  'Recompiled.OverlayPatches.HeapFree'),
            # Direct level tests must select the full retail descriptor, not only
            # substitute its filenames. See patches/LevelSwitch.cs.
            ('func_80018800', 'pre', 'Recompiled.LevelSwitch.SelectDescriptor')):
        if fn in names:
            patches.append({'overlay': 'main', 'function': fn, 'mode': mode, 'target': target})
        else:
            skipped.append(f'{fn}({mode})')

    # Instrumentation for overlay residency and actor spawning; see patches/GameTrace.cs.
    for fn, mode, target in (
            ('LoadOverlay', 'pre',  'Recompiled.GameTrace.LoadOverlay'),
            ('LoadLevel',   'pre',  'Recompiled.GameTrace.LoadLevel'),
            ('LoadLevel',   'post', 'Recompiled.GameTrace.LoadLevelExit'),
            ('LoadPsx',     'pre',  'Recompiled.GameTrace.LoadPsx'),
            ('RunTriggerScript', 'pre', 'Recompiled.GameTrace.RunTriggerScript'),
            ('LoadTriggers', 'pre', 'Recompiled.GameTrace.LoadTriggers'),
            ('SetDrawAreaPrim', 'pre', 'Recompiled.GameTrace.SetDrawArea'),
            ('SetDrawAreaPrim', 'post','Recompiled.GameTrace.SetDrawAreaExit'),
            ('DrawPrimSet',  'pre', 'Recompiled.GameTrace.DrawPrimSet'),
            ('DrawPrimSet',  'post','Recompiled.GameTrace.DrawPrimSetExit'),
            ('FatalHalt',    'pre', 'Recompiled.GameTrace.FatalHalt'),
            ('RenderObjectList', 'pre', 'Recompiled.GameTrace.RenderObjectList'),
            ('RenderObjectList', 'post', 'Recompiled.GameTrace.RenderObjectListExit'),
            ('LevelIntro',   'pre', 'Recompiled.GameTrace.LevelIntro'),
            ('LevelIntro',   'post','Recompiled.GameTrace.LevelIntroExit'),
            ('ShowCover',    'pre', 'Recompiled.GameTrace.ShowCover'),
            ('ShowCover',    'post','Recompiled.GameTrace.ShowCoverExit'),
            ('LevelIntroDispatch','pre','Recompiled.GameTrace.LevelIntroDispatch'),
            ('LevelIntroDispatch','post','Recompiled.GameTrace.LevelIntroDispatchExit'),
            ('RunFrame',     'pre', 'Recompiled.GameTrace.RunFrame'),
            ('RunFrame',     'post','Recompiled.GameTrace.RunFrameExit'),
            ('TriggerPass',  'pre', 'Recompiled.GameTrace.TriggerPass'),
            ('TriggerType8', 'pre', 'Recompiled.GameTrace.TriggerType8'),
            ('SpawnActor',  'pre',  'Recompiled.GameTrace.SpawnActor'),
            ('SpawnActor',  'post', 'Recompiled.GameTrace.SpawnActorExit'),
            ('ModelFind',   'pre',  'Recompiled.ModelGuard.FindEnter'),
            ('ModelFind',   'post', 'Recompiled.ModelGuard.FindExit'),
            # SM1's menu expression targets are hard-coded for the retail
            # 38-vertex head. Restore the game's own backup after that pass when
            # a higher-detail Dreamcast head is active.
            ('func_800472C0', 'post', 'Recompiled.DcModelCompatibility.RestoreHeadAfterPs1Morph'),
            # Bag-Man's complete inner head/neck uses the engine's per-face OT
            # depth-offset channel behind the outer paper shell.
            ('DrawPrimSet', 'pre', 'Recompiled.DcModelCompatibility.ApplyBagmanNestedShellDepth'),
            ('DrawPrimSet', 'post', 'Recompiled.DcModelCompatibility.RestoreBagmanNestedShellDepth'),
            # Opt-in segmented-character diagnostics. These hooks are inert unless
            # RECOMP_TRACE_MODEL_STITCHES is set; keeping them in generated output
            # makes the Dreamcast compatibility audit reproducible.
            ('func_80074C98', 'pre',  'Recompiled.ModelDiagnostics.ParseEnter'),
            ('func_80074C98', 'post', 'Recompiled.ModelDiagnostics.ParseExit'),
            ('func_8007B798', 'pre',  'Recompiled.ModelDiagnostics.TransformEnter'),
            ('func_8007B798', 'post', 'Recompiled.ModelDiagnostics.TransformExit'),
            ('func_8007B9CC', 'pre',  'Recompiled.ModelDiagnostics.TransformEnter'),
            ('func_8007B9CC', 'post', 'Recompiled.ModelDiagnostics.TransformExit'),
            ('func_8007BBD4', 'pre',  'Recompiled.ModelDiagnostics.TransformEnter'),
            ('func_8007BBD4', 'post', 'Recompiled.ModelDiagnostics.TransformExit'),
            ('func_8007BD04', 'pre',  'Recompiled.ModelDiagnostics.TransformEnter'),
            ('func_8007BD04', 'post', 'Recompiled.ModelDiagnostics.TransformExit'),
            ('DrawPrimSet', 'pre', 'Recompiled.ModelDiagnostics.DrawFacesEnter')):
        if fn in names:
            patches.append({'overlay': 'main', 'function': fn, 'mode': mode, 'target': target})
        else:
            skipped.append(f'{fn}({mode})')

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

    # The 20-entry costume system retains the retail shell viewer and player
    # constructor, extending their data/configuration at the two stable entry points.
    patches.append({'overlay': 'shell', 'function': 'func_80261C70', 'mode': 'pre',
                    'target': 'Recompiled.Costume.PrepareViewer'})
    if 'func_80046B40' in names:
        patches.append({'overlay': 'main', 'function': 'func_80046B40', 'mode': 'pre',
                        'target': 'Recompiled.Costume.RunRetailTextureOverlay'})
    else:
        skipped.append('func_80046B40(pre)')
    if 'func_80047DF8' in names:
        patches.append({'overlay': 'main', 'function': 'func_80047DF8', 'mode': 'post',
                        'target': 'Recompiled.Costume.ApplyAbilityProfile'})
    else:
        skipped.append('func_80047DF8(post)')
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
        'game': {'id': 'SLUS-00875', 'name': 'SpiderMan', 'output': '../generated'},
        'cue': '../extracted',
        'funcMap': 'funcmaps/main.json',
        'overlays': overlays,
        'patches': patches,
        'callRing': True,
    }
    dst = os.path.join(ROOT, 'config', 'spiderman.json')
    with open(dst, 'w') as fh:
        json.dump(cfg, fh, indent=2)
    print(f'wrote {dst}: {len(overlays)} overlays, {len(patches)} patches')
    if skipped:
        print('no symbol recovered for: ' + ', '.join(skipped))


if __name__ == '__main__':
    main()
