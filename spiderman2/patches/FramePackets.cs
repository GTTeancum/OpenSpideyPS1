using System;
using RecompOne.Runtime.Assets;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>Bounded double-buffered native draw commands for denser actors.</summary>
public static class FramePackets
{
    public const uint Capacity = 0x40000; // Two 256 KiB blocks, including retail safety slack.
    static readonly bool Trace = Environment.GetEnvironmentVariable("SPIDEY_PACKET_TRACE") == "1";
    static uint _base, _peak;
    static bool _reported;

    // Exact retail allocation callsites in func_8006BD90. Ordering tables retain
    // their original allocations; only the two 0x17000-byte primitive pools move.
    public static bool TryAllocate(CpuContext c)
    {
        if (c.A0 != 0x17000 || (c.RA != 0x8006BDE0 && c.RA != 0x8006BDF8)) return false;
        c.V0 = LooseWadOverrides.AllocateScratch(Capacity, "SM2 frame packets");
        return true;
    }

    // Retail func_800314E4 computes pool base + 0x16F00. Keep its 256-byte
    // safety reserve and the renderer's additional per-primitive bounds checks.
    public static void SetLimit(CpuContext c, IMemory m)
    {
        uint frame = m.ReadU32(0x800C247C);
        uint pool = m.ReadU32(frame + 0x74);
        if (!LooseWadOverrides.OwnsAllocation(pool)) return;
        _base = pool & 0x7FFFFFFF;
        m.WriteU32(c.GP + 0x8D0, _base + Capacity - 0x100);
    }

    public static void Audit(IMemory m)
    {
        if (!Trace || _base == 0) return;
        uint cursor = m.ReadU32(0x800C2484) & 0x7FFFFFFF;
        if (cursor < _base || cursor > _base + Capacity) return;
        uint used = cursor - _base;
        if (used <= _peak) return;
        _peak = used;
        if (!_reported && used >= 0x16F00 - 100)
        {
            _reported = true;
            Console.WriteLine($"[frame-packets] exceeded retail draw capacity: {used} bytes; expanded capacity {Capacity}");
        }
        if (used >= Capacity - 0x164)
            throw new InvalidOperationException("expanded frame packet capacity exhausted");
    }
}
