using Silk.NET.OpenGL;

namespace RecompOne.Runtime.Hle;

public sealed class GlDisplayRt
{
    public int X, Y, W, H;
    public int Margin;
    public uint Tex, Fbo;
    // PS1 ordering-table buckets cannot resolve intersecting clothing surfaces.
    // Allocate depth only when a suit with exact vertex depth is actually drawn.
    public uint ModelDepth;
    public long ModelDepthFrame = long.MinValue;

    public void EnsureModelDepth(GL gl, long frame)
    {
        if (ModelDepth == 0)
        {
            ModelDepth = gl.GenRenderbuffer();
            gl.BindRenderbuffer(RenderbufferTarget.Renderbuffer, ModelDepth);
            gl.RenderbufferStorage(RenderbufferTarget.Renderbuffer, InternalFormat.DepthComponent24,
                (uint)TexW, (uint)TexH);
            gl.FramebufferRenderbuffer(FramebufferTarget.Framebuffer, FramebufferAttachment.DepthAttachment,
                RenderbufferTarget.Renderbuffer, ModelDepth);
        }
        if (ModelDepthFrame != frame)
        {
            gl.Disable(EnableCap.ScissorTest);
            gl.DepthMask(true);
            gl.ClearDepth(1.0);
            gl.Clear(ClearBufferMask.DepthBufferBit);
            gl.Enable(EnableCap.ScissorTest);
            ModelDepthFrame = frame;
        }
    }
    /// <summary>
    /// R = touched by a visible submitted primitive, G = visible GTE/world geometry,
    /// B = visible HUD, A = an authored transparent texture cut-out. It is kept separate
    /// from PS1 mask-bit alpha so coverage diagnostics do not change render semantics.
    /// </summary>
    public uint CoverageTex, CoverageFbo;
    /// <summary>Latest rendered color for exact GTE/world geometry, before HUD overdraw.</summary>
    public uint WorldTex, WorldFbo;
    public byte ClearR, ClearG, ClearB;
    public byte DrawClearR, DrawClearG, DrawClearB;
    public bool Dirty;
    public long Stamp;
    public long LastDrawFrame;

    public int Wide1x => W + Margin * 2;
    public int TexW => Wide1x * GlVram.Scale;
    public int TexH => H * GlVram.Scale;

    public bool Contains(int cx0, int cy0, int cx1, int cy1)
        => cx0 >= X && cx1 <= X + W - 1 && cy0 >= Y && cy1 <= Y + H - 1;

    public bool Covers(int cx0, int cy0, int cx1, int cy1)
        => cx0 <= X && cx1 >= X + W - 1 && cy0 <= Y && cy1 >= Y + H - 1;

    public bool Intersects(int rx, int ry, int rw, int rh)
        => rx < X + W && X < rx + rw && ry < Y + H && Y < ry + rh;

    public void Create(GL gl, bool coverage)
    {
        Tex = gl.GenTexture();
        gl.BindTexture(TextureTarget.Texture2D, Tex);
        gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.Nearest);
        gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Nearest);
        gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.ClampToEdge);
        gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.ClampToEdge);
        // The display target is a host rendering surface, not emulated VRAM. Keeping it
        // RGB5A1 here silently reintroduced the console's color limit after the shader
        // had produced a full 8-bit result. Writeback to the real VRAM texture still
        // converts to PS1 format when game feedback or readback actually requires it.
        gl.TexImage2D<byte>(TextureTarget.Texture2D, 0, InternalFormat.Rgba8,
            (uint)TexW, (uint)TexH, 0, PixelFormat.Rgba, PixelType.UnsignedByte,
            new byte[TexW * TexH * 4].AsSpan());

        Fbo = gl.GenFramebuffer();
        gl.BindFramebuffer(FramebufferTarget.Framebuffer, Fbo);
        gl.FramebufferTexture2D(FramebufferTarget.Framebuffer, FramebufferAttachment.ColorAttachment0,
            TextureTarget.Texture2D, Tex, 0);
        gl.ClearColor(0f, 0f, 0f, 0f);
        gl.Disable(EnableCap.ScissorTest);
        gl.Clear(ClearBufferMask.ColorBufferBit);

        if (coverage)
        {
            CoverageTex = gl.GenTexture();
            gl.BindTexture(TextureTarget.Texture2D, CoverageTex);
            gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.Nearest);
            gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Nearest);
            gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.ClampToEdge);
            gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.ClampToEdge);
            gl.TexImage2D<byte>(TextureTarget.Texture2D, 0, InternalFormat.Rgba8,
                (uint)TexW, (uint)TexH, 0, PixelFormat.Rgba, PixelType.UnsignedByte,
                new byte[TexW * TexH * 4].AsSpan());

            CoverageFbo = gl.GenFramebuffer();
            gl.BindFramebuffer(FramebufferTarget.Framebuffer, CoverageFbo);
            gl.FramebufferTexture2D(FramebufferTarget.Framebuffer,
                FramebufferAttachment.ColorAttachment0, TextureTarget.Texture2D,
                CoverageTex, 0);
            gl.ClearColor(0f, 0f, 0f, 0f);
            gl.Clear(ClearBufferMask.ColorBufferBit);

            WorldTex = gl.GenTexture();
            gl.BindTexture(TextureTarget.Texture2D, WorldTex);
            gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter, (int)GLEnum.Nearest);
            gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter, (int)GLEnum.Nearest);
            gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.ClampToEdge);
            gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.ClampToEdge);
            gl.TexImage2D<byte>(TextureTarget.Texture2D, 0, InternalFormat.Rgba8,
                (uint)TexW, (uint)TexH, 0, PixelFormat.Rgba, PixelType.UnsignedByte,
                new byte[TexW * TexH * 4].AsSpan());

            WorldFbo = gl.GenFramebuffer();
            gl.BindFramebuffer(FramebufferTarget.Framebuffer, WorldFbo);
            gl.FramebufferTexture2D(FramebufferTarget.Framebuffer,
                FramebufferAttachment.ColorAttachment0, TextureTarget.Texture2D,
                WorldTex, 0);
            gl.ClearColor(0f, 0f, 0f, 0f);
            gl.Clear(ClearBufferMask.ColorBufferBit);
        }
        gl.BindFramebuffer(FramebufferTarget.Framebuffer, 0);
    }

    public void Destroy(GL gl)
    {
        if (ModelDepth != 0) gl.DeleteRenderbuffer(ModelDepth);
        ModelDepth = 0;
        ModelDepthFrame = long.MinValue;
        if (Fbo != 0) gl.DeleteFramebuffer(Fbo);
        if (Tex != 0) gl.DeleteTexture(Tex);
        if (CoverageFbo != 0) gl.DeleteFramebuffer(CoverageFbo);
        if (CoverageTex != 0) gl.DeleteTexture(CoverageTex);
        if (WorldFbo != 0) gl.DeleteFramebuffer(WorldFbo);
        if (WorldTex != 0) gl.DeleteTexture(WorldTex);
        Fbo = Tex = CoverageFbo = CoverageTex = WorldFbo = WorldTex = 0;
    }
}
