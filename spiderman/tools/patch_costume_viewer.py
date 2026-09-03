#!/usr/bin/env python3
"""Extend the generated SM1 costume viewer from 10 to 20 entries.

The retail table ends immediately before unrelated shell data, so Costume.PrepareViewer
builds a relocated table in the port's eight-megabyte RAM. This deterministic generated-
source transform changes only the two loop bounds, the UI capacity, and the four hard-
coded table-base calculations inside func_80261C70.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "generated" / "shell.cs"
FUNCTION = "public static void func_80261C70(CpuContext c, IMemory m)"
NEXT_FUNCTION = "public static void func_80262774(CpuContext c, IMemory m)"


def replace_exact(text: str, old: str, new: str, expected: int) -> str:
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"expected {expected} occurrences of {old!r}, found {count}")
    return text.replace(old, new)


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index(FUNCTION)
    end = source.index(NEXT_FUNCTION, start)
    function = source[start:end]

    function = replace_exact(
        function, "c.V1 = 0x0000000Au;", "c.V1 = 0x00000014u;", 1
    )
    function = replace_exact(
        function, "< 0x0000000Au ? 1u : 0u;", "< 0x00000014u ? 1u : 0u;", 2
    )
    function = replace_exact(
        function,
        "        SpiderMan.func_80016424(c, m);\n",
        "        SpiderMan.func_80016424(c, m);\n"
        "        Recompiled.Costume.ConfigureViewerList(m, c.S5);\n",
        1,
    )

    # Each occurrence is emitted as a two-instruction constant construction. The
    # destination register is not always the register holding 0x80270000, so replace
    # the subtract instruction and leave the now-harmless constant load in place.
    pattern = re.compile(
        r"c\.SetDerived\((?P<dst>\d+), c\.[A-Z0-9]+ - 0x6C58u, \d+\);"
    )
    function, count = pattern.subn(
        lambda match: "c.SetDerived(" + match.group("dst") +
        ", Recompiled.Costume.ViewerTable, 0);",
        function,
    )
    if count != 4:
        raise RuntimeError(f"expected 4 costume table-base constructions, found {count}")

    # Four reads represent the globally selected row and must use the port's extended
    # saved value. A fifth read feeds the retail costXX resource-name table and must
    # deliberately keep reading the safe 0..9 proxy byte.
    lines = function.splitlines()
    selected_read_pattern = re.compile(
        r"RecompOne\.Runtime\.Hardware\.GteScreen\.LoadU8"
        r"\(c, (?P<reg>\d+), m, \(c\.[A-Z0-9]+ \+ 0x7Cu\), false\);"
    )
    selected_reads = [
        index for index, line in enumerate(lines) if selected_read_pattern.search(line)
    ]
    if len(selected_reads) != 5:
        raise RuntimeError(f"expected 5 selected-byte reads, found {len(selected_reads)}")
    retail_reads = [
        index for index in selected_reads
        if "0x7480u" in "\n".join(lines[index:index + 8])
    ]
    if len(retail_reads) != 1:
        raise RuntimeError(f"expected 1 retail resource-table read, found {len(retail_reads)}")
    for index in selected_reads:
        if index == retail_reads[0]:
            continue
        match = selected_read_pattern.search(lines[index])
        register = {2: "V0", 3: "V1", 5: "A1"}[int(match.group("reg"))]
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index] = (
            f"{indent}c.{register} = Recompiled.Costume.ReadSelected(m);"
        )

    selected_writes = [
        index for index, line in enumerate(lines)
        if re.search(r"m\.WriteU8\(\(c\.[A-Z0-9]+ \+ 0x7Cu\), \(byte\)c\.S3\);", line)
    ]
    if len(selected_writes) != 1:
        raise RuntimeError(f"expected 1 selected-byte write, found {len(selected_writes)}")
    lines[selected_writes[0]] = re.sub(
        r"m\.WriteU8\(\(c\.[A-Z0-9]+ \+ 0x7Cu\), \(byte\)c\.S3\);",
        "Recompiled.Costume.WriteSelected(m, (byte)c.S3);",
        lines[selected_writes[0]],
    )
    function = "\n".join(lines) + ("\n" if function.endswith("\n") else "")

    SOURCE.write_text(source[:start] + function + source[end:], encoding="utf-8")
    print("  costume viewer: 20 entries, scrolling list, table relocated to 0x807C0000")


if __name__ == "__main__":
    main()
