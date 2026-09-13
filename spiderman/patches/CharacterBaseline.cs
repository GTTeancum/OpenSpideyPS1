using System;
using System.Collections.Generic;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>Opt-in L1A1 crowd draw fixture. No controller input or persistent actor edits.</summary>
public static class CharacterBaseline
{
    static readonly bool Enabled = Environment.GetEnvironmentVariable("SPIDEY_BASELINE_CROWD") == "1";
    static long _frame;
    static long _lastReport = -1;
    static readonly List<(uint Pointer, uint X, uint Y, uint Z, ushort Flags)> Saved = new();
    static readonly (int X, int Z)[] Offsets = [(-140, 160), (-45, 220), (65, 200), (155, 120)];

    static CharacterBaseline()
    {
        if (Enabled) Event.AddListener<VSyncEvent>(e => _frame = e.Frame);
    }

    public static void Enter(CpuContext c, IMemory m)
    {
        if (!Enabled || _frame < 3450 || _frame > 4050) return;
        uint head = m.ReadU32(0x800B5234u), player = m.ReadU32(0x800B5268u);
        if (c.A0 != head || head == 0 || player == 0) return;
        if (Saved.Count != 0) throw new InvalidOperationException("Nested crowd draw fixture");
        uint node = head;
        for (int i = 0; node != 0; i++)
        {
            if (i >= 4 || node < 0x80000000 || node >= 0x80200000 || m.ReadU16(node+0x34) != 0x138)
                throw new InvalidOperationException("Crowd fixture requires the four L1A1 thugs");
            Saved.Add((node,m.ReadU32(node+4),m.ReadU32(node+8),m.ReadU32(node+12),m.ReadU16(node)));
            node = m.ReadU32(node+0x1C);
        }
        if (Saved.Count != 4) throw new InvalidOperationException("Missing crowd actors");
        for (int i=0;i<Saved.Count;i++)
        {
            var actor=Saved[i];
            m.WriteU32(actor.Pointer+4,unchecked(m.ReadU32(player+4)+(uint)(Offsets[i].X*4096)));
            m.WriteU32(actor.Pointer+8,m.ReadU32(player+8));
            m.WriteU32(actor.Pointer+12,unchecked(m.ReadU32(player+12)+(uint)(Offsets[i].Z*4096)));
            m.WriteU16(actor.Pointer,(ushort)(actor.Flags & ~0x8000));
        }
        if (_frame/120 != _lastReport)
        {
            _lastReport=_frame/120;
            Console.WriteLine($"[character-baseline] frame={_frame} drawing four existing henchmen beside player");
        }
    }

    public static void Exit(CpuContext c, IMemory m)
    {
        FramePackets.Audit(m);
        if (!Enabled || Saved.Count == 0) return;
        foreach (var actor in Saved)
        {
            m.WriteU32(actor.Pointer+4,actor.X);m.WriteU32(actor.Pointer+8,actor.Y);m.WriteU32(actor.Pointer+12,actor.Z);
            m.WriteU16(actor.Pointer,(ushort)((m.ReadU16(actor.Pointer)&~0x8000)|(actor.Flags&0x8000)));
        }
        Saved.Clear();
    }
}
