namespace RecompOne.Runtime.Hle;

public static class GpuHle
{
    public static bool Active { get; set; }
    public static IGpuBackend? Backend { get; set; }

    public static float WideAspect { get; set; }
    public static float OutputAspect { get; set; } = 4f / 3f;

    public static float SourceAspect { get; set; } = 4f / 3f;
    public static int LastDisplayW { get; set; }
    public static int LastDisplayH { get; set; }
    public static float TargetAspect { get; set; } = 4f / 3f;
    public const float BaseAspect = 4f / 3f;

    /// <summary>
    /// Set by a title patch when its projection and HUD paths support a player-facing
    /// 4:3/16:9 switch. The generic runtime does not offer a fake stretch mode.
    /// </summary>
    public static bool WidescreenSupported { get; set; }
    public static bool WidescreenDefault { get; set; }

    /// <summary>Apply FXAA to the final host-resolution frame. Enabled by default.</summary>
    public static bool FxaaEnabled { get; set; } = true;

    /// <summary>
    /// Textured triangles drawn with complete recovered GTE depth versus triangles for
    /// which no complete camera-space depth exists (normally true screen-space art).
    /// </summary>
    public static long PerspectiveTriangles, NoDepthTextureTriangles;
    public static long WorldPerspectiveTriangles, WorldNoDepthTextureTriangles;
    public static long ScreenTextureTriangles;
    public static long WorldDepthFlatTriangles, WorldDepthVaryingTriangles;
    public static long WorldDepthExtremeTriangles, WorldSubpixelVertices, WorldVertices;
    static readonly bool TracePerspective =
        Environment.GetEnvironmentVariable("RECOMP_PERSPECTIVE_TRACE") == "1";

    internal static void NoteTextureTriangle(bool perspective, bool world)
    {
        if (world)
        {
            if (perspective) Interlocked.Increment(ref WorldPerspectiveTriangles);
            else Interlocked.Increment(ref WorldNoDepthTextureTriangles);
        }
        else Interlocked.Increment(ref ScreenTextureTriangles);

        long total;
        if (perspective) total = Interlocked.Increment(ref PerspectiveTriangles) +
                                 Volatile.Read(ref NoDepthTextureTriangles);
        else total = Interlocked.Increment(ref NoDepthTextureTriangles) +
                     Volatile.Read(ref PerspectiveTriangles);
        if (TracePerspective && (total & 0x3FFF) == 0)
            Console.WriteLine($"[perspective] corrected={Volatile.Read(ref PerspectiveTriangles)} " +
                              $"no-depth={Volatile.Read(ref NoDepthTextureTriangles)} " +
                              $"world={Volatile.Read(ref WorldPerspectiveTriangles)} " +
                              $"world-missing={Volatile.Read(ref WorldNoDepthTextureTriangles)} " +
                              $"screen={Volatile.Read(ref ScreenTextureTriangles)} " +
                              $"gte-stores={Volatile.Read(ref Hardware.GteScreen.TaggedStores)} " +
                              $"gte-loads={Volatile.Read(ref Hardware.GteScreen.TaggedLoads)} " +
                              $"packet-reads={Volatile.Read(ref Hardware.GteScreen.PacketReads)} " +
                              $"gp0-depth={Volatile.Read(ref Gpu.PacketWordsWithDepth)} " +
                              $"mixed-depth-prims={Volatile.Read(ref Gpu.MixedDepthPrimitives)} " +
                              $"depth-flat/varying/extreme=" +
                              $"{Volatile.Read(ref WorldDepthFlatTriangles)}/" +
                              $"{Volatile.Read(ref WorldDepthVaryingTriangles)}/" +
                              $"{Volatile.Read(ref WorldDepthExtremeTriangles)} " +
                              $"subpixel-verts={Volatile.Read(ref WorldSubpixelVertices)}/" +
                              $"{Volatile.Read(ref WorldVertices)} " +
                              $"oversize-accepted-x/y=" +
                              $"{Volatile.Read(ref Gpu.WideSpanAccepted)}/" +
                              $"{Volatile.Read(ref Gpu.TallSpanAccepted)} " +
                              $"world-depth-verts=" +
                              $"{Volatile.Read(ref Gpu.WorldDepthVertexCounts[0])}/" +
                              $"{Volatile.Read(ref Gpu.WorldDepthVertexCounts[1])}/" +
                              $"{Volatile.Read(ref Gpu.WorldDepthVertexCounts[2])}/" +
                              $"{Volatile.Read(ref Gpu.WorldDepthVertexCounts[3])}/" +
                              $"{Volatile.Read(ref Gpu.WorldDepthVertexCounts[4])}");
    }

