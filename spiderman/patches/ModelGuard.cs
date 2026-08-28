using System;
using System.Text;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Answers a model-name lookup that would otherwise fail, when a level was entered out
/// of order.
///
/// `ModelFind` (0x800694B8) walks a 40-record table at 0x800A0904 comparing names and
/// returns the index, or -1. Its caller at 0x8005904C stores that straight into a byte
/// field, so -1 becomes 0xFF, and then indexes record 255 -- 16 KB past the end of the
/// table, in static data that is all 0xFF -- and dereferences the 0xFFFFFFFF it finds
/// there. On hardware a `lw` from 0xFFFFFFFF is unaligned and would fault, so that path
/// is never reached in normal play: the model is simply always resident.
///
/// It is not always resident when SPIDEY_LEVEL jumps straight into an act. Resources
/// persist across the acts of a level, so each act's list only asks for what is not
/// already loaded -- level 5 act 2 loads `venom`, and act 3 lists only `venom2` because
/// `venom` is still there from act 2. Start in act 3 and it never was.
///
/// So when the lookup fails, the closest resident variant answers instead: `venom2` for
/// `venom`, and the other way round -- the pairing the game's own resource lists use.
/// This is deliberately done *at the lookup* rather than by adding a table entry. An
/// added entry means two records pointing at one model, and the game owns those
/// pointers; doing that corrupts the level far more thoroughly than the missing model
/// did. Returning an existing index touches nothing.
///
/// Only active when SPIDEY_LEVEL is set. Played in order, every act finds its models.
/// </summary>
public static class ModelGuard
{
    const uint Table = 0x800A0904;
    const int Records = 40, Stride = 64, MaxName = 8;

    static bool _on;
    static string _wanted;
    public static int Rescued { get; private set; }

    public static void Install()
        => _on = !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("SPIDEY_LEVEL"));

    static string ReadName(IMemory m, uint addr)
    {
        var sb = new StringBuilder();
        for (uint i = 0; i < 16; i++)
        {
            byte b = m.ReadU8(addr + i);
            if (b == 0) break;
            sb.Append((char)b);
        }
        return sb.ToString();
    }

    /// <summary>pre-hook -- a0 is the name being looked up.</summary>
    public static void FindEnter(CpuContext c, IMemory m)
        => _wanted = _on ? ReadName(m, c.A0) : null;

    /// <summary>post-hook -- v0 is the index, or -1.</summary>
    public static void FindExit(CpuContext c, IMemory m)
    {
        if (!_on || c.V0 != 0xFFFFFFFFu || string.IsNullOrEmpty(_wanted)) return;

        // First choice is the digit pairing the resource lists use: venom <-> venom2.
        string alt = Counterpart(_wanted);
        int slot = alt == null ? -1 : IndexOf(m, alt);

        // Otherwise the closest relative that is loaded. Variants are named by prefix --
        // level 2 wants `henchman` and has `Henchngt` resident -- so the longest shared
        // prefix picks the right one. Five characters is enough to stop it reaching for
        // something unrelated, and short names simply go unrescued.
        if (slot < 0)
        {
            int best = 0;
            for (int i = 0; i < Records; i++)
            {
                var name = ReadName(m, Table + (uint)(i * Stride));
                if (name.Length == 0) continue;
                int n = SharedPrefix(name, _wanted);
                if (n >= 5 && n > best) { best = n; slot = i; alt = name; }
            }
        }

        if (slot < 0) { Unrescued(m, alt); return; }

        Console.WriteLine($"[model] '{_wanted}' is not loaded here; using '{alt}' (slot {slot})");
        c.V0 = (uint)slot;
        Rescued++;
    }

    static int IndexOf(IMemory m, string want)
    {
        for (int i = 0; i < Records; i++)
            if (string.Equals(ReadName(m, Table + (uint)(i * Stride)), want, StringComparison.OrdinalIgnoreCase))
                return i;
        return -1;
    }

    static int SharedPrefix(string a, string b)
    {
        int n = 0;
        while (n < a.Length && n < b.Length && char.ToLowerInvariant(a[n]) == char.ToLowerInvariant(b[n])) n++;
        return n;
    }

    static string _lastMoan;

    /// <summary>Name the miss once, with what is loaded, so the gap is identifiable.</summary>
    static void Unrescued(IMemory m, string alt)
    {
        if (_wanted == _lastMoan) return;
        _lastMoan = _wanted;

        var have = new System.Collections.Generic.List<string>();
        for (int i = 0; i < Records; i++)
        {
            var n = ReadName(m, Table + (uint)(i * Stride));
            if (n.Length > 0) have.Add(n);
        }
        Console.WriteLine($"[model] MISS '{_wanted}'" + (alt != null ? $" (tried '{alt}')" : "") +
                          " -- loaded: " + string.Join(" ", have));
    }

    /// <summary>venom2 -> venom and venom -> venom2: how the resource lists pair them.</summary>
    static string Counterpart(string name)
    {
        if (name.Length > 1 && char.IsDigit(name[^1]))
        {
            var b = name.TrimEnd('0', '1', '2', '3', '4', '5', '6', '7', '8', '9');
            return b.Length > 0 ? b : null;
        }
        return name.Length < MaxName ? name + "2" : null;
    }
}
