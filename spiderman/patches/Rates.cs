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
    static readonly Stopwatch _clock = Stopwatch.StartNew();
    static double _lastAt;
    static long _frames, _ot, _disp, _wait, _poll, _present, _service, _vcount;

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

        string s =
            $"rates/s: RunFrame {(frames - _frames) / dt,6:F1} | " +
            $"PutDispEnv {(disp - _disp) / dt,6:F1} | " +
            $"DrawOTag {(ot - _ot) / dt,6:F1} | " +
            $"VSync(0) {(wait - _wait) / dt,6:F1} | " +
            $"VSync(-1) {(poll - _poll) / dt,8:F0} | " +
            $"present {(present - _present) / dt,6:F1} | " +
            $"service {(service - _service) / dt,7:F0} | " +
            $"vblank {(vcount - _vcount) / dt,6:F1}";

        _frames = frames; _ot = ot; _disp = disp; _wait = wait;
        _poll = poll; _present = present; _service = service; _vcount = vcount;
        return s + "\n[diag] swap sites: " + Top(RecompOne.Runtime.Sdk.LibGpu.DispCallers)
                 + "\n[diag] draw sites: " + Top(RecompOne.Runtime.Sdk.LibGpu.OtCallers)
                 + "\n[diag] frame loop: " + Top(RecompOne.Runtime.Sdk.LibGpu.DispGrandparents);
    }
}
