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
    static readonly Regex CostumeFile = new(@"^cost[a-z0-9]*\.psx$", RegexOptions.IgnoreCase);

    static string _target;
    static string _source;
    static string _costume;
    public static int Rewrites { get; private set; }

    /// <summary>
    /// The costume skins. These are not models -- every one is exactly 1452 bytes, a
    /// palette and texture set over the 288 KB `spidey.psx`. Handing the game one of
    /// these where it expected the model truncates it and it dies on a short pointer,
    /// so the redirect targets the skin file and leaves the model alone.
    ///
    /// INCOMPLETE: the redirect loads the requested skin, but nothing changes on screen.
    /// The game only *applies* a skin when its costume selection says to, and the
    /// default Spider-Man wears none -- his colours are in the model. Switching costume
    /// therefore needs that selection variable, not a different file. The table the
    /// game picks the filename from is at 0x80098C10 (costarm, cost99, costbag, costblk,
    /// costcapt, costscar), but nothing in the main executable or the shell overlay
    /// forms that address with a lui/addiu pair, so it is reached some other way and the
    /// index has not been found yet. A RAM diff across a costume change would find it.
    /// </summary>
    static readonly System.Collections.Generic.Dictionary<string, string> Costumes =
        new(StringComparer.OrdinalIgnoreCase)
    {
        ["default"] = null,      ["spidey"] = null,
        ["symbiote"] = "costblk", ["black"] = "costblk",
        ["2099"] = "cost99",
        ["bagman"] = "costbag",   ["bag"] = "costbag",
        ["captain"] = "costcapt", ["universe"] = "costcapt",
        ["peter"] = "costpete",   ["parker"] = "costpete",
        ["scarlet"] = "costscar",
        ["armour"] = "costarm",   ["armor"] = "costarm",
    };

    public static void Install()
    {
        var want = Environment.GetEnvironmentVariable("SPIDEY_LEVEL");
        if (!string.IsNullOrWhiteSpace(want))
        {
            _target = want.Trim().ToLowerInvariant();
            Console.WriteLine($"[level] starting in '{_target}'");
        }

        var cos = Environment.GetEnvironmentVariable("SPIDEY_COSTUME");
        if (!string.IsNullOrWhiteSpace(cos))
        {
            if (Costumes.TryGetValue(cos.Trim(), out var file))
            {
                _costume = file;
                if (file != null) Console.WriteLine($"[costume] wearing '{cos.Trim()}' ({file}.psx)");
            }
            else
            {
                // A raw file name works too, for the ones without a friendly alias.
                _costume = cos.Trim();
                Console.WriteLine($"[costume] wearing '{_costume}.psx'");
            }
        }
    }

    /// <summary>
    /// Called first thing from the CdWadFind pre-hook. Returns the name the game should
    /// actually look up, having pointed a0 at it when it changed.
    /// </summary>
    public static string Redirect(CpuContext c, IMemory m, string name)
    {
        if (name == null) return name;

        // The costume is a skin file, so whichever one the game asks for is swapped for
        // the one wanted. a0 is pointed at scratch rather than the game's own buffer, so
        // it still registers under the name the game used and every lookup resolves.
        if (_costume != null && CostumeFile.IsMatch(name))
            return Rewrite(c, m, name, _costume + ".psx");

        if (_target == null) return name;

        var hit = LevelName.Match(name);
        if (!hit.Success) return name;

        string prefix = hit.Groups[1].Value, rest = hit.Groups[2].Value;

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
