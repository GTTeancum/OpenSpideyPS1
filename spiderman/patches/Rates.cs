using System;
using System.Diagnostics;

namespace Recompiled;

/// <summary>
/// Every rate that could plausibly be "the frame rate", sampled together against one
/// wall clock.
///
/// Measuring one counter at a time is what made the speed problem hard to pin down:
/// TriggerPass turned out to be per level-load, DrawOTag is per rendering pass rather
/// than per frame, and the frame number in the log is the console's vblank counter.
/// Each of those reads like a frame rate and none of them is one. Printing them side
/// by side makes the relationships -- draws per frame, vblanks per frame, presents per
/// frame -- readable directly instead of inferred.
/// </summary>
public static class Rates
{
    /// <summary>
    /// A counter the game advances once per gameplay update, so measured against a real
    /// clock this is the game's speed -- which the host present rate and the vblank rate
    /// both fail to report on their own.
    ///
    /// This used to read 0x800A4E2C, described as the simulation tick. It is not one.
    /// That address is inside the pad debounce array the helper at 0x8006B208 maintains
    /// -- +0 pressed, +1 edge, +4 frames held, +8 frames released, +12 the counter this
    /// was reading -- and it resets whenever the button changes, which is why the column
    /// used to print 8.4, then 3.2, then 136, and sometimes a negative rate. Those
    /// numbers described a button, not the game.
    ///
    /// 0x800B4F38 was found by differencing RAM snapshots and then checked against the
    /// draw rate. In steady gameplay it advances once per DrawOTag/PutDispEnv update:
    /// 15 times while the runtime presents 30 times and delivers 60 vblanks.
    /// </summary>
    const uint TickCounter = 0x800B4F38;

    /// <summary>
    /// Incremented by the function registered with VSyncCallback at 0x8005E510.
    /// Unlike the host event counter, this proves how many vblank IRQs game code
    /// actually received. It must stay near 60/s even though gameplay updates at 15/s.
    /// </summary>
    const uint VBlankCallbackCounter = 0x800B5468;

    static RecompOne.Runtime.Memory.IMemory _mem;

    public static void Install()
        => RecompOne.Runtime.Events.Event.AddListener<RecompOne.Runtime.Events.VSyncEvent>(
               e => _mem = e.Memory);

    static readonly Stopwatch _clock = Stopwatch.StartNew();
    static double _lastAt;
    static long _frames, _ot, _disp, _wait, _poll, _present, _service, _vcount, _tick, _vblankCallback;

    static string Top(System.Collections.Concurrent.ConcurrentDictionary<uint, long> d)
    {
        var top = new System.Collections.Generic.List<string>();
        foreach (var kv in d) top.Add($"0x{kv.Key:X8}x{kv.Value}");
        top.Sort();
        return string.Join(" ", top.GetRange(0, Math.Min(6, top.Count)));
    }

    public static string Sample()
    {
        double now = _clock.Elapsed.TotalSeconds;
        double dt = Math.Max(now - _lastAt, 0.001);
        _lastAt = now;

        long frames  = GameTrace.Frames;
        long ot      = RecompOne.Runtime.Sdk.LibGpu.OtCount;
        long disp    = RecompOne.Runtime.Sdk.LibGpu.DispCount;
        long wait    = RecompOne.Runtime.Sdk.LibEtc.WaitCalls;
        long poll    = RecompOne.Runtime.Sdk.LibEtc.PollCalls;
        long present = RecompOne.Runtime.Runtime.Presents;
        long service = RecompOne.Runtime.Runtime.ServicePasses;
        long vcount  = System.Threading.Interlocked.Read(ref Diag.Frame);
        long tick    = _mem != null ? (int)_mem.ReadU32(TickCounter) : 0;
        long vblankCallback = _mem != null ? (int)_mem.ReadU32(VBlankCallbackCounter) : 0;

        string s =
            $"rates/s: RunFrame {(frames - _frames) / dt,6:F1} | " +
            $"PutDispEnv {(disp - _disp) / dt,6:F1} | " +
            $"DrawOTag {(ot - _ot) / dt,6:F1} | " +
            $"VSync(0) {(wait - _wait) / dt,6:F1} | " +
            $"VSync(-1) {(poll - _poll) / dt,8:F0} | " +
            $"present {(present - _present) / dt,6:F1} | " +
            $"service {(service - _service) / dt,7:F0} | " +
            $"vblank {(vcount - _vcount) / dt,6:F1} | " +
            $"GAME TICK {(tick - _tick) / dt,6:F1} | " +
            $"VBLANK IRQ {Math.Max(0, vblankCallback - _vblankCallback) / dt,6:F1}" +
            $" | wedge hits {RecompOne.Runtime.Gpu.WedgeHits} of {RecompOne.Runtime.Gpu.TotalVerts} verts" +
            $" | wide spans accepted {RecompOne.Runtime.Gpu.WideSpanAccepted}" +
            $" rejected x/y {RecompOne.Runtime.Gpu.SpanXRejected}/{RecompOne.Runtime.Gpu.SpanYRejected}";

        _frames = frames; _ot = ot; _disp = disp; _wait = wait;
        _poll = poll; _present = present; _service = service; _vcount = vcount; _tick = tick;
        _vblankCallback = vblankCallback;
        return s + "\n[diag] swap sites: " + Top(RecompOne.Runtime.Sdk.LibGpu.DispCallers)
                 + "\n[diag] draw sites: " + Top(RecompOne.Runtime.Sdk.LibGpu.OtCallers)
                 + "\n[diag] frame loop: " + Top(RecompOne.Runtime.Sdk.LibGpu.DispGrandparents);
    }
}
