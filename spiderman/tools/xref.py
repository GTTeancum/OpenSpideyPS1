"""Resolve lui/lo16 register pairs in a PS-X EXE into the addresses they form.

MIPS builds a 32-bit constant from `lui reg, hi` plus a later instruction that adds a
signed 16-bit low half using the same register. Tracking that pairing per register
turns the disassembly into something searchable by target address, which is how you
find the code that touches a given string, table or hardware register.

Usage:
    python tools/xref.py 0x80094FE8 [0x...]     # who forms these addresses
    python tools/xref.py --dump-all             # every resolved address, sorted
"""
import struct
import sys

BASE = 0x80010000
EXE = 'extracted/SLUS_008.75'
HDR = 0x800

LO_OPS = {0x09: 'addiu', 0x0d: 'ori', 0x20: 'lb', 0x21: 'lh', 0x23: 'lw',
          0x24: 'lbu', 0x25: 'lhu', 0x28: 'sb', 0x29: 'sh', 0x2b: 'sw',
          0x32: 'lwc2', 0x3a: 'swc2'}


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def scan(path=EXE, base=BASE, hdr=HDR, size=None):
    """Yield (pc_of_lo, address, op) for every resolved lui/lo16 pair."""
    d = open(path, 'rb').read()
    text = d[hdr:hdr + size] if size else d[hdr:]
    hi = {}
    out = []
    for i in range(0, len(text) - 3, 4):
        w = struct.unpack('<I', text[i:i + 4])[0]
        pc = base + i
        op = w >> 26
        rs = (w >> 21) & 31
        rt = (w >> 16) & 31
        imm = w & 0xffff
        if op == 0x0f:                      # lui
            hi[rt] = (imm << 16, pc)
            continue
        if op in LO_OPS and rs in hi:
            val, luipc = hi[rs]
            out.append((pc, (val + s16(imm)) & 0xffffffff, LO_OPS[op], luipc))
            if op == 0x09 and rt == rs:     # addiu reg,reg -- pointer now in reg
                hi[rt] = ((val + s16(imm)) & 0xffffffff, luipc)
            elif rt in hi and op in (0x09, 0x0d):
                hi.pop(rt, None)
            continue
        # any other definition of a register kills its pending hi
        if op == 0 and (w & 0x3f) not in (0x08,):
            rd = (w >> 11) & 31
            hi.pop(rd, None)
        elif op in (0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x23, 0x24, 0x25, 0x20, 0x21):
            hi.pop(rt, None)
    return out


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--dump-all':
        for pc, addr, op, luipc in scan():
            print(f'{pc:08X} {op:5s} -> {addr:08X}  (lui at {luipc:08X})')
        return
    targets = {int(a, 0) for a in sys.argv[1:]}
    if not targets:
        sys.exit(__doc__)
    for pc, addr, op, luipc in scan():
        if addr in targets:
            print(f'{pc:08X} {op:5s} -> {addr:08X}  (lui at {luipc:08X})')


if __name__ == '__main__':
    main()
