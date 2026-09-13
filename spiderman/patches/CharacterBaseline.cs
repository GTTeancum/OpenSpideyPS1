using System;
using System.Collections.Generic;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>Opt-in L1A1 crowd/roster fixture. All changes remain in the test process.</summary>
public static class CharacterBaseline
{
    static readonly bool Full = Environment.GetEnvironmentVariable("SPIDEY_BASELINE_ROSTER") == "1";
    static readonly bool Enabled = Full || Environment.GetEnvironmentVariable("SPIDEY_BASELINE_CROWD") == "1";
    static readonly HashSet<uint> Visited = new();
    static uint _gp;
    static long _nextSpawn = 3600;
    static bool _complete;
    static long _frame;
    static long _lastReport = -1;
    static readonly List<(uint Pointer, uint X, uint Y, uint Z, ushort Flags)> Saved = new();
    static readonly (int X, int Z)[] Offsets = [(-140, 160), (-45, 220), (65, 200), (155, 120)];

    static CharacterBaseline()
    {
        if (Enabled) Event.AddListener<VSyncEvent>(e => { _frame = e.Frame; if (Full) VisitRoster(); });
    }

    public static void ObserveTrigger(CpuContext c, IMemory m)
    {
        if (!Full) return;
        _gp = c.GP;
        uint table=m.ReadU32(_gp+0xBCC), count=m.ReadU32(_gp+0xBD0);
        if (c.A0>=count || table==0) return;
        uint record=m.ReadU32(table+c.A0*4);
        if (m.ReadU16(record)!=1) return;
        ushort type=m.ReadU16(record+2);
        if ((type==0x138 || type==0x13F) && Visited.Add(c.A0))
            Console.WriteLine($"[character-roster] visited record={c.A0} type={type:X4} frame={_frame}");
    }

    static void VisitRoster()
    {
        if (_complete || _gp==0 || _frame<_nextSpawn) return;
        var m=RecompOne.Runtime.Runtime.Mem;
        uint table=m.ReadU32(_gp+0xBCC),count=m.ReadU32(_gp+0xBD0);
        if (count!=294 || m.ReadU32(0x800B5268)==0) throw new InvalidOperationException("Roster fixture requires initialized SM1 L1A1");
        int authored=0;
        for(uint i=0;i<count;i++)
        {
            uint record=m.ReadU32(table+i*4);
            if (m.ReadU16(record)!=1) continue;
            ushort type=m.ReadU16(record+2);
            if(type!=0x138 && type!=0x13F) continue;
            authored++;
            if(Visited.Contains(i)) continue;
            Console.WriteLine($"[character-roster] activate record={i} type={type:X4} frame={_frame}");
            var c=new CpuContext {GP=_gp,SP=0x807F0000,A0=i};
            SpiderMan.func_8005B014(c,m);
            _nextSpawn=_frame+300;
            return;
        }
        if(authored!=9 || Visited.Count!=9) throw new InvalidOperationException("Incomplete L1A1 character census");
        _complete=true;
        Console.WriteLine($"[character-roster] COMPLETE records={authored} frame={_frame}");
    }

    public static void Enter(CpuContext c, IMemory m)
    {
        if (!Enabled || _frame < 3450 || (!Full && _frame > 4050)) return;
        uint head = m.ReadU32(0x800B5234u), player = m.ReadU32(0x800B5268u);
        if (c.A0 != head || head == 0 || player == 0) return;
        if (Saved.Count != 0) throw new InvalidOperationException("Nested crowd draw fixture");
        uint node = head;
        for (int i = 0; node != 0; i++)
        {
            if (i >= (Full ? 9 : 4) || node < 0x80000000 || node >= 0x80200000)
                throw new InvalidOperationException("Crowd fixture encountered an unexpected L1A1 enemy list");
            ushort type=m.ReadU16(node+0x34);
            if (Full && type==0x13F) { node=m.ReadU32(node+0x1C); continue; }
            if (type!=0x138) throw new InvalidOperationException("Unexpected character type in L1A1 crowd");
            Saved.Add((node,m.ReadU32(node+4),m.ReadU32(node+8),m.ReadU32(node+12),m.ReadU16(node)));
            node = m.ReadU32(node+0x1C);
        }
        if (Saved.Count < 4 || Saved.Count > (Full ? 5 : 4)) throw new InvalidOperationException("Missing or unexpected crowd actors");
        for (int i=0;i<Saved.Count;i++)
        {
            var actor=Saved[i];
            var offset=i<4 ? Offsets[i] : (X:0,Z:110);
            m.WriteU32(actor.Pointer+4,unchecked(m.ReadU32(player+4)+(uint)(offset.X*4096)));
            m.WriteU32(actor.Pointer+8,m.ReadU32(player+8));
            m.WriteU32(actor.Pointer+12,unchecked(m.ReadU32(player+12)+(uint)(offset.Z*4096)));
            m.WriteU16(actor.Pointer,(ushort)(actor.Flags & ~0x8000));
        }
        if (_frame/120 != _lastReport)
        {
            _lastReport=_frame/120;
            Console.WriteLine($"[character-baseline] frame={_frame} drawing {Saved.Count} existing henchmen beside player");
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
