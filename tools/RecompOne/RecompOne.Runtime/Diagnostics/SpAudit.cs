using System;

namespace RecompOne.Runtime.Diagnostics;

/// <summary>
/// Checks that every recompiled function leaves the stack pointer where it found it.
///
/// A function that returns without unwinding its frame does not fail where it happens.
/// Its caller's saved registers are read back from the wrong addresses, so a value the
/// caller was relying on quietly turns into whatever was in that memory -- and the
/// crash lands somewhere else entirely, often thousands of instructions later.
///
/// Recompilers grow this bug easily: an unconditional jump that leaves a function is a
/// tail call on real hardware, made *after* the epilogue, but if it is emitted as
/// "call the target, then return" from a point before the epilogue, the frame is never
/// popped. Enable with "spAudit": true and read the first report -- inner functions
/// return first, so the first mismatch is the innermost offender.
/// </summary>
public static class SpAudit
{
    public static int Reported;
    public static int Limit = 400;

    /// <summary>
    /// Functions known to use callee-saved registers as scratch on purpose. Spider-Man
    /// has hand-written leaf helpers that do this and whose callers know it, so they
    /// are true positives against the ABI but not bugs -- and left in they crowd out
    /// the report budget for the ones that are.
    /// </summary>
    static readonly HashSet<uint> Benign = new() { 0x8007FF28u };

    public static void Check(uint addr, string name, uint entrySp, uint exitSp)
    {
        if (entrySp == exitSp || Reported >= Limit) return;
        Reported++;
        int delta = (int)(exitSp - entrySp);
        Console.WriteLine($"[sp] {name} @ 0x{addr:X8} returned with sp {delta:+#;-#;0} " +
                          $"(0x{entrySp:X8} -> 0x{exitSp:X8})");
    }

    /// <summary>
    /// The callee-saved registers, checked the same way as the stack pointer.
    ///
    /// A function that returns without restoring s0..s7 or fp corrupts its caller just
    /// as thoroughly as one that leaves the stack unbalanced, and far more confusingly:
    /// the caller keeps running with a pointer that has silently become someone else's
    /// data, and dies later somewhere unrelated.
    /// </summary>
    public static void CheckRegs(uint addr, string name, uint[] entry, Context.CpuContext c)
    {
        if (Reported >= Limit || Benign.Contains(addr)) return;
        Span<uint> now = stackalloc uint[9];
        now[0] = c.S0; now[1] = c.S1; now[2] = c.S2; now[3] = c.S3; now[4] = c.S4;
        now[5] = c.S5; now[6] = c.S6; now[7] = c.S7; now[8] = c.FP;
        for (int i = 0; i < 9; i++)
        {
            if (now[i] == entry[i]) continue;
            Reported++;
            string reg = i == 8 ? "fp" : "s" + i;
            Console.WriteLine($"[reg] {name} @ 0x{addr:X8} did not restore {reg}: " +
                              $"0x{entry[i]:X8} -> 0x{now[i]:X8}");
            return;
        }
    }

    [ThreadStatic] static Stack<uint[]> _pool;

    public static uint[] Snapshot(Context.CpuContext c)
    {
        _pool ??= new Stack<uint[]>();
        var a = _pool.Count > 0 ? _pool.Pop() : new uint[9];
        a[0] = c.S0; a[1] = c.S1; a[2] = c.S2; a[3] = c.S3; a[4] = c.S4;
        a[5] = c.S5; a[6] = c.S6; a[7] = c.S7; a[8] = c.FP;
        return a;
    }

    public static void Release(uint[] a) { _pool ??= new Stack<uint[]>(); if (_pool.Count < 256) _pool.Push(a); }
}
