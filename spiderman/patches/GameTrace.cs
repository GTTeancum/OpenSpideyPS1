using System;
using RecompOne.Runtime;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Instrumentation for the two game-level mechanisms a static recompile has to get
/// right: which code overlays are resident, and whether an actor spawn found one.
///
/// SpawnActor (0x8001BEC4) hashes the actor's name, walks the list of loaded overlays
/// looking for a matching hash, and calls a constructor out of that overlay's table.
/// When nothing matches it returns *without writing the out-pointer*, so the caller
/// reads whatever was on the stack and then dereferences it. That failure surfaces
/// far from its cause -- as a call through a null vtable in the script interpreter --
/// which is why the miss is worth naming at the point it happens.
///
/// On unless SPIDEY_TRACE_GAME is unset.
/// </summary>
public static class GameTrace
{
    /// <summary>Verbose by default -- this game is cheap enough that it costs nothing,
    /// and a lock-up is unreadable without it. SPIDEY_QUIET turns it off.</summary>
    public static bool On =
        string.IsNullOrEmpty(Environment.GetEnvironmentVariable("SPIDEY_QUIET"));

    static string _spawnName;
    static bool _spawnResident;

    static string Str(IMemory m, uint addr, int max = 32)
    {
        if (addr == 0) return "(null)";
        var sb = new System.Text.StringBuilder();
        for (int i = 0; i < max; i++)
        {
            byte b = m.ReadU8(addr + (uint)i);
            if (b == 0) break;
            sb.Append((char)b);
        }
        return sb.ToString();
    }

    // The runtime-built level file names, filled in before LoadLevel reads them.
    static readonly uint[] NameBufs =
        { 0x800B5728, 0x800B5730, 0x800B5738, 0x800B5740, 0x800B5748, 0x800B5750 };

    /// <summary>
    /// pre-hook on RunTriggerScript(cmds, ...) -- the trigger command interpreter.
    /// Opcode 126/128 load a .psx, 189 loads a code overlay, so whether this runs at
    /// all is what decides if a level gets its resources.
    /// </summary>
    public static void RunTriggerScript(CpuContext c, IMemory m)
    {
        uint p = c.A0;
        var ops = new System.Text.StringBuilder();
        int n = 0;
        bool sawLoad = false;
        for (; n < 400; n++)
        {
            ushort w = m.ReadU16(p + (uint)n * 2);
            if (w == 0xFFFF) break;
            if (w == 126 || w == 128 || w == 189) sawLoad = true;
            if (n < 40) ops.Append(w + " ");
        }
        Console.WriteLine($"[game] RunTriggerScript(0x{p:X8}) len={n} words hasLoadOpcode={sawLoad}");
        Console.WriteLine($"[game]    {ops}");
    }

    /// <summary>
    /// The level intro. Opcode 190 in a trigger script calls this, and every resource
    /// the level needs is loaded by the commands that come *after* it, so if it does
    /// not return the level gets none of them.
    /// </summary>
    static uint _liSp;

    public static void LevelIntro(CpuContext c, IMemory m)
    {
        _liSp = c.SP;
        Console.WriteLine($"[game] LevelIntro({c.A0}) enter  sp=0x{c.SP:X8} s1=0x{c.S1:X8} next=0x{m.ReadU16(c.S1):X4}");
    }

    public static void LevelIntroExit(CpuContext c, IMemory m)
        => Console.WriteLine($"[game] LevelIntro exit   sp=0x{c.SP:X8} (delta {(int)(c.SP - _liSp)}) s1=0x{c.S1:X8}");

    public static void ShowCover(CpuContext c, IMemory m)
        => Console.WriteLine($"[game]   ShowCover(\"{Str(m, c.A0)}\") enter s1=0x{c.S1:X8} fp=0x{c.FP:X8}");

