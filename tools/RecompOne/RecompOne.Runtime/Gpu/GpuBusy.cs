using System;
using System.Diagnostics;

namespace RecompOne.Runtime;

/// <summary>
/// How long the GPU is still working on the ordering table it was handed.
///
/// Some games never call VSync during gameplay and pace themselves purely on the GPU
/// finishing: they submit an ordering table, then spin on DrawSync until the drawing is
/// done, and that spin *is* the frame. Spider-Man is one of them -- its gameplay loop is
///
///     do { tick(); } while (DrawSync(1) != 0);
///     swap(); DrawOTag(next);
///
/// with no vblank wait anywhere. A DrawSync that always answers "idle" therefore removes
/// the only thing pacing the game, and it runs as fast as the host will let it.
///
/// This models the wait rather than the rasterising. Modelling the pixels would not be
/// enough on its own: on hardware a frame is mostly the CPU's own work -- game logic,
/// GTE transforms, building the table -- and a recompile does all of that in a fraction
/// of a millisecond, so a faithful fill-rate model would still come out several times
/// too fast. What is reproducible is the cadence the game was built to hit, so the
/// budget is expressed as a frame period and the GPU is reported busy until it is spent.
/// </summary>
public static class GpuBusy
{
    static readonly Stopwatch _clock = Stopwatch.StartNew();
    static double _busyUntilMs;

    /// <summary>
    /// How long a submitted ordering table keeps the GPU busy, in milliseconds.
    /// Zero disables the model, and DrawSync answers "idle" as it did before.
    /// </summary>
    public static double FrameBudgetMs;

    /// <summary>Set from the drawing submission -- the GPU has work again.</summary>
    public static void Submit()
    {
        if (FrameBudgetMs <= 0) return;
        // Deliberately not queued behind whatever is outstanding. Stacking budgets would
        // let a burst of submissions -- a loading screen, a cutscene, anything that
        // draws without waiting -- run the backlog up into whole seconds of false stall.
        _busyUntilMs = _clock.Elapsed.TotalMilliseconds + FrameBudgetMs;
    }

    /// <summary>Milliseconds of drawing still outstanding; 0 when the GPU is idle.</summary>
    public static double RemainingMs()
    {
        if (FrameBudgetMs <= 0) return 0;
        double left = _busyUntilMs - _clock.Elapsed.TotalMilliseconds;
        return left > 0 ? left : 0;
    }

    /// <summary>Give up the rest of the budget -- for a reset, or a mode change.</summary>
    public static void Clear() => _busyUntilMs = 0;
}
