using System;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Dispatch;
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
    const uint ResourceTable = 0x800ACED8u;
    const uint ResourceStride = 64u;
    const uint ResourcePermanentOffset = 0x0Bu;
    const uint ResourceBindingStart = 0x0Cu;
    const uint ResourceBindingEnd = 0x38u;
    const uint SpideyResourceIndex = 0x800C236Du;
    const uint LoadPsx = 0x80074C38u;
    const uint ScratchName = 0x807F0000u;

    static readonly (int Slot, string Request, string Source, uint NameAddress)[] SpecialActors =
    {
        (13, "spbagdc", "spidey-slot13.psx", ScratchName),
        (17, "spparkdc", "spidey-slot17.psx", ScratchName + 0x20u),
    };

    /// <summary>The retail costume viewer order.</summary>
    static readonly string[] Names =
    {
        "Spider-Man", "Spider-Phoenix", "Prodigy", "Dusk", "Insulated Suit",
        "Alex Ross - Red", "Alex Ross - White", "Venom 2 - Earth X", "Negative Zone",
        "Symbiote Spider-Man", "Spider-Man 2099", "Captain Universe", "Spidey Unlimited",
        "Amazing Bag Man", "Scarlet Spidey", "Ben Reilly", "Quick Change Spidey",
        "Peter Parker", "Battle Damaged",
    };

    static readonly System.Collections.Generic.Dictionary<string, int> Aliases =
        new(StringComparer.OrdinalIgnoreCase)
    {
        ["default"] = 0,
        ["spider-man"] = 0,
        ["spiderman"] = 0,
        ["spidey"] = 0,
        ["spiderphoenix"] = 1,
        ["spider-phoenix"] = 1,
        ["phoenix"] = 1,
        ["prodigy"] = 2,
        ["dusk"] = 3,
        ["insulated"] = 4,
        ["insulatedsuit"] = 4,
        ["rossred"] = 5,
        ["alexrossred"] = 5,
        ["rosswhite"] = 6,
        ["alexrosswhite"] = 6,
        ["venom2"] = 7,
        ["earthx"] = 7,
        ["venomearthx"] = 7,
        ["negative"] = 8,
        ["negativezone"] = 8,
        // Retained for old audit commands that used the internal costrhit label.
        ["ricochet"] = 8,
        ["symbiote"] = 9,
        ["black"] = 9,
        ["2099"] = 10,
        ["captain"] = 11,
        ["captainuniverse"] = 11,
        ["unlimited"] = 12,
        ["spideyunlimited"] = 12,
        ["bagman"] = 13,
        ["bag-man"] = 13,
        ["scarlet"] = 14,
        ["scarletspider"] = 14,
        ["ben"] = 15,
        ["benreilly"] = 15,
        ["quick"] = 16,
        ["quickchange"] = 16,
        ["peter"] = 17,
        ["parker"] = 17,
        ["peterparker"] = 17,
        ["battle"] = 18,
        ["battledamaged"] = 18,
    };

    static int _slot = -1;
    static bool _forced;
    static bool _reported;
    static bool _headMorphReported;
    static int _activeActorSlot = -1;
    static uint[] _genericBinding;
    static readonly System.Collections.Generic.Dictionary<int, int> SpecialActorResources = new();

    /// <summary>
    /// Resolve the private short resource names used to keep the dedicated actors
    /// resident.  The normal spidey.psx lookup is intentionally never aliased: the
    /// game loads that shared actor once, and costume changes do not reload it.
    /// </summary>
    public static string DreamcastAssetFor(string requestedName)
    {
        string source = requestedName.ToLowerInvariant() switch
        {
            "spbagdc.psx" => "spidey-slot13.psx",
            "spparkdc.psx" => "spidey-slot17.psx",
            "sp_tex13.psx" when _slot == 13 => "sp_tex13-dc.psx",
            "sp_tex17.psx" when _slot == 17 => "sp_tex17-dc.psx",
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
                $"[costume] unknown '{spec}'; expected a retail costume name or slot " +
                $"from 0 through {CostumeCount - 1}");
            return;
        }

        _forced = true;
        Console.WriteLine(
            $"[costume] requested {Names[_slot]} (slot {_slot:D2}, sp_tex{_slot:D2}.psx)");
    }

    /// <summary>Pre-hook on func_8004E4BC(actor data, one-based costume).</summary>
    public static void SelectTextureLibrary(CpuContext c, IMemory m)
    {
        if (_forced)
            c.A1 = (uint)(_slot + 1);
        else if (c.A1 >= 1 && c.A1 <= CostumeCount)
            _slot = (int)c.A1 - 1;
        else
            return;

        ActivateActor(c, m, _slot);
        if (_reported) return;
        _reported = true;
        Console.WriteLine(
            $"[costume] selected {Names[_slot]} through retail loader slot {_slot:D2} " +
            $"-> sp_tex{_slot:D2}.psx");
    }

    static uint ResourceEntry(int index)
        => ResourceTable + checked((uint)index * ResourceStride);

    static void WriteCString(IMemory m, uint address, string value)
    {
        for (int index = 0; index < value.Length; index++)
            m.WriteU8(address + (uint)index, (byte)value[index]);
        m.WriteU8(address + (uint)value.Length, 0);
    }

    static int LoadSpecialActor(CpuContext c, IMemory m, int slot)
    {
        foreach (var special in SpecialActors)
        {
            if (special.Slot != slot) continue;
            WriteCString(m, special.NameAddress, special.Request);
            var snapshot = c.Snapshot();
            c.A0 = special.NameAddress;
            c.A1 = 0;
            Dispatcher.Call(c, m, LoadPsx);
            int index = unchecked((int)c.V0);
            c.Restore(snapshot);
            if (index < 0 || index >= 40)
                throw new InvalidOperationException(
                    $"failed to load dedicated costume actor {special.Source}");

            uint entry = ResourceEntry(index);
            uint pointer = m.ReadU32(entry + 0x14u);
            if (pointer == 0)
                throw new InvalidOperationException(
                    $"dedicated costume actor {special.Source} has no resource pointer");
            m.WriteU8(entry + ResourcePermanentOffset, 1);
            Console.WriteLine(
                $"[costume] resident actor slot {slot:D2}: {special.Source} " +
                $"at 0x{pointer:X8} (resource {index})");
            return index;
        }
        throw new InvalidOperationException($"slot {slot:D2} has no dedicated actor");
    }

    static uint[] ReadBinding(IMemory m, uint entry)
    {
        int count = checked((int)((ResourceBindingEnd - ResourceBindingStart) / 4u + 1u));
        var binding = new uint[count];
        for (int index = 0; index < count; index++)
            binding[index] = m.ReadU32(entry + ResourceBindingStart + (uint)(index * 4));
        return binding;
    }

    static void WriteBinding(IMemory m, uint entry, uint[] binding)
    {
        for (int index = 0; index < binding.Length; index++)
            m.WriteU32(
                entry + ResourceBindingStart + (uint)(index * 4), binding[index]);
    }

    static void RebindMorphTargets(CpuContext c, IMemory m, int spideyIndex)
    {
        foreach (var target in new (uint Address, uint Mesh)[]
        {
            (0x800C2258u, 7u),
            (0x800C225Cu, 17u),
            (0x800C2260u, 14u),
        })
        {
            m.WriteU32(target.Address, 0);
            var snapshot = c.Snapshot();
            c.A0 = (uint)spideyIndex;
            c.A1 = target.Mesh;
            c.A2 = target.Address;
            Dispatcher.Call(c, m, 0x8004EB74u);
            c.Restore(snapshot);
        }
    }

    /// <summary>
    /// Retail keeps one spidey resource resident and changes only its texture/morph
    /// state. Bag-Man and Peter alter topology, so keep their complete converted actors
    /// in private resource records and switch the shared record's data pointer before
    /// the retail texture loader runs. This works for ordinary interactive selection as
    /// well as the process-local proof selector and avoids a test-only pre-load alias.
    /// </summary>
    static void ActivateActor(CpuContext c, IMemory m, int slot)
    {
        int spideyIndex = m.ReadU8(SpideyResourceIndex);
        if (spideyIndex < 0 || spideyIndex >= 40) return;
        uint spideyEntry = ResourceEntry(spideyIndex);
        if (_genericBinding == null)
            _genericBinding = ReadBinding(m, spideyEntry);
        if (_genericBinding[2] == 0) return;

        int actorSlot = slot == 13 || slot == 17 ? slot : 0;
        if (_activeActorSlot == actorSlot) return;
        uint[] binding = _genericBinding;
        if (actorSlot != 0 && !SpecialActorResources.TryGetValue(actorSlot, out int resource))
        {
            resource = LoadSpecialActor(c, m, actorSlot);
            SpecialActorResources[actorSlot] = resource;
        }
        if (actorSlot != 0)
            binding = ReadBinding(m, ResourceEntry(SpecialActorResources[actorSlot]));

        // The runtime actor binding is a family of processed pointers, not just the
        // container base at +0x14. Copying only that base leaves the generic mesh table
        // at +0x10 active and produces a black generic silhouette with special textures.
        WriteBinding(m, spideyEntry, binding);
        RebindMorphTargets(c, m, spideyIndex);
        _activeActorSlot = actorSlot;
        uint pointer = binding[2];
        Console.WriteLine(
            $"[costume] active actor {(actorSlot == 0 ? "shared Dreamcast Spider-Man" : $"slot {actorSlot:D2}")} " +
            $"at 0x{pointer:X8}");
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
