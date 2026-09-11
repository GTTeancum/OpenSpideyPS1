"""Replace a compatible converted actor's animation chunk with its DC source bank."""
import argparse
from pathlib import Path
import struct
from pack_sm2_costume_to_dc import container_layout
from audit_dc_rigs import read, compare


def restore(raw, source):
    original, converted = read(source), read(raw)
    if original['objects'] != converted['objects'] or original['tags'].get(0x52454948) != converted['tags'].get(0x52454948):
        raise ValueError('Animation replacement requires the original object table and hierarchy')
    bank = original['tags'][44]
    p = struct.unpack_from('<I', raw, 4)[0]
    while struct.unpack_from('<I', raw, p)[0] != 0xffffffff:
        tag, size = struct.unpack_from('<II', raw, p)
        if tag == 44:
            if raw[p+8:p+8+size] == bank:return raw
            layout = container_layout(raw)
            output = bytearray(raw[:p+4] + struct.pack('<I',len(bank)) + bank + raw[p+8+size:])
            delta = len(bank)-size
            for i in range(layout['textureCount']):
                offset = layout['texturePointerTable']+4*i
                value = struct.unpack_from('<I',raw,offset)[0]
                struct.pack_into('<I',output,offset+delta,value+delta)
            result=bytes(output)
            assert read(result)['tags'][44] == bank
            assert compare(read(raw),read(result))['originalFullDetailOwnersAndPositionsPreserved']
            return result
        p += 8+size
    raise ValueError('Expected an existing compatible compressed animation bank')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actor',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_bytes(restore(args.actor.read_bytes(),args.source.read_bytes()))


if __name__=='__main__':main()
