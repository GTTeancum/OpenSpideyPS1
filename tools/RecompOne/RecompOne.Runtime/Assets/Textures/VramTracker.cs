namespace RecompOne.Runtime.Assets.Textures;

public static class VramTracker
{
    public const int BlockW = 16;
    public const int BlockH = 16;
    public const int Cols = 1024 / BlockW;
    public const int Rows = 512 / BlockH;

    static readonly int[] _gen = new int[Cols * Rows];
    static readonly bool[] _gpuDirty = new bool[Cols * Rows];
    static int _clock;

    /// <summary>One image the CPU uploaded into VRAM, as the rectangle it landed in.</summary>
    public readonly struct Upload
    {
        public readonly int X, Y, W, H;
        public readonly int Stamp;
        public Upload(int x, int y, int w, int h, int stamp) { X = x; Y = y; W = w; H = h; Stamp = stamp; }
        public readonly bool Contains(int x, int y, int w, int h) =>
            x >= X && y >= Y && x + w <= X + W && y + h <= Y + H;
        public readonly int Area => W * H;
    }

    // The last few uploads overlapping each block. A texture is whatever the game
    // uploaded as one image, and that is the only honest answer to "which pixels are
    // this texture" -- a fixed page window instead takes in whatever else shares those
    // VRAM rows. Several images can land inside one 16x16 block, so keep a few per
    // block and let the lookup pick between them.
    const int PerBlock = 4;
    static readonly Upload[] _uploads = new Upload[Cols * Rows * PerBlock];
    static int _uploadClock;

    public static void Reset()
    {
        Array.Clear(_gen);
        Array.Clear(_gpuDirty);
        Array.Clear(_uploads);
        _clock = 0;
        _uploadClock = 0;
    }

    /// <summary>Record an image the CPU DMA'd into VRAM. Call this for uploads only.</summary>
    public static void NoteUpload(int x, int y, int w, int h)
    {
        if (w <= 0 || h <= 0 || w > 1024 || h > 512) return;
        var up = new Upload(x, y, w, h, ++_uploadClock);
        Bounds(x, y, w, h, out int c0, out int r0, out int c1, out int r1);
        for (int r = r0; r <= r1; r++)
            for (int c = c0; c <= c1; c++)
            {
                int slot = (r * Cols + c) * PerBlock;
                // Shuffle down; oldest falls off the end.
                for (int i = PerBlock - 1; i > 0; i--) _uploads[slot + i] = _uploads[slot + i - 1];
                _uploads[slot] = up;
            }
    }

    /// <summary>
    /// The smallest still-recorded upload that wholly contains this rectangle.
    ///
    /// Smallest rather than newest: a large background image and the small sprite drawn
    /// over the same rows both contain the sprite's tile, and the sprite is the texture
    /// being sampled. Ties break towards the more recent upload.
    /// </summary>
    public static bool TryFindUpload(int x, int y, int w, int h, out Upload found)
    {
        found = default;
        bool any = false;
        int c = Math.Clamp(x / BlockW, 0, Cols - 1);
        int r = Math.Clamp(y / BlockH, 0, Rows - 1);
        int slot = (r * Cols + c) * PerBlock;
        for (int i = 0; i < PerBlock; i++)
        {
            var up = _uploads[slot + i];
            if (up.Stamp == 0 || !up.Contains(x, y, w, h)) continue;
            if (!any || up.Area < found.Area || (up.Area == found.Area && up.Stamp > found.Stamp))
            {
                found = up;
                any = true;
            }
        }
        return any;
    }

    static void Bounds(int x, int y, int w, int h, out int c0, out int r0, out int c1, out int r1)
    {
        if (w < 0) { x += w; w = -w; }
        if (h < 0) { y += h; h = -h; }
        c0 = Math.Clamp(x / BlockW, 0, Cols - 1);
        r0 = Math.Clamp(y / BlockH, 0, Rows - 1);
        c1 = Math.Clamp((x + Math.Max(0, w - 1)) / BlockW, 0, Cols - 1);
        r1 = Math.Clamp((y + Math.Max(0, h - 1)) / BlockH, 0, Rows - 1);
    }

    public static void MarkCpuWrite(int x, int y, int w, int h)
    {
        int stamp = ++_clock;
        Bounds(x, y, w, h, out int c0, out int r0, out int c1, out int r1);
        for (int r = r0; r <= r1; r++)
            for (int c = c0; c <= c1; c++)
            {
                int i = r * Cols + c;
                _gen[i] = stamp;
                _gpuDirty[i] = false;
            }
    }

    public static void MarkGpuWrite(int x, int y, int w, int h)
    {
        int stamp = ++_clock;
        Bounds(x, y, w, h, out int c0, out int r0, out int c1, out int r1);
        for (int r = r0; r <= r1; r++)
            for (int c = c0; c <= c1; c++)
            {
                int i = r * Cols + c;
                _gen[i] = stamp;
                _gpuDirty[i] = true;
            }
    }

    public static int Generation(int x, int y, int w, int h)
    {
        Bounds(x, y, w, h, out int c0, out int r0, out int c1, out int r1);
        int acc = 0;
        for (int r = r0; r <= r1; r++)
            for (int c = c0; c <= c1; c++)
                acc = acc * 31 + _gen[r * Cols + c];
        return acc;
    }

    public static bool IsGpuDirty(int x, int y, int w, int h)
    {
        Bounds(x, y, w, h, out int c0, out int r0, out int c1, out int r1);
        for (int r = r0; r <= r1; r++)
            for (int c = c0; c <= c1; c++)
                if (_gpuDirty[r * Cols + c]) return true;
        return false;
    }
}