    internal static void NoteWorldGeometry(float z0, float z1, float z2,
        bool subpixel0, bool subpixel1, bool subpixel2)
    {
        if (!TracePerspective) return;
        float lo = MathF.Min(z0, MathF.Min(z1, z2));
        float hi = MathF.Max(z0, MathF.Max(z1, z2));
        if (hi - lo < 0.5f) Interlocked.Increment(ref WorldDepthFlatTriangles);
        else Interlocked.Increment(ref WorldDepthVaryingTriangles);
        if (lo > 0f && hi / lo >= 8f)
            Interlocked.Increment(ref WorldDepthExtremeTriangles);
        Interlocked.Add(ref WorldSubpixelVertices,
            (subpixel0 ? 1 : 0) + (subpixel1 ? 1 : 0) + (subpixel2 ? 1 : 0));
        Interlocked.Add(ref WorldVertices, 3);
    }

    /// <summary>
    /// Complete untouched pixels in a widened view from nearby world coverage. This is
    /// deliberately opt-in per title: it is for authored scene meshes that end just
    /// outside their original 4:3 camera, not a generic image filter.
    /// </summary>
    public static bool WideBackgroundCompletion { get; set; }
    public static bool WideCoverageView { get; set; }

    /// <summary>
    /// True only while LibGpu submits the draw-environment background rectangle. The
    /// GPU command itself is indistinguishable from an ordinary flat rectangle later.
    /// </summary>
    public static bool SubmittingBackground { get; set; }

    /// <summary>
    /// Authored draw-environment clear before diagnostics replace it with magenta.
    /// Coverage completion uses this behind submitted transparent cut-outs, preserving
    /// the level's intended backdrop without mistaking a grate or window for a missing
    /// polygon.
    /// </summary>
    public static byte BackgroundR, BackgroundG, BackgroundB;

    /// <summary>
    /// Color actually submitted for the draw-environment clear. It differs from the
    /// authored background only while the magenta coverage diagnostic is active.
    /// </summary>
    public static byte DrawBackgroundR, DrawBackgroundG, DrawBackgroundB;

    public struct DispRect { public int X, Y, W, H; public long Stamp; public bool Valid; }

    static readonly DispRect[] _rects = new DispRect[2];
    static long _stamp;

    public static void NotifyDisplay(int x, int y, int w, int h)
    {
        if (w <= 0 || h <= 0) return;
        int slot = -1;
        for (int i = 0; i < _rects.Length; i++)
            if (_rects[i].Valid && _rects[i].X == x && _rects[i].Y == y) { slot = i; break; }
        if (slot < 0)
        {
            slot = 0;
            for (int i = 1; i < _rects.Length; i++)
                if (!_rects[i].Valid || _rects[i].Stamp < _rects[slot].Stamp) slot = i;
        }
        _rects[slot] = new DispRect { X = x, Y = y, W = w, H = h, Stamp = ++_stamp, Valid = true };
    }

    public static int RectCount => _rects.Length;

    public static DispRect GetRect(int i) => _rects[i];

    /// <summary>
    /// Largest primitive span the recompilation renderer will accept.
    ///
    /// Real hardware drops triangles wider than 1023 or taller than 511. Those limits
    /// protected a fixed-function rasteriser; preserving them in the recompilation was
    /// dropping otherwise valid GTE-saturated surfaces and directly exposing background
    /// clear pixels in widescreen scenes. Coordinates saturate to -1024..1023, so 2047
    /// admits the entire representable span without accepting anything out of range.
    /// </summary>
    public const int MaxSpanX = 2047;
    public const int MaxSpanY = 2047;

    /// <summary>
    /// Horizontal squeeze applied to projected X, as a fraction. 3/4 fits a 16:9 field
    /// of view into a 4:3 framebuffer, which is then presented at 16:9. Equal values
    /// mean no change. See Hardware.Gte.Rtp.
    /// </summary>
    public static int FovNum = 1, FovDen = 1;




    public static int WideMargin(int w)
    {
        if (WideAspect <= 0f) return 0;
        float source = SourceAspect > 0f ? SourceAspect : BaseAspect;
        int wide = (int)MathF.Ceiling(w * WideAspect / source);
        return Math.Max(0, (wide - w + 1) / 2);
    }
}
