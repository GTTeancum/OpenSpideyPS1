using System;
using System.Text;
using RecompOne.Runtime.Context;
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
    const int OriginalCostumeCount = 10;
    const uint Selected = 0x800A5704;
    const uint Unlocks = 0x800A5708;
    // Retail uses only the low byte of the 32-bit selected-costume field. Keep the
    // extended value and a two-byte signature in its three padding bytes so none of
    // the retail unlock words are repurposed. The legacy constants migrate saves
    // written by the first 20-costume implementation.
    const uint ExtendedSelected = Selected + 1;
    const uint ExtendedSelectionMarker = Selected + 2;
    const ushort ExtendedSelectionMagic = 0x3253; // "S2" in little endian
    const uint LegacySelectionMarker = 0x80000000;
    const uint LegacySelectionMask = 0x1F000000;

    // The retail table at 0x802693A8 has ten 12-byte entries and is followed by
    // unrelated shell data. The generated-viewer transform points the costume
    // viewer at this port-only arena instead, where all twenty entries fit.
    public const uint ViewerTable = 0x807C0000;
    const uint ViewerStrings = ViewerTable + 0x800;
    const uint ViewerDescriptions = ViewerTable + 0x1000;
    const uint ViewerModelName = ViewerTable + 0x5000;
    const uint RetailViewerTable = 0x802693A8;
    const uint ModelCache = 0x800A0904;

    // SM1 changes Spider-Man's appearance by loading sp_tex00..09 over one
    // low-detail spidey.psx.  The Dreamcast release instead ships a dedicated
    // high-detail actor for each slot.  Keep the game's requested resource name
    // intact, but let the loose override loader source that request from the
    // corresponding converted Dreamcast actor.
    static readonly string[] DreamcastModels =
    {
        "spidey.psx", "sp2099.psx", "spsymbi.psx", "spuniv.psx", "spunlim.psx",
        "spbagman.psx", "spscar.psx", "spreilly.psx", "spquick.psx", "sppark.psx",
        "sp2phoenix.psx", "sp2prodigy.psx", "sp2dusk.psx", "sp2insulated.psx",
        "sp2rossred.psx", "sp2rosswhite.psx", "sp2venomx.psx", "sp2negative.psx",
        "sp2battle.psx", "sp2default.psx",
    };

    /// <summary>The COSTUME VIEWER's list, in its own order.</summary>
    static readonly string[] Names =
    {
        "spiderman", "2099", "symbiote", "captain", "unlimited",
        "bagman", "scarlet", "benreilly", "quickchange", "peterparker",
        "spiderphoenix", "prodigy", "dusk", "insulated", "alexrossred",
        "alexrosswhite", "venomearthx", "negativezone", "battledamaged",
        "spidermanwinged",
    };

    static readonly string[] ViewerNames =
    {
        "spider-man", "Spider-man 2099", "symbiote spider-man", "Captain Universe",
        "Spidey unlimited", "Amazing bag man", "Scarlet Spidey", "Ben Reilly",
        "Quick Change Spidey", "Peter Parker", "Spider-Phoenix", "Prodigy", "Dusk",
        "Insulated Suit", "Alex Ross - Red", "Alex Ross - White",
        "Venom 2 - Earth X", "Negative Zone", "Battle Damaged",
        "Spider-Man - Wings",
    };

    static readonly string[][] ImportedPowerText =
    {
        new[] { "INVULNERABLE", "ENHANCED STRENGTH", "UNLIMITED WEBBING" },
        new[] { "NO SPIDEY BELT" },
        new[] { "STEALTH MODE" },
        new[] { "ENHANCED STRENGTH" },
        new[] { "STANDARD POWERS" },
        new[] { "STANDARD POWERS" },
        new[] { "UNLIMITED WEBBING" },
        new[] { "NO SPIDEY BELT" },
        new[] { "STANDARD POWERS" },
        new[] { "STANDARD POWERS" },
    };

    static readonly string[] ImportedUnlockText =
    {
        "CAPTAIN UNIVERSE", "AMAZING BAG MAN", "SPIDEY UNLIMITED",
        "SPIDER-MAN 2099", "SCARLET SPIDEY", "BEN REILLY",
        "SYMBIOTE SPIDER-MAN", "QUICK CHANGE SPIDEY", "PETER PARKER",
        "START",
    };

    // Every entry owns its own value. AbilityDonors documents where each imported
    // value was copied from; gameplay never follows a donor pointer at runtime.
    // Peter Parker (9) is deliberately absent. Default is the sole ability trio:
    // SM1 default, Battle-Damaged, and default SM2 with wings.
    static readonly int[] AbilityDonors =
    {
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
        3, 5, 4, 1, 6, 7, 2, 8, 0, 0,
    };

    // Exact retail costume-configuration words written by func_80047DF8. These
    // ultimately drive the costume-specific web/ammo/ability presentation.
    static readonly uint[] AbilityConfig =
    {
        0x00202040, 0x00402020, 0x00200000, 0x00404040, 0x00402020,
        0x00403030, 0x00202040, 0x00402020, 0x00200000, 0x00200000,
        0x00404040, 0x00403030, 0x00402020, 0x00402020, 0x00202040,
        0x00402020, 0x00200000, 0x00200000, 0x00202040, 0x00202040,
    };

    // Imported unlocks pair with the existing SM1 events. Peter still unlocks a
    // partner (Battle-Damaged); that partner copies default abilities, not Peter's.
    static readonly int[] UnlockPartnerByOriginal =
    {
        -1, 13, 16, 10, 12, 11, 14, 15, 17, 18,
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
        ["spiderphoenix"] = 10, ["spider-phoenix"] = 10, ["phoenix"] = 10,
        ["prodigy"] = 11,
        ["dusk"] = 12,
        ["insulated"] = 13, ["insulatedsuit"] = 13,
        ["alexrossred"] = 14, ["rossred"] = 14,
        ["alexrosswhite"] = 15, ["rosswhite"] = 15,
        ["venomearthx"] = 16, ["venom2"] = 16, ["earthx"] = 16,
        ["negativezone"] = 17, ["negative"] = 17, ["ricochet"] = 17,
        ["battledamaged"] = 18, ["battle"] = 18,
        ["spidermanwinged"] = 19, ["winged"] = 19, ["sm2default"] = 19,
    };

    static int _want = -1;
    static int _loadedCostume = -1;
    public static int LoadedCostume => _loadedCostume;
    public static uint ViewerCount => (uint)(Names.Length + SuitMods.Catalogue.Count);
    static string ModelFor(int selected) => SuitMods.IsMod(selected) ? "spidey.psx" : DreamcastModels[selected];
    public static bool IsUnlocked(IMemory memory, uint index) => index < ViewerCount &&
        (SuitMods.IsMod((int)index) || (memory.ReadU32(Unlocks) & (1u << (int)index)) != 0);
    static bool _selfTest;
    static bool _selfTestDone;

    public static string DreamcastAssetFor(string requestedName, IMemory memory)
    {
        int selected = _want >= 0 ? _want : ReadSelected(memory);
        if ((uint)selected >= ViewerCount) selected = 0;
        string source = requestedName;
        if (requestedName.Equals("spidey.psx", StringComparison.OrdinalIgnoreCase))
        {
            source = ModelFor(selected);
            _loadedCostume = selected;
        }
        if (!source.Equals(requestedName, StringComparison.OrdinalIgnoreCase))
            Console.WriteLine($"[costume] Dreamcast asset {requestedName} <- {source}");
        return source;
    }

    /// <summary>
    /// Replace the retail texture-only costume transition with a complete actor reload.
    /// The viewer actor stores the 0..39 model-cache slot, not a private model pointer.
    /// Unloading and immediately reloading "spidey" therefore keeps that stable slot
    /// while replacing the complete Dreamcast model, skeleton, and baked textures.
    /// </summary>
    public static bool RunRetailTextureOverlay(CpuContext c, IMemory memory)
    {
        int selected = _want >= 0 ? _want : ReadSelected(memory);
        if ((uint)selected >= ViewerCount) selected = 0;

        int slot = FindModelSlot(memory, "spidey");
        if (slot < 0)
            throw new InvalidOperationException(
                "costume viewer cannot reload the missing spidey model-cache slot");
        if (_loadedCostume == selected)
        {
            Console.WriteLine(
                $"[costume] viewer actor already loaded: {ModelFor(selected)}");
            return false;
        }

        uint modelEntry = ModelCache + (uint)slot * 0x40u;
        uint modelBase = memory.ReadU32(modelEntry + 0x14u);
        TextureRegistry.RemoveModelTextures(memory, c.GP + 0xA98u, modelEntry, modelBase);

        uint savedRa = c.RA;
        c.A0 = (uint)slot;
        c.A1 = 1;
        c.RA = 0x807C0400;
        SpiderMan.func_800695D0(c, memory);

        WriteCString(memory, ViewerModelName, "spidey");
        c.A0 = ViewerModelName;
        c.A1 = 0;
        c.RA = 0x807C0404;
        SpiderMan.LoadPsx(c, memory);
        int reloadedSlot = unchecked((int)c.V0);
        c.RA = savedRa;

        if (reloadedSlot != slot)
            throw new InvalidOperationException(
                $"costume viewer model slot moved from {slot} to {reloadedSlot}");
        if (selected >= OriginalCostumeCount)
            Console.WriteLine(
                "[costume] skipped SM1 retail texture overlay for baked imported actor");
        Console.WriteLine($"[costume] viewer actor reload slot {slot}: {ModelFor(selected)}");
        return false;
    }

    static int FindModelSlot(IMemory memory, string name)
    {
        for (int slot = 0; slot < 40; slot++)
        {
            uint entry = ModelCache + (uint)slot * 0x40;
            int i = 0;
            for (; i < name.Length; i++)
                if ((memory.ReadU8(entry + (uint)i) & 0xDF) != (name[i] & 0xDF))
                    break;
            if (i == name.Length && memory.ReadU8(entry + (uint)i) == 0)
                return slot;
        }
        return -1;
    }

    /// <summary>Pre-hook for shell:func_80261C70.</summary>
    public static void PrepareViewer(CpuContext c, IMemory memory)
    {
        ApplyPersistentState(memory);

        // Preserve the ten retail records verbatim, including their animation/style
        // words, then append ten normal Spider-Man records with port-owned labels.
        for (uint i = 0; i < 10; i++)
            for (uint o = 0; o < 12; o += 4)
                memory.WriteU32(ViewerTable + i * 12 + o,
                    memory.ReadU32(RetailViewerTable + i * 12 + o));

        uint text = ViewerStrings;
        uint description = ViewerDescriptions;
        for (int i = 10; i < ViewerCount; i++)
        {
            string name = SuitMods.IsMod(i) ? SuitMods.At(i).Name : ViewerNames[i];
            WriteCString(memory, text, name);
            uint entry = ViewerTable + (uint)i * 12;
            memory.WriteU32(entry, text);
            memory.WriteU32(entry + 4, description);
            memory.WriteU32(entry + 8, 0x004C0008); // retail default Spider-Man style
            text += (uint)Encoding.ASCII.GetByteCount(name) + 1;
            description = SuitMods.IsMod(i) ? WriteModDescription(memory, description, i) : WriteImportedDescription(memory, description, i);
            if (text >= ViewerDescriptions || description >= ViewerModelName)
                throw new InvalidOperationException("costume viewer text arena exhausted");
        }
    }

    /// <summary>
    /// Align the first text line with the description and fit eleven stock-spaced rows.
    /// </summary>
    public static void ConfigureViewerList(IMemory memory, uint list)
    {
        memory.WriteU32(list + 0x20, 70); // Right-column first text line.
        memory.WriteU8(list + 0x15, 11); // Last baseline 170, inside the frame ending at 175.
    }

    /// <summary>Align the list frame with the description frame without changing its text layout.</summary>
    public static void AlignViewerFrame(IMemory memory, uint list)
    {
        uint frame = memory.ReadU32(list + 4);
        if (frame == 0) return;
        // Right-panel constructor in shell:func_80261C70: Y=0x3A, height=0x75.
        // Width, X, opening animation, font and ten-pixel row pitch stay retail.
        memory.WriteU32(frame + 0x20, 0x3A);
        memory.WriteU32(frame + 0x10, 0x75);
    }

    static uint WriteImportedDescription(IMemory memory, uint address, int index)
    {
        uint cursor = address;
        cursor = WriteViewerColor(memory, cursor, heading: true);
        cursor = WriteViewerLine(memory, cursor, "SPECIAL COSTUME");
        cursor = WriteViewerColor(memory, cursor, heading: false);
        cursor = WriteViewerLine(memory, cursor, ViewerNames[index].ToUpperInvariant());
        cursor = WriteViewerColor(memory, cursor, heading: true);
        cursor = WriteViewerLine(memory, cursor, "GAME POWERS:");
        cursor = WriteViewerColor(memory, cursor, heading: false);
        foreach (string line in ImportedPowerText[index - 10])
            cursor = WriteViewerLine(memory, cursor, line);
        cursor = WriteViewerColor(memory, cursor, heading: true);
        cursor = WriteViewerLine(memory, cursor, "UNLOCKED WITH:");
        cursor = WriteViewerColor(memory, cursor, heading: false);
        cursor = WriteViewerLine(memory, cursor, ImportedUnlockText[index - 10]);
        memory.WriteU8(cursor++, 0xFF);
        return cursor;
    }

    static uint WriteModDescription(IMemory memory, uint cursor, int index)
    {
        var mod = SuitMods.At(index);
        cursor = WriteViewerColor(memory, cursor, heading: true);
        cursor = WriteViewerLine(memory, cursor, "COSTUME:");
        cursor = WriteViewerColor(memory, cursor, heading: false);
        cursor = WriteViewerLine(memory, cursor, mod.Name.ToUpperInvariant());
        cursor = WriteViewerColor(memory, cursor, heading: true);
        cursor = WriteViewerLine(memory, cursor, "GAME POWERS:");
        cursor = WriteViewerColor(memory, cursor, heading: false);
        foreach (string power in RecompOne.Runtime.Assets.Suits.SuitManifest.PowerText[mod.AbilityProfile])
            cursor = WriteViewerLine(memory, cursor, power);
        cursor = WriteViewerColor(memory, cursor, heading: true);
        cursor = WriteViewerLine(memory, cursor, "COMMENTS:");
        cursor = WriteViewerColor(memory, cursor, heading: false);
        foreach (string line in RecompOne.Runtime.Assets.Suits.SuitManifest.WrapComments(mod.Comments))
            cursor = WriteViewerLine(memory, cursor, line);
        memory.WriteU8(cursor++, 255);
        return cursor;
    }

    // Exact RGB tokens from retail charbio.dat's costume entries. Keep the
    // original viewer's font, 10-pixel line pitch, anchor and shadow renderer.
    static uint WriteViewerColor(IMemory memory, uint address, bool heading) => heading
        ? WriteColor(memory, address, 105, 105, 0)
        : WriteColor(memory, address, 68, 68, 100);

    static uint WriteColor(IMemory memory, uint address, byte r, byte g, byte b)
    {
        memory.WriteU8(address++, 2);
        memory.WriteU8(address++, r);
        memory.WriteU8(address++, g);
        memory.WriteU8(address++, b);
        return address;
    }

    static uint WriteViewerLine(IMemory memory, uint address, string value)
    {
        WriteCString(memory, address, value);
        return address + (uint)Encoding.ASCII.GetByteCount(value) + 1;
    }

    /// <summary>Post-hook for main:func_80047DF8 (Spider-Man construction).</summary>
    public static void ApplyAbilityProfile(CpuContext c, IMemory memory)
    {
        int selected = ReadSelected(memory);
        if (SuitMods.IsMod(selected)) selected = SuitMods.At(selected).AbilityProfile;
        if ((uint)selected >= AbilityConfig.Length) selected = 0;
        uint player = c.V0;
        if ((player & 0xFF000000u) != 0x80000000u) return;
        memory.WriteU32(player + 0x584, AbilityConfig[selected]);
        Console.WriteLine($"[costume] ability config {Names[selected]} " +
            $"<- {Names[AbilityDonors[selected]]}: 0x{AbilityConfig[selected]:X8}");
    }

    static void ApplyPersistentState(IMemory memory)
    {
        uint bits = memory.ReadU32(Unlocks);
        byte retail = memory.ReadU8(Selected);
        if (retail >= 10) retail = 0;

        int selected = retail;
        byte extended = memory.ReadU8(ExtendedSelected);
        if (memory.ReadU16(ExtendedSelectionMarker) == ExtendedSelectionMagic &&
            extended < Names.Length)
        {
            selected = extended;
        }
        else
        {
            int legacy = (int)((bits & LegacySelectionMask) >> 24);
            byte expectedProxy = legacy < 10 ? (byte)legacy : (byte)0;
            if ((bits & LegacySelectionMarker) != 0 && legacy < Names.Length &&
                retail == expectedProxy)
            {
                selected = legacy;
                bits &= ~(LegacySelectionMarker | LegacySelectionMask);
            }
        }

        bits |= 1u | (1u << 19);
        for (int original = 1; original < UnlockPartnerByOriginal.Length; original++)
            if ((bits & (1u << original)) != 0)
                bits |= 1u << UnlockPartnerByOriginal[original];
        memory.WriteU32(Unlocks, bits);
        WriteSelected(memory, (byte)(SuitMods.Active >= 0 ? SuitMods.Active : selected));
    }

    /// <summary>
    /// The retail selected byte cannot exceed nine: several shell resource tables use
    /// it directly. The port persists the full 0..19 selection in otherwise-unused
    /// padding bytes of that same saved field and leaves a safe retail proxy byte.
    /// </summary>
    public static byte ReadSelected(IMemory memory)
    {
        if (SuitMods.Active >= 0) return (byte)SuitMods.Active;
        byte extended = memory.ReadU8(ExtendedSelected);
        if (memory.ReadU16(ExtendedSelectionMarker) == ExtendedSelectionMagic &&
            extended < Names.Length)
            return extended;

        // Read legacy saves before the next persistent-state tick migrates them.
        uint bits = memory.ReadU32(Unlocks);
        int legacy = (int)((bits & LegacySelectionMask) >> 24);
        byte retail = memory.ReadU8(Selected);
        byte expectedProxy = legacy < 10 ? (byte)legacy : (byte)0;
        if ((bits & LegacySelectionMarker) != 0 && legacy < Names.Length &&
            retail == expectedProxy)
            return (byte)legacy;
        return retail < 10 ? retail : (byte)0;
    }

    public static void WriteSelected(IMemory memory, byte selected)
    {
        if (SuitMods.IsMod(selected))
        {
            if (SuitMods.Select(selected))
            {
                // Persist identity on the host, never a catalogue index in a retail save.
                byte proxy = (byte)SuitMods.At(selected).AbilityProfile;
                memory.WriteU8(ExtendedSelected, 0); // stock fallback if the mod is later removed
                memory.WriteU16(ExtendedSelectionMarker, ExtendedSelectionMagic);
                memory.WriteU8(Selected, proxy);
                return;
            }
            selected = 0;
        }
        SuitMods.Select(-1);
        if (selected >= Names.Length) selected = 0;
        memory.WriteU8(ExtendedSelected, selected);
        memory.WriteU16(ExtendedSelectionMarker, ExtendedSelectionMagic);
        memory.WriteU8(Selected, selected < 10 ? selected : (byte)0);
    }

    static void WriteCString(IMemory memory, uint address, string value)
    {
        byte[] bytes = Encoding.ASCII.GetBytes(value);
        for (uint i = 0; i < bytes.Length; i++) memory.WriteU8(address + i, bytes[i]);
        memory.WriteU8(address + (uint)bytes.Length, 0);
    }

    static void RunSelfTest(IMemory memory)
    {
        uint savedBits = memory.ReadU32(Unlocks);
        uint savedSelection = memory.ReadU32(Selected);
        const uint DummyPlayer = ViewerTable + 0x6000;
        try
        {
            for (int original = 1; original <= 9; original++)
            {
                memory.WriteU32(Unlocks, 1u << original);
                memory.WriteU8(Selected, (byte)original);
                ApplyPersistentState(memory);
                uint expected = 1u | (1u << 19) | (1u << original) |
                    (1u << UnlockPartnerByOriginal[original]);
                uint actual = memory.ReadU32(Unlocks) & 0x000FFFFFu;
                if (actual != expected)
                    throw new InvalidOperationException(
                        $"unlock migration {original}: 0x{actual:X8} != 0x{expected:X8}");
            }

            for (byte selected = 0; selected < Names.Length; selected++)
            {
                const uint UnlockSentinel = 0x60A00000;
                memory.WriteU32(Unlocks, UnlockSentinel);
                WriteSelected(memory, selected);
                if (ReadSelected(memory) != selected)
                    throw new InvalidOperationException($"selection round trip {selected}");
                if (memory.ReadU32(Unlocks) != UnlockSentinel)
                    throw new InvalidOperationException($"selection changed unlock word {selected}");
                byte proxy = memory.ReadU8(Selected);
                if (proxy != (selected < 10 ? selected : 0))
                    throw new InvalidOperationException($"retail proxy {selected}: {proxy}");

                ApplyAbilityProfile(new CpuContext { V0 = DummyPlayer }, memory);
                if (memory.ReadU32(DummyPlayer + 0x584) != AbilityConfig[selected])
                    throw new InvalidOperationException($"ability config {selected}");
            }

            int importedDefaultCopies = 0;
            for (int imported = OriginalCostumeCount; imported < AbilityDonors.Length; imported++)
            {
                if (AbilityDonors[imported] == 0) importedDefaultCopies++;
                if (AbilityDonors[imported] == 9)
                    throw new InvalidOperationException("Peter Parker donates an imported ability");
            }
            if (importedDefaultCopies != 2 || AbilityDonors[18] != 0 ||
                AbilityDonors[19] != 0)
                throw new InvalidOperationException(
                    $"default ability imports: {importedDefaultCopies}, expected slots 18 and 19 only");

            Console.WriteLine(
                "[costume-self-test] PASS 9 paired unlock migrations; " +
                "20 persistent selections; 20 independent ability configs; " +
                "Peter donor count 0; default ability trio only");
        }
        finally
        {
            memory.WriteU32(Unlocks, savedBits);
            memory.WriteU32(Selected, savedSelection);
        }
    }

    public static void Install()
    {
        SuitMods.Install();
        _selfTest = !string.IsNullOrEmpty(
            Environment.GetEnvironmentVariable("SPIDEY_COSTUME_SELF_TEST"));
        Event.AddListener<VSyncEvent>(e =>
        {
            if (e.Memory == null) return;
            SuitMods.Observe(e.Memory);
            if (_selfTest && !_selfTestDone)
            {
                _selfTestDone = true;
                RunSelfTest(e.Memory);
            }
            ApplyPersistentState(e.Memory);
            if (_want >= 0) WriteSelected(e.Memory, (byte)_want);
        });

        var spec = Environment.GetEnvironmentVariable("SPIDEY_COSTUME");
        if (string.IsNullOrWhiteSpace(spec)) return;
        spec = spec.Trim();

        int mod = SuitMods.Catalogue.FindIndex(m => m.Id.Equals(spec, StringComparison.OrdinalIgnoreCase));
        if (mod >= 0) _want = SuitMods.StockCount + mod;
        else if (int.TryParse(spec, out int n) && n >= 0 && n < ViewerCount) _want = n;
        else if (Aliases.TryGetValue(spec, out int a)) _want = a;
        else
        {
            Console.Error.WriteLine($"[costume] unknown '{spec}'; one of: {string.Join(", ", Names)}");
            return;
        }

        Console.WriteLine($"[costume] {(SuitMods.IsMod(_want) ? SuitMods.At(_want).Id : Names[_want])} (index {_want})");
    }
}
