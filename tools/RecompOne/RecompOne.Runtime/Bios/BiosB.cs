using RecompOne.Runtime.Context;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace RecompOne.Runtime.Bios;

public static class BiosB
{
    static readonly PadReadEvent _padEvent = new();
    struct EvCB { public uint Status, Class, Spec, Mode, Func; }
    const int MaxEvents = 64;
    static readonly EvCB[] _evCBs = new EvCB[MaxEvents];
    struct TCB { public bool Used; }
    const int MaxThreads = 4;
    static readonly TCB[] _tcbs = new TCB[MaxThreads];

    static readonly uint[] _intChain = new uint[4];

    public static uint IntrEnvInInterruptAddr = 0u;

    static uint _padBuf;
    static uint _padCardBuf1, _padCardBuf2;
    static bool _padCardStarted;

    public static void Reset()
    {
        Array.Clear(_evCBs);
        Array.Clear(_tcbs);
        Array.Clear(_intChain);
        _cardDone.Clear();
        IntrEnvInInterruptAddr = 0u;
        _padBuf = 0u;
        _padCardBuf1 = _padCardBuf2 = 0u;
        _padCardStarted = false;
    }

    public static void DeliverEvent(uint @class, uint spec)
    {
        for (int i = 0; i < MaxEvents; i++)
            if (_evCBs[i].Status == 2u && _evCBs[i].Class == @class && _evCBs[i].Spec == spec)
                _evCBs[i].Status = 4u;
    }
    
    public static int DeliverEventIntr(CpuContext c, IMemory m, uint @class, uint spec)
    {
        int hits = 0;
        for (int i = 0; i < MaxEvents; i++)
        {
            if (_evCBs[i].Status != 2u || _evCBs[i].Class != @class || _evCBs[i].Spec != spec) continue;
            hits++;
            if ((_evCBs[i].Mode & 0x1000u) != 0 && _evCBs[i].Func != 0u)
            {
                var snap = c.Snapshot();
                RecompOne.Runtime.Dispatch.Dispatcher.Call(c, m, _evCBs[i].Func);
                c.Restore(snap);
            }
            else
            {
                _evCBs[i].Status = 4u;
            }
        }
        return hits;
    }
    
    static readonly List<(uint Port, int Delay)> _cardDone = new();

    /// <summary>How long a card completion stays available for re-delivery, in frames.</summary>
    public static int CardMaxAgeFrames = 240;

    /// <summary>
    /// Card operations finish asynchronously on hardware. libmcrd starts one, then
    /// clears its event flags and only afterwards waits for them, so a completion
    /// delivered inside (or immediately after) the BIOS call gets wiped by the game's
    /// own clear and the wait never ends. A real directory load takes several frames
    /// of sector reads, so hold the completion for a few frames and let the game reach
    /// its wait first.
    /// </summary>
    public static void CardComplete(CpuContext c, IMemory m, uint port)
        => _cardDone.Add((port, 0));

    /// <param name="idle">
    /// True when the game is spinning rather than running its frame loop.
    ///
    /// libmcrd starts a card operation, and only some frames later clears its event
    /// flags and waits on them -- so a completion handed over once, at any fixed
    /// delay, is as likely to be wiped by that clear as to be seen. Instead a pending
    /// completion stays available: it is re-delivered on every idle spin until it
    /// ages out, which means whichever wait the game reaches first observes it. The
    /// callbacks only store a flag, so repeating them is harmless.
    /// </param>
    public static void PumpCard(CpuContext c, IMemory m, bool idle)
    {
        for (int k = _cardDone.Count - 1; k >= 0; k--)
        {
            var (p, d) = _cardDone[k];
            int age = d + 1;
            _cardDone[k] = (p, age);
            if (age > CardMaxAgeFrames) { _cardDone.RemoveAt(k); continue; }
            if (!idle) continue;
            uint port = p;
            var card = (port & 0x10u) != 0 ? Runtime.CardB : Runtime.CardA;
            uint spec = card.Enabled ? 0x0004u : 0x0100u;

            int a = DeliverEventIntr(c, m, 0xF4000001u, spec);
            int b = DeliverEventIntr(c, m, 0xF0000011u, spec);
            if (age == 1) Log.Bios($"  PumpCard port=0x{port:X} spec=0x{spec:X4} delivered {a}+{b}");
        }
    }

