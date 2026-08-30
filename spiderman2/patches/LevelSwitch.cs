using System;
using System.Text;
using System.Text.RegularExpressions;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Boots straight into a chosen level, by rewriting the archive lookup.
///
/// Every level in CD.WAD is a handful of files sharing a prefix -- `e1m1e.vab`,
/// `e1m1.sfx`, `e1m1_t.trg`, `e1m1_l.psx`, `e1m1_o.psx`, `e1m1_g.psx` -- so which level the game
/// loads is decided entirely by the name it asks the archive for. Swapping the prefix
/// at that lookup puts any level behind the menu's normal "start playing" route, which
/// is worth far more than driving the level-select UI: the UI still has to be found, and
/// this covers all 44 prefixes the archive carries geometry for.
///
///     SPIDEY_LEVEL=e3m1     start in episode 3, mission 1
///
/// The first level prefix the game asks for is the one that gets redirected -- normally
/// the level a new game starts on. Once bound, only that prefix is rewritten, so
/// when the level finishes and the game moves on to the next act it loads normally
/// rather than looping on the same assets.
/// </summary>
public static class LevelSwitch
{
    // Scratch for the rewritten name. Above the overlay region, inside the 8 MB the port
    // runs with, and never allocated from -- see OverlayPatches for why that space exists.
    const uint Scratch = 0x802B0000;

    static readonly Regex LevelName = new(@"^(e\d+m\d+|tr\d{2}|wr\d{2}|xt\d{2}|dem\d)(.*)$", RegexOptions.IgnoreCase);

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

        // Never bind to a demo. The attract loop plays dem1..dem4 while the title screen
        // is up, so on a normal boot the first level prefix the game asks for belongs to
        // the attract demo, not to the game the player is about to start -- binding there
        // would redirect the demo and leave the real level alone. Demos are still
        // redirectable if asked for by name.
        if (_source == null && prefix.StartsWith("dem", StringComparison.OrdinalIgnoreCase)
                            && !_target.StartsWith("dem", StringComparison.OrdinalIgnoreCase))
            return name;

        // Bind to whichever level the game asks for first and redirect only that one.
        _source ??= prefix.ToLowerInvariant();
        if (!string.Equals(prefix, _source, StringComparison.OrdinalIgnoreCase)) return name;

        // Follow the case the game used, in case the archive compare is case sensitive.
        string swapped = char.IsUpper(prefix[0]) ? _target.ToUpperInvariant() : _target;
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
