using RecompOne.Runtime.Context;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace RecompOne.Runtime.Sdk;

public static class LibEtc
{
    static int _vcount;

    /// <summary>Rate instrumentation -- VSync(0) waits vs VSync(-1) polls.</summary>
    public static long WaitCalls, PollCalls;

    static double FrameSeconds => Runtime.VBlanksPerFrame / 60.0;
    static readonly VSyncEvent _vsyncEvent = new();
    static readonly System.Diagnostics.Stopwatch _sinceFrame = System.Diagnostics.Stopwatch.StartNew();

    public static void VSync(CpuContext c, IMemory m)
    {
        int mode = (int)c.A0;
        Log.Sdk($"VSync({mode})");
        if (mode < 0)
        {
            PollCalls++;
            // VSync(-1) reads the vblank counter without waiting. On hardware that
            // counter advances on its own, so a game can poll it to wait; here it only
            // moves when a frame is presented, and a poll loop would spin forever.
            // Present one once enough real time has passed, which is when the console
            // would have counted a vblank anyway.
            if (_sinceFrame.Elapsed.TotalSeconds >= FrameSeconds) Runtime.IdleTick();
            c.V0 = (uint)_vcount;
            return;
        }
        //if (mode == 1) { c.V0 = 0; return; }
        
        WaitCalls++;
        Pump(c, m);
        c.V0 = 0;
    }

    static readonly System.Diagnostics.Stopwatch _sinceService = System.Diagnostics.Stopwatch.StartNew();

    /// <summary>
    /// What the idle breakers call. Delivers a real vblank when one is due, and
    /// otherwise just keeps the host and the hardware serviced -- see
    /// Runtime.ServiceOnly for why those two have to be separate.
    /// </summary>
    public static void Service(CpuContext c, IMemory m)
    {
        if (_sinceFrame.Elapsed.TotalSeconds >= FrameSeconds) { Pump(c, m); return; }
        // Cheap, but not free: rate-limit it so a tight spin does not spend all its
        // time presenting instead of running the game.
        if (_sinceService.Elapsed.TotalMilliseconds < 4) return;
        _sinceService.Restart();
        Runtime.ServiceOnly();
    }

    /// <summary>
    /// Advance one frame: present, and let the game see a vblank. Called by VSync, and
    /// by the idle-loop breaker when the game busy-waits on an interrupt-updated flag
    /// instead of calling VSync itself.
    /// </summary>
    public static void Pump(CpuContext c, IMemory m)
    {
        Runtime.PresentFrame();
        _vcount += Runtime.VBlankStep;
        _sinceFrame.Restart();

        if (Event.HasAnyListeners<VSyncEvent>())
        {
            var e = _vsyncEvent;
            e.Context = c; e.Memory = m;
            e.Frame = _vcount;
            Event.Dispatch(e);
        }
    }
}
