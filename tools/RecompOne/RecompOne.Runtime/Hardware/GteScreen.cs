using System.Collections.Generic;

namespace RecompOne.Runtime.Hardware;

/// <summary>
/// The screen coordinates the GTE produced during the current frame.
///
/// This exists to answer one question exactly: is a primitive part of the world, or part
/// of the HUD? A widescreen hack has to know, because the world is squeezed at the
/// projection and the HUD has to be squeezed to match by hand -- and squeezing the wrong
/// thing drags scenery out of place.
///
/// Every proxy for that question leaks. Shape leaks: a HUD panel projects to an
/// axis-aligned rectangle, and so does a building sign, and so does a strip of ground.
/// Screen position leaks: the HUD lives in the corners, and so does whatever the camera
/// happens to point at. Draw order leaks: it is an ordering table, not a sequence.
///
/// The real difference is upstream of all of them. World geometry reaches the GPU by way
/// of the GTE; the HUD is laid out on the CPU and never goes near it. So the coordinates
/// the GTE emitted are recorded as they are produced, and a primitive whose every vertex
/// is one of them came from the world. That is the distinction itself rather than a
/// symptom of it.
///
/// It relies on the game handing GTE output to the GPU unaltered, which this one does --
/// vertices arrive pinned at exactly 1023, the GTE's own saturation limit, which is only
/// possible if nothing clipped or subdivided them on the way.
/// </summary>
public static class GteScreen
{
    public readonly record struct VertexTag(float Depth, float ScreenX, float ScreenY,
        bool HasSubpixel)
    {
        public static VertexTag DepthOnly(float depth) => new(depth, 0f, 0f, false);
    }

    public static long TaggedStores, TaggedLoads, PacketReads;
    /// <summary>
    /// Always enabled: projection provenance now supplies camera-space depth to the
    /// shared renderer as well as distinguishing world geometry from HUD primitives.
    /// </summary>
    public static bool Tracking = true;

    // Four submitted-frame generations. These games build ordering tables ahead of the
    // buffer they display, and SM2 can service multiple vblanks before it swaps that
    // buffer. Rolling at every vblank discarded all projection points before their
    // primitives reached the GPU. Wide rolls this ring on actual PutDispEnv swaps; four
    // generations cover both double buffering and an ahead-built table without turning
    // this into an unbounded history. LibGpu rolls this ring on actual PutDispEnv swaps;
    // every vertex must still match.
    const int Generations = 4;
    static readonly HashSet<int>[] _sets =
        [new(8192), new(8192), new(8192), new(8192)];
    static readonly Dictionary<int, int>[] _depths =
        [new(8192), new(8192), new(8192), new(8192)];
    static int _cur;

    readonly record struct RamDepth(uint Value, ushort Z, float ScreenX, float ScreenY,
        bool HasSubpixel);
    static readonly Dictionary<uint, RamDepth> _ramDepths = new(32768);

    static int Key(int x, int y) => ((x & 0xFFFF) << 16) | (y & 0xFFFF);

    public static void StoreU32(Memory.IMemory memory, uint address, uint value, float z)
        => StoreU32(memory, address, value, VertexTag.DepthOnly(z));

    public static void StoreU32(Memory.IMemory memory, uint address, uint value, VertexTag tag)
    {
        memory.WriteU32(address, value);
        if (tag.Depth > 0f && memory is Memory.PSMemory ps)
            ps.TagGteVertex(address, value, tag);
    }

    public static void LoadU32(Context.CpuContext context, int cpuRegister,
        Memory.IMemory memory, uint address)
    {
        uint value = memory.ReadU32(address);
        VertexTag tag = memory is Memory.PSMemory ps &&
                        ps.TryGetGteVertex(address, value, out VertexTag found)
            ? found : default;
        if (tag.Depth > 0f) Interlocked.Increment(ref TaggedLoads);
        context.SetGteRead(cpuRegister, value, tag);
    }

    public static void LoadU16(Context.CpuContext context, int cpuRegister,
        Memory.IMemory memory, uint address, bool signed)
    {
        ushort raw = memory.ReadU16(address);
        uint value = signed ? (uint)(short)raw : raw;
        float depth = memory is Memory.PSMemory ps && ps.TryGetContainingGteDepth(address, out float z)
            ? z : 0f;
        if (depth > 0f) Interlocked.Increment(ref TaggedLoads);
        context.SetGteRead(cpuRegister, value, VertexTag.DepthOnly(depth));
    }

    public static void LoadU8(Context.CpuContext context, int cpuRegister,
        Memory.IMemory memory, uint address, bool signed)
    {
        byte raw = memory.ReadU8(address);
        uint value = signed ? (uint)(sbyte)raw : raw;
        float depth = memory is Memory.PSMemory ps && ps.TryGetContainingGteDepth(address, out float z)
            ? z : 0f;
        if (depth > 0f) Interlocked.Increment(ref TaggedLoads);
        context.SetGteRead(cpuRegister, value, VertexTag.DepthOnly(depth));
    }

