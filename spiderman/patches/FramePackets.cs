using System;
using RecompOne.Runtime.Assets;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>Bounded native draw-command pools for dense character crowds.</summary>
public static class FramePackets
{
    public const uint Capacity = 0x40000;
    static readonly bool Trace = Environment.GetEnvironmentVariable("SPIDEY_PACKET_TRACE") == "1";
    static uint _base, _peak;

    public static bool TryAllocate(CpuContext c)
    {
        // Only the two primitive pools in func_80061230, not its ordering tables.
        if (c.A0 != 0x17000 || (c.RA != 0x80061280 && c.RA != 0x80061298)) return false;
        c.V0 = LooseWadOverrides.AllocateScratch(Capacity,"SM1 frame packets");
        return true;
    }

    public static void SetLimit(CpuContext c, IMemory m)
    {
        uint frame = m.ReadU32(0x800B54A8);
        uint pool = m.ReadU32(frame+0x74);
        if (!LooseWadOverrides.OwnsAllocation(pool)) return;
        _base = pool & 0x7FFFFFFF;
        // Preserve retail's 256-byte slack and per-primitive capacity checks.
        m.WriteU32(c.GP+0x7F4,_base+Capacity-0x100);
    }

    public static void Audit(IMemory m)
    {
        if (!Trace || _base == 0) return;
        uint cursor = m.ReadU32(0x800B54B0)&0x7FFFFFFF;
        if (cursor < _base || cursor > _base+Capacity)
            throw new InvalidOperationException("SM1 frame packet cursor outside active allocation");
        uint used = cursor-_base;
        if (used > _peak)
        {
            _peak=used;
            Console.WriteLine($"[frame-packets] peak={used} capacity={Capacity} retail-limit=93952");
        }
        if (used >= Capacity-0x164)
            throw new InvalidOperationException("SM1 expanded frame packet capacity exhausted");
    }
}
