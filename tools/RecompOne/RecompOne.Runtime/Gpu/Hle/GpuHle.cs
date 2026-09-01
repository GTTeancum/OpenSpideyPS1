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

    /// <summary>Apply FXAA to the final host-resolution frame. Enabled by default.</summary>
    public static bool FxaaEnabled { get; set; } = true;

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
