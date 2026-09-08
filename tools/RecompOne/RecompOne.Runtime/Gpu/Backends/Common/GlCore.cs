using System.Runtime.InteropServices;
using Silk.NET.OpenGL;

namespace RecompOne.Runtime.Hle;

public sealed class GlCore : IGpuBackend
{
    [StructLayout(LayoutKind.Sequential)]
    struct GlVertex
    {
        public float X, Y;
        public float R, G, B;
        public float Clut, Texpage;
        public float U, V;
        public float World, Hud;
        public float PerspectiveW;
    }

    const int MaxVerts = 0x40000;

    readonly GL _gl;
    readonly IGlVram _vram;
    readonly List<uint> _images = [];
    readonly GlDisplayRt?[] _rts = new GlDisplayRt?[2];
    long _rtStamp;
    long _frame;
    static readonly bool AuditComposite = Environment.GetEnvironmentVariable("RECOMP_AUDIT_COMPOSITE") == "1";
    long _lastCompositeAudit = -1;

    uint _vao, _vbo, _presentVao, _presentVbo, _progPrim, _progPresent, _progPresent24;
    bool _drewSincePresent;
    uint _presentFbo, _presentTex;
    int _presentW, _presentH;
    bool _presentNearest;
    uint _finalFbo;
    int _finalW, _finalH;
    uint _preFxaaFbo;
    int _preFxaaW, _preFxaaH;

    uint _postProg, _postFbo, _postTex;
    int _postW, _postH, _postVersion = -1;
    int _uPostTexSize, _uPostOutputSize, _uPostTime, _uPostFrame;
    int _postFrame, _postParamVersion = -1;
    (string Name, float Value)[] _postParams = [];
    int[] _postParamLoc = [];
    readonly System.Diagnostics.Stopwatch _postClock = System.Diagnostics.Stopwatch.StartNew();

    uint _fxaaProg, _fxaaFbo, _fxaaTex;
    int _fxaaW, _fxaaH, _uFxaaTexSize;

    uint _coverageProg, _worldCopyProg;
    int _uCoveragePosBias, _uCoverageFbInv, _uCoverageTexWindow;
    int _uCoverageRepRect, _uCoverageRepClutCount;
    int _uWorldCopyPosBias, _uWorldCopyFbInv, _uWorldCopySize;
    uint _wideCompleteProg, _wideCompleteFbo, _wideCompleteTex;
    int _wideCompleteW, _wideCompleteH;
    int _uWideCompleteTexSize, _uWideCompleteBaseFraction, _uWideCompleteDebug,
        _uWideCompleteClearColor, _uWideCompleteDrawClearColor,
        _uWideCompleteDiagnosticClear;

    readonly GlVertex[] _verts = new GlVertex[MaxVerts];
    int _count;
    float _drawMinX, _drawMinY, _drawMaxX, _drawMaxY;

    HleDrawEnv _env;

    GlDisplayRt? _kTarget;
    bool _kTransparent;
    int _kImage = -1;
    int _kBlend, _kSetMask, _kCheckMask, _kBackground, _kIgnoreCoverage;
    byte _kClearR, _kClearG, _kClearB, _kDrawClearR, _kDrawClearG, _kDrawClearB;
    int _kTwAndX, _kTwAndY, _kTwOrX, _kTwOrY;
    int _kClipX0, _kClipY0, _kClipX1, _kClipY1;
    uint _kRepTex, _kRepClut;
    float _kRepX, _kRepY, _kRepW, _kRepH;
    int _kRepClutCount;
    int _uTexWindow, _uBlend, _uBlendOpaque, _uSetMask, _uCheckMask, _uPosBias, _uFbInv;
    int _uRepRect, _uRepClutCount;
    int _uPresentOrigin, _uPresentSize, _uPresentTexSize, _uPresent24Origin, _uPresent24Size;

    public bool Ready { get; private set; }

    readonly bool _legacy;
    int _uVramSize, _uDestSize, _uSemiTrans, _uBlendMode;

    public GlCore(GL gl, IGlVram vram, bool legacy = false)
    {
        _gl = gl;
        _vram = vram;
        _legacy = legacy;
    }

