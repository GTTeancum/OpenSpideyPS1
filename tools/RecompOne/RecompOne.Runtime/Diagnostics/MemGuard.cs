using System;
using System.Collections.Generic;
using RecompOne.Runtime.Memory;

namespace RecompOne.Runtime.Diagnostics;

/// <summary>
/// Catches the write that corrupts a known address.
///
/// When a pointer in memory turns into rubbish, the crash happens wherever that
/// pointer is next followed, which is usually nowhere near the code that wrote it.
/// Watching the address itself and printing the call ring at the moment it changes
/// turns that into a direct answer.
/// </summary>
public static class MemGuard
{
    /// <summary>Physical address to watch, or 0 for off.</summary>
    public static uint Address;

    /// <summary>
    /// A value to watch for instead of an address. When the corrupting write is known
    /// by what it stores rather than where -- a pointer that keeps turning up wrong --
    /// this catches it at the instant it is written, anywhere in RAM.
    /// </summary>
    public static uint Value;
    public static bool WatchValue;
    public static int Reported;
    public static int Limit = 40;

    /// <summary>Only report writes whose value is not a plausible pointer or zero.</summary>
    public static bool BadValuesOnly = System.Environment.GetEnvironmentVariable("SPIDEY_GUARD_ALL") == null;

    /// <summary>Called for every 32-bit write when WatchValue is on.</summary>
    public static void HitValue(uint phys, uint written)
    {
        if (Reported >= Limit || written != Value) return;
        Reported++;
        Console.WriteLine($"[guard] value 0x{written:X8} written to 0x{phys | 0x80000000u:X8}");
        var tail = CallRing.Tail(10);
        var sb = new System.Text.StringBuilder("[guard]   functions, most recent last: ");
        foreach (uint a in tail) sb.Append($"0x{a:X8} ");
        Console.WriteLine(sb.ToString());
    }

    public static bool Lenient;
    static int _unmapped;
    static readonly HashSet<uint> _seen = new();

    public static void NoteUnmapped(uint address)
    {
        if (_unmapped >= 30 || !_seen.Add(address & 0xFFFFF000u)) return;
        _unmapped++;
        var tail = CallRing.Tail(4);
        var sb = new System.Text.StringBuilder();
        foreach (uint a in tail) sb.Append($"0x{a:X8} ");
        Console.WriteLine($"[lenient] unmapped 0x{address:X8} (in {sb})");
    }

    public static void Hit(IMemory m)
    {
        if (Reported >= Limit) return;
        uint v = m.ReadU32(Address | 0x80000000u);
        bool plausible = v == 0 || (v >= 0x80000000u && v < 0x80800000u && (v & 3) == 0);
        if (BadValuesOnly && plausible) return;
        Reported++;
        Console.WriteLine($"[guard] 0x{Address | 0x80000000u:X8} written with 0x{v:X8}");
        // Spider-Man keeps its two heap descriptors at 0x8009C5B8; printing them says
        // whether the allocator was inside its own arena when it did this.
        Console.WriteLine($"[guard]   heap0=[0x{m.ReadU32(0x8009C5B8):X8},0x{m.ReadU32(0x8009C5BC):X8}) " +
                          $"heap1=[0x{m.ReadU32(0x8009C5C0):X8},0x{m.ReadU32(0x8009C5C4):X8})");
        var tail = CallRing.Tail(12);
        var sb = new System.Text.StringBuilder("[guard]   callers, most recent last: ");
        foreach (uint a in tail) sb.Append($"0x{a:X8} ");
        Console.WriteLine(sb.ToString());
    }
}
