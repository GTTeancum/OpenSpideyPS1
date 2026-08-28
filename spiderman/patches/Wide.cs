using System;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Hle;
using RecompOne.Runtime.Sdk;

namespace Recompiled;

/// <summary>
/// 16:9 widescreen.
///
/// The renderer draws into a target widened by GpuHle.WideMargin, which reveals
/// geometry the 4:3 frame was clipping away -- the GTE saturates projected X well beyond
/// the screen, so the world is submitted and merely cut off. That part needs no help
/// from the game.
///
/// The margins do come up torn -- geometry missing along the edges -- because the game
/// culls what it believes is off screen. Widening libgpu's clamp limits at
/// 0x800B0E2C/0x800B0E2E (1024 and 512 here) was tried and makes no difference, so those
/// are not the gate and the write is not kept. The cull is somewhere in the game's own
/// renderer; an enclosed interior tears too, which rules out the alternative explanation
/// that the rooftop simply stops being modelled past the 4:3 frame.
/// </summary>
public static class Wide
{
    public static bool Enabled { get; private set; }

    /// <summary>
    /// The gameplay loop's buffer swap, at 0x8002C2AC -- the `jal` to the swap routine
    /// in the loop that spins on DrawSync. Identified positively rather than by
    /// excluding the menus: the menu swap arrives through a path where the saved return
    /// address is not at sp+16, so reading it there yields a junk value (0x000000F0 in
    /// practice) that cannot be matched against reliably.
    ///
    /// In-engine cutscenes run through this same loop, so they widen with gameplay,
    /// which is what was wanted. FMV needs no help either way: it presents through the
    /// 24-bit path, which never takes a widened target.
    /// </summary>
    const uint GameplaySwap = 0x8002C2AC;

    static float _aspect;

    public static void Install()
    {
        if (Environment.GetEnvironmentVariable("SPIDEY_WIDE") != "1") return;
        Enabled = true;
        var a = Environment.GetEnvironmentVariable("SPIDEY_WIDE_ASPECT");
        _aspect = float.TryParse(a, out float f) && f > 1.3f && f < 3f ? f : 16f / 9f;
        Display.WideAspect = _aspect;
        Event.AddListener<VSyncEvent>(_ => Follow());
        RecompOne.Runtime.Diagnostics.DrawEnvWarn.TintBackground =
            Environment.GetEnvironmentVariable("SPIDEY_WIDE_DEBUG") == "1";
        Console.WriteLine($"[wide] aspect {_aspect:F3}, gameplay only");
    }

    /// <summary>
    /// Widen for gameplay, and hand back the console's own 4:3 everywhere else, which
    /// the window then pillarboxes.
    /// </summary>
    static void Follow()
    {
        bool wide = LibGpu.LastDispGrandparent == GameplaySwap;
        float want = wide ? _aspect : 0f;
        if (Display.WideAspect != want) Display.WideAspect = want;
    }

}
