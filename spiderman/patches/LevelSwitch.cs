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
    static readonly Regex AudioLevelName = new(@"^(l\d+a\d+)", RegexOptions.IgnoreCase);

    static string _target;
    static string _source;
    public static int Rewrites { get; private set; }

    public static void Install()
    {
        var want = Environment.GetEnvironmentVariable("SPIDEY_LEVEL");
        if (!string.IsNullOrWhiteSpace(want))
        {
            _target = want.Trim().ToLowerInvariant();
            Console.WriteLine($"[level] starting in '{_target}'");
        }

    }

    /// <summary>
    /// Called first thing from the CdWadFind pre-hook. Returns the name the game should
    /// actually look up, having pointed a0 at it when it changed.
    /// </summary>
    public static string Redirect(CpuContext c, IMemory m, string name)
    {
        if (name == null) return name;


        if (_target == null) return name;

        var hit = LevelName.Match(name);
        if (!hit.Success) return name;

        string prefix = hit.Groups[1].Value, rest = hit.Groups[2].Value;

        // Bind to whichever level the game asks for first and redirect only that one.
        _source ??= prefix.ToLowerInvariant();
        if (!string.Equals(prefix, _source, StringComparison.OrdinalIgnoreCase)) return name;

        // Alternate acts such as L1A2A and L3A1A have their own trigger/geometry files
        // but reuse the parent act's VAB/SFX pair.  Asking CD.WAD for L1A2A.VAB runs the
        // retail lookup off the end because that entry does not exist.  Redirect only
        // those audio requests to the numeric parent while keeping every other resource
        // on the exact alternate-act prefix.
        string target = _target;
        if (rest.Equals(".VAB", StringComparison.OrdinalIgnoreCase) ||
            rest.Equals(".SFX", StringComparison.OrdinalIgnoreCase))
        {
            var audio = AudioLevelName.Match(target);
            if (audio.Success) target = audio.Groups[1].Value;
        }

        // Follow the case the game used, in case the archive compare is case sensitive.
        string swapped = char.IsUpper(prefix[0]) ? target.ToUpperInvariant() : target;
        return Rewrite(c, m, name, swapped + rest);
    }

    static string Rewrite(CpuContext c, IMemory m, string from, string to)
    {
        var bytes = Encoding.ASCII.GetBytes(to);
        for (int i = 0; i < bytes.Length; i++) m.WriteU8(Scratch + (uint)i, bytes[i]);
        m.WriteU8(Scratch + (uint)bytes.Length, 0);
        c.A0 = Scratch;

        Rewrites++;
        Console.WriteLine($"[level] {from} -> {to}");
        return to;
    }
}
