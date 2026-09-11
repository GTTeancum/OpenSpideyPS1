using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using RecompOne.Runtime.Assets;
using RecompOne.Runtime.Assets.Suits;
using RecompOne.Runtime.Assets.Textures;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>SM1 data-only suit catalogue and host-owned material bindings.</summary>
public static class SuitMods
{
    public const int StockCount = 20;
    public const int MaxCount = 60; // Total stock + mod rows in the expanded selector.
    public static readonly List<SuitManifest> Catalogue = new();
    public static int Active { get; private set; } = -1;
    static Dictionary<uint, ReplacementTexture> _textures = new();
    static string _root;
    static IMemory _memory;
    static readonly HashSet<uint> _reported = new();
    static readonly bool Trace = Environment.GetEnvironmentVariable("SPIDEY_MOD_TRACE") == "1";
    static readonly HashSet<string> _misses = new();
    static ulong _layoutSignature;
    public static SuitManifest At(int index) => Catalogue[index - StockCount];
    public static bool IsMod(int index) => index >= StockCount && index < StockCount + Catalogue.Count;

    public static void Install()
    {
        string exe = Path.GetDirectoryName(Environment.ProcessPath) ?? AppContext.BaseDirectory;
        _root = Path.GetFullPath(Environment.GetEnvironmentVariable("SPIDEY_SUIT_MOD_DIR") ?? Path.Combine(exe, "mods", "suits"));
        if (!Directory.Exists(_root)) return;
        if ((File.GetAttributes(_root) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("suit mod root cannot be a link");
        foreach (string dir in Directory.EnumerateDirectories(_root).Order(StringComparer.Ordinal))
        {
            string file = Path.Combine(dir, "suit.json");
            if (!File.Exists(file)) continue;
            try
            {
                var mod = SuitManifest.Read(file);
                if (Catalogue.Any(m => m.Id == mod.Id)) throw new InvalidDataException("duplicate suit id");
                if (Catalogue.Count >= MaxCount - StockCount) throw new InvalidDataException($"suit selector is full ({MaxCount - StockCount} mod entries)");
                Catalogue.Add(mod);
                Console.WriteLine($"[suit-mod] registered {mod.Id}: {mod.Name}; model {mod.Model}; SM1 profile {SuitManifest.Profiles[mod.AbilityProfile]}; {mod.Textures.Count} external PNGs; always unlocked");
            }
            catch (Exception e) { Console.Error.WriteLine($"[suit-mod] rejected {file}: {e.Message}"); }
        }
        string state = Path.Combine(_root, "selected-suit.txt");
        try
        {
            if (File.Exists(state) && new FileInfo(state).Length <= 128 &&
                (File.GetAttributes(state) & FileAttributes.ReparsePoint) == 0)
            {
                string id = File.ReadAllText(state).Trim();
                int i = Catalogue.FindIndex(m => m.Id == id);
                if (i >= 0) Select(StockCount + i, persist: false);
            }
        }
        catch (Exception e) { Console.Error.WriteLine($"[suit-mod] selection restore: {e.Message}"); }
        TextureResolver.ActorMaterials = Resolve;
    }

    public static bool Select(int index, bool persist = true)
    {
        int next = IsMod(index) ? index : -1;
        if (next == Active) return true;
        Dictionary<uint, ReplacementTexture> loaded = new();
        if (next >= 0)
        {
            try { loaded = At(next).Decode(); }
            catch (Exception e)
            {
                Console.Error.WriteLine($"[suit-mod] activation rejected {At(next).Id}: {e.Message}; using stock Spider-Man");
                Select(0, persist);
                return false;
            }
        }
        foreach (var texture in _textures.Values) texture.Retired = true;
        _textures = loaded;
        Active = next;
        _reported.Clear();
        Console.WriteLine(next < 0 ? "[suit-mod] stock materials restored" :
            $"[suit-mod] active {At(next).Id}: {_textures.Values.Sum(t => (long)t.Rgba.Length)} host RGBA bytes; no guest texture upload");
        if (persist && Directory.Exists(_root))
        {
            try
            {
                string state = Path.Combine(_root, "selected-suit.txt");
                string temporary = state + "." + Guid.NewGuid().ToString("N") + ".tmp";
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write))
                using (var writer = new StreamWriter(stream)) writer.Write(next < 0 ? "" : At(next).Id);
                File.Move(temporary, state, overwrite: true);
            }
            catch (Exception e) { Console.Error.WriteLine($"[suit-mod] could not save selection: {e.Message}"); }
        }
        return true;
    }

