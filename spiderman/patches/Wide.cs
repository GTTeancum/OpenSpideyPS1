using System;
using RecompOne.Runtime.Hle;

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

    public static void Install()
    {
        if (Environment.GetEnvironmentVariable("SPIDEY_WIDE") != "1") return;
        Enabled = true;
        var a = Environment.GetEnvironmentVariable("SPIDEY_WIDE_ASPECT");
        Display.WideAspect = float.TryParse(a, out float f) && f > 1.3f && f < 3f ? f : 16f / 9f;
        Console.WriteLine($"[wide] aspect {Display.WideAspect:F3}");
    }

}
