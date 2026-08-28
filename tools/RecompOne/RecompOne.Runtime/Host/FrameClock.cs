using System.Diagnostics;

namespace RecompOne.Runtime.Host;

internal static class FrameClock
{
    const double VBlankMs = 1000.0 / 60.0;
    const double SpinMs = 1.5;

    /// <summary>
    /// Console vblanks per game frame. 1 is a 60 fps game; 2 is a 30 fps game.
    ///
    /// This is not a cosmetic frame cap. A PS1 game paces itself by asking for the
    /// next vblank and getting whichever one it is ready for -- so a title whose frame
    /// costs more than 16.7 ms on real hardware is a 30 fps game, permanently, because
    /// it always misses. A recompile does that same frame in a fraction of a
    /// millisecond and therefore never misses, which makes the whole game run at
    /// double speed. Setting this to 2 restores the cadence the game was built around.
    /// </summary>
    public static int VBlanksPerFrame = 1;

    static double FrameMs => VBlankMs * VBlanksPerFrame;

    static readonly Stopwatch _clock = Stopwatch.StartNew();
    static double _nextFrameMs;

    public static bool VSync { get; set; }

    public static double LastFrameMs { get; private set; }
    public static double LastWaitMs { get; private set; }

    static double _lastStart;


    public static void Throttle()
    {
        double now = _clock.Elapsed.TotalMilliseconds;
        LastFrameMs = now - _lastStart;
        _lastStart = now;

        _nextFrameMs += FrameMs;
        double wait = _nextFrameMs - now;

        if (wait < -100)
        {
            _nextFrameMs = now;
            LastWaitMs = 0;
            return;
        }

        if (wait <= 0)
        {
            LastWaitMs = 0;
            return;
        }

        if (VSync && wait < FrameMs * 0.75)
        {
            LastWaitMs = 0;
            return;
        }

        double sleepUntil = _nextFrameMs - SpinMs;
        if (now < sleepUntil)
        {
            int ms = (int)(sleepUntil - now);
            if (ms > 0) Thread.Sleep(ms);
        }

        while (_clock.Elapsed.TotalMilliseconds < _nextFrameMs)
            Thread.SpinWait(48);

        LastWaitMs = wait;
    }

    public static void Resync() => _nextFrameMs = _clock.Elapsed.TotalMilliseconds;
}