    static void CardRead(CpuContext c, IMemory m)
    {
        var card = (c.A0 & 0x10u) != 0 ? Runtime.CardB : Runtime.CardA;
        if (card.Enabled && c.A2 != 0u)
        {
            Span<byte> f = stackalloc byte[0x80];
            card.FrameRead((int)(c.A1 & 0x3FFu), f);
            for (uint i = 0; i < 0x80u; i++) m.WriteU8(c.A2 + i, f[(int)i]);
        }
        CardComplete(c, m, c.A0);
        c.V0 = 1u;
    }

    static void CardWrite(CpuContext c, IMemory m)
    {
        var card = (c.A0 & 0x10u) != 0 ? Runtime.CardB : Runtime.CardA;
        if (card.Enabled && c.A2 != 0u)
        {
            Span<byte> f = stackalloc byte[0x80];
            for (uint i = 0; i < 0x80u; i++) f[(int)i] = m.ReadU8(c.A2 + i);
            card.FrameWrite((int)(c.A1 & 0x3FFu), f);
        }
        CardComplete(c, m, c.A0);
        c.V0 = 1u;
    }

    public static uint GetFreeEvSlot()
    {
        for (int i = 0; i < MaxEvents; i++) if (_evCBs[i].Status == 0u) return (uint)i;
        return 0xFFFFFFFFu;
    }
    
    static ushort FirePad(IMemory m, int port, ushort buttons)
    {
        if (!Event.HasAnyListeners<PadReadEvent>()) return buttons;
        var e = _padEvent;
        e.Context = Runtime.Cpu!; e.Memory = m;
        e.Port = port; e.Buttons = buttons;
        Event.Dispatch(e);
        return e.Buttons;
    }

    static void PadRead(IMemory m)
    {
        if (_padBuf == 0) return;
        ushort s = Hardware.Controller.State;
        ushort swapped = (ushort)((s >> 8) | (s << 8));
        ushort s2 = Hardware.Controller.State2;
        ushort swapped2 = (ushort)((s2 >> 8) | (s2 << 8));
        swapped = FirePad(m, 0, swapped);
        swapped2 = FirePad(m, 1, swapped2);
        m.WriteU32(_padBuf,     ((uint)swapped2 << 16) | swapped);
        m.WriteU8(_padBuf + 4, Hardware.Controller.RightX);
        m.WriteU8(_padBuf + 5, Hardware.Controller.RightY);
        m.WriteU8(_padBuf + 6, Hardware.Controller.LeftX);
        m.WriteU8(_padBuf + 7, Hardware.Controller.LeftY);
    }

    static void InitPad(IMemory m, uint buf1, uint siz1, uint buf2, uint siz2)
    {
        _padCardBuf1 = buf1;
        _padCardBuf2 = buf2;
        for (uint i = 0; i < siz1; i++) m.WriteU8(buf1 + i, 0);
        for (uint i = 0; i < siz2; i++) m.WriteU8(buf2 + i, 0);
    }

    static void PadCardIrq(IMemory m)
    {
        if (!_padCardStarted) return;

        ushort b1 = Unswap(FirePad(m, 0, Swap(Hardware.Controller.State)));
        WritePadSlot(m, _padCardBuf1, true, b1,
            Hardware.Controller.RightX, Hardware.Controller.RightY,
            Hardware.Controller.LeftX, Hardware.Controller.LeftY);

        ushort b2 = Unswap(FirePad(m, 1, Swap(Hardware.Controller.State2)));
        WritePadSlot(m, _padCardBuf2, Hardware.Controller.Connected2, b2,
            Hardware.Controller.RightX2, Hardware.Controller.RightY2,
            Hardware.Controller.LeftX2, Hardware.Controller.LeftY2);
    }

    static ushort Swap(ushort v) => (ushort)((v >> 8) | (v << 8));

    static ushort Unswap(ushort v) => (ushort)((v >> 8) | (v << 8));

    static void WritePadSlot(IMemory m, uint buf, bool connected, ushort buttons,
        byte rx, byte ry, byte lx, byte ly)
    {
        if (buf == 0) return;
        if (!connected)
        {
            m.WriteU8(buf, 0xFF);
            m.WriteU8(buf + 1, 0);
            return;
        }
        m.WriteU8(buf, 0);
        m.WriteU8(buf + 1, 0x41);
        m.WriteU8(buf + 2, (byte)buttons);
        m.WriteU8(buf + 3, (byte)(buttons >> 8));
        m.WriteU8(buf + 4, rx);
        m.WriteU8(buf + 5, ry);
        m.WriteU8(buf + 6, lx);
        m.WriteU8(buf + 7, ly);
    }

