#!/usr/bin/env python3
"""Relocate SM1's 17-entry texture registry into recomp-only expanded RAM.

Retail stores 8-byte texture records at 0x80099A18. The animation-event pointer
table starts only 0x88 bytes later, so record 17's terminator and every subsequent
record overwrite gameplay animation data. Dreamcast actors exceed that ceiling.

This deterministic generated-source transform moves all five registry-base uses to
TextureRegistry.Table and inserts an explicit capacity check in the sole appender.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "generated" / "main.cs"
APPENDER = "public static void func_800468F0(CpuContext c, IMemory m)"
NEXT_FUNCTION = "public static void func_80046928(CpuContext c, IMemory m)"
TEXTURE_ALLOCATOR = "public static void func_80062A70(CpuContext c, IMemory m)"
CLUT_ALLOCATOR = "public static void func_80062AC0(CpuContext c, IMemory m)"
NEXT_AFTER_CLUT_ALLOCATOR = "public static void func_80062B10(CpuContext c, IMemory m)"
MODEL_LOADER = "public static void func_80068BB0(CpuContext c, IMemory m)"
NEXT_AFTER_MODEL_LOADER = "public static void ModelFind(CpuContext c, IMemory m)"


def replace_exact(text: str, old: str, new: str, expected: int) -> str:
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"expected {expected} occurrences of {old!r}, found {count}")
    return text.replace(old, new)


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    # One writer and two reader routines construct the retail base five times.
    source = replace_exact(
        source,
        "c.SetDerived(7, c.A3 - 0x65E8u, 7);",
        "c.A3 = Recompiled.TextureRegistry.Table;",
        1,
    )
    source = replace_exact(
        source,
        "RecompOne.Runtime.Hardware.GteScreen.LoadU32(c, 5, m, (c.A0 - 0x65E8u));",
        "RecompOne.Runtime.Hardware.GteScreen.LoadU32(c, 5, m, Recompiled.TextureRegistry.Table);",
        1,
    )
    source = replace_exact(
        source,
        "c.SetDerived(17, c.A0 - 0x65E8u, 4);",
        "c.S1 = Recompiled.TextureRegistry.Table;",
        1,
    )
    source = replace_exact(
        source,
        "RecompOne.Runtime.Hardware.GteScreen.LoadU32(c, 16, m, (c.A1 - 0x65E8u));",
        "RecompOne.Runtime.Hardware.GteScreen.LoadU32(c, 16, m, Recompiled.TextureRegistry.Table);",
        1,
    )
    source = replace_exact(
        source,
        "c.SetDerived(19, c.A1 - 0x65E8u, 5);",
        "c.S3 = Recompiled.TextureRegistry.Table;",
        1,
    )

    start = source.index(APPENDER)
    end = source.index(NEXT_FUNCTION, start)
    function = source[start:end]
    function = replace_exact(
        function,
        "        RecompOne.Runtime.Hardware.GteScreen.LoadU32(c, 3, m, (c.GP + 0xA98u));\n",
        "        RecompOne.Runtime.Hardware.GteScreen.LoadU32(c, 3, m, (c.GP + 0xA98u));\n"
        "        Recompiled.TextureRegistry.ValidateAppend(c.V1);\n"
        "        Recompiled.TextureRegistry.TraceAppend(c.V1, c.A0, c.A1, c.A2);\n",
        1,
    )
    source = source[:start] + function + source[end:]

    # Retail registers texture pages only when their hashes match the 13 built-in
    # Spider-Man materials. Converted and community skins necessarily have other
    # hashes. Register every texture belonging to the shell/gameplay player slots,
    # while retaining the original whitelist for every other model slot.
    start = source.index(MODEL_LOADER)
    end = source.index(NEXT_AFTER_MODEL_LOADER, start)
    function = source[start:end]
    function = replace_exact(
        function,
        "        c.SetDerived(30, c.A2 + 0x14u, 6);\n"
        "        c.V0 = c.V0 < c.V1 ? 1u : 0u;\n",
        "        c.SetDerived(30, c.A2 + 0x14u, 6);\n"
        "        if (Recompiled.TextureRegistry.IsPlayerModelSlot(m.ReadU32(c.SP + 0x78u)))\n"
        "            goto L80069040;\n"
        "        c.V0 = c.V0 < c.V1 ? 1u : 0u;\n",
        1,
    )
    source = source[:start] + function + source[end:]

    start = source.index(TEXTURE_ALLOCATOR)
    end = source.index(CLUT_ALLOCATOR, start)
    function = source[start:end]
    function = replace_exact(
        function,
        "        c.SetDerived(2, c.A0 + 0u, 4, 0);\n        return;\n",
        "        c.SetDerived(2, c.A0 + 0u, 4, 0);\n"
        "        Recompiled.TextureRegistry.ValidateTextureBlock(c.V0);\n"
        "        return;\n",
        1,
    )
    source = source[:start] + function + source[end:]

    start = source.index(CLUT_ALLOCATOR)
    end = source.index(NEXT_AFTER_CLUT_ALLOCATOR, start)
    function = source[start:end]
    function = replace_exact(
        function,
        "        c.SetDerived(2, c.A0 + 0u, 4, 0);\n        return;\n",
        "        c.SetDerived(2, c.A0 + 0u, 4, 0);\n"
        "        Recompiled.TextureRegistry.ValidateClutSlot(c.V0);\n"
        "        return;\n",
        1,
    )
    source = source[:start] + function + source[end:]

    SOURCE.write_text(source, encoding="utf-8")
    print(
        "  texture registry: 17 -> 32768 records, relocated to "
        "0x80780000..0x807C0000"
    )


if __name__ == "__main__":
    main()
