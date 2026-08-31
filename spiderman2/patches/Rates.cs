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
    /// The game's simulation tick. Everything that moves advances with it, so measured
    /// against a real clock this is the game's speed -- which the draw rate and the
    /// vblank rate both fail to report on their own.
    ///
    /// 0x800C1F94, found by differencing RAM snapshots during level 1 and then checked
    /// against the draw rate: in steady gameplay it advances once per DrawOTag update.
    /// SPIDEY_TICK overrides it, and SPIDEY_TICK=0 turns the column off.
    ///
    /// Do not point this at the block around 0x800B29D0, which advances at 2.00 per frame
    /// and looks like a double-speed clock. That is the pad debounce array -- the input
    /// code walks it twice per update -- and reading it as a tick is what made the
    /// Spider-Man port's equivalent column print nonsense for so long.
    /// </summary>
    static readonly uint TickCounter = ParseAddr(Environment.GetEnvironmentVariable("SPIDEY_TICK"));

    const uint DefaultTick = 0x800C1F94;

    /// <summary>
    /// Incremented by the function registered with VSyncCallback at 0x800690A8.
    /// It measures delivered vblank IRQs from inside the retail game, independently
    /// of the runtime's host event counter.
    /// </summary>
    const uint VBlankCallbackCounter = 0x800C2434;

    static uint ParseAddr(string s)
    {
        if (string.IsNullOrWhiteSpace(s)) return DefaultTick;
        try { return Convert.ToUInt32(s.Trim().Replace("0x", ""), 16); }
        catch { return 0; }
    }

    static RecompOne.Runtime.Memory.IMemory _mem;

    public static void Install()
        => RecompOne.Runtime.Events.Event.AddListener<RecompOne.Runtime.Events.VSyncEvent>(
               e => _mem = e.Memory);

    static readonly Stopwatch _clock = Stopwatch.StartNew();
    static double _lastAt;
    static long _ot, _disp, _wait, _poll, _present, _service, _vcount, _tick, _vblankCallback;

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

        long ot      = RecompOne.Runtime.Sdk.LibGpu.OtCount;
        long disp    = RecompOne.Runtime.Sdk.LibGpu.DispCount;
        long wait    = RecompOne.Runtime.Sdk.LibEtc.WaitCalls;
        long poll    = RecompOne.Runtime.Sdk.LibEtc.PollCalls;
        long present = RecompOne.Runtime.Runtime.Presents;
        long service = RecompOne.Runtime.Runtime.ServicePasses;
        long vcount  = System.Threading.Interlocked.Read(ref Diag.Frame);
        long tick    = (_mem != null && TickCounter != 0) ? (int)_mem.ReadU32(TickCounter) : 0;
        long vblankCallback = _mem != null ? (int)_mem.ReadU32(VBlankCallbackCounter) : 0;

        string s =
            $"rates/s: PutDispEnv {(disp - _disp) / dt,6:F1} | " +
            $"DrawOTag {(ot - _ot) / dt,6:F1} | " +
            $"VSync(0) {(wait - _wait) / dt,6:F1} | " +
            $"VSync(-1) {(poll - _poll) / dt,8:F0} | " +
            $"present {(present - _present) / dt,6:F1} | " +
            $"service {(service - _service) / dt,7:F0} | " +
            $"vblank {(vcount - _vcount) / dt,6:F1} | " +
            $"GAME TICK {(tick - _tick) / dt,6:F1} | " +
            $"VBLANK IRQ {Math.Max(0, vblankCallback - _vblankCallback) / dt,6:F1}" +
            $" | wedge hits {RecompOne.Runtime.Gpu.WedgeHits} of {RecompOne.Runtime.Gpu.TotalVerts} verts";

        _ot = ot; _disp = disp; _wait = wait;
        _poll = poll; _present = present; _service = service; _vcount = vcount; _tick = tick;
        _vblankCallback = vblankCallback;
        return s + "\n[diag] swap sites: " + Top(RecompOne.Runtime.Sdk.LibGpu.DispCallers)
                 + "\n[diag] draw sites: " + Top(RecompOne.Runtime.Sdk.LibGpu.OtCallers)
                 + "\n[diag] frame loop: " + Top(RecompOne.Runtime.Sdk.LibGpu.DispGrandparents);
    }
}
