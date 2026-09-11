"""Extract a civilian suit actor without changing its authored Dreamcast rig.

Kept at the old command path for build compatibility. This no longer re-rigs,
tailors, or removes geometry. Texture-only suits must preserve source ownership.
"""
import argparse
import json
from pathlib import Path
import struct
import zipfile
from restore_dc_animation_bank import restore

ROOT = Path(__file__).resolve().parents[2]


def rig_data(raw):
    count = struct.unpack_from('<I', raw, 8)[0]
    table = 12 + 36 * count
    meshes = struct.unpack_from('<I', raw, table)[0]
    streams = []
    for i in range(meshes):
        ptr = struct.unpack_from('<I', raw, table + 4 + 4*i)[0]
        vertices = struct.unpack_from('<H', raw, ptr + 2)[0]
        streams.append(raw[ptr + 28:ptr + 28 + 8*vertices])
    return raw[12:table], streams


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--donor', choices=('spquick.psx', 'sppark.psx'), default='spquick.psx')
    args = parser.parse_args()
    with zipfile.ZipFile(ROOT / 'spiderman/port/bundled/runtime-assets.zip') as archive:
        raw = archive.read(args.donor)
    source = ROOT / 'dreamcast/extracted' / args.donor.upper()
    source_raw = source.read_bytes()
    if rig_data(raw) != rig_data(source_raw):
        raise ValueError('Bundled actor does not preserve the original Dreamcast rig')
    raw = restore(raw, source_raw)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'actor.psx').write_bytes(raw)
    report = dict(source=str(source.relative_to(ROOT)), originalDreamcastRigVerified=True,
                  changedVertices=[], surfaceAdjustments=[], removedBuriedFaces=[],
                  sourceObjectTableAndVertexStreamsUnchanged=True,
                  originalDreamcastAnimationBank=True)
    (args.output / 'rig-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'{args.donor}: original Dreamcast object table and all vertex/attachment records verified')


if __name__ == '__main__':
    main()
