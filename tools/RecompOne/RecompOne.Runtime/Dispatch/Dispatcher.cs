using RecompOne.Runtime.Context;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;
using BiosKernel = RecompOne.Runtime.Bios.Bios;

namespace RecompOne.Runtime.Dispatch;

public static class Dispatcher
{
    static readonly OverlayLoadedEvent _overlayEvent = new();
    static readonly Dictionary<string, IOverlay> _registry = new(StringComparer.OrdinalIgnoreCase);
    static readonly Dictionary<int, string> _lbaToName = [];
    static readonly List<string> _active = [];
    static readonly Dictionary<uint, Action<CpuContext, IMemory>> _funcMap = [];
    private static IOverlay? _pending;
    public static void Register(string name, IOverlay overlay)
    {
        _registry[name] = overlay;
        if (overlay.LbaStart >= 0) _lbaToName[overlay.LbaStart] = name;
    }

    public static string[] ActiveNames
    {
        get { lock (_active) return _active.ToArray(); }
    }
    
    public static IReadOnlyDictionary<string, IOverlay> Overlays => _registry;

    public static void LoadByLba(int lba)
    {
        if (!_lbaToName.TryGetValue(lba, out var name)) return;
        var overlay = _registry[name];
        if(overlay.Base == 0) {
            Load(name);
            return;
        }

        _pending = overlay;
    }

    public static void NotifyWrite(uint phys)
    {
        var p = _pending;
        if (p == null) return;
        uint start = p.Base & 0x1FFFFFFFu;
        if (phys < start || phys >= start + 0x800u) return;
        _pending = null;
        Load(p.Name);
    }
    public static void ClearPending() => _pending = null;

    public static void Reset()
    {
        _pending = null;
        lock (_active) _active.Clear();
        _funcMap.Clear();
    }

    public static void Load(string name)
    {
        if (!_registry.TryGetValue(name, out var overlay))
            throw new KeyNotFoundException($"overlay not registered: {name}");

        bool already;
        lock (_active) already = _active.Remove(name);

        if (!already) HandleRegionOverwrites(overlay);

        lock (_active) _active.Add(name);
        foreach (var (addr, fn) in overlay.Functions)
            _funcMap[addr] = fn;

        if (already) return;
        Runtime.OverlayLog.Record(name, OverlayEventKind.Loaded);
        Console.WriteLine($"[Dispatcher] loaded overlay: {name}");

        if (Event.HasAnyListeners<OverlayLoadedEvent>())
        {
            var e = _overlayEvent;
            e.Context = Runtime.Cpu!; e.Memory = Runtime.Mem!;
            e.Name = name;
            Event.Dispatch(e);
        }
    }

    static void HandleRegionOverwrites(IOverlay overlay)
    {
        uint newStart = overlay.Base & 0x1FFFFFFFu;
        uint newEnd = newStart + overlay.Size;
        bool hasRegion = overlay.Base != 0 && overlay.Size != 0;

        List<string>? overwritten = null;
        List<(string Name, int Funcs)>? vramCollisions = null;

        lock (_active)
        {
            foreach (var activeName in _active)
            {
                var other = _registry[activeName];
                bool otherHasRegion = other.Base != 0 && other.Size != 0;

                if (hasRegion && otherHasRegion)
                {
                    uint s = other.Base & 0x1FFFFFFFu;
                    uint e = s + other.Size;

                    if (s < newEnd && e > newStart)
                    {
                        if (s >= newStart && e <= newEnd)
                        {
                            overwritten ??= [];
                            overwritten.Add(activeName);
                        }
                        continue;
                    }
                }

                int shared = CountSharedFunctions(overlay, other);
                if (shared > 0)
                {
                    vramCollisions ??= [];
                    vramCollisions.Add((activeName, shared));
                }
            }

            if (overwritten != null)
                foreach (var d in overwritten) _active.Remove(d);
        }

        if (overwritten != null)
        {
            Rebuild();
            foreach (var d in overwritten)
            {
                Runtime.OverlayLog.Record(d, OverlayEventKind.Overwritten, overlay.Name);
                Console.WriteLine($"[Dispatcher] overlay {d} overwritten by {overlay.Name}");
            }
        }

        if (vramCollisions != null)
        {
            foreach (var (otherName, n) in vramCollisions)
            {
                Runtime.OverlayLog.Record(overlay.Name, OverlayEventKind.VramCollision, $"{otherName} ({n} funcs)");
                Console.WriteLine($"[Dispatcher] overlay {overlay.Name} vvram colision with {otherName}: {n} functions");
            }
        }
    }

    static int CountSharedFunctions(IOverlay a, IOverlay b)
    {
        var smaller = a.Functions.Count <= b.Functions.Count ? a : b;
        var larger = ReferenceEquals(smaller, a) ? b : a;

        int n = 0;
        foreach (var addr in smaller.Functions.Keys)
            if (larger.Functions.ContainsKey(addr)) n++;
        return n;
    }

    public static void TryLoad(string name)
    {
        if (_registry.ContainsKey(name))
            Load(name);
    }

    public static void Unload(string name)
    {
        bool removed;
        lock (_active) removed = _active.Remove(name);
        if (!removed) return;
        Rebuild();
        Runtime.OverlayLog.Record(name, OverlayEventKind.Unloaded);
    }

    public static void Call(CpuContext c, IMemory m, uint addr)
    {
        if (BiosKernel.TryDispatch(c, m, addr)) return;
        if (!_funcMap.TryGetValue(addr, out var fn))
            throw new InvalidOperationException($"unmapped call: 0x{addr:X8}\n{Context(c)}");
        fn(c, m);
    }

    /// <summary>
    /// Registers at the point of a failed dispatch. An address alone says nothing about
    /// why it was reached: a call through a vtable slot needs the object it came from,
    /// and a jump-table default needs the index that selected it.
    /// </summary>
    static string Context(CpuContext c) =>
        $"  a0={c.A0:X8} a1={c.A1:X8} a2={c.A2:X8} a3={c.A3:X8} v0={c.V0:X8} v1={c.V1:X8} ra={c.RA:X8}\n" +
        $"  s0={c.S0:X8} s1={c.S1:X8} s2={c.S2:X8} s3={c.S3:X8} s4={c.S4:X8} s5={c.S5:X8} s6={c.S6:X8} s7={c.S7:X8}\n" +
        $"  active overlays: {string.Join(", ", ActiveNames)}";

    static void Rebuild()
    {
        _funcMap.Clear();
        lock (_active)
        {
            foreach (var name in _active)
                foreach (var (addr, fn) in _registry[name].Functions)
                    _funcMap[addr] = fn;
        }
    }
}