    public static void RefreshPad(IMemory m)
    {
        PadRead(m);
        PadCardIrq(m);
    }
    public static void Dispatch(CpuContext c, IMemory m, uint fn)
    {
        Log.Bios($"B({fn:X2}) {BiosNames.B(fn)}");
        switch (fn)
        {
            case 0x00: c.V0 = 0u; break;
            case 0x01: break;
            case 0x02: c.V0 = 0u; break;
            case 0x03: c.V0 = 0u; break;
            case 0x04: break;
            case 0x05: break;
            case 0x06: break;
            case 0x07: Log.Bios($"  DeliverEvent(class=0x{c.A0:X8} spec=0x{c.A1:X4})"); DeliverEvent(c.A0, c.A1); break;
            case 0x08: c.V0 = OpenEvent(c.A0, c.A1, c.A2, c.A3); Log.Bios($"  OpenEvent(class=0x{c.A0:X8} spec=0x{c.A1:X4} mode=0x{c.A2:X4} func=0x{c.A3:X8}) -> 0x{c.V0:X8}"); break;
            case 0x09: CloseEvent(c.A0); c.V0 = 1u; break;
            case 0x0A: c.V0 = WaitEvent(c.A0); break;
            case 0x0B: c.V0 = TestEvent(c.A0); Log.Bios($"  TestEvent(0x{c.A0:X8}) -> {c.V0}"); break;
            case 0x0C: Log.Bios($"  EnableEvent(0x{c.A0:X8})"); EnableEvent(c.A0); c.V0 = 1u; break;
            case 0x0D: DisableEvent(c.A0); c.V0 = 1u; break;
            case 0x0E: c.V0 = OpenTh(c.A0, c.A1, c.A2); break;
            case 0x0F: CloseTh(c.A0); c.V0 = 1u; break;
            case 0x10: break;
            case 0x11: break;
            case 0x12: InitPad(m, c.A0, c.A1, c.A2, c.A3); break;
            case 0x13: _padCardStarted = true; break;
            case 0x14: _padCardStarted = false; break;
            case 0x15: _padBuf = c.A1; break;
            case 0x16: PadRead(m); break;
            case 0x17: break;
            case 0x18: IntrEnvInInterruptAddr = 0u; break;
            case 0x19: IntrEnvInInterruptAddr = c.A0 != 0u ? c.A0 - 0x36u : 0u; break;
            case 0x1A: break;
            case 0x1B: break;
            case 0x1C: break;
            case 0x1D: break;
            case 0x1E: break;
            case 0x1F: break;
            case 0x20: UnDeliverEvent(c.A0, c.A1); break;
            case 0x2B: break;
            case 0x2C: break;
            case 0x2D: break;
            case 0x2E: break;
            case 0x2F: c.V0 = 0u; break;
            case 0x30: c.V0 = 0u; break;
            case 0x31: c.V0 = 0u; break;
            case 0x32: BiosA.Dispatch(c, m, 0x00); break;
            case 0x33: BiosA.Dispatch(c, m, 0x01); break;
            case 0x34: BiosA.Dispatch(c, m, 0x02); break;
            case 0x35: BiosA.Dispatch(c, m, 0x03); break;
            case 0x36: BiosA.Dispatch(c, m, 0x04); break;
            case 0x37: BiosA.Dispatch(c, m, 0x05); break;
            case 0x38: BiosA.Dispatch(c, m, 0x06); break;
            case 0x39: c.V0 = c.A0 <= 2u ? 2u : 0u; break;
            case 0x3A: c.V0 = 0xFFFFFFFFu; break;
            case 0x3B: Console.Write((char)(c.A0 & 0xFF)); c.V0 = c.A0; break;
            case 0x3C: c.V0 = 0xFFFFFFFFu; break;
            case 0x3D: Console.Write((char)(c.A0 & 0xFF)); c.V0 = c.A0; break;
            case 0x3E: c.V0 = 0u; break;
            case 0x3F: Console.Write(Bios.ReadString(m, c.A0)); c.V0 = c.A0; break;
            case 0x40: c.V0 = 1u; break;
            case 0x41: c.V0 = BiosA.CardFormat(m, c.A0); break;
            case 0x42: c.V0 = BiosA.FirstFile(m, c.A0, c.A1); break;
            case 0x43: c.V0 = BiosA.NextFile(m, c.A0); break;
            case 0x44: c.V0 = 0u; break;
            case 0x45: c.V0 = BiosA.CardDelete(m, c.A0); break;
            case 0x46: c.V0 = 0u; break;
            case 0x47: c.V0 = GetFreeEvSlot(); break;
            case 0x48: c.V0 = 0xFFFFFFFFu; break;
            case 0x49: break;
            case 0x4A: c.V0 = 1u; break;
            case 0x4B: c.V0 = 1u; break;
            case 0x4C: c.V0 = 1u; break;
            case 0x4D: break;
            case 0x4E: CardWrite(c, m); break;
            case 0x4F: CardRead(c, m); break;
            case 0x50: break;
            case 0x51: c.V0 = KromFont.Krom2RawAdd(c.A0); break;
            case 0x53: c.V0 = KromFont.Krom2Offset(c.A0); break;
            case 0x54: c.V0 = BiosA.LastErrno; break;
            case 0x55: c.V0 = 0u; break;
            case 0x56: c.V0 = 0u; break;
            case 0x57: c.V0 = 0u; break;
            case 0x58: break;
            case 0x59: c.V0 = BiosA.TestDevice(m, c.A0); break;
            case 0x5B: c.V0 = 0u; break;
            case 0x5C: c.V0 = 0u; break;
            case 0x5D: break;
            default: break;
        }
    }