    public unsafe void InitGl()
    {
        _vram.Init();
        bool ditherWasEnabled = _gl.IsEnabled(EnableCap.Dither);
        _gl.Disable(EnableCap.Dither);
        Console.WriteLine($"[Gpu] dithering: before={ditherWasEnabled} after={_gl.IsEnabled(EnableCap.Dither)}");

        string primVs = _legacy ? GlShaders.PrimVs120 : GlShaders.PrimVs;
        string primFs = _legacy ? GlShaders.PrimFs120 : GlShaders.PrimFs;
        string fullVs = _legacy ? GlShaders.FullscreenVs120 : GlShaders.FullscreenVs;
        string presentFs = _legacy ? GlShaders.PresentFs120 : GlShaders.PresentFs;
        string present24Fs = _legacy ? GlShaders.Present24Fs120 : GlShaders.Present24Fs;
        string fxaaFs = _legacy ? GlShaders.FxaaFs120 : GlShaders.FxaaFs;
        string coverageVs = _legacy ? GlShaders.CoverageVs120 : GlShaders.CoverageVs;
        string coverageFs = _legacy ? GlShaders.CoverageFs120 : GlShaders.CoverageFs;
        string worldCopyFs = _legacy ? GlShaders.WorldCopyFs120 : GlShaders.WorldCopyFs;
        string wideCompleteFs = _legacy ? GlShaders.WideCompleteFs120 : GlShaders.WideCompleteFs;

        _progPrim = GlShaders.BuildPrim(_gl, primVs, primFs, "prim");
        _progPresent = GlShaders.BuildFullscreen(_gl, fullVs, presentFs, "present");
        _progPresent24 = GlShaders.BuildFullscreen(_gl, fullVs, present24Fs, "present24");
        _fxaaProg = GlShaders.BuildFullscreen(_gl, fullVs, fxaaFs, "fxaa");
        _coverageProg = GlShaders.BuildPrim(_gl, coverageVs, coverageFs, "coverage");
        _worldCopyProg = GlShaders.BuildPrim(_gl, coverageVs, worldCopyFs, "world-copy");
        _wideCompleteProg = GlShaders.BuildFullscreen(_gl, fullVs, wideCompleteFs, "wide-complete");
        if (_progPrim == 0 || _progPresent == 0 || _progPresent24 == 0 || _fxaaProg == 0) return;
        if (_coverageProg == 0 || _worldCopyProg == 0 || _wideCompleteProg == 0)
        {
            GpuHle.WideBackgroundCompletion = false;
            Console.WriteLine("[wide] coverage completion unavailable; raw widened view retained");
        }

        _uVramSize = _gl.GetUniformLocation(_progPrim, "uVramSize");
        _uDestSize = _gl.GetUniformLocation(_progPrim, "uDestSize");
        _uSemiTrans = _gl.GetUniformLocation(_progPrim, "uSemiTrans");
        _uBlendMode = _gl.GetUniformLocation(_progPrim, "uBlendMode");

        _uTexWindow = _gl.GetUniformLocation(_progPrim, "uTexWindow");
        _uBlend = _gl.GetUniformLocation(_progPrim, "uBlend");
        _uBlendOpaque = _gl.GetUniformLocation(_progPrim, "uBlendOpaque");
        _uSetMask = _gl.GetUniformLocation(_progPrim, "uSetMask");
        _uCheckMask = _gl.GetUniformLocation(_progPrim, "uCheckMask");
        _uPosBias = _gl.GetUniformLocation(_progPrim, "uPosBias");
        _uFbInv = _gl.GetUniformLocation(_progPrim, "uFbInv");
        _uRepRect = _gl.GetUniformLocation(_progPrim, "uRepRect");
        _uRepClutCount = _gl.GetUniformLocation(_progPrim, "uRepClutCount");

        _gl.UseProgram(_progPrim);
        _gl.Uniform1(_gl.GetUniformLocation(_progPrim, "uVram"), 0);
        _gl.Uniform1(_gl.GetUniformLocation(_progPrim, "uDest"), 1);
        _gl.Uniform1(_gl.GetUniformLocation(_progPrim, "uExtTex"), 2);
        _gl.Uniform1(_gl.GetUniformLocation(_progPrim, "uRepTex"), 3);
        _gl.Uniform1(_gl.GetUniformLocation(_progPrim, "uRepClut"), 4);
        SetScaleUniform(_progPrim);
        if (_uVramSize >= 0) _gl.Uniform2(_uVramSize, (float)GlVram.Width, GlVram.Height);

        _uPresentOrigin = _gl.GetUniformLocation(_progPresent, "uOrigin");
        _uPresentSize = _gl.GetUniformLocation(_progPresent, "uSize");
        _uPresentTexSize = _gl.GetUniformLocation(_progPresent, "uTexSize");
        _gl.UseProgram(_progPresent);
        _gl.Uniform1(_gl.GetUniformLocation(_progPresent, "uVram"), 0);

        _uPresent24Origin = _gl.GetUniformLocation(_progPresent24, "uOrigin");
        _uPresent24Size = _gl.GetUniformLocation(_progPresent24, "uSize");
        _gl.UseProgram(_progPresent24);
        _gl.Uniform1(_gl.GetUniformLocation(_progPresent24, "uVram"), 0);
        SetScaleUniform(_progPresent24);
        int uVramSize24 = _gl.GetUniformLocation(_progPresent24, "uVramSize");
        if (uVramSize24 >= 0) _gl.Uniform2(uVramSize24, (float)GlVram.Width, GlVram.Height);

        _gl.UseProgram(_fxaaProg);
        _gl.Uniform1(_gl.GetUniformLocation(_fxaaProg, "uTex"), 0);
        _uFxaaTexSize = _gl.GetUniformLocation(_fxaaProg, "uTexSize");

        if (_coverageProg != 0)
        {
            _uCoveragePosBias = _gl.GetUniformLocation(_coverageProg, "uPosBias");
            _uCoverageFbInv = _gl.GetUniformLocation(_coverageProg, "uFbInv");
            _uCoverageTexWindow = _gl.GetUniformLocation(_coverageProg, "uTexWindow");
            _uCoverageRepRect = _gl.GetUniformLocation(_coverageProg, "uRepRect");
            _uCoverageRepClutCount = _gl.GetUniformLocation(_coverageProg, "uRepClutCount");
            _gl.UseProgram(_coverageProg);
            _gl.Uniform1(_gl.GetUniformLocation(_coverageProg, "uVram"), 0);
            _gl.Uniform1(_gl.GetUniformLocation(_coverageProg, "uExtTex"), 2);
            _gl.Uniform1(_gl.GetUniformLocation(_coverageProg, "uRepTex"), 3);
            _gl.Uniform1(_gl.GetUniformLocation(_coverageProg, "uRepClut"), 4);
            SetScaleUniform(_coverageProg);
            int uCoverageVramSize = _gl.GetUniformLocation(_coverageProg, "uVramSize");
            if (uCoverageVramSize >= 0)
                _gl.Uniform2(uCoverageVramSize, (float)GlVram.Width, GlVram.Height);
        }
        if (_worldCopyProg != 0)
        {
            _uWorldCopyPosBias = _gl.GetUniformLocation(_worldCopyProg, "uPosBias");
            _uWorldCopyFbInv = _gl.GetUniformLocation(_worldCopyProg, "uFbInv");
            _uWorldCopySize = _gl.GetUniformLocation(_worldCopyProg, "uRenderedSize");
            _gl.UseProgram(_worldCopyProg);
            _gl.Uniform1(_gl.GetUniformLocation(_worldCopyProg, "uRendered"), 5);
        }
        if (_wideCompleteProg != 0)
        {
            _gl.UseProgram(_wideCompleteProg);
            _gl.Uniform1(_gl.GetUniformLocation(_wideCompleteProg, "uTex"), 0);
            _gl.Uniform1(_gl.GetUniformLocation(_wideCompleteProg, "uCoverage"), 1);
            _gl.Uniform1(_gl.GetUniformLocation(_wideCompleteProg, "uWorld"), 2);
            _uWideCompleteTexSize = _gl.GetUniformLocation(_wideCompleteProg, "uTexSize");
            _uWideCompleteBaseFraction = _gl.GetUniformLocation(_wideCompleteProg, "uBaseFraction");
            _uWideCompleteDebug = _gl.GetUniformLocation(_wideCompleteProg, "uDebugCoverage");
            _uWideCompleteClearColor = _gl.GetUniformLocation(_wideCompleteProg, "uClearColor");
            _uWideCompleteDrawClearColor = _gl.GetUniformLocation(_wideCompleteProg, "uDrawClear");
            _uWideCompleteDiagnosticClear = _gl.GetUniformLocation(_wideCompleteProg, "uDiagnosticClear");
        }

        _vao = _gl.GenVertexArray();
        _vbo = _gl.GenBuffer();
        _gl.BindVertexArray(_vao);
        _gl.BindBuffer(BufferTargetARB.ArrayBuffer, _vbo);
        _gl.BufferData(BufferTargetARB.ArrayBuffer, (nuint)(MaxVerts * sizeof(GlVertex)), null, BufferUsageARB.DynamicDraw);
        uint stride = (uint)sizeof(GlVertex);
        _gl.EnableVertexAttribArray(0); _gl.VertexAttribPointer(0, 2, VertexAttribPointerType.Float, false, stride, (void*)0);
        _gl.EnableVertexAttribArray(1); _gl.VertexAttribPointer(1, 3, VertexAttribPointerType.Float, false, stride, (void*)8);
        _gl.EnableVertexAttribArray(2); _gl.VertexAttribPointer(2, 1, VertexAttribPointerType.Float, false, stride, (void*)20);
        _gl.EnableVertexAttribArray(3); _gl.VertexAttribPointer(3, 1, VertexAttribPointerType.Float, false, stride, (void*)24);
        _gl.EnableVertexAttribArray(4); _gl.VertexAttribPointer(4, 2, VertexAttribPointerType.Float, false, stride, (void*)28);
        _gl.EnableVertexAttribArray(5); _gl.VertexAttribPointer(5, 1, VertexAttribPointerType.Float, false, stride, (void*)36);
        _gl.EnableVertexAttribArray(6); _gl.VertexAttribPointer(6, 1, VertexAttribPointerType.Float, false, stride, (void*)40);
        _gl.EnableVertexAttribArray(7); _gl.VertexAttribPointer(7, 1, VertexAttribPointerType.Float, false, stride, (void*)44);

        // fullscreen quad for present, real vbo since gl_VertexID without arrays does not draw on mesa for some reason?? or i did it wrong?
        _presentVao = _gl.GenVertexArray();
        _presentVbo = _gl.GenBuffer();
        _gl.BindVertexArray(_presentVao);
        _gl.BindBuffer(BufferTargetARB.ArrayBuffer, _presentVbo);
        float[] quad = { -1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f };
        fixed (float* qp = quad)
            _gl.BufferData(BufferTargetARB.ArrayBuffer, (nuint)(quad.Length * sizeof(float)), qp, BufferUsageARB.StaticDraw);
        _gl.EnableVertexAttribArray(0);
        _gl.VertexAttribPointer(0, 2, VertexAttribPointerType.Float, false, 2 * sizeof(float), (void*)0);
        _gl.BindBuffer(BufferTargetARB.ArrayBuffer, 0);

        _presentTex = _gl.GenTexture();
        _gl.BindTexture(TextureTarget.Texture2D, _presentTex);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.LinearMipmapLinear);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Linear);
        _presentFbo = _gl.GenFramebuffer();
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _presentFbo);
        _gl.FramebufferTexture2D(FramebufferTarget.Framebuffer, FramebufferAttachment.ColorAttachment0, TextureTarget.Texture2D, _presentTex, 0);
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, 0);

        _kClipX1 = 1023; _kClipY1 = 511;
        Ready = true;
    }

    public void SetDrawEnv(in HleDrawEnv env) => _env = env;

    const int FbSlackW = 64;
    const int FbSlackH = 32;

    GlDisplayRt? Classify()
    {
        int clipX = _env.ClipX0, clipY = _env.ClipY0;
        int clipW = _env.ClipX1 - _env.ClipX0 + 1, clipH = _env.ClipY1 - _env.ClipY0 + 1;
        if (clipW <= 0 || clipH <= 0) return null;

        long bestStamp = -1;
        int fbX = 0, fbY = 0, fbW = 0, fbH = 0;
        for (int i = 0; i < GpuHle.RectCount; i++)
        {
            var r = GpuHle.GetRect(i);
            if (!r.Valid || r.W <= 0 || r.H <= 0 || r.Stamp <= bestStamp) continue;

            bool clipInside = clipX >= r.X && clipX + clipW <= r.X + r.W &&
                              clipY >= r.Y && clipY + clipH <= r.Y + r.H;
            bool clipIsFb = clipX <= r.X && clipX + clipW >= r.X + r.W &&
                            clipY <= r.Y && clipY + clipH >= r.Y + r.H &&
                            clipW - r.W <= FbSlackW && clipH - r.H <= FbSlackH;
            if (clipInside) { bestStamp = r.Stamp; fbX = r.X; fbY = r.Y; fbW = r.W; fbH = r.H; }
            else if (clipIsFb) { bestStamp = r.Stamp; fbX = clipX; fbY = clipY; fbW = clipW; fbH = clipH; }
        }
        if (Log.GpuOn && (_frame % 120) == 0)
        {
            var sb = new System.Text.StringBuilder();
            sb.Append($"classify clip=({clipX},{clipY}) {clipW}x{clipH} -> ");
            if (bestStamp < 0) sb.Append("NO MATCH; rects:");
            else sb.Append($"fb=({fbX},{fbY}) {fbW}x{fbH}; rects:");
            for (int i = 0; i < GpuHle.RectCount; i++)
            {
                var r = GpuHle.GetRect(i);
                sb.Append(r.Valid ? $" [{r.X},{r.Y} {r.W}x{r.H}]" : " [invalid]");
            }
            Log.Gpu(sb.ToString());
        }
        return bestStamp < 0 ? null : GetOrCreateRt(fbX, fbY, fbW, fbH);
    }

    GlDisplayRt GetOrCreateRt(int fbX, int fbY, int fbW, int fbH)
    {
        int slot = -1;
        for (int i = 0; i < _rts.Length; i++)
            if (_rts[i] is { } rt && rt.X == fbX && rt.Y == fbY)
            {
                bool sameW = rt.W == fbW;
                bool fitsH = rt.H >= fbH && rt.H - fbH <= FbSlackH;
                if (sameW && fitsH && rt.Margin == GpuHle.WideMargin(rt.W))
                {
                    rt.Stamp = ++_rtStamp;
                    return rt;
                }
                slot = i;
                break;
            }

        if (slot < 0)
        {
            slot = 0;
            for (int i = 1; i < _rts.Length; i++)
            {
                if (_rts[i] == null) { slot = i; break; }
                if (_rts[slot] != null && _rts[i]!.Stamp < _rts[slot]!.Stamp) slot = i;
            }
        }

        if (_rts[slot] is { } old)
        {
            if (old.Dirty) Writeback(old);
            old.Destroy(_gl);
        }

        var fresh = new GlDisplayRt { X = fbX, Y = fbY, W = fbW, H = fbH, Margin = GpuHle.WideMargin(fbW), Stamp = ++_rtStamp, LastDrawFrame = _frame };
        fresh.Create(_gl, GpuHle.WideBackgroundCompletion && _coverageProg != 0);
        _rts[slot] = fresh;
        SyncRtFromVram(fresh, fbX, fbY, fbW, fbH);
        return fresh;
    }

    void Writeback(GlDisplayRt rt)
    {
        int s = GlVram.Scale;
        _gl.Disable(EnableCap.ScissorTest);
        _gl.BindFramebuffer(FramebufferTarget.ReadFramebuffer, rt.Fbo);
        _gl.BindFramebuffer(FramebufferTarget.DrawFramebuffer, _vram.Fbo);
        _gl.BlitFramebuffer(rt.Margin * s, 0, (rt.Margin + rt.W) * s, rt.H * s,
            rt.X * s, rt.Y * s, (rt.X + rt.W) * s, (rt.Y + rt.H) * s,
            ClearBufferMask.ColorBufferBit, BlitFramebufferFilter.Nearest);
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, 0);
        rt.Dirty = false;
        Assets.Textures.VramTracker.MarkGpuWrite(rt.X, rt.Y, rt.W, rt.H);
    }

    void SyncRtFromVram(GlDisplayRt rt, int rx, int ry, int rw, int rh)
    {
        int x0 = Math.Max(rx, rt.X), y0 = Math.Max(ry, rt.Y);
        int x1 = Math.Min(rx + rw, rt.X + rt.W), y1 = Math.Min(ry + rh, rt.Y + rt.H);
        if (x0 >= x1 || y0 >= y1) return;
        int s = GlVram.Scale;
        _gl.Disable(EnableCap.ScissorTest);
        _gl.BindFramebuffer(FramebufferTarget.ReadFramebuffer, _vram.Fbo);
        _gl.BindFramebuffer(FramebufferTarget.DrawFramebuffer, rt.Fbo);
        _gl.BlitFramebuffer(x0 * s, y0 * s, x1 * s, y1 * s,
            (x0 - rt.X + rt.Margin) * s, (y0 - rt.Y) * s, (x1 - rt.X + rt.Margin) * s, (y1 - rt.Y) * s,
            ClearBufferMask.ColorBufferBit, BlitFramebufferFilter.Nearest);
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, 0);
    }

    void WritebackDirtyIntersecting(int x, int y, int w, int h)
    {
        foreach (var rt in _rts)
            if (rt is { Dirty: true } && rt.Intersects(x, y, w, h)) Writeback(rt);
    }

    void SyncRtsFromVram(int x, int y, int w, int h)
    {
        foreach (var rt in _rts)
            if (rt != null && rt.Intersects(x, y, w, h)) SyncRtFromVram(rt, x, y, w, h);
    }

    void CheckTextureFeedback(in PrimFlags f)
    {
        if (!f.Textured || f.UseImage) return;
        int px = (f.TPage & 0xF) * 64;
        int py = ((f.TPage >> 4) & 1) * 256;
        int depth = (f.TPage >> 7) & 3;
        int pw = depth == 0 ? 64 : depth == 1 ? 128 : 256;
        foreach (var rt in _rts)
            if (rt is { Dirty: true } && rt.Intersects(px, py, pw, 256))
            {
                Flush();
                Writeback(rt);
            }
    }

    bool DesiredMatches(bool transparent, int blend, int image, bool background,
        bool ignoreCoverage)
    {
        int twAndX = ~(_env.TwMaskX * 8) & 0xFF, twAndY = ~(_env.TwMaskY * 8) & 0xFF;
        int twOrX = (_env.TwOffX & _env.TwMaskX) * 8, twOrY = (_env.TwOffY & _env.TwMaskY) * 8;
        return _kRepTex == _pendingRepTex && _kRepClut == _pendingRepClut
            && (_pendingRepTex == 0 || (_kRepX == _pendingRepX && _kRepY == _pendingRepY
                                        && _kRepW == _pendingRepW && _kRepH == _pendingRepH))
            && _kTransparent == transparent && _kBlend == blend && _kImage == image
            && _kBackground == (background ? 1 : 0)
            && (!background ||
                (_kClearR == GpuHle.BackgroundR && _kClearG == GpuHle.BackgroundG &&
                 _kClearB == GpuHle.BackgroundB &&
                 _kDrawClearR == GpuHle.DrawBackgroundR &&
                 _kDrawClearG == GpuHle.DrawBackgroundG &&
                 _kDrawClearB == GpuHle.DrawBackgroundB))
            && _kIgnoreCoverage == (ignoreCoverage ? 1 : 0)
            && _kSetMask == (_env.SetMask ? 1 : 0) && _kCheckMask == (_env.CheckMask ? 1 : 0)
            && _kTwAndX == twAndX && _kTwAndY == twAndY && _kTwOrX == twOrX && _kTwOrY == twOrY
            && _kClipX0 == _env.ClipX0 && _kClipY0 == _env.ClipY0 && _kClipX1 == _env.ClipX1 && _kClipY1 == _env.ClipY1;
    }

    void Begin(in PrimFlags f, int vertsNeeded)
    {
        bool transparent = f.SemiTrans;
        int blend = f.BlendMode;
        int image = f.UseImage ? f.Image : -1;
        var target = Classify();
        if (_count > 0 && (target != _kTarget ||
            !DesiredMatches(transparent, blend, image, f.Background,
                f.IgnoreCoverage))) Flush();
        if (_count + vertsNeeded > MaxVerts) Flush();
        CheckTextureFeedback(f);

        _kTarget = target;
        _kImage = image;
        _kBackground = f.Background ? 1 : 0;
        if (f.Background)
        {
            _kClearR = GpuHle.BackgroundR;
            _kClearG = GpuHle.BackgroundG;
            _kClearB = GpuHle.BackgroundB;
            _kDrawClearR = GpuHle.DrawBackgroundR;
            _kDrawClearG = GpuHle.DrawBackgroundG;
            _kDrawClearB = GpuHle.DrawBackgroundB;
        }
        _kIgnoreCoverage = f.IgnoreCoverage ? 1 : 0;
        _kTransparent = transparent; _kBlend = blend;
        _kSetMask = _env.SetMask ? 1 : 0; _kCheckMask = _env.CheckMask ? 1 : 0;
        _kTwAndX = ~(_env.TwMaskX * 8) & 0xFF; _kTwAndY = ~(_env.TwMaskY * 8) & 0xFF;
        _kTwOrX = (_env.TwOffX & _env.TwMaskX) * 8; _kTwOrY = (_env.TwOffY & _env.TwMaskY) * 8;
        _kClipX0 = _env.ClipX0; _kClipY0 = _env.ClipY0; _kClipX1 = _env.ClipX1; _kClipY1 = _env.ClipY1;
        _kRepTex = _pendingRepTex; _kRepClut = _pendingRepClut; _kRepClutCount = _pendingRepClutCount;
        _kRepX = _pendingRepX; _kRepY = _pendingRepY; _kRepW = _pendingRepW; _kRepH = _pendingRepH;
    }

    uint _pendingRepTex, _pendingRepClut;
    int _pendingRepClutCount = 16;
    float _pendingRepX, _pendingRepY, _pendingRepW = 1, _pendingRepH = 1;

    readonly Dictionary<Assets.ReplacementTexture, uint> _repTextures = [];
    readonly Dictionary<Assets.ReplacementClut, uint> _repCluts = [];

    // Replacement textures were uploaded once and kept forever. That is fine for a pack
    // of a few hundred, but an upscaled pack can hold tens of thousands, and at 4x each
    // one is sixteen times the area of the original -- a long session would upload its
    // way through all the video memory the machine has. Track what a texture cost and
    // drop the ones the game has stopped drawing.
    readonly Dictionary<Assets.ReplacementTexture, (uint Handle, long Bytes, long Frame)> _repUse = [];
    long _repBytes;

    /// <summary>Video memory to spend on replacement textures before evicting.</summary>
    public static long RepTextureBudget = 512L * 1024 * 1024;

    void ResolveReplacement(in PrimFlags f, int uMin, int vMin, int uMax, int vMax)
    {
        _pendingRepTex = 0;
        _pendingRepClut = 0;

        if (!f.Textured || f.UseImage) return;

        int twAndX = ~(_env.TwMaskX * 8) & 0xFF, twAndY = ~(_env.TwMaskY * 8) & 0xFF;
        int twOrX = (_env.TwOffX & _env.TwMaskX) * 8, twOrY = (_env.TwOffY & _env.TwMaskY) * 8;

        if (!Assets.Textures.TextureResolver.Resolve(f.TPage, f.Clut, uMin, vMin, uMax, vMax,
                twAndX, twAndY, twOrX, twOrY, out var res))
            return;

        if (res.Texture is { Mode: Assets.TextureMode.Rgba } tex)
        {
            _pendingRepTex = EnsureRepTexture(tex);
            _pendingRepX = res.Rect.U0;
            _pendingRepY = res.Rect.V0;
            _pendingRepW = res.Rect.W;
            _pendingRepH = res.Rect.H;
        }

        if (_pendingRepTex == 0 && res.Clut is { } clut && res.Rect.ClutCount > 0 && clut.Count == res.Rect.ClutCount)
        {
            _pendingRepClut = EnsureRepClut(clut);
            _pendingRepClutCount = clut.Count;
        }
    }

    unsafe uint EnsureRepTexture(Assets.ReplacementTexture tex)
    {
        if (_repTextures.TryGetValue(tex, out uint handle))
        {
            var was = _repUse[tex];
            _repUse[tex] = (was.Handle, was.Bytes, _frame);
            return handle;
        }

        _gl.ActiveTexture(TextureUnit.Texture7);
        handle = _gl.GenTexture();
        _gl.BindTexture(TextureTarget.Texture2D, handle);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.Linear);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Linear);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.ClampToEdge);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.ClampToEdge);
        byte[] upload = PremultiplyAlpha(tex.Rgba);
        _gl.TexImage2D<byte>(TextureTarget.Texture2D, 0, InternalFormat.Rgba8, (uint)tex.Width, (uint)tex.Height, 0,
            PixelFormat.Rgba, PixelType.UnsignedByte, upload);
        _gl.GenerateMipmap(TextureTarget.Texture2D);
        _gl.ActiveTexture(TextureUnit.Texture0);

        _repTextures[tex] = handle;
        long bytes = (long)tex.Width * tex.Height * 4;
        _repUse[tex] = (handle, bytes, _frame);
        _repBytes += bytes;
        if (_repBytes > RepTextureBudget) EvictReplacements();
        return handle;
    }

    /// <summary>
    /// Linear filtering must not mix the RGB stored in transparent source texels into
    /// an actor silhouette. Dreamcast pages retain magenta-key RGB under alpha zero;
    /// filtering that straight-alpha data produces a colored fringe around Spider-Man
    /// at 4x. Upload premultiplied RGB and undo it after sampling in the primitive
    /// shader so both base-level filtering and generated mipmaps have clean edges.
    /// </summary>
    static byte[] PremultiplyAlpha(byte[] source)
    {
        byte[] result = (byte[])source.Clone();
        for (int i = 0; i + 3 < result.Length; i += 4)
        {
            int alpha = result[i + 3];
            result[i] = (byte)((result[i] * alpha + 127) / 255);
            result[i + 1] = (byte)((result[i + 1] * alpha + 127) / 255);
            result[i + 2] = (byte)((result[i + 2] * alpha + 127) / 255);
        }
        return result;
    }

    /// <summary>
    /// Drop least-recently-drawn replacement textures until back inside the budget.
    /// Anything touched this frame is left alone: the batch being built still refers to
    /// it, and deleting a bound texture would draw the wrong thing.
    /// </summary>
    void EvictReplacements()
    {
        var order = new List<KeyValuePair<Assets.ReplacementTexture, (uint Handle, long Bytes, long Frame)>>(_repUse);
        order.Sort((a, b) => a.Value.Frame.CompareTo(b.Value.Frame));

        long target = RepTextureBudget * 3 / 4;
        int freed = 0;
        foreach (var (tex, info) in order)
        {
            if (_repBytes <= target) break;
            if (info.Frame >= _frame) continue;
            _gl.DeleteTexture(info.Handle);
            _repTextures.Remove(tex);
            _repUse.Remove(tex);
            _repBytes -= info.Bytes;
            freed++;
        }
        if (freed > 0)
            Console.WriteLine($"[assets] evicted {freed} replacement texture(s), " +
                              $"{_repBytes / (1024 * 1024)} MB still resident");
    }

    unsafe uint EnsureRepClut(Assets.ReplacementClut clut)
    {
        if (_repCluts.TryGetValue(clut, out uint handle)) return handle;

        _gl.ActiveTexture(TextureUnit.Texture7);
        handle = _gl.GenTexture();
        _gl.BindTexture(TextureTarget.Texture2D, handle);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.Nearest);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Nearest);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.ClampToEdge);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.ClampToEdge);
        _gl.TexImage2D<byte>(TextureTarget.Texture2D, 0, InternalFormat.Rgba8, (uint)clut.Count, 1, 0,
            PixelFormat.Rgba, PixelType.UnsignedByte, clut.Rgba);
        _gl.ActiveTexture(TextureUnit.Texture0);

        _repCluts[clut] = handle;
        return handle;
    }

    GlVertex V(in HleVertex v, in PrimFlags f)
    {
        bool raw = f.Textured && f.RawTexture;
        float cr = raw ? 128f : v.R, cg = raw ? 128f : v.G, cb = raw ? 128f : v.B;
        int tpage = f.UseImage ? 0x4000 : f.Textured ? (f.TPage & 0x1FF) : 0x8000;
        if (_pendingRepTex != 0) tpage |= 0x2000;
        else if (_pendingRepClut != 0) tpage |= 0x1000;
        if (_count == 0)
        {
            _drawMinX = _drawMaxX = v.X;
            _drawMinY = _drawMaxY = v.Y;
        }
        else
        {
            if (v.X < _drawMinX) _drawMinX = v.X;
            if (v.X > _drawMaxX) _drawMaxX = v.X;
            if (v.Y < _drawMinY) _drawMinY = v.Y;
            if (v.Y > _drawMaxY) _drawMaxY = v.Y;
        }

        return new GlVertex
        {
            X = v.X, Y = v.Y,
            R = cr, G = cg, B = cb,
            Clut = f.Clut & 0x7FFF,
            Texpage = tpage,
            U = v.U, V = v.V,
            World = f.World ? 1f : 0f,
            Hud = f.Hud ? 1f : 0f,
            PerspectiveW = f.Textured && v.HasGteZ ? Math.Max(v.Z, 1f) : 1f,
        };
    }

    public void DrawTri(in HleVertex a, in HleVertex b, in HleVertex c, in PrimFlags f)
    {
        ResolveReplacement(f,
            (int)Math.Min(a.U, Math.Min(b.U, c.U)), (int)Math.Min(a.V, Math.Min(b.V, c.V)),
            (int)Math.Max(a.U, Math.Max(b.U, c.U)), (int)Math.Max(a.V, Math.Max(b.V, c.V)));
        Begin(f, 3);
        _verts[_count++] = V(a, f); _verts[_count++] = V(b, f); _verts[_count++] = V(c, f);
    }

    public void DrawRect(in HleRect r, in PrimFlags f)
    {
        ResolveReplacement(f, r.U, r.V, r.U + Math.Max(0, r.W - 1), r.V + Math.Max(0, r.H - 1));
        Begin(f, 6);
        var a = new HleVertex { X = r.X, Y = r.Y, R = r.R, G = r.G, B = r.B, U = r.U, V = r.V };
        var b = new HleVertex { X = r.X + r.W, Y = r.Y, R = r.R, G = r.G, B = r.B, U = (short)(r.U + r.W), V = r.V };
        var c = new HleVertex { X = r.X, Y = r.Y + r.H, R = r.R, G = r.G, B = r.B, U = r.U, V = (short)(r.V + r.H) };
        var d = new HleVertex { X = r.X + r.W, Y = r.Y + r.H, R = r.R, G = r.G, B = r.B, U = (short)(r.U + r.W), V = (short)(r.V + r.H) };
        _verts[_count++] = V(a, f); _verts[_count++] = V(b, f); _verts[_count++] = V(c, f);
        _verts[_count++] = V(b, f); _verts[_count++] = V(d, f); _verts[_count++] = V(c, f);
    }

    public void DrawLine(in HleVertex a, in HleVertex b, in PrimFlags f)
    {
        _pendingRepTex = 0;
        _pendingRepClut = 0;
        Begin(f, 6);
        float x1 = a.X, y1 = a.Y;
        float x2 = b.X, y2 = b.Y;
        float dx = x2 - x1, dy = y2 - y1;

        if (dx == 0 && dy == 0)
        {
            LineVert(x1, y1, a, f); LineVert(x1 + 1, y1, a, f); LineVert(x1 + 1, y1 + 1, a, f);
            LineVert(x1 + 1, y1 + 1, a, f); LineVert(x1, y1 + 1, a, f); LineVert(x1, y1, a, f);
            return;
        }

        float xo, yo;
        if (Math.Abs(dx) > Math.Abs(dy)) { xo = 0; yo = 1; if (dx > 0) x2++; else x1++; }
        else { xo = 1; yo = 0; if (dy > 0) y2++; else y1++; }

        LineVert(x1, y1, a, f); LineVert(x2, y2, b, f); LineVert(x2 + xo, y2 + yo, b, f);
        LineVert(x2 + xo, y2 + yo, b, f); LineVert(x1 + xo, y1 + yo, a, f); LineVert(x1, y1, a, f);
    }

    void LineVert(float x, float y, in HleVertex src, in PrimFlags f)
    {
        var v = src; v.X = x; v.Y = y;
        _verts[_count++] = V(v, f);
    }

    public void FillRect(int x, int y, int w, int h, ushort color15)
    {
        Flush();
        _vram.Fill(x, y, w, h, color15);
        foreach (var rt in _rts)
        {
            if (rt == null || !rt.Intersects(x, y, w, h)) continue;
            if (rt.Covers(x, y, x + w - 1, y + h - 1))
            {
                FillRtFull(rt, color15);
                rt.Dirty = false;
                rt.LastDrawFrame = _frame;
                _drewSincePresent = true;
                if (Log.GpuOn && (_frame % 120) == 0)
                    Log.Gpu($"  fill COVERS rt ({x},{y}) {w}x{h} margin={rt.Margin}");
            }
            else
            {
                if (Log.GpuOn && (_frame % 120) == 0)
                    Log.Gpu($"  fill PARTIAL ({x},{y}) {w}x{h} -> resync from vram, margin={rt.Margin}");
                SyncRtFromVram(rt, x, y, w, h);
            }
        }
    }

    void FillRtFull(GlDisplayRt rt, ushort color15)
    {
        float r = (color15 & 0x1F) / 31f, g = ((color15 >> 5) & 0x1F) / 31f, b = ((color15 >> 10) & 0x1F) / 31f;
        float a = (color15 & 0x8000) != 0 ? 1f : 0f;
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, rt.Fbo);
        _gl.Disable(EnableCap.ScissorTest);
        _gl.ClearColor(r, g, b, a);
        _gl.Clear(ClearBufferMask.ColorBufferBit);
        if (rt.CoverageFbo != 0)
        {
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, rt.CoverageFbo);
            _gl.ClearColor(0f, 0f, 0f, 0f);
            _gl.Clear(ClearBufferMask.ColorBufferBit);
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, rt.WorldFbo);
            _gl.ClearColor(r, g, b, 1f);
            _gl.Clear(ClearBufferMask.ColorBufferBit);
        }
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, 0);
    }

    public void CopyVram(int sx, int sy, int dx, int dy, int w, int h)
    {
        Flush();
        WritebackDirtyIntersecting(sx, sy, w, h);
        _vram.CopyRect(sx, sy, dx, dy, w, h);
        SyncRtsFromVram(dx, dy, w, h);
    }

    public void WriteVram(int x, int y, int w, int h, ReadOnlySpan<ushort> px)
    {
        Flush();
        _vram.WriteRect(x, y, w, h, px);
        SyncRtsFromVram(x, y, w, h);
    }

    public void ReadVram(int x, int y, int w, int h, Span<ushort> px)
    {
        Flush();
        WritebackDirtyIntersecting(x, y, w, h);
        _vram.ReadRect(x, y, w, h, px);
    }

    public unsafe byte[]? ReadScaled(int x, int y, int w, int h, out int outW, out int outH)
    {
        outW = outH = 0;
        if (!Ready || w <= 0 || h <= 0) return null;

        Flush();
        WritebackDirtyIntersecting(x, y, w, h);

        int s = GlVram.Scale;
        outW = w * s;
        outH = h * s;
        var buf = new byte[outW * outH * 4];

        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _vram.Fbo);
        fixed (byte* p = buf)
            _gl.ReadPixels(x * s, y * s, (uint)outW, (uint)outH,
                           PixelFormat.Rgba, PixelType.UnsignedByte, p);
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, 0);
        return buf;
    }

    public unsafe byte[]? ReadPresented(out int outW, out int outH)
        => ReadFrameBuffer(_finalFbo, _finalW, _finalH, out outW, out outH);

    public unsafe byte[]? ReadPreFxaa(out int outW, out int outH)
        => ReadFrameBuffer(_preFxaaFbo, _preFxaaW, _preFxaaH, out outW, out outH);

    unsafe byte[]? ReadFrameBuffer(uint fbo, int width, int height, out int outW, out int outH)
    {
        outW = outH = 0;
        if (!Ready || fbo == 0 || width <= 0 || height <= 0) return null;

        outW = width;
        outH = height;
        var buf = new byte[outW * outH * 4];

        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, fbo);
        fixed (byte* p = buf)
            _gl.ReadPixels(0, 0, (uint)outW, (uint)outH,
                           PixelFormat.Rgba, PixelType.UnsignedByte, p);
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, 0);
        return buf;
    }

    public int RegisterImage(ReadOnlySpan<byte> rgba, int width, int height)
    {
        _gl.ActiveTexture(TextureUnit.Texture7);
        uint t = _gl.GenTexture();
        _gl.BindTexture(TextureTarget.Texture2D, t);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.Nearest);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Nearest);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.ClampToEdge);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.ClampToEdge);
        _gl.TexImage2D(TextureTarget.Texture2D, 0, InternalFormat.Rgba8, (uint)width, (uint)height, 0,
            PixelFormat.Rgba, PixelType.UnsignedByte, rgba);
        _gl.ActiveTexture(TextureUnit.Texture0);

        _images.Add(t);
        return _images.Count - 1;
    }

    public void Flush()
    {
        if (_count == 0) return;

        var rt = _kTarget;
        uint destTex;
        if (rt == null)
        {
            _vram.BindDraw();
            destTex = _vram.Texture;
        }
        else
        {
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, rt.Fbo);
            _gl.Viewport(0, 0, (uint)rt.TexW, (uint)rt.TexH);
            destTex = rt.Tex;
        }
        int destW = rt == null ? GlVram.Width : rt.TexW;
        int destH = rt == null ? GlVram.Height : rt.TexH;

        GpuGlAccess.Gl = _gl;
        GpuGlAccess.TargetFbo = rt == null ? _vram.Fbo : rt.Fbo;
        GpuGlAccess.TargetWidth = destW;
        GpuGlAccess.TargetHeight = destH;
        GpuGlAccess.TargetOriginX = rt == null ? 0 : rt.X;
        GpuGlAccess.TargetOriginY = rt == null ? 0 : rt.Y;
        GpuGlAccess.TargetMargin = rt == null ? 0 : rt.Margin;

        _gl.Disable(EnableCap.DepthTest);
        _gl.Disable(EnableCap.CullFace);
        _gl.Enable(EnableCap.ScissorTest);
        int s = GlVram.Scale;

        int clipX0, clipY0, clipX1, clipY1;
        if (rt == null)
        {
            clipX0 = _kClipX0; clipY0 = _kClipY0; clipX1 = _kClipX1; clipY1 = _kClipY1;
        }
        else
        {
            clipX0 = _kClipX0 - rt.X + rt.Margin; clipY0 = _kClipY0 - rt.Y;
            clipX1 = _kClipX1 - rt.X + rt.Margin; clipY1 = _kClipY1 - rt.Y;
            bool spansFb = _kClipX0 <= rt.X && _kClipX1 >= rt.X + rt.W - 1;
            if (rt.Margin > 0 && spansFb) { clipX0 = 0; clipX1 = rt.Wide1x - 1; }
            else if (rt.Margin > 0 && Log.GpuOn && _count > 0)
                Log.Gpu($"  clip NOT widened: game clip x {_kClipX0}..{_kClipX1}, " +
                        $"fb x {rt.X}..{rt.X + rt.W - 1}, verts={_count}");
        }

        int bx0 = (int)Math.Floor(_drawMinX) + (rt == null ? 0 : rt.Margin - rt.X);
        int by0 = (int)Math.Floor(_drawMinY) - (rt == null ? 0 : rt.Y);
        int bx1 = (int)Math.Ceiling(_drawMaxX) + (rt == null ? 0 : rt.Margin - rt.X);
        int by1 = (int)Math.Ceiling(_drawMaxY) - (rt == null ? 0 : rt.Y);

        int rx0 = Math.Max(clipX0, bx0), ry0 = Math.Max(clipY0, by0);
        int rx1 = Math.Min(clipX1, bx1), ry1 = Math.Min(clipY1, by1);

        _gl.Scissor(clipX0 * s, clipY0 * s,
            (uint)Math.Max(0, (clipX1 - clipX0 + 1) * s), (uint)Math.Max(0, (clipY1 - clipY0 + 1) * s));

        int readX = Math.Max(0, rx0 * s);
        int readY = Math.Max(0, ry0 * s);
        int readW = Math.Max(0, (rx1 - rx0 + 1) * s);
        int readH = Math.Max(0, (ry1 - ry0 + 1) * s);
        destTex = _vram.BeginDestRead(destTex, destW, destH, readX, readY, readW, readH);
        RebindTarget(rt);

        _gl.UseProgram(_progPrim);
        _gl.BindVertexArray(_vao);
        _gl.ActiveTexture(TextureUnit.Texture0);
        _gl.BindTexture(TextureTarget.Texture2D, _vram.Texture);
        _gl.ActiveTexture(TextureUnit.Texture1);
        _gl.BindTexture(TextureTarget.Texture2D, destTex);
        if (_kImage >= 0 && _kImage < _images.Count)
        {
            _gl.ActiveTexture(TextureUnit.Texture2);
            _gl.BindTexture(TextureTarget.Texture2D, _images[_kImage]);
        }
        if (_kRepTex != 0)
        {
            _gl.ActiveTexture(TextureUnit.Texture3);
            _gl.BindTexture(TextureTarget.Texture2D, _kRepTex);
            _gl.Uniform4(_uRepRect, _kRepX, _kRepY, _kRepW, _kRepH);
        }
        if (_kRepClut != 0)
        {
            _gl.ActiveTexture(TextureUnit.Texture4);
            _gl.BindTexture(TextureTarget.Texture2D, _kRepClut);
            _gl.Uniform1(_uRepClutCount, (float)_kRepClutCount);
        }
        _gl.ActiveTexture(TextureUnit.Texture0);
        if (rt != null)
        {
            _gl.Uniform2(_uPosBias, (float)(rt.Margin - rt.X), (float)(-rt.Y));
            _gl.Uniform2(_uFbInv, 2f / rt.Wide1x, 2f / rt.H);
        }
        else
        {
            _gl.Uniform2(_uPosBias, 0f, 0f);
            _gl.Uniform2(_uFbInv, 2f / VramShadow.Width, 2f / VramShadow.Height);
        }
        if (_legacy)
        {
            _gl.Uniform4(_uTexWindow, (float)_kTwAndX, _kTwAndY, _kTwOrX, _kTwOrY);
            _gl.Uniform1(_uSetMask, _kSetMask == 1 ? 1f : 0f);
            _gl.Uniform1(_uCheckMask, _kCheckMask == 1 ? 1f : 0f);
            if (_uDestSize >= 0) _gl.Uniform2(_uDestSize, (float)destW, destH);
            if (_uSemiTrans >= 0) _gl.Uniform1(_uSemiTrans, _kTransparent ? 1f : 0f);
            if (_uBlendMode >= 0) _gl.Uniform1(_uBlendMode, (float)_kBlend);
        }
        else
        {
            _gl.Uniform4(_uTexWindow, _kTwAndX, _kTwAndY, _kTwOrX, _kTwOrY);
            _gl.Uniform1(_uSetMask, _kSetMask == 1 ? 1f : 0f);
            _gl.Uniform1(_uCheckMask, _kCheckMask);
            _gl.Uniform4(_uBlendOpaque, 1f, 1f, 1f, 0f);
        }

        _gl.BindBuffer(BufferTargetARB.ArrayBuffer, _vbo);
        _gl.BufferSubData<GlVertex>(BufferTargetARB.ArrayBuffer, 0, _verts.AsSpan(0, _count));

        if (_legacy)
        {
            _gl.Disable(EnableCap.Blend);
            _gl.DrawArrays(PrimitiveType.Triangles, 0, (uint)_count);
        }
        else if (!_kTransparent)
        {
            _gl.Disable(EnableCap.Blend);
            _gl.DrawArrays(PrimitiveType.Triangles, 0, (uint)_count);
        }
        else
        {
            _gl.Enable(EnableCap.Blend);
            _gl.BlendFuncSeparate(BlendingFactor.Src1Color, BlendingFactor.Src1Alpha, BlendingFactor.One, BlendingFactor.Zero);
            if (_kBlend == 2)
            {
                _gl.BlendEquation(BlendEquationModeEXT.FuncAdd);
                SetBlend(0f, 1f);
                _gl.DrawArrays(PrimitiveType.Triangles, 0, (uint)_count);

                _vram.BeginDestRead(destTex, destW, destH, readX, readY, readW, readH);
                RebindTarget(rt);
                _gl.BlendEquationSeparate(BlendEquationModeEXT.FuncReverseSubtract, BlendEquationModeEXT.FuncAdd);
                SetBlend(1f, 1f);
                _gl.Uniform4(_uBlendOpaque, 0f, 0f, 0f, 1f);
                _gl.DrawArrays(PrimitiveType.Triangles, 0, (uint)_count);
            }
            else
            {
                _gl.BlendEquation(BlendEquationModeEXT.FuncAdd);
                SetBlend(_kBlend switch { 0 => 0.5f, 3 => 0.25f, _ => 1f }, _kBlend == 0 ? 0.5f : 1f);
                _gl.DrawArrays(PrimitiveType.Triangles, 0, (uint)_count);
            }
        }

        if (rt is { CoverageFbo: not 0 } &&
            GpuHle.SourceAspect > GpuHle.BaseAspect + 0.001f)
        {
            if (_kBackground != 0)
            {
                rt.ClearR = _kClearR;
                rt.ClearG = _kClearG;
                rt.ClearB = _kClearB;
                rt.DrawClearR = _kDrawClearR;
                rt.DrawClearG = _kDrawClearG;
                rt.DrawClearB = _kDrawClearB;
                ClearCoverage(rt);
            }
            else if (_kIgnoreCoverage == 0) DrawCoverage(rt);
        }

        _gl.Disable(EnableCap.ScissorTest);
        if (Log.GpuOn && (_frame % 120) == 0 && rt != null && _count > 0)
            Log.Gpu($"  batch x {_drawMinX:F0}..{_drawMaxX:F0} (target space, margin={rt.Margin}, " +
                    $"wide=0..{rt.Wide1x - 1}) verts={_count}");
        if (rt != null) { rt.Dirty = true; rt.LastDrawFrame = _frame; _drewSincePresent = true; }
        else
        {
            int x0 = Math.Max(_kClipX0, (int)Math.Floor(_drawMinX));
            int y0 = Math.Max(_kClipY0, (int)Math.Floor(_drawMinY));
            int x1 = Math.Min(_kClipX1, (int)Math.Ceiling(_drawMaxX));
            int y1 = Math.Min(_kClipY1, (int)Math.Ceiling(_drawMaxY));
            if (x1 >= x0 && y1 >= y0)
                Assets.Textures.VramTracker.MarkGpuWrite(x0, y0, x1 - x0 + 1, y1 - y0 + 1);
        }
        _count = 0;
    }

    /// <summary>
    /// Record submitted primitive footprints independently of PS1 framebuffer alpha.
    /// The second channel carries the projection provenance supplied by Wide.Screen;
    /// exact world fragments are also copied to a separate HUD-free color target so
    /// screen-space art can never become source material for side completion.
    /// </summary>
    void DrawCoverage(GlDisplayRt rt)
    {
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, rt.CoverageFbo);
        _gl.Viewport(0, 0, (uint)rt.TexW, (uint)rt.TexH);
        _gl.Disable(EnableCap.DepthTest);
        _gl.Enable(EnableCap.Blend);
        _gl.BlendEquation(BlendEquationModeEXT.Max);
        _gl.BlendFunc(BlendingFactor.One, BlendingFactor.One);
        _gl.Disable(EnableCap.CullFace);
        _gl.UseProgram(_coverageProg);
        _gl.BindVertexArray(_vao);
        _gl.ActiveTexture(TextureUnit.Texture0);
        _gl.BindTexture(TextureTarget.Texture2D, _vram.Texture);
        if (_kImage >= 0 && _kImage < _images.Count)
        {
            _gl.ActiveTexture(TextureUnit.Texture2);
            _gl.BindTexture(TextureTarget.Texture2D, _images[_kImage]);
        }
        if (_kRepTex != 0)
        {
            _gl.ActiveTexture(TextureUnit.Texture3);
            _gl.BindTexture(TextureTarget.Texture2D, _kRepTex);
        }
        if (_kRepClut != 0)
        {
            _gl.ActiveTexture(TextureUnit.Texture4);
            _gl.BindTexture(TextureTarget.Texture2D, _kRepClut);
        }
        _gl.ActiveTexture(TextureUnit.Texture0);
        if (_uCoveragePosBias >= 0)
            _gl.Uniform2(_uCoveragePosBias, (float)(rt.Margin - rt.X), (float)(-rt.Y));
        if (_uCoverageFbInv >= 0)
            _gl.Uniform2(_uCoverageFbInv, 2f / rt.Wide1x, 2f / rt.H);
        if (_uCoverageTexWindow >= 0)
        {
            if (_legacy)
                _gl.Uniform4(_uCoverageTexWindow, (float)_kTwAndX, _kTwAndY, _kTwOrX, _kTwOrY);
            else
                _gl.Uniform4(_uCoverageTexWindow, _kTwAndX, _kTwAndY, _kTwOrX, _kTwOrY);
        }
        if (_uCoverageRepRect >= 0)
            _gl.Uniform4(_uCoverageRepRect, _kRepX, _kRepY, _kRepW, _kRepH);
        if (_uCoverageRepClutCount >= 0)
            _gl.Uniform1(_uCoverageRepClutCount, (float)_kRepClutCount);
        _gl.DrawArrays(PrimitiveType.Triangles, 0, (uint)_count);
        _gl.Disable(EnableCap.Blend);

        if (rt.WorldFbo != 0 && _worldCopyProg != 0)
        {
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, rt.WorldFbo);
            _gl.Viewport(0, 0, (uint)rt.TexW, (uint)rt.TexH);
            _gl.Disable(EnableCap.Blend);
            _gl.UseProgram(_worldCopyProg);
            _gl.BindVertexArray(_vao);
            _gl.ActiveTexture(TextureUnit.Texture5);
            _gl.BindTexture(TextureTarget.Texture2D, rt.Tex);
            if (_uWorldCopyPosBias >= 0)
                _gl.Uniform2(_uWorldCopyPosBias, (float)(rt.Margin - rt.X), (float)(-rt.Y));
            if (_uWorldCopyFbInv >= 0)
                _gl.Uniform2(_uWorldCopyFbInv, 2f / rt.Wide1x, 2f / rt.H);
            if (_uWorldCopySize >= 0)
            {
                if (_legacy) _gl.Uniform2(_uWorldCopySize, (float)rt.TexW, rt.TexH);
                else _gl.Uniform2(_uWorldCopySize, rt.TexW, rt.TexH);
            }
            _gl.DrawArrays(PrimitiveType.Triangles, 0, (uint)_count);
            _gl.ActiveTexture(TextureUnit.Texture0);
        }
        RebindTarget(rt);
    }

    void ClearCoverage(GlDisplayRt rt)
    {
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, rt.CoverageFbo);
        _gl.Disable(EnableCap.ScissorTest);
        _gl.ClearColor(0f, 0f, 0f, 0f);
        _gl.Clear(ClearBufferMask.ColorBufferBit);
        if (rt.WorldFbo != 0)
        {
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, rt.WorldFbo);
            _gl.ClearColor(rt.ClearR / 255f, rt.ClearG / 255f, rt.ClearB / 255f, 1f);
            _gl.Clear(ClearBufferMask.ColorBufferBit);
        }
        _gl.Enable(EnableCap.ScissorTest);
        RebindTarget(rt);
    }

    void SetBlend(float src, float dst) => _gl.Uniform4(_uBlend, src, src, src, dst);

    void SetScaleUniform(uint prog)
    {
        int loc = _gl.GetUniformLocation(prog, "uScale");
        if (loc < 0) return;
        if (_legacy) _gl.Uniform1(loc, (float)GlVram.Scale);
        else _gl.Uniform1(loc, GlVram.Scale);
    }

    void RebindTarget(GlDisplayRt? rt)
    {
        if (rt == null)
        {
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _vram.Fbo);
            _gl.Viewport(0, 0, (uint)GlVram.Width, (uint)GlVram.Height);
        }
        else
        {
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, rt.Fbo);
            _gl.Viewport(0, 0, (uint)rt.TexW, (uint)rt.TexH);
        }
    }

    public void Present(in HleDispEnv disp) => PresentDisplay(disp.X, disp.Y, disp.W, disp.H, disp.Rgb24);

    public unsafe (uint tex, int w, int h, float aspect) PresentDisplay(int dispX, int dispY, int w, int h, bool rgb24 = false, int outW = 0, int outH = 0)
    {
        if (!Ready || w <= 0 || h <= 0) return (0, 0, 0, GpuHle.OutputAspect);
        Flush();

        // Count rendered frames, not calls. Present is driven by the host, and the idle
        // breaker services the window far more often than the game draws -- around eight
        // presents per drawn frame here. Ageing display targets per call made every one
        // of them stale within a single game frame, so the widescreen target was never
        // eligible and presentation silently fell back to 4:3 every time.
        if (_drewSincePresent) { _frame++; _drewSincePresent = false; }
        foreach (var tex in _repTextures.Keys.Where(t => t.Retired).ToArray())
        {
            var info = _repUse[tex];
            if (info.Frame >= _frame) continue;
            _gl.DeleteTexture(info.Handle);
            _repTextures.Remove(tex);
            _repUse.Remove(tex);
            _repBytes -= info.Bytes;
            tex.Rgba = [];
        }

        for (int i = 0; i < _rts.Length; i++)
        {
            if (_rts[i] is not { } rt) continue;
            if (rt.Dirty) Writeback(rt);
            if (_frame - rt.LastDrawFrame > 300)
            {
                rt.Destroy(_gl);
                _rts[i] = null;
            }
        }

        GlDisplayRt? src = null;
        if (!rgb24)
            foreach (var rt in _rts)
            {
                if (rt == null || _frame - rt.LastDrawFrame > 4) continue;
                if (dispX < rt.X || dispY < rt.Y || dispX + w > rt.X + rt.W || dispY + h > rt.Y + rt.H) continue;
                if (src == null || rt.LastDrawFrame > src.LastDrawFrame) src = rt;
            }

        if (Log.GpuOn && (_frame % 120) == 0)
            for (int i = 0; i < _rts.Length; i++)
            {
                var rt = _rts[i];
                if (rt == null) { Log.Gpu($"  rt[{i}] null"); continue; }
                bool stale = _frame - rt.LastDrawFrame > 4;
                bool covers = !(dispX < rt.X || dispY < rt.Y || dispX + w > rt.X + rt.W || dispY + h > rt.Y + rt.H);
                Log.Gpu($"  rt[{i}] ({rt.X},{rt.Y}) {rt.W}x{rt.H} margin={rt.Margin} " +
                        $"age={_frame - rt.LastDrawFrame}{(stale ? " STALE" : "")}{(covers ? "" : " NOCOVER")}");
            }

        int w1x = src != null ? w + src.Margin * 2 : w;
        int h1x = h;
        float aspect = src is { Margin: > 0 } ? GpuHle.WideAspect : src != null ? GpuHle.SourceAspect : GpuHle.OutputAspect;

        if (Log.GpuOn && (_frame % 120) == 0)
            Log.Gpu($"present disp=({dispX},{dispY}) {w}x{h}  rt=" +
                    (src == null ? "none" : $"({src.X},{src.Y}) {src.W}x{src.H} margin={src.Margin}") +
                    $"  w1x={w1x} aspect={aspect:F3}");


        GpuHle.LastDisplayW = w;
        GpuHle.LastDisplayH = h;

        int presentScale = GlVram.Scale;
        int fbW = w1x * presentScale;
        int fbH = h1x * presentScale;
        EnsurePresentSize(fbW, fbH, GlVram.Scale == 1);

        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _presentFbo);
        _gl.Viewport(0, 0, (uint)fbW, (uint)fbH);
        _gl.Disable(EnableCap.DepthTest);
        _gl.Disable(EnableCap.Blend);
        _gl.Disable(EnableCap.ScissorTest);
        _gl.Disable(EnableCap.CullFace);

        _gl.UseProgram(rgb24 ? _progPresent24 : _progPresent);
        _gl.BindVertexArray(_presentVao);
        _gl.ActiveTexture(TextureUnit.Texture0);
        _gl.BindTexture(TextureTarget.Texture2D, src?.Tex ?? _vram.Texture);
        if (rgb24)
        {
            _gl.Uniform2(_uPresent24Origin, (float)dispX, dispY);
            _gl.Uniform2(_uPresent24Size, (float)w, h);
        }
        else if (src != null)
        {
            _gl.Uniform2(_uPresentOrigin, (float)(dispX - src.X), dispY - src.Y);
            _gl.Uniform2(_uPresentSize, (float)w1x, h1x);
            _gl.Uniform2(_uPresentTexSize, (float)src.Wide1x, src.H);
        }
        else
        {
            _gl.Uniform2(_uPresentOrigin, (float)dispX, dispY);
            _gl.Uniform2(_uPresentSize, (float)w, h);
            _gl.Uniform2(_uPresentTexSize, (float)VramShadow.Width, VramShadow.Height);
        }
        _gl.DrawArrays(PrimitiveType.TriangleStrip, 0, 4);

        uint outTex = _presentTex;
        uint outFbo = _presentFbo;
        uint completedTex = ApplyWideBackground(outTex, src, fbW, fbH, aspect);
        if (completedTex != outTex)
        {
            outTex = completedTex;
            outFbo = _wideCompleteFbo;
        }
        uint postTex = ApplyPostFx(outTex, fbW, fbH);
        if (postTex != outTex)
        {
            outTex = postTex;
            outFbo = _postFbo;
        }
        _preFxaaFbo = outFbo;
        _preFxaaW = fbW;
        _preFxaaH = fbH;
        if (GpuHle.FxaaEnabled)
        {
            uint fxaaTex = ApplyFxaa(outTex, fbW, fbH);
            if (fxaaTex != outTex)
            {
                outTex = fxaaTex;
                outFbo = _fxaaFbo;
            }
        }
        _finalFbo = outFbo;
        _finalW = fbW;
        _finalH = fbH;

        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, 0);
        return (outTex, fbW, fbH, aspect);
    }

    unsafe uint ApplyWideBackground(uint srcTex, GlDisplayRt? src, int w, int h, float aspect)
    {
        if (!GpuHle.WideBackgroundCompletion || _wideCompleteProg == 0 ||
            src is not { CoverageTex: not 0, WorldTex: not 0 } ||
            aspect <= GpuHle.BaseAspect + 0.001f)
            return srcTex;

        if (_wideCompleteTex == 0)
        {
            _wideCompleteTex = _gl.GenTexture();
            _gl.BindTexture(TextureTarget.Texture2D, _wideCompleteTex);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.Nearest);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Nearest);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.ClampToEdge);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.ClampToEdge);
            _wideCompleteFbo = _gl.GenFramebuffer();
        }
        if (w != _wideCompleteW || h != _wideCompleteH)
        {
            _gl.BindTexture(TextureTarget.Texture2D, _wideCompleteTex);
            _gl.TexImage2D(TextureTarget.Texture2D, 0, InternalFormat.Rgba8, (uint)w, (uint)h, 0,
                PixelFormat.Rgba, PixelType.UnsignedByte, null);
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _wideCompleteFbo);
            _gl.FramebufferTexture2D(FramebufferTarget.Framebuffer, FramebufferAttachment.ColorAttachment0,
                TextureTarget.Texture2D, _wideCompleteTex, 0);
            _wideCompleteW = w;
            _wideCompleteH = h;
        }

        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _wideCompleteFbo);
        _gl.Viewport(0, 0, (uint)w, (uint)h);
        _gl.Disable(EnableCap.DepthTest);
        _gl.Disable(EnableCap.Blend);
        _gl.Disable(EnableCap.ScissorTest);
        _gl.Disable(EnableCap.CullFace);
        _gl.UseProgram(_wideCompleteProg);
        _gl.BindVertexArray(_presentVao);
        _gl.ActiveTexture(TextureUnit.Texture0);
        _gl.BindTexture(TextureTarget.Texture2D, srcTex);
        _gl.ActiveTexture(TextureUnit.Texture1);
        _gl.BindTexture(TextureTarget.Texture2D, src.CoverageTex);
        _gl.ActiveTexture(TextureUnit.Texture2);
        _gl.BindTexture(TextureTarget.Texture2D, src.WorldTex);
        if (_uWideCompleteTexSize >= 0) _gl.Uniform2(_uWideCompleteTexSize, (float)w, h);
        if (_uWideCompleteBaseFraction >= 0)
            _gl.Uniform1(_uWideCompleteBaseFraction, GpuHle.BaseAspect / aspect);
        if (_uWideCompleteDebug >= 0)
            _gl.Uniform1(_uWideCompleteDebug, GpuHle.WideCoverageView ? 1f : 0f);
        if (_uWideCompleteClearColor >= 0)
            _gl.Uniform3(_uWideCompleteClearColor,
                src.ClearR / 255f, src.ClearG / 255f, src.ClearB / 255f);
        if (_uWideCompleteDrawClearColor >= 0)
            _gl.Uniform3(_uWideCompleteDrawClearColor,
                src.DrawClearR / 255f, src.DrawClearG / 255f, src.DrawClearB / 255f);
        if (_uWideCompleteDiagnosticClear >= 0)
            _gl.Uniform1(_uWideCompleteDiagnosticClear,
                RecompOne.Runtime.Diagnostics.DrawEnvWarn.TintBackground ? 1f : 0f);
        _gl.DrawArrays(PrimitiveType.TriangleStrip, 0, 4);
        _gl.ActiveTexture(TextureUnit.Texture0);
        if (AuditComposite && _frame != _lastCompositeAudit)
        {
            _lastCompositeAudit = _frame;
            AuditWideComposite(src, w, h);
        }
        return _wideCompleteTex;
    }

    unsafe void AuditWideComposite(GlDisplayRt src, int w, int h)
    {
        // Numeric framebuffer invariants only. No images are written or exposed.
        byte[] Read(uint fbo)
        {
            byte[] pixels = new byte[checked(w * h * 4)];
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, fbo);
            fixed (byte* pointer = pixels)
                _gl.ReadPixels(0, 0, (uint)w, (uint)h, PixelFormat.Rgba, PixelType.UnsignedByte, pointer);
            return pixels;
        }
        var before = Read(_presentFbo);
        var after = Read(_wideCompleteFbo);
        var coverage = Read(src.CoverageFbo);
        long changed = 0, drawnChanged = 0, worldChanged = 0, drawn = 0;
        for (int i = 0; i < before.Length; i += 4)
        {
            bool visible = coverage[i] >= 128;
            if (visible) drawn++;
            int delta = Math.Max(Math.Abs(before[i] - after[i]),
                Math.Max(Math.Abs(before[i + 1] - after[i + 1]), Math.Abs(before[i + 2] - after[i + 2])));
            if (delta <= 1) continue;
            changed++;
            if (visible) drawnChanged++;
            if (visible && coverage[i + 1] >= 128) worldChanged++;
        }
        Console.WriteLine($"[composite-audit] render-frame={_frame} size={w}x{h} " +
            $"changed={changed} drawn={drawn} drawn-changed={drawnChanged} world-changed={worldChanged}");
        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _wideCompleteFbo);
    }

    unsafe uint ApplyFxaa(uint srcTex, int w, int h)
    {
        if (_fxaaProg == 0) return srcTex;
        if (_fxaaTex == 0)
        {
            _fxaaTex = _gl.GenTexture();
            _gl.BindTexture(TextureTarget.Texture2D, _fxaaTex);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.Linear);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Linear);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.ClampToEdge);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.ClampToEdge);
            _fxaaFbo = _gl.GenFramebuffer();
        }
        if (w != _fxaaW || h != _fxaaH)
        {
            _gl.BindTexture(TextureTarget.Texture2D, _fxaaTex);
            _gl.TexImage2D(TextureTarget.Texture2D, 0, InternalFormat.Rgba8, (uint)w, (uint)h, 0,
                PixelFormat.Rgba, PixelType.UnsignedByte, null);
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _fxaaFbo);
            _gl.FramebufferTexture2D(FramebufferTarget.Framebuffer, FramebufferAttachment.ColorAttachment0,
                TextureTarget.Texture2D, _fxaaTex, 0);
            _fxaaW = w;
            _fxaaH = h;
        }

        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _fxaaFbo);
        _gl.Viewport(0, 0, (uint)w, (uint)h);
        _gl.Disable(EnableCap.DepthTest);
        _gl.Disable(EnableCap.Blend);
        _gl.Disable(EnableCap.ScissorTest);
        _gl.Disable(EnableCap.CullFace);
        _gl.UseProgram(_fxaaProg);
        _gl.BindVertexArray(_presentVao);
        _gl.ActiveTexture(TextureUnit.Texture0);
        _gl.BindTexture(TextureTarget.Texture2D, srcTex);
        if (_uFxaaTexSize >= 0) _gl.Uniform2(_uFxaaTexSize, (float)w, h);
        _gl.DrawArrays(PrimitiveType.TriangleStrip, 0, 4);
        return _fxaaTex;
    }
    
    //support for post-fx shaders to be loaded, so you can have cool shaders (this was too anonying to implement)
    unsafe uint ApplyPostFx(uint srcTex, int w, int h)
    {
        if (!PostFx.Active) return srcTex;
        if (!EnsurePostProgram()) return srcTex;

        if (_postTex == 0)
        {
            _postTex = _gl.GenTexture();
            _gl.BindTexture(TextureTarget.Texture2D, _postTex);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.Linear);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Linear);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.ClampToEdge);
            _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.ClampToEdge);
            _postFbo = _gl.GenFramebuffer();
        }
        if (w != _postW || h != _postH)
        {
            _gl.BindTexture(TextureTarget.Texture2D, _postTex);
            _gl.TexImage2D(TextureTarget.Texture2D, 0, InternalFormat.Rgba8, (uint)w, (uint)h, 0,
                PixelFormat.Rgba, PixelType.UnsignedByte, null);
            _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _postFbo);
            _gl.FramebufferTexture2D(FramebufferTarget.Framebuffer, FramebufferAttachment.ColorAttachment0,
                TextureTarget.Texture2D, _postTex, 0);
            _postW = w; _postH = h;
        }

        _gl.BindFramebuffer(FramebufferTarget.Framebuffer, _postFbo);
        _gl.Viewport(0, 0, (uint)w, (uint)h);
        _gl.Disable(EnableCap.DepthTest);
        _gl.Disable(EnableCap.Blend);
        _gl.Disable(EnableCap.ScissorTest);

        _gl.UseProgram(_postProg);
        _gl.BindVertexArray(_presentVao);
        _gl.ActiveTexture(TextureUnit.Texture0);
        _gl.BindTexture(TextureTarget.Texture2D, srcTex);
        if (_uPostTexSize >= 0) _gl.Uniform2(_uPostTexSize, (float)w, h);
        if (_uPostOutputSize >= 0) _gl.Uniform2(_uPostOutputSize, (float)w, h);
        if (_uPostTime >= 0) _gl.Uniform1(_uPostTime, (float)_postClock.Elapsed.TotalSeconds);
        if (_uPostFrame >= 0) _gl.Uniform1(_uPostFrame, _postFrame++);
        ApplyPostParams();
        _gl.DrawArrays(PrimitiveType.TriangleStrip, 0, 4);

        return _postTex;
    }

    void ApplyPostParams()
    {
        int version = PostFx.ParamVersion;
        if (version != _postParamVersion)
        {
            _postParamVersion = version;
            _postParams = PostFx.SnapshotParams();
            _postParamLoc = new int[_postParams.Length];
            for (int i = 0; i < _postParams.Length; i++)
                _postParamLoc[i] = _gl.GetUniformLocation(_postProg, _postParams[i].Name);
        }

        for (int i = 0; i < _postParams.Length; i++)
            if (_postParamLoc[i] >= 0) _gl.Uniform1(_postParamLoc[i], _postParams[i].Value);
    }

    bool EnsurePostProgram()
    {
        int version = PostFx.Version;
        if (version == _postVersion) return _postProg != 0;
        _postVersion = version;

        if (_postProg != 0) { _gl.DeleteProgram(_postProg); _postProg = 0; }

        string? src = PostFx.Source;
        if (src == null) return false;

        _postProg = GlShaders.Build(_gl, GlShaders.FullscreenVs, src, "postfx", out string? error);
        if (_postProg == 0)
        {
            PostFx.Error = error ?? "shader fails to build";
            Console.WriteLine($"[gpu-pfx] {PostFx.Error}");
            return false;
        }

        PostFx.Error = null;
        _gl.UseProgram(_postProg);
        _gl.Uniform1(_gl.GetUniformLocation(_postProg, "uTex"), 0);
        _uPostTexSize = _gl.GetUniformLocation(_postProg, "uTexSize");
        _uPostOutputSize = _gl.GetUniformLocation(_postProg, "uOutputSize");
        _uPostTime = _gl.GetUniformLocation(_postProg, "uTime");
        _uPostFrame = _gl.GetUniformLocation(_postProg, "uFrame");
        _postParamVersion = -1;
        return true;
    }

    unsafe void EnsurePresentSize(int w, int h, bool nearest)
    {
        if (w == _presentW && h == _presentH && nearest == _presentNearest) return;
        _gl.BindTexture(TextureTarget.Texture2D, _presentTex);
        _gl.TexImage2D(TextureTarget.Texture2D, 0, InternalFormat.Rgba8, (uint)w, (uint)h, 0, PixelFormat.Rgba, PixelType.UnsignedByte, null);
        var filter = nearest ? GLEnum.Nearest : GLEnum.Linear;
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)filter);
        _gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)filter);
        _presentW = w; _presentH = h; _presentNearest = nearest;
    }

    public void Dispose()
    {
        foreach (var rt in _rts) rt?.Destroy(_gl);
        _vram.Dispose();
        if (_vbo != 0) _gl.DeleteBuffer(_vbo);
        if (_presentVbo != 0) _gl.DeleteBuffer(_presentVbo);
        if (_vao != 0) _gl.DeleteVertexArray(_vao);
        if (_presentVao != 0) _gl.DeleteVertexArray(_presentVao);
        if (_progPrim != 0) _gl.DeleteProgram(_progPrim);
        if (_progPresent != 0) _gl.DeleteProgram(_progPresent);
        if (_progPresent24 != 0) _gl.DeleteProgram(_progPresent24);
        if (_fxaaProg != 0) _gl.DeleteProgram(_fxaaProg);
        if (_coverageProg != 0) _gl.DeleteProgram(_coverageProg);
        if (_worldCopyProg != 0) _gl.DeleteProgram(_worldCopyProg);
        if (_wideCompleteProg != 0) _gl.DeleteProgram(_wideCompleteProg);
        if (_presentTex != 0) _gl.DeleteTexture(_presentTex);
        if (_presentFbo != 0) _gl.DeleteFramebuffer(_presentFbo);
        if (_postProg != 0) _gl.DeleteProgram(_postProg);
        if (_postTex != 0) _gl.DeleteTexture(_postTex);
        if (_postFbo != 0) _gl.DeleteFramebuffer(_postFbo);
        if (_fxaaTex != 0) _gl.DeleteTexture(_fxaaTex);
        if (_fxaaFbo != 0) _gl.DeleteFramebuffer(_fxaaFbo);
        if (_wideCompleteTex != 0) _gl.DeleteTexture(_wideCompleteTex);
        if (_wideCompleteFbo != 0) _gl.DeleteFramebuffer(_wideCompleteFbo);
    }
}
