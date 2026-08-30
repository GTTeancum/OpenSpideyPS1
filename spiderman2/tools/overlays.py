"""Relocate Spider-Man's code overlays to fixed addresses.

The game loads each `<name>.bin` from CD.WAD into a heap block and then walks
`<name>.rel` to patch it for wherever it landed. A static recompile cannot follow a
heap address, so every overlay is instead assigned a fixed base of its own, above the
2 MB the game's allocator knows about, and the image is relocated there ahead of time.
The runtime patch that redirects the game's own allocation to the same address makes
the bytes in RAM identical to the image the recompiler was built from.

The relocation stream is a flat array of u32 terminated by 0xFFFFFFFF. Each entry is
a byte offset into the image with the relocation type in the low two bits, which are
free because every site is word aligned:

    0  a stored 32-bit pointer      *site += base
    1  lui of a hi/lo pair          hi16 of (base + addend); the addend is the
                                    following u32, because a lui alone cannot know
                                    the low half it will be paired with
    2  the lo16 half                low 16 of (site + base) -- the instruction's own
                                    immediate is the addend, so no extra word
    3  jal/j                        retarget the 26-bit field

This mirrors the game's own relocator at 0x8001BF58 exactly, including its quirk of
adding `base` to the whole instruction word for type 2 and masking afterwards.

Usage:
    python tools/overlays.py plan            # print the base assignment
    python tools/overlays.py build OUT_DIR   # write relocated images
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdwad

# Above the 2 MB the game's heap can reach, so a fixed overlay never collides with a
# real allocation. RecompOne's RAM window goes to 8 MB.
OVERLAY_REGION = 0x80200000
ALIGN = 0x1000

HERE = os.path.dirname(os.path.abspath(__file__))
WADDIR = os.path.join(HERE, '..', 'extracted', 'wad')


def names():
    return sorted(n[:-4] for n in os.listdir(WADDIR) if n.endswith('.bin'))


def plan():
    """Assign every overlay a fixed, non-overlapping base."""
    out = {}
    addr = OVERLAY_REGION
    for n in names():
        size = os.path.getsize(os.path.join(WADDIR, n + '.bin'))
        out[n] = (addr, size)
        addr = (addr + size + ALIGN - 1) & ~(ALIGN - 1)
    return out, addr


def relocate(image, rel, base):
    """Apply one overlay's relocation stream. Returns the patched image."""
    b = bytearray(image)
    vals = struct.unpack(f'<{len(rel) // 4}I', rel[:len(rel) // 4 * 4])
    i = 0
    counts = {0: 0, 1: 0, 2: 0, 3: 0}
    while i < len(vals) and vals[i] != 0xFFFFFFFF:
        e = vals[i]
        i += 1
        off = e & ~3
        t = e & 3
        site = struct.unpack_from('<I', b, off)[0]
        if t == 0:
            new = (site + base) & 0xFFFFFFFF
        elif t == 1:
            addend = vals[i]
            i += 1
            new = (site & 0xFFFF0000) | (((addend + base + 0x8000) >> 16) & 0xFFFF)
        elif t == 2:
            new = (site & 0xFFFF0000) | ((site + base) & 0xFFFF)
        else:
            tgt = ((((site & 0x03FFFFFF) << 2) + base) >> 2) & 0x03FFFFFF
            new = (site & 0xFC000000) | tgt
        struct.pack_into('<I', b, off, new & 0xFFFFFFFF)
        counts[t] += 1
    return bytes(b), counts


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'plan'
    p, end = plan()
    if cmd == 'plan':
        for n, (a, s) in p.items():
            print(f'{n:12s} base=0x{a:08X} size={s:7d} end=0x{a + s:08X}')
        print(f'{len(p)} overlays, region 0x{OVERLAY_REGION:08X}..0x{end:08X} '
              f'({(end - OVERLAY_REGION) / 1024:.0f} KB)')
    elif cmd == 'build':
        out = os.path.abspath(sys.argv[2])
        os.makedirs(out, exist_ok=True)
        manifest = {}
        for n, (base, size) in p.items():
            img = open(os.path.join(WADDIR, n + '.bin'), 'rb').read()
            rel = open(os.path.join(WADDIR, n + '.rel'), 'rb').read()
            patched, counts = relocate(img, rel, base)
            with open(os.path.join(out, n + '.bin'), 'wb') as fh:
                fh.write(patched)
            manifest[n] = {'base': f'0x{base:08X}', 'size': size,
                           'relocs': sum(counts.values())}
            print(f'{n:12s} -> 0x{base:08X}  {sum(counts.values()):5d} relocs '
                  f'(ptr={counts[0]} hi={counts[1]} lo={counts[2]} jal={counts[3]})')
        with open(os.path.join(out, 'manifest.json'), 'w') as fh:
            json.dump(manifest, fh, indent=2)
        print(f'\nwrote {len(p)} relocated images to {out}')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