    public static void Note(int x, int y, ushort z)
    {
        if (!Tracking) return;

        int key = Key(x, y);
        _sets[_cur].Add(key);

        // This is only the safety net for packets whose exact RAM provenance could not
        // be carried. Keep the most recent projection rather than disabling perspective
        // correction when two camera vertices quantise to the same pixel.
        if (z != 0) _depths[_cur][key] = z;
    }

    /// <summary>Tag a packet coordinate store with its exact source-register depth.</summary>
    public static void NoteRamWrite(uint physicalAddress, uint value, VertexTag tag)
    {
        if (tag.Depth > 0f)
        {
            _ramDepths[physicalAddress] = new RamDepth(value,
                (ushort)Math.Clamp(tag.Depth, 1f, ushort.MaxValue),
                tag.ScreenX, tag.ScreenY, tag.HasSubpixel);
            Interlocked.Increment(ref TaggedStores);
        }
    }

    public static void InvalidateRamWrite(uint physicalAddress) => _ramDepths.Remove(physicalAddress);

    /// <summary>Recover exact camera Z attached to this GPU packet word in RAM.</summary>
    public static bool TryGetRamDepth(uint physicalAddress, uint value, out float z)
    {
        if (_ramDepths.TryGetValue(physicalAddress, out var depth) &&
            depth.Value == value && depth.Z != 0)
        {
            Interlocked.Increment(ref PacketReads);
            z = depth.Z;
            return true;
        }
        z = 0f;
        return false;
    }

    public static bool TryGetRamVertex(uint physicalAddress, uint value, out VertexTag tag)
    {
        if (_ramDepths.TryGetValue(physicalAddress, out var stored) &&
            stored.Value == value && stored.Z != 0)
        {
            Interlocked.Increment(ref PacketReads);
            tag = new VertexTag(stored.Z, stored.ScreenX, stored.ScreenY,
                stored.HasSubpixel);
            return true;
        }
        tag = default;
        return false;
    }

    public static bool Has(int x, int y)
    {
        int k = Key(x, y);
        for (int i = 0; i < Generations; i++)
            if (_sets[i].Contains(k)) return true;
        return false;
    }

    /// <summary>
    /// Recover the camera-space Z that produced a submitted screen coordinate.
    /// Newest display-buffer generations win.
    /// </summary>
    public static bool TryGetDepth(int x, int y, out float z)
    {
        int key = Key(x, y);
        for (int age = 0; age < Generations; age++)
        {
            int generation = (_cur - age + Generations) % Generations;
            if (!_depths[generation].TryGetValue(key, out int depth)) continue;
            if (depth > 0)
            {
                z = depth;
                return true;
            }
        }
        z = 1f;
        return false;
    }

    /// <summary>
    /// Recover every vertex of one GPU primitive from one projection generation.
    /// Combining independently selected generations can make an otherwise ordinary
    /// triangle inherit three unrelated camera depths when screen coordinates are
    /// reused by later frames.
    /// </summary>
    public static bool TryGetPrimitiveDepths(
        ReadOnlySpan<int> xs, ReadOnlySpan<int> ys, Span<float> zs)
    {
        if (xs.Length != ys.Length || zs.Length < xs.Length) return false;

        for (int age = 0; age < Generations; age++)
        {
            int generation = (_cur - age + Generations) % Generations;
            bool complete = true;
            for (int i = 0; i < xs.Length; i++)
            {
                if (!_depths[generation].TryGetValue(Key(xs[i], ys[i]), out int depth))
                {
                    complete = false;
                    break;
                }
                if (depth <= 0) { complete = false; break; }
                zs[i] = depth;
            }

            if (complete) return true;
        }

        return false;
    }

    public static int Count
    {
        get
        {
            int count = 0;
            for (int i = 0; i < Generations; i++) count += _sets[i].Count;
            return count;
        }
    }

    /// <summary>A few of the recorded points, for checking the coordinate convention.</summary>
    public static string Sample(int n = 6)
    {
        var sb = new System.Text.StringBuilder();
        int i = 0;
        foreach (int k in _sets[_cur])
        {
            if (i++ >= n) break;
            sb.Append($"({(short)(k >> 16)},{(short)k}) ");
        }
        return sb.ToString();
    }

    /// <summary>
    /// Called once per actual display-buffer swap.
    /// </summary>
    public static void Roll()
    {
        _cur = (_cur + 1) % Generations;
        _sets[_cur].Clear();
        _depths[_cur].Clear();
    }
}
