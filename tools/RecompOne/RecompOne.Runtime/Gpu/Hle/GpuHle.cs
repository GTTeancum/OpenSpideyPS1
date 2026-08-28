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
    /// Largest primitive the GPU will accept, horizontally.
    ///
    /// Real hardware drops anything wider than 1023, and games lean on that. The catch
    /// in widescreen is that the GTE saturates a projected X to +/-1024, so a polygon
    /// running off the side of the screen arrives with a clamped vertex and a span of
    /// 2047 -- and gets dropped. At 4:3 that costs nothing, because what it would have
    /// covered is off screen anyway. Widen the view and those are exactly the polygons
    /// the new margins needed: the floor stops short and the background shows through.
    ///
    /// So the limit opens to the saturated span while a margin is in play, which admits
    /// those polygons and nothing wilder. At 4:3 the hardware rule is untouched.
    /// </summary>
    public static int MaxSpanX => WideAspect > 0f ? 2047 : 1023;



    public static int WideMargin(int w)
    {
        if (WideAspect <= 0f) return 0;
        float source = SourceAspect > 0f ? SourceAspect : BaseAspect;
        int wide = (int)MathF.Ceiling(w * WideAspect / source);
        return Math.Max(0, (wide - w + 1) / 2);
    }
}
