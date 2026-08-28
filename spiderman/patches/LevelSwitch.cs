using System;
using System.Text;
using System.Text.RegularExpressions;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Boots straight into a chosen level, by rewriting the archive lookup.
///
/// Every level in CD.WAD is six files sharing a prefix -- `l1a1.vab`, `l1a1.sfx`,
/// `l1a1_t.trg`, `l1a1_l.psx`, `l1a1_o.psx`, `l1a1_g.psx` -- so which level the game
/// loads is decided entirely by the name it asks the archive for. Swapping the prefix
/// at that lookup puts any level behind the menu's normal "start playing" route, which
/// is worth far more than driving the level-select UI: the UI still has to be found, and
/// this works today for all 47 prefixes.
///
///     SPIDEY_LEVEL=l5a3     start in level 5, act 3
///     SPIDEY_LEVEL=list     print every prefix and exit
///
/// The first level prefix the game asks for is the one that gets redirected -- normally
/// `l1a1`, the level a new game starts on. Once bound, only that prefix is rewritten, so
/// when the level finishes and the game moves on to the next act it loads normally
/// rather than looping on the same assets.
/// </summary>
public static class LevelSwitch
{
    // Scratch for the rewritten name. Above the overlay region, inside the 8 MB the port
    // runs with, and never allocated from -- see OverlayPatches for why that space exists.
    const uint Scratch = 0x802B0000;

    static readonly Regex LevelName = new(@"^(l\d+a\d+[a-z]?)(.*)$", RegexOptions.IgnoreCase);

    static string _target;
    static string _source;
    public static int Rewrites { get; private set; }

    public static void Install()
    {
        var want = Environment.GetEnvironmentVariable("SPIDEY_LEVEL");
        if (string.IsNullOrWhiteSpace(want)) return;
        _target = want.Trim().ToLowerInvariant();
        Console.WriteLine($"[level] starting in '{_target}'");
    }

    /// <summary>
    /// Called first thing from the CdWadFind pre-hook. Returns the name the game should
    /// actually look up, having pointed a0 at it when it changed.
    /// </summary>
    public static string Redirect(CpuContext c, IMemory m, string name)
    {
        if (_target == null || name == null) return name;

        var hit = LevelName.Match(name);
        if (!hit.Success) return name;

        string prefix = hit.Groups[1].Value, rest = hit.Groups[2].Value;

        // Bind to whichever level the game asks for first and redirect only that one.
        _source ??= prefix.ToLowerInvariant();
        if (!string.Equals(prefix, _source, StringComparison.OrdinalIgnoreCase)) return name;

        // Follow the case the game used, in case the archive compare is case sensitive.
        string swapped = char.IsUpper(prefix[0]) ? _target.ToUpperInvariant() : _target;
        string renamed = swapped + rest;

        var bytes = Encoding.ASCII.GetBytes(renamed);
        for (int i = 0; i < bytes.Length; i++) m.WriteU8(Scratch + (uint)i, bytes[i]);
        m.WriteU8(Scratch + (uint)bytes.Length, 0);
        c.A0 = Scratch;

        Rewrites++;
        Console.WriteLine($"[level] {name} -> {renamed}");
        return renamed;
    }
}
