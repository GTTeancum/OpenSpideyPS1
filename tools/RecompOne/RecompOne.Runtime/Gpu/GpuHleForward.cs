using RecompOne.Runtime.Hle;

namespace RecompOne.Runtime;

public sealed partial class Gpu
{
    // Opt-in geometry-only inspection: remove texture cutouts from one CLUT's
    // triangles without changing vertex positions, culling or primitive ordering.
    static readonly int SolidGeometryClut = int.TryParse(Environment.GetEnvironmentVariable("RECOMP_SOLID_GEOMETRY_CLUT"), out var solidClut) ? solidClut : -1;
    static bool HleOn => GpuHle.Active && GpuHle.Backend is { Ready: true };

    int CurTPage() => ((_texPageX / 64) & 0xf) | (((_texPageY / 256) & 1) << 4)
                    | ((_blendMode & 3) << 5) | ((_texDepth & 3) << 7);

    HleDrawEnv CurEnv() => new()
    {
        ClipX0 = _drawAreaLeft, ClipY0 = _drawAreaTop, ClipX1 = _drawAreaRight, ClipY1 = _drawAreaBottom,
        TwMaskX = _texWinMaskX, TwMaskY = _texWinMaskY, TwOffX = _texWinOffX, TwOffY = _texWinOffY,
        SetMask = _setMask, CheckMask = _checkMask,
    };

    static HleVertex HV(in Vert v) => new()
    {
        // At 4x, retaining only the PS1 packet's integer SXY magnifies vertex snapping
        // into visible texture swim and cracks between adjacent polygons. The sidecar
        // reaches this point only when its rounded SXY was validated against the exact
        // packet word, so a derived or moved coordinate cannot reuse stale geometry.
        X = v.HasSubpixel ? v.RenderX : v.X,
        Y = v.HasSubpixel ? v.RenderY : v.Y,
        R = (byte)v.R, G = (byte)v.G, B = (byte)v.B, U = (short)v.U, V = (short)v.V,
        Z = v.Z, HasGteZ = v.HasGteZ,
    };

    PrimFlags PrimOf(bool tex, bool semi, bool raw, int clut, bool gouraud = false,
        bool world = false, bool hud = false, bool background = false,
        bool ignoreCoverage = false) => new()
    {
        Textured = tex, SemiTrans = semi, RawTexture = raw, Gouraud = gouraud,
        World = world, Hud = hud, Background = background,
        IgnoreCoverage = ignoreCoverage,
        TPage = (ushort)CurTPage(), Clut = (ushort)clut,
    };

    void HleTri(in Vert a, in Vert b, in Vert c, bool tex, bool gouraud, bool semi,
        bool raw, int clut, bool world, bool hud, bool background,
        bool ignoreCoverage)
    {
        int spanX = Math.Max(a.X, Math.Max(b.X, c.X)) - Math.Min(a.X, Math.Min(b.X, c.X));
        int spanY = Math.Max(a.Y, Math.Max(b.Y, c.Y)) - Math.Min(a.Y, Math.Min(b.Y, c.Y));
        if (RejectSpan(spanX, spanY)) return;

        if (tex && world)
            GpuHle.NoteWorldGeometry(a.Z, b.Z, c.Z,
                a.HasSubpixel, b.HasSubpixel, c.HasSubpixel);

        var be = GpuHle.Backend!;
        be.SetDrawEnv(CurEnv());
        if (tex) GpuHle.NoteTextureTriangle(a.HasGteZ && b.HasGteZ && c.HasGteZ, world);
        var flags = PrimOf(tex, semi, raw, clut, gouraud, world, hud, background, ignoreCoverage);
        GeometryTrace.Triangle(HV(a), HV(b), HV(c), CurEnv(), flags);
        if (world && tex && clut == SolidGeometryClut)
        {
            var va = HV(a); var vb = HV(b); var vc = HV(c);
            va.R = va.G = va.B = vb.R = vb.G = vb.B = vc.R = vc.G = vc.B = 255;
            flags.Textured = false; flags.Gouraud = false; flags.SemiTrans = false;
            be.DrawTri(va, vb, vc, flags);
            return;
        }
        be.DrawTri(HV(a), HV(b), HV(c), flags);
    }

    void HleRect(int x, int y, int w, int h, int u, int v, int clut, int r,
        int g, int b, bool tex, bool semi, bool raw, bool world, bool hud,
        bool background, bool ignoreCoverage)
    {
        var be = GpuHle.Backend!;
        be.SetDrawEnv(CurEnv());
        be.DrawRect(new HleRect { X = x, Y = y, W = w, H = h, U = (short)u, V = (short)v, R = (byte)r, G = (byte)g, B = (byte)b },
            PrimOf(tex, semi, raw, clut, world: world, hud: hud,
                background: background, ignoreCoverage: ignoreCoverage));
    }

    void HleLine(int x0, int y0, int r0, int g0, int b0, int x1, int y1, int r1, int g1, int b1, bool semi, bool gouraud)
    {
        if (RejectSpan(Math.Abs(x1 - x0), Math.Abs(y1 - y0))) return;

        var be = GpuHle.Backend!;
        be.SetDrawEnv(CurEnv());
        be.DrawLine(
            new HleVertex { X = x0, Y = y0, R = (byte)r0, G = (byte)g0, B = (byte)b0 },
            new HleVertex { X = x1, Y = y1, R = (byte)r1, G = (byte)g1, B = (byte)b1 },
            PrimOf(false, semi, false, 0, gouraud));
    }

    void HleFill(int x, int y, int w, int h, ushort color) => GpuHle.Backend!.FillRect(x, y, w, h, color);
    void HleCopy(int sx, int sy, int dx, int dy, int w, int h) => GpuHle.Backend!.CopyVram(sx, sy, dx, dy, w, h);

    ushort[] _readBuf = Array.Empty<ushort>();

    void HleReadback(int x, int y, int w, int h)
    {
        int n = w * h;
        if (_readBuf.Length < n) _readBuf = new ushort[n];
        GpuHle.Backend!.ReadVram(x, y, w, h, _readBuf);

        for (int row = 0; row < h; row++)
        {
            int dst = ((y + row) & (VramHeight - 1)) * VramWidth;
            for (int col = 0; col < w; col++)
                Vram[dst + ((x + col) & (VramWidth - 1))] = _readBuf[row * w + col];
        }
        Assets.Textures.VramTracker.MarkCpuWrite(x, y, w, h);
    }

    //img load
    ushort[] _hleLoad = Array.Empty<ushort>();
    bool _hleLoadActive;
    int _hleLoadPos;

    void HleLoadBegin()
    {
        _hleLoadActive = HleOn;
        if (!_hleLoadActive) return;
        int n = _loadW * _loadH;
        if (_hleLoad.Length < n) _hleLoad = new ushort[n];
        _hleLoadPos = 0;
    }

    void HleLoadPut(ushort value)
    {
        if (_hleLoadActive && _hleLoadPos < _hleLoad.Length) _hleLoad[_hleLoadPos++] = value;
    }

    void HleLoadFlush()
    {
        if (!_hleLoadActive) return;
        GpuHle.Backend!.WriteVram(_loadX, _loadY, _loadW, _loadH, _hleLoad.AsSpan(0, _loadW * _loadH));
        _hleLoadActive = false;
    }
}
