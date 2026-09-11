using System;
using RecompOne.Runtime.Assets.Suits;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

public static partial class Costume
{
    public const uint ViewerTable = 0x807C0000;
    const uint Selected = 0x800B31F2;
    public static uint ViewerCount => (uint)(SuitMods.StockCount + SuitMods.Catalogue.Count);

    public static uint ReadSelected(IMemory m) => SuitMods.Active >= 0
        ? (uint)SuitMods.Active : m.ReadU8(Selected);

    public static bool IsUnlocked(IMemory m, uint index) => index < ViewerCount &&
        (SuitMods.IsMod((int)index) || (m.ReadU32(0x800B31F8) & (1u << (int)index)) != 0);

    public static void WriteSelected(IMemory m, int selected)
    {
        if ((uint)selected >= ViewerCount) return;
        if (SuitMods.IsMod(selected) && SuitMods.Select(selected)) ApplyModPowers(m);
        else
        {
            SuitMods.Select(-1);
            m.WriteU8(Selected, (byte)(selected < SuitMods.StockCount ? selected : 0));
        }
        LoadedCostume = -1;
    }

    static void ApplyModPowers(IMemory m)
    {
        if (SuitMods.Active < 0) return;
        int profile = SuitMods.At(SuitMods.Active).AbilityProfile;
        m.WriteU8(Selected, (byte)profile); // Every unmodified retail table sees a valid 0..18.
        var ids = SuitRules.PowerIds[profile];
        for (uint i = 0; i < 3; i++) m.WriteU8(Selected + 1 + i, ids[i]);
        for (uint i = 0; i < 7; i++) m.WriteU32(0x800C2210 + i * 4, 0);
        foreach (byte id in ids)
            if (id != 0) m.WriteU32(0x800C2210 + (uint)(id - 1) * 4, 1);
    }

    public static void PrepareViewer(CpuContext c, IMemory m)
    {
        ApplyModPowers(m);
        for (uint i = 0; i < SuitMods.StockCount * 12; i += 4)
            m.WriteU32(ViewerTable + i, m.ReadU32(0x80251560 + i));
        uint name = ViewerTable + 0x800, description = ViewerTable + 0x1000;
        for (int i = SuitMods.StockCount; i < ViewerCount; i++)
        {
            var mod = SuitMods.At(i);
            uint entry = ViewerTable + (uint)i * 12;
            m.WriteU32(entry, name);
            m.WriteU32(entry + 4, description);
            m.WriteU32(entry + 8, m.ReadU32(0x80251568));
            name = Line(m, name, mod.Name);
            description = Color(m, description, true);
            description = Line(m, description, "COSTUME:");
            description = Color(m, description, false);
            description = Line(m, description, mod.Name.ToUpperInvariant());
            description = Color(m, description, true);
            description = Line(m, description, "GAME POWERS:");
            description = Color(m, description, false);
            foreach (string power in SuitRules.PowerText[mod.AbilityProfile]) description = Line(m, description, power);
            description = Color(m, description, true);
            description = Line(m, description, "COMMENTS:");
            description = Color(m, description, false);
            foreach (string line in SuitManifest.WrapComments(mod.Comments)) description = Line(m, description, line);
            m.WriteU8(description++, 255);
            if (name >= ViewerTable + 0x1000 || description >= ViewerTable + 0x5000)
                throw new InvalidOperationException("costume text arena exhausted");
        }
    }

    static uint Line(IMemory m, uint p, string text)
    {
        WriteCString(m, p, text);
        return p + (uint)text.Length + 1;
    }

    static uint Color(IMemory m, uint p, bool heading)
    {
        m.WriteU8(p++, 2);
        m.WriteU8(p++, heading ? (byte)105 : (byte)68);
        m.WriteU8(p++, heading ? (byte)105 : (byte)68);
        m.WriteU8(p++, heading ? (byte)0 : (byte)100);
        return p;
    }

    public const uint ViewerListBytes = 0x28 + 32 * SuitMods.MaxCount;

    public static void ConfigureViewerList(IMemory m, uint list)
    {
        // The retail constructor initializes forty inline rows. Extend only this
        // viewer; other menus retain their original allocation and constructor.
        for (uint row = 40; row < SuitMods.MaxCount; row++)
        {
            uint target = list + 0x28 + row * 32;
            for (uint offset = 0; offset < 32; offset++) m.WriteU8(target + offset, 0);
            m.WriteU16(target + 8, m.ReadU16(list + 0x30));
            m.WriteU16(target + 10, m.ReadU16(list + 0x32));
            for (uint offset = 16; offset < 32; offset++)
                m.WriteU8(target + offset, m.ReadU8(list + 0x28 + offset));
            m.WriteU32(target + 16, 1);
        }
        m.WriteU32(list + 0x20, 70);
        m.WriteU8(list + 0x15, 11);
    }

    public static void AlignViewerFrame(IMemory m, uint list)
    {
        uint frame = m.ReadU32(list + 4);
        if (frame == 0) return;
        m.WriteU32(frame + 0x20, 58);
        m.WriteU32(frame + 0x10, 117);
    }
}
