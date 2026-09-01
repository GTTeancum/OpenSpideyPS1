using System;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Selects one of SM2's nineteen Spider-Man texture libraries without menu input.
///
/// The actor is shared: func_8004E4BC receives a one-based costume number and uses it
/// to index the retail sp_tex00.psx ... sp_tex18.psx table at 0x800B30E4.  A pre-hook
/// changes that argument before the game's own loader runs, so tests exercise the same
/// archive lookup and texture upload path as an interactive costume selection.
///
///     SPIDEY_COSTUME=0       SPIDEY_COSTUME=18
///     SPIDEY_COSTUME=default SPIDEY_COSTUME=prodigy
///
/// This is process-local instrumentation only. It does not send input to Windows and
/// it is entirely inactive unless SPIDEY_COSTUME is set.
/// </summary>
public static class Costume
{
    const int CostumeCount = 19;

    static readonly System.Collections.Generic.Dictionary<string, int> Aliases =
        new(StringComparer.OrdinalIgnoreCase)
    {
        ["default"] = 0,
        ["spider-man"] = 0,
        ["spiderman"] = 0,
        ["spidey"] = 0,
        ["prodigy"] = 2,
        ["dusk"] = 3,
        ["ricochet"] = 8,
        ["bagman"] = 13,
        ["bag-man"] = 13,
        ["peter"] = 17,
        ["parker"] = 17,
        ["peterparker"] = 17,
    };

    static int _slot = -1;
    static bool _reported;
    static bool _headMorphReported;

    /// <summary>
    /// Slots 13 and 17 change the head/body silhouette and cannot use the shared
    /// Dreamcast SPIDEY mesh.  During a forced validation run, source the game's
    /// spidey.psx request from the dedicated native SM2-skeleton actor instead.
    /// </summary>
    public static string DreamcastAssetFor(string requestedName)
    {
        string source = (_slot, requestedName.ToLowerInvariant()) switch
        {
            (13, "spidey.psx") => "spidey-slot13.psx",
            (17, "spidey.psx") => "spidey-slot17.psx",
            (13, "sp_tex13.psx") => "sp_tex13-dc.psx",
            (17, "sp_tex17.psx") => "sp_tex17-dc.psx",
            _ => requestedName,
        };
        if (!source.Equals(requestedName, StringComparison.OrdinalIgnoreCase))
            Console.WriteLine($"[costume] Dreamcast asset {requestedName} <- {source}");
        return source;
    }

    public static void Install()
    {
        var spec = Environment.GetEnvironmentVariable("SPIDEY_COSTUME");
        if (string.IsNullOrWhiteSpace(spec)) return;
        spec = spec.Trim();

        if (int.TryParse(spec, out int numeric) && numeric >= 0 && numeric < CostumeCount)
            _slot = numeric;
        else if (Aliases.TryGetValue(spec, out int alias))
            _slot = alias;
        else
        {
            Console.Error.WriteLine(
                $"[costume] unknown '{spec}'; expected a slot from 0 through {CostumeCount - 1}");
            return;
        }

        Console.WriteLine($"[costume] requested slot {_slot:D2} (sp_tex{_slot:D2}.psx)");
    }

    /// <summary>Pre-hook on func_8004E4BC(actor data, one-based costume).</summary>
    public static void SelectTextureLibrary(CpuContext c, IMemory m)
    {
        if (_slot < 0) return;

        c.A1 = (uint)(_slot + 1);
        if (_reported) return;
        _reported = true;
        Console.WriteLine(
            $"[costume] selected retail loader slot {_slot:D2} -> sp_tex{_slot:D2}.psx");
    }

    /// <summary>
    /// Pre-hook on func_8004EC34(scale, mesh index, retail vertex target).
    ///
    /// Retail slots 13 and 17 rewrite mesh 7 from fixed low-detail Bag-Man/Peter
    /// coordinate tables.  The dedicated Dreamcast actors already contain those
    /// silhouettes, and the retail tables are shorter than their high-detail heads;
    /// letting the loop use the target mesh's larger vertex count reads beyond the
    /// tables and destroys the head.  Other meshes and non-dedicated slots retain the
    /// original scaling path.
    /// </summary>
    public static bool SkipRetailSpecialHeadMorph(CpuContext c, IMemory m)
    {
        if ((_slot != 13 && _slot != 17) || c.A1 != 7u) return true;
        if (!_headMorphReported)
        {
            _headMorphReported = true;
            Console.WriteLine(
                $"[costume] bypassed retail slot {_slot:D2} mesh-7 morph for dedicated DC actor");
        }
        return false;
    }
}