    public static void Observe(IMemory memory) => _memory = memory;
    static bool Ram(uint p, uint size) => p >= 0x80000000 && p <= 0x80800000 - size;

    static ResolvedTexture Resolve(TileRect tile)
    {
        // The loader, not the JSON, owns all addresses. Resolve from the currently cached
        // player on each draw so scene transitions cannot leave stale VRAM bindings.
        if (Active < 0 || _memory == null || Costume.LoadedCostume != Active) return default;
        IMemory m = _memory;
        uint entry = 0;
        for (uint i = 0; i < 40; i++)
        {
            uint p = 0x800A0904 + i * 64;
            if (m.ReadU32(p) == 0x64697073 && m.ReadU16(p + 4) == 0x7965 && m.ReadU8(p + 6) == 0)
            { entry = p; break; }
        }
        if (entry == 0) return default;
        uint model = m.ReadU32(entry + 0x14);
        if (!Ram(model, 16)) return default;
        uint objects = m.ReadU32(model + 8);
        if (objects > 1024 || !Ram(model, 16 + objects * 36)) return default;
        uint meshes = m.ReadU32(model + 12 + objects * 36);
        uint metadata = m.ReadU32(entry + 12);
        if (meshes > 4096 || !Ram(metadata, meshes * 4 + 4)) return default;
        uint start = metadata + meshes * 4;
        uint count = m.ReadU32(start);
        if (count > 4096 || !Ram(start, 4 + count * 4)) return default;
        if (Trace && count > 0)
        {
            uint first = m.ReadU32(start + 4);
            if (Ram(first, 32))
            {
                ulong signature = ((ulong)m.ReadU32(first) << 32) | m.ReadU32(first + 4);
                if (signature != _layoutSignature)
                {
                    _layoutSignature = signature;
                    for (uint j = 0; j < count; j++)
                    {
                        uint d = m.ReadU32(start + 4 + j * 4);
                        if (Ram(d, 32)) Console.WriteLine($"[suit-mod-layout] {m.ReadU32(d+20):X8} page={m.ReadU16(d+6):X4} clut={m.ReadU16(d+2):X4} uv={m.ReadU8(d)},{m.ReadU8(d+1)}..{m.ReadU8(d+4)},{m.ReadU8(d+9)}");
                    }
                }
            }
        }
        string candidates = "";
        for (uint i = 0; i < count; i++)
        {
            uint p = m.ReadU32(start + 4 + i * 4);
            if (!Ram(p, 32) || !_textures.TryGetValue(m.ReadU32(p + 20), out var texture)) continue;
            int u = m.ReadU8(p), v = m.ReadU8(p + 1);
            int w = ((m.ReadU8(p + 4) - u) & 255) + 1;
            int h = ((m.ReadU8(p + 9) - v) & 255) + 1;
            var rect = TextureTile.Describe(m.ReadU16(p + 6), m.ReadU16(p + 2), u, v, w, h);
            if (Trace && tile.ClutX == rect.ClutX && tile.ClutY == rect.ClutY && tile.PageY == rect.PageY &&
                (tile.PageX != rect.PageX || tile.U0 < u || tile.V0 < v || tile.U0 + tile.W > u+w+1 || tile.V0+tile.H > v+h+1))
            {
                string detail = $"{m.ReadU32(p+20):X8} tile page {tile.PageX},{tile.PageY} uv {tile.U0},{tile.V0} {tile.W}x{tile.H}; material page {rect.PageX},{rect.PageY} uv {u},{v} {w}x{h}";
                candidates += detail + "; ";
            }
            if (tile.PageX != rect.PageX || tile.PageY != rect.PageY || tile.Bpp != rect.Bpp ||
                tile.ClutX != rect.ClutX || tile.ClutY != rect.ClutY ||
                tile.U0 < u || tile.V0 < v || tile.U0 >= u + w || tile.V0 >= v + h ||
                tile.U0 + tile.W > u + w + 1 || tile.V0 + tile.H > v + h + 1)
                continue;
            uint id = m.ReadU32(p + 20);
            if (_reported.Add(id)) Console.WriteLine($"[suit-mod] material {id:X8}: {w}x{h} -> {texture.Width}x{texture.Height} host PNG");
            return new ResolvedTexture { Texture = texture, Rect = rect, Hit = true };
        }
        if (Trace && candidates.Length != 0 && _misses.Count < 40 && _misses.Add(candidates))
            Console.WriteLine("[suit-mod-miss] " + candidates);
        return default;
    }
}