    public static void ShowCoverExit(CpuContext c, IMemory m)
        => Console.WriteLine($"[game]   ShowCover exit          s1=0x{c.S1:X8} fp=0x{c.FP:X8}");

    public static void LevelIntroDispatch(CpuContext c, IMemory m)
        => Console.WriteLine($"[game]  Dispatch({c.A0}) enter    s1=0x{c.S1:X8} fp=0x{c.FP:X8}");

    public static void LevelIntroDispatchExit(CpuContext c, IMemory m)
        => Console.WriteLine($"[game]  Dispatch exit            s1=0x{c.S1:X8} fp=0x{c.FP:X8}");

    static uint _rfSp, _rfRa;

    public static void RunFrame(CpuContext c, IMemory m)
    {
        _rfSp = c.SP; _rfRa = c.RA;
        Console.WriteLine($"[game]    RunFrame({c.A0}) enter  sp=0x{c.SP:X8} ra=0x{c.RA:X8} s1=0x{c.S1:X8} fp=0x{c.FP:X8}");
    }

    public static void RunFrameExit(CpuContext c, IMemory m)
        => Console.WriteLine($"[game]    RunFrame exit          sp=0x{c.SP:X8} (delta {(int)(c.SP - _rfSp)}) ra=0x{c.RA:X8} s1=0x{c.S1:X8} fp=0x{c.FP:X8}");

