"""Carry hand-identified function names from one game to another built on the same engine.

Two titles from the same studio and generation share most of their engine, but every
address moves: code is inserted, the linker reorders, and absolute fields differ
everywhere. So a byte compare finds nothing and a name recovered by hand in one port
would have to be recovered by hand again in the next.

The match is on *instruction shape* rather than bytes. Each word is reduced to the
part a relink cannot change -- the opcode, the register fields, and for SPECIAL the
function code -- while everything a relocation or a different global address would
move is dropped: branch displacements, load/store and arithmetic immediates, and the
26-bit target of j/jal. What survives is the register allocation and control flow the
compiler produced, which is stable across a rebuild of the same source.

A candidate is scored as the fraction of words whose shape agrees. Real matches for a
function of any size score far above the noise -- a hundred-word function has no
accidental twin -- so the gap between the best and second-best score is the thing to
read, and it is printed. Short functions cannot be told apart this way and are
reported as such rather than guessed at.

The output is a starting point, not an answer: every name it places still has to be
read at its new address before it is trusted. Nothing here is specific to either game.

Usage:
    python tools/enginematch.py --from OLD.exe --from-base 80010000 --from-size B6800 \
                                --syms old_manual.json \
                                --to NEW.exe --to-base 80010000 --to-size BF800 \
                                [--min-score 0.55] [--out new_manual.json]
"""
import argparse
import json
import struct
import sys

SPECIAL, REGIMM, J, JAL = 0x00, 0x01, 0x02, 0x03
COP2 = 0x12


def shape(w):
    """The part of an instruction a relink cannot move."""
    op = w >> 26
    if op in (J, JAL):
        return (J,)                       # target is a relocation; j and jal are
        # deliberately not distinguished -- a tail call can become either.
    if op == COP2:
        return (op, w & 0x03FFFFFF)       # GTE: the whole encoding is the operation
    if op == SPECIAL:
        # funct + all three register fields + shamt: no immediate to lose
        return (op, w & 0x3F, (w >> 21) & 0x1F, (w >> 16) & 0x1F,
                (w >> 11) & 0x1F, (w >> 6) & 0x1F)
    if op == REGIMM:
        return (op, (w >> 21) & 0x1F, (w >> 16) & 0x1F)
    # everything else is I-type: keep the registers, drop the immediate
    return (op, (w >> 21) & 0x1F, (w >> 16) & 0x1F)


def text_of(path, base, size):
    d = open(path, 'rb').read()
    hdr = 0x800 if d[:8] == b'PS-X EXE' else 0
    return d[hdr:hdr + size]


def words(text):
    return list(struct.unpack(f'<{len(text) // 4}I', text[:len(text) // 4 * 4]))


def shapes(ws):
    return [shape(w) for w in ws]


def score_at(pat, hay, i):
    hit = 0
    for k, s in enumerate(pat):
        if hay[i + k] == s:
            hit += 1
    return hit / len(pat)


def find(pat, hay, top=3):
    """The best-scoring alignments of pat within hay."""
    n = len(pat)
    best = []
    for i in range(len(hay) - n + 1):
        # cheap reject: the first four shapes must agree, which a real match's
        # prologue does and 99.9% of offsets do not
        if hay[i] != pat[0] or hay[i + 1] != pat[1] or hay[i + 2] != pat[2]:
            continue
        best.append((score_at(pat, hay, i), i))
    best.sort(reverse=True)
    return best[:top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='src', required=True)
    ap.add_argument('--from-base', default='80010000')
    ap.add_argument('--from-size', required=True)
    ap.add_argument('--syms', required=True)
    ap.add_argument('--to', dest='dst', required=True)
    ap.add_argument('--to-base', default='80010000')
    ap.add_argument('--to-size', required=True)
    ap.add_argument('--min-score', type=float, default=0.55)
    ap.add_argument('--min-words', type=int, default=12)
    ap.add_argument('--out')
    a = ap.parse_args()

    sbase, dbase = int(a.from_base, 16), int(a.to_base, 16)
    src = shapes(words(text_of(a.src, sbase, int(a.from_size, 16))))
    dst_w = words(text_of(a.dst, dbase, int(a.to_size, 16)))
    dst = shapes(dst_w)

    syms = json.load(open(a.syms))['functions']
    placed, weak, missing = [], [], []
    for s in syms:
        addr = int(s['address'], 16)
        size = s.get('size')
        if not size:
            missing.append((s['name'], 'no size in source map'))
            continue
        n = size // 4
        off = (addr - sbase) // 4
        pat = src[off:off + n]
        if len(pat) < n:
            missing.append((s['name'], 'source extent past end of text'))
            continue
        if n < a.min_words:
            missing.append((s['name'], f'only {n} words -- too short to be distinctive'))
            continue
        hits = find(pat, dst)
        if not hits:
            missing.append((s['name'], 'no alignment with a matching prologue'))
            continue
        top, second = hits[0], (hits[1] if len(hits) > 1 else (0.0, 0))
        gap = top[0] - second[0]
        rec = {'name': s['name'], 'address': '0x%08X' % (dbase + top[1] * 4),
               'score': round(top[0], 3), 'gap': round(gap, 3), 'words': n}
        (placed if top[0] >= a.min_score else weak).append(rec)

    for r in sorted(placed, key=lambda r: -r['score']):
        print('%-20s %s  score=%.3f gap=%.3f (%d words)'
              % (r['name'], r['address'], r['score'], r['gap'], r['words']))
    for r in weak:
        print('weak  %-14s %s  score=%.3f' % (r['name'], r['address'], r['score']))
    for n, why in missing:
        print('none  %-14s %s' % (n, why))
    print('\n%d placed, %d weak, %d unmatched' % (len(placed), len(weak), len(missing)))

    if a.out:
        doc = {'_comment': 'Seeded by tools/enginematch.py; every name must be read at '
                           'its new address before it is trusted.',
               'functions': [{'address': r['address'], 'name': r['name']}
                             for r in sorted(placed, key=lambda r: r['address'])]}
        json.dump(doc, open(a.out, 'w'), indent=1)
        print('wrote ' + a.out)


if __name__ == '__main__':
    sys.exit(main())
