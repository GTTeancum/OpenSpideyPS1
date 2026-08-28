using System;

namespace RecompOne.Runtime.Diagnostics;

/// <summary>Reports a draw environment whose clip rectangle is empty.</summary>
public static class DrawEnvWarn
{
    /// <summary>Paint the draw-environment background magenta -- see LibGpu.PutDrawEnv.</summary>
    public static bool TintBackground;

    static int _count;
    static int _areaCount;

    /// <summary>
    /// A drawing-area command whose Y lands outside VRAM. The framebuffer is 1024x512,
    /// so a top or bottom above 511 cannot be real: it means the word reaching the GPU
    /// was not the command it was taken for, which usually means an ordering-table walk
    /// lost sync and started reading payload as opcodes.
    /// </summary>
    public static void Area(int cmd, uint word, int x, int y)
    {
        if (System.Environment.GetEnvironmentVariable("SPIDEY_AREA_ALL") == null && y <= 511) return;
        if (_areaCount++ >= 20000) return;
        Console.WriteLine($"[gpu] GP0(0x{cmd:X2}) word 0x{word:X8} -> ({x},{y}); y is outside VRAM");
    }

    public static void Degenerate(uint env, short x, short y, short w, short h)
    {
        if (_count++ >= 10) return;
        Console.WriteLine($"[gpu] PutDrawEnv at 0x{env:X8} has an empty clip: " +
                          $"({x},{y}) {w}x{h} -- everything after this is clipped away");
        var tail = CallRing.Tail(8);
        var sb = new System.Text.StringBuilder("[gpu]   callers, most recent last: ");
        foreach (uint a in tail) sb.Append($"0x{a:X8} ");
        Console.WriteLine(sb.ToString());
    }
}
