using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace RecompOne.Runtime.Assets;

/// <summary>Serves CD.WAD entries from an extracted host directory.</summary>
public static class LooseWadOverrides
{
    static Dictionary<string, string> _files = new(StringComparer.OrdinalIgnoreCase);
    static Dictionary<string, string> _overrides = new(StringComparer.OrdinalIgnoreCase);
    static byte[]? _pending;
    static string? _pendingName;
    static bool _pendingExternal;
    static uint _pendingRoundedSize;

    // The retail allocator only owns the original 2 MB address space. Recompiled
    // ports can reserve expanded RAM for larger loose replacement files without
    // changing the game's normal heap or colliding with fixed code overlays.
    const uint ArenaLo = 0x80300000;
    const uint ArenaHi = 0x80780000;
    static readonly SortedDictionary<uint, uint> _arenaFree = new();
    static readonly Dictionary<uint, (uint Size, string Name)> _arenaUsed = new();

    public static void Initialize(string gameDataRoot)
    {
        Cdrom.LooseDiscImporter.EnsureWad(gameDataRoot);
        _files = Index(Path.Combine(gameDataRoot, "wad"), required: true);
        string? external = Environment.GetEnvironmentVariable("SPIDEY_ASSET_DIR");
        _overrides = string.IsNullOrWhiteSpace(external)
            ? new(StringComparer.OrdinalIgnoreCase)
            : Index(Path.GetFullPath(external), required: true);
        ResetArena();
        Console.WriteLine($"[loose-wad] {_files.Count} extracted entries; {_overrides.Count} overrides");
    }

    static void ResetArena()
    {
        _arenaFree.Clear();
        _arenaUsed.Clear();
        _arenaFree[ArenaLo] = ArenaHi - ArenaLo;
    }

    /// <summary>
    /// Serve the allocation immediately following an external WAD lookup from
    /// expanded RAM. The original game heap remains byte-for-byte unchanged.
    /// </summary>
    public static bool TryAllocatePending(uint requestedSize, out uint address)
    {
        address = 0;
        if (!_pendingExternal || _pending == null || requestedSize != _pendingRoundedSize)
            return false;

        uint size = checked((requestedSize + 15u) & ~15u);
        foreach (var block in _arenaFree.ToArray())
        {
            if (block.Value < size) continue;
            address = block.Key;
            _arenaFree.Remove(block.Key);
            if (block.Value > size)
                _arenaFree[block.Key + size] = block.Value - size;
            _arenaUsed[address] = (size, _pendingName ?? "<override>");
            Console.WriteLine(
                $"[loose-wad] arena {_pendingName}: {size} bytes at 0x{address:X8}");
            return true;
        }
        throw new OutOfMemoryException(
            $"loose override arena exhausted while allocating {_pendingName} ({size} bytes)");
    }

    /// <summary>Release an exact pointer previously returned by the override arena.</summary>
    public static bool TryFree(uint address)
    {
        if (!_arenaUsed.Remove(address, out var allocation)) return false;
        uint start = address;
        uint size = allocation.Size;

        var before = _arenaFree.LastOrDefault(block => block.Key + block.Value == start);
        if (before.Value != 0)
        {
            _arenaFree.Remove(before.Key);
            start = before.Key;
            size += before.Value;
        }
        if (_arenaFree.Remove(start + size, out uint afterSize))
            size += afterSize;
        _arenaFree[start] = size;
        Console.WriteLine(
            $"[loose-wad] arena free {allocation.Name}: {allocation.Size} bytes at 0x{address:X8}");
        return true;
    }

    static Dictionary<string, string> Index(string directory, bool required)
    {
        if (!Directory.Exists(directory))
        {
            if (required) throw new DirectoryNotFoundException($"loose WAD directory does not exist: {directory}");
            return new(StringComparer.OrdinalIgnoreCase);
        }
        return Directory.EnumerateFiles(directory, "*", SearchOption.TopDirectoryOnly)
            .ToDictionary(path => Path.GetFileName(path)!, Path.GetFullPath, StringComparer.OrdinalIgnoreCase);
    }

    public static void Find(string name)
    {
        _pending = null;
        _pendingName = null;
        _pendingExternal = false;
        _pendingRoundedSize = 0;

        if (!Path.GetFileName(name).Equals(name, StringComparison.Ordinal)) return;
        string? path;
        if (_overrides.TryGetValue(name, out path)) _pendingExternal = true;
        else if (!_files.TryGetValue(name, out path)) return;

        byte[] data = File.ReadAllBytes(path);
        if (data.Length == 0) throw new InvalidDataException($"loose WAD entry is empty: {path}");
        _pending = data;
        _pendingName = name;
        _pendingRoundedSize = checked((uint)((data.Length + 0x7FF) & ~0x7FF));
    }

    public static void FindExit(CpuContext c)
    {
        if (_pending == null) return;
        c.V0 = _pendingRoundedSize;
        if (_pendingExternal)
            Console.WriteLine($"[loose-wad] override {_pendingName}: {_pending.Length} bytes " +
                              $"({_pendingRoundedSize} allocated)");
    }

    public static bool Read(CpuContext c, IMemory m)
    {
        if (_pending == null) return true;
        m.ZeroRange(c.A0, _pendingRoundedSize);
        m.LoadBytes(c.A0, _pending);
        c.V0 = 0xFFFFFFFFu;
        _pending = null;
        _pendingName = null;
        _pendingExternal = false;
        _pendingRoundedSize = 0;
        return false;
    }
}
