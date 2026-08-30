using System.Runtime.CompilerServices;

namespace RecompOne.Runtime.Diagnostics;

/// <summary>
/// A ring of recently entered function addresses, plus a stall breaker.
///
/// When a recompiled game locks up there is no interpreter loop to inspect and no PC
/// to print: the only evidence is which recompiled functions ran last. Printing every
/// entry (the recompiler's `debug` flag) is far too slow to reach the failure, so the
/// generated code calls <see cref="Enter"/> instead -- one array store and a decrement
/// -- and a watchdog dumps the tail once the game stops presenting frames.
///
/// The same counter doubles as a second idle-loop breaker. Runtime.IdleTick covers
/// loops that spin on a memory location, but a loop whose body is a call (a game
/// polling an SDK function that returns "not ready") reads nothing and would freeze
/// the window with it. Frames only stop for good when something is wrong, so a very
/// large call count with no frame in between is a safe trigger.
/// </summary>
public static class CallRing
{
    public const int Size = 1 << 16;

    static readonly uint[] _buf = new uint[Size];

    /// <summary>
    /// Long, not int. A game that spins on an SDK call polls it millions of times a
    /// second, so a 32-bit index wraps negative within minutes -- and then Tail's
    /// "start &lt; 0" clamp set the count from a negative end and threw, which took the
    /// stall dump out exactly when a long run finally wedged and the dump was the whole
    /// point of keeping the ring.
    /// </summary>
    static long _idx;

    /// <summary>Calls without an intervening frame before the stall breaker fires.</summary>
    /// <summary>
    /// Low on purpose. It used to be four million, which meant a game spinning without
    /// calling VSync got its CD serviced and its window pumped roughly once every
    /// 60 ms -- the window went "Not Responding" and every wait crawled. What the
    /// breaker runs is now cheap and rate-limited (Runtime.ServiceOnly), so it can
    /// afford to fire often.
    /// </summary>
    public static int StallCalls = 50_000;

    static int _sinceFrame;

    /// <summary>How many times the stall breaker has had to force a frame.</summary>
    public static long StallBreaks;

    public static bool Enabled = true;

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    public static void Enter(uint addr)
    {
        if (!Enabled) return;
        _buf[_idx++ & (Size - 1)] = addr;
        if (++_sinceFrame >= StallCalls)
        {
            _sinceFrame = 0;
            StallBreaks++;
            Runtime.IdleTick();
        }
    }

    /// <summary>Called once a frame has actually been presented.</summary>
    public static void NoteFrame() => _sinceFrame = 0;

    public static long TotalCalls => _idx;

    /// <summary>Most recent entries, oldest first.</summary>
    public static uint[] Tail(int count)
    {
        if (count > Size) count = Size;
        if (count < 0) count = 0;
        long end = _idx;
        long start = end - count;
        if (start < 0) { start = 0; count = (int)end; }
        var outp = new uint[count];
        for (int i = 0; i < count; i++)
            outp[i] = _buf[(start + i) & (Size - 1)];
        return outp;
    }
}