    /// <summary>
    /// pre-hook on the object renderer, which walks a linked list through offset 4.
    /// One node's next pointer is landing outside RAM; this reports the node it came
    /// from so the write that corrupted it can be found.
    /// </summary>
    /// <summary>Per-frame render tracing is off unless SPIDEY_TRACE_RENDER is set.</summary>
    public static readonly bool TraceRender =
        !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("SPIDEY_TRACE_RENDER"));

    static int _rolCalls;
    static uint _rolPrimAtEntry;
    static uint _rolHeadPtr;
    static int _rolNonEmpty;

    /// <summary>post-hook on the object renderer.</summary>
    public static void RenderObjectListExit(CpuContext c, IMemory m)
    {
        if (!TraceRender) return;
        uint node = m.ReadU32(_rolHeadPtr);
        for (int i = 0; i < 20000 && node != 0; i++)
        {
            if (node < 0x80000000 || node >= 0x80800000 || (node & 3) != 0)
            {
                Console.WriteLine($"[game] RenderObjectList: list CORRUPTED by the body -- bad next 0x{node:X8} at depth {i}");
                return;
            }
            node = m.ReadU32(node + 4);
        }
    }

    public static void RenderObjectList(CpuContext c, IMemory m)
    {
        if (!TraceRender) return;
        // The primitive buffer the packet writer fills. If this pointer climbs without
        // being reset each frame it eventually walks into whatever follows it in RAM.
        uint primPtr = m.ReadU32(0x800B5944);
        _rolPrimAtEntry = primPtr;
        _rolCalls++;
        _rolHeadPtr = c.A0;
        uint h = m.ReadU32(c.A0);
        if (h != 0 && _rolNonEmpty++ < 12)
        {
            int depth = 0;
            uint n2 = h;
            while (n2 != 0 && depth < 20000 && n2 >= 0x80000000 && n2 < 0x80800000 && (n2 & 3) == 0)
            { n2 = m.ReadU32(n2 + 4); depth++; }
            var nodes = new System.Text.StringBuilder();
            uint n3 = h;
            for (int i = 0; i < 10 && n3 != 0 && n3 >= 0x80000000 && n3 < 0x80800000; i++)
            { nodes.Append($"0x{n3:X8}(next=0x{m.ReadU32(n3 + 4):X8}) "); n3 = m.ReadU32(n3 + 4); }
            Console.WriteLine($"[game] RenderObjectList #{_rolCalls}: a0=0x{c.A0:X8} sp=0x{c.SP:X8} " +
                              $"depth={depth} nodes: {nodes}");
        }

        uint head = m.ReadU32(c.A0);
        uint node = head;
        var chain = new System.Text.StringBuilder();
        for (int i = 0; i < 20000 && node != 0; i++)
        {
            bool ok = node >= 0x80000000 && node < 0x80800000 && (node & 3) == 0;
            if (!ok)
            {
                string tailChain = chain.ToString();
                if (tailChain.Length > 300) tailChain = "..." + tailChain.Substring(tailChain.Length - 300);
                Console.WriteLine($"[game] RenderObjectList: bad node 0x{node:X8} at depth {i}; last nodes: {tailChain}");
                return;
            }
            if (chain.Length > 4000) chain.Remove(0, 2000);
            chain.Append($"0x{node:X8} ");
            node = m.ReadU32(node + 4);
        }
    }

    /// <summary>
    /// pre-hook on the game's fatal halt (0x80064F74): it clears the screen to a
    /// colour and then spins on `j self` forever. Whatever called it is the real
    /// failure, and without this the only evidence is a flat coloured window.
    /// </summary>
    public static void FatalHalt(CpuContext c, IMemory m)
    {
        Console.WriteLine($"[game] FATAL HALT: screen r={c.A0} g={c.A1} b={c.A2}");
        var tail = RecompOne.Runtime.Diagnostics.CallRing.Tail(16);
        var sb = new System.Text.StringBuilder("[game]   callers, most recent last: ");
        foreach (uint a in tail) sb.Append($"0x{a:X8} ");
        Console.WriteLine(sb.ToString());
    }

    static uint _dpsS0;
    static int _dpsCount;

    /// <summary>
    /// pre/post on the packet writer the object renderer calls per node. The renderer
    /// keeps the node it is walking in s0 across this call and reads s0->next straight
    /// afterwards, so whether s0 survives here decides whether the crash is a clobbered
    /// register or genuinely corrupt memory.
    /// </summary>
    public static void DrawPrimSet(CpuContext c, IMemory m)
    {
        if (!TraceRender) return;
        _dpsS0 = c.S0;
        _dpsNext = (c.S0 >= 0x80000000 && c.S0 < 0x80800000) ? m.ReadU32(c.S0 + 4) : 0xDEADBEEF;
    }

    static uint _dpsNext;

    public static void DrawPrimSetExit(CpuContext c, IMemory m)
    {
        if (!TraceRender) return;
        uint nextNow = (c.S0 >= 0x80000000 && c.S0 < 0x80800000) ? m.ReadU32(c.S0 + 4) : 0xDEADBEEF;
        if ((c.S0 != _dpsS0 || nextNow != _dpsNext) && _dpsCount++ < 10)
            Console.WriteLine($"[game] DrawPrimSet changed things: s0 0x{_dpsS0:X8}->0x{c.S0:X8}, " +
                              $"s0->next 0x{_dpsNext:X8}->0x{nextNow:X8}, ra on exit 0x{c.RA:X8}");
    }

    /// <summary>pre-hook on LoadTriggers(char *area)</summary>
    public static void LoadTriggers(CpuContext c, IMemory m)
        => Console.WriteLine($"[game] LoadTriggers(\"{Str(m, c.A0)}\")");

    /// <summary>pre-hook on TriggerPass -- walks the list spawning and loading.</summary>
    public static void TriggerPass(CpuContext c, IMemory m)
        => Console.WriteLine("[game] TriggerPass");

    /// <summary>pre-hook on TriggerType8 -- the resource entry handler.</summary>
    public static void TriggerType8(CpuContext c, IMemory m)
        => Console.WriteLine($"[game] TriggerType8(a0=0x{c.A0:X8} a1={c.A1})");

    /// <summary>pre-hook on LoadLevel -- the driver that pulls in level geometry.</summary>
    public static void LoadLevel(CpuContext c, IMemory m)
    {
        Console.WriteLine("[game] LoadLevel enter: " +
            string.Join(" ", Array.ConvertAll(NameBufs, b => $"\"{Str(m, b, 20)}\"")));
    }

    /// <summary>post-hook on LoadLevel</summary>
    public static void LoadLevelExit(CpuContext c, IMemory m)
        => Console.WriteLine("[game] LoadLevel exit");

    /// <summary>pre-hook on LoadPsx(char *name, int)</summary>
    public static void LoadPsx(CpuContext c, IMemory m)
    {
        if (On) Console.WriteLine($"[game]   LoadPsx(\"{Str(m, c.A0)}\") from ra=0x{c.RA:X8}");
    }

    /// <summary>pre-hook on LoadOverlay(char *name, int heap)</summary>
    public static void LoadOverlay(CpuContext c, IMemory m)
    {
        if (On) Console.WriteLine($"[game] LoadOverlay(\"{Str(m, c.A0)}\", heap={c.A1})");
    }

    /// <summary>pre-hook on SpawnActor(char *name, int slot, void *params, void **out)</summary>
    public static void SpawnActor(CpuContext c, IMemory m)
    {
        _spawnName = Str(m, c.A0);
        if (On) Console.WriteLine($"[game] SpawnActor(\"{_spawnName}\", slot={c.A1})");

        if (OnDemand) EnsureResident(c, m, c.A0, _spawnName);
        _spawnResident = Resident(_spawnName);
    }

    /// <summary>
    /// Load an actor's overlay if it is not resident yet.
    ///
    /// The level's trigger list spawns actors by name and expects their overlays to
    /// already be loaded; when one is not, SpawnActor returns without writing its
    /// out-pointer and the caller dereferences null. Loading it here is the game's own
    /// idiom -- 0x8006F294 does exactly LoadOverlay(name, 1) then SpawnActor(name, ...)
    /// -- applied at the point the need is discovered rather than ahead of it.
    ///
    /// LoadOverlay is itself idempotent: it hashes the name, walks the resident list
    /// and returns immediately on a match, so calling it for something already loaded
    /// costs a list walk and nothing else.
    /// </summary>
    static void EnsureResident(CpuContext c, IMemory m, uint namePtr, string name)
    {
        if (namePtr == 0 || !OverlayPatches.Knows(name)) return;
        if (Resident(name)) return;

        Console.WriteLine($"[game] '{name}' not resident at spawn; loading it now");
        var snap = c.Snapshot();
        c.A0 = namePtr;
        c.A1 = 1;
        RecompOne.Runtime.Dispatch.Dispatcher.Call(c, m, LoadOverlayAddr);
        c.Restore(snap);
    }

    const uint LoadOverlayAddr = 0x8001B990u;

    /// <summary>Set SPIDEY_NO_ONDEMAND to see the raw failure instead.</summary>
    public static bool OnDemand =
        string.IsNullOrEmpty(Environment.GetEnvironmentVariable("SPIDEY_NO_ONDEMAND"));

    /// <summary>
    /// post-hook on SpawnActor.
    ///
    /// Residency is the thing to report, not the out-pointer. SpawnActor's a3 is
    /// handed straight to the overlay's constructor and is not always a writable word
    /// -- an earlier version of this hook zeroed it to make a miss obvious and
    /// corrupted the front end doing so. Reading the loaded-overlay list costs nothing
    /// and touches no game memory.
    /// </summary>
    public static void SpawnActorExit(CpuContext c, IMemory m)
    {
        if (!_spawnResident && OverlayPatches.Knows(_spawnName))
            Console.WriteLine($"[game] SpawnActor(\"{_spawnName}\") MISSED -- overlay not resident. " +
                              $"active: {string.Join(",", RecompOne.Runtime.Dispatch.Dispatcher.ActiveNames)}");
    }

    static bool Resident(string name) =>
        Array.IndexOf(RecompOne.Runtime.Dispatch.Dispatcher.ActiveNames, name) >= 0;
}
