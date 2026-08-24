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
    public static bool On =
        !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("SPIDEY_TRACE_GAME"));

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