    static uint OpenEvent(uint @class, uint spec, uint mode, uint func)
    {
        for (int i = 0; i < MaxEvents; i++)
        {
            if (_evCBs[i].Status == 0u)
            {
                _evCBs[i] = new EvCB { Status = 1u, Class = @class, Spec = spec, Mode = mode, Func = func };
                return 0xF0000000u | (uint)i;
            }
        }
        return 0xFFFFFFFFu;
    }

    static int EvSlot(uint ev)
    {
        int i = (int)(ev & 0xFFu);
        return i < MaxEvents ? i : -1;
    }

    static void CloseEvent(uint ev)
    {
        int s = EvSlot(ev);
        if (s >= 0) _evCBs[s] = default;
    }

    static uint WaitEvent(uint ev)
    {
        int s = EvSlot(ev);
        if (s >= 0 && _evCBs[s].Status == 4u) _evCBs[s].Status = 2u;
        return 1u;
    }

    static uint TestEvent(uint ev)
    {
        int s = EvSlot(ev);
        if (s >= 0 && _evCBs[s].Status == 4u) { _evCBs[s].Status = 2u; return 1u; }
        return 0u;
    }

    static void EnableEvent(uint ev)
    {
        int s = EvSlot(ev);
        if (s >= 0) _evCBs[s].Status = 2u;
    }

    static void DisableEvent(uint ev)
    {
        int s = EvSlot(ev);
        if (s >= 0 && _evCBs[s].Status != 0u) _evCBs[s].Status = 1u;
    }

    static void UnDeliverEvent(uint @class, uint spec)
    {
        for (int i = 0; i < MaxEvents; i++)
            if (_evCBs[i].Status == 4u && _evCBs[i].Class == @class && _evCBs[i].Spec == spec)
                _evCBs[i].Status = 2u;
    }
    static uint OpenTh(uint pc, uint spFp, uint gp)
    {
        for (int i = 0; i < MaxThreads; i++)
            if (!_tcbs[i].Used) { _tcbs[i] = new TCB { Used = true }; return 0xFF000000u | (uint)i; }
        return 0xFFFFFFFFu;
    }
    static void CloseTh(uint handle)
    {
        int i = (int)(handle & 0xFFu);
        if (i < MaxThreads) _tcbs[i] = default;
    }

    public static void SysEnqIntRP(CpuContext c, IMemory m)
    {
        uint priority = c.A0 & 3u;
        uint struc = c.A1;
        c.V0 = _intChain[priority];
        m.WriteU32(struc, _intChain[priority]);
        _intChain[priority] = struc;
    }
    public static void SysDeqIntRP(CpuContext c, IMemory m)
    {
        uint priority = c.A0 & 3u;
        uint struc = c.A1;
        if (_intChain[priority] == struc)
        {
            _intChain[priority] = m.ReadU32(struc);
            c.V0 = 1u;
            return;
        }
        uint cur = _intChain[priority];
        while (cur != 0u)
        {
            uint next = m.ReadU32(cur);
            if (next == struc) { m.WriteU32(cur, m.ReadU32(struc)); c.V0 = 1u; return; }
            cur = next;
        }
        c.V0 = 0u;
    }
}
