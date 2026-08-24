using System.Diagnostics;

namespace RecompOne.Runtime.Diagnostics;

/// <summary>
/// Where a frame's wall time actually goes: drawing it, waiting to pace it, or running
/// game code in between. A recompiled game that feels stuck is usually one of those
/// three and they need very different fixes, so guessing is expensive.
/// </summary>
public static class FrameProfile
{
    static readonly double TicksPerMs = Stopwatch.Frequency / 1000.0;
    static long _lastEnd;

    public static double PresentMs, ThrottleMs, GameMs;
    public static long Frames;

    public static void Note(long t0, long t1, long t2)
    {
        PresentMs += (t1 - t0) / TicksPerMs;
        ThrottleMs += (t2 - t1) / TicksPerMs;
        if (_lastEnd != 0) GameMs += (t0 - _lastEnd) / TicksPerMs;
        _lastEnd = t2;
        Frames++;
    }

    public static string Summary()
    {
        if (Frames == 0) return "no frames";
        string s = $"per frame: present {PresentMs / Frames:F2}ms, throttle {ThrottleMs / Frames:F2}ms, " +
                   $"game {GameMs / Frames:F2}ms";
        PresentMs = ThrottleMs = GameMs = 0;
        Frames = 0;
        return s;
    }
}
