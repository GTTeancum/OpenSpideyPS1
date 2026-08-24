"""Read CD.HED / CD.WAD, Spider-Man's asset archive.

CD.HED is a flat table of entries. A record is the file name as a NUL-terminated
string padded with NULs to a 4-byte boundary, then a 32-bit byte offset into CD.WAD
and a 32-bit length. Offsets are 2048-byte aligned, so every entry starts on a
sector -- the archive is read straight off the CD with no seeking inside a sector.

The name field is variable width, which is why a fixed-stride read of this table
falls apart a few hundred entries in: `sfx.vab` occupies 8 bytes of name and
`sp_tex00.psx` occupies 16.

Usage:
    python tools/cdwad.py list
    python tools/cdwad.py extract OUT_DIR [GLOB]
"""
import fnmatch
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HED = os.path.join(HERE, '..', 'extracted', 'CD.HED')
WAD = os.path.join(HERE, '..', 'extracted', 'CD.WAD')


def align4(n):
    return (n + 3) & ~3


def entries(hed_path=HED):
    """Every (name, offset, size) in the archive index, in table order."""
    d = open(hed_path, 'rb').read()
    out = []
    i = 0
    while i < len(d):
        end = d.find(b'\0', i)
        if end < 0:
            break
        name = d[i:end].decode('latin-1')
        if not name:
            break
        field = align4(end - i + 1)
        rec = i + field
        if rec + 8 > len(d):
            break
        off, size = struct.unpack('<II', d[rec:rec + 8])
        out.append((name, off, size))
        i = rec + 8
    return out


class Wad:
    def __init__(self, hed=HED, wad=WAD):
        self.entries = entries(hed)
        self.index = {n.lower(): (o, s) for n, o, s in self.entries}
        self.fh = open(wad, 'rb')

    def read(self, name):
        off, size = self.index[name.lower()]
        self.fh.seek(off)
        return self.fh.read(size)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    if cmd == 'list':
        es = entries()
        for name, off, size in es:
            print(f'0x{off:08x} {size:9d}  {name}')
        print(f'{len(es)} entries')
        bad = [e for e in es if e[1] % 2048]
        if bad:
            print(f'WARNING: {len(bad)} entries are not sector aligned')
    elif cmd == 'extract':
        out = os.path.abspath(sys.argv[2])
        pat = sys.argv[3] if len(sys.argv) > 3 else '*'
        os.makedirs(out, exist_ok=True)
        w = Wad()
        n = 0
        for name, off, size in w.entries:
            if not fnmatch.fnmatch(name.lower(), pat.lower()):
                continue
            with open(os.path.join(out, name), 'wb') as fh:
                fh.write(w.read(name))
            n += 1
        print(f'extracted {n} entries to {out}')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
