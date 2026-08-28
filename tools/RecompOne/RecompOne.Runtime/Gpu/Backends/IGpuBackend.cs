namespace RecompOne.Runtime.Hle;

/// <summary>
/// GPU BACKEND
/// </summary>
public interface IGpuBackend
{
    // false in headless or if gl init failed
    bool Ready { get; }

    // submit
    void SetDrawEnv(in HleDrawEnv env);
    void DrawTri(in HleVertex a, in HleVertex b, in HleVertex c, in PrimFlags f);
    void DrawRect(in HleRect r, in PrimFlags f);
    void DrawLine(in HleVertex a, in HleVertex b, in PrimFlags f);
    void FillRect(int x, int y, int w, int h, ushort color15);
    void CopyVram(int sx, int sy, int dx, int dy, int w, int h);
    void WriteVram(int x, int y, int w, int h, ReadOnlySpan<ushort> px);
    void ReadVram(int x, int y, int w, int h, Span<ushort> px);

    /// <summary>
    /// A region of VRAM at full internal resolution, as RGBA8, bottom row first.
    /// ReadVram downsamples back to console resolution; this is what the rasteriser
    /// actually produced, which is the only honest way to capture an upscaled frame.
    /// Returns null on backends that cannot do it.
    /// </summary>
    byte[]? ReadScaled(int x, int y, int w, int h, out int outW, out int outH)
    {
        outW = outH = 0;
        return null;
    }
    
    /// <summary>
    /// The frame as it was last presented, at full internal resolution, RGBA8, bottom
    /// row first. This is the only view that includes the widescreen margins: those are
    /// rendered into the presentation target and the blit back to VRAM deliberately
    /// takes the console-width centre, so a VRAM readback can never show them.
    /// Returns null on backends that cannot do it.
    /// </summary>
    byte[]? ReadPresented(out int outW, out int outH)
    {
        outW = outH = 0;
        return null;
    }

    //add other stuff
    int RegisterImage(ReadOnlySpan<byte> rgba, int width, int height);

    // these touch gl
    void Flush();
    void Present(in HleDispEnv disp);
}
