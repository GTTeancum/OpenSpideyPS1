using System;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Picks Spider-Man's costume.
///
/// The choice is a word at 0x800A5704, inside the block at 0x800A5688 that the game
/// saves to the memory card -- the same structure the "everything" cheat fills in, a few
/// fields along from the unlock bits. It indexes the list the COSTUME VIEWER shows under
/// SPECIAL, in that order.
///
///     SPIDEY_COSTUME=symbiote     SPIDEY_COSTUME=2099     SPIDEY_COSTUME=7
///
/// It was tempting to do this by swapping the costume file at the archive lookup, and
/// that does not work: the cost*.psx files are 1452-byte palette and texture sets, not
/// models, and the game only applies one when this variable tells it to. Swapping the
/// model itself (spidey.psx, 288 KB) for a 1452-byte skin truncates it and the game dies
/// on a short pointer.
///
/// Written every frame, like the cheat flags, because the block is the same memory a
/// save is built from.
/// </summary>
public static class Costume
{
    const uint Selected = 0x800A5704;

    /// <summary>The COSTUME VIEWER's list, in its own order.</summary>
    static readonly string[] Names =
    {
        "spiderman", "2099", "symbiote", "captain", "unlimited",
        "bagman", "scarlet", "benreilly", "quickchange", "peterparker",
    };

    static readonly System.Collections.Generic.Dictionary<string, int> Aliases =
        new(StringComparer.OrdinalIgnoreCase)
    {
        ["default"] = 0, ["spidey"] = 0, ["spiderman"] = 0,
        ["2099"] = 1,
        ["symbiote"] = 2, ["black"] = 2, ["symbi"] = 2,
        ["captain"] = 3, ["universe"] = 3,
        ["unlimited"] = 4,
        ["bagman"] = 5, ["bag"] = 5,
        ["scarlet"] = 6,
        ["benreilly"] = 7, ["ben"] = 7, ["reilly"] = 7,
        ["quickchange"] = 8, ["quick"] = 8,
        ["peterparker"] = 9, ["peter"] = 9, ["parker"] = 9,
    };

    static int _want = -1;

    public static void Install()
    {
        var spec = Environment.GetEnvironmentVariable("SPIDEY_COSTUME");
        if (string.IsNullOrWhiteSpace(spec)) return;
        spec = spec.Trim();

        if (int.TryParse(spec, out int n) && n >= 0 && n < Names.Length) _want = n;
        else if (Aliases.TryGetValue(spec, out int a)) _want = a;
        else
        {
            Console.Error.WriteLine($"[costume] unknown '{spec}'; one of: {string.Join(", ", Names)}");
            return;
        }

        Console.WriteLine($"[costume] {Names[_want]} (index {_want})");
        Event.AddListener<VSyncEvent>(e => e.Memory?.WriteU32(Selected, (uint)_want));
    }
}
