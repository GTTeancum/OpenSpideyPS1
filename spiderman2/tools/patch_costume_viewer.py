"""Bounded SM2 mod selector; all other retail paths retain a native power-profile index."""
from pathlib import Path
import re

SOURCE = Path(__file__).resolve().parents[1] / 'generated/shell.cs'


def exact(text, old, new, count=1):
    if text.count(old) != count:
        raise RuntimeError(f'Expected {count} occurrences of {old!r}, got {text.count(old)}')
    return text.replace(old, new)


def main():
    source = SOURCE.read_text(encoding='utf-8')
    start = source.index('public static void func_80249280(')
    end = source.index('public static void func_80249F04(', start)
    f = source[start:end]
    # charbio pointers must be ready before copying the original nineteen records.
    entry = 'c.RA = 0x802492B4u;\n        SpiderMan2.func_8023D074(c, m);'
    f = exact(f, entry, entry + '\n        Recompiled.Costume.PrepareViewer(c, m);')
    f = exact(f, '< 0x00000013u ? 1u : 0u;', '< Recompiled.Costume.ViewerCount ? 1u : 0u;', 2)
    old = 'c.SetDerived(3, c.V1 & c.V0, 3, 2);'
    if f.count(old) != 2:
        raise RuntimeError('Unlock-test shape changed')
    for reg in ['S0', 'S2']:
        f = f.replace(old, f'c.V1 = Recompiled.Costume.IsUnlocked(m, c.{reg}) ? 1u : 0u;', 1)
    for offset, expected in [('1560', 4), ('1568', 1)]:
        pattern = rf'c\.SetDerived\((\d+), c\.[A-Z0-9]+ \+ 0x{offset}u, \d+\);'
        delta = ' + 8u' if offset == '1568' else ''
        f, count = re.subn(pattern, lambda m: f'c.SetDerived({m[1]}, Recompiled.Costume.ViewerTable{delta}, 0);', f)
        if count != expected:
            raise RuntimeError(f'Table {offset}: {count}, expected {expected}')
    pattern = r'RecompOne\.Runtime\.Hardware\.GteScreen\.LoadU8\(c, (\d+), m, \(c\.[A-Z0-9]+ \+ 0x72u\), false\);'
    reads = list(re.finditer(pattern, f))
    if len(reads) != 6:
        raise RuntimeError(f'Expected six selected-byte reads, got {len(reads)}')
    # A1 goes to the texture-library loader; A0 at exit chooses native powers.
    # Both must retain the bounded stock proxy, never the host catalogue index.
    f = re.sub(pattern, lambda m: m[0] if m[1] in ['4', '5'] else
               f'c.{dict([(2,"V0"),(3,"V1")])[int(m[1])]} = Recompiled.Costume.ReadSelected(m);', f)
    f = exact(f, 'm.WriteU8((c.A3 + 0x72u), (byte)c.S2);',
              'Recompiled.Costume.WriteSelected(m, (int)c.S2);')
    f = exact(f, 'm.WriteU8((c.S5 + 0x15u), (byte)c.V1);',
              'm.WriteU8((c.S5 + 0x15u), (byte)c.V1);\n        Recompiled.Costume.ConfigureViewerList(m, c.S5);')
    f = exact(f, 'SpiderMan2.func_80017EF8(c, m);',
              'SpiderMan2.func_80017EF8(c, m);\n        Recompiled.Costume.AlignViewerFrame(m, c.S5);')
    SOURCE.write_text(source[:start] + f + source[end:], encoding='utf-8')
    print('  SM2 costume viewer: nineteen stock + twelve bounded data-only mods')


if __name__ == '__main__':
    main()
