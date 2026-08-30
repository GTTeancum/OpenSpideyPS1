"""List every jal/j that targets a given address in the main executable."""
import struct
import sys

BASE = 0x80010000
d = open('extracted/SLUS_013.78', 'rb').read()
text = d[0x800:0x800 + 0xBF800]

targets = {int(a, 0) for a in sys.argv[1:]}
for i in range(0, len(text), 4):
    w = struct.unpack('<I', text[i:i + 4])[0]
    op = w >> 26
    if op in (2, 3):
        tgt = ((BASE + i) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
        if tgt in targets:
            print(f'{BASE + i:08X} {"jal" if op == 3 else "j":3s} {tgt:08X}')
