namespace RecompOne.Runtime.Assets.Textures;

public struct ResolvedTexture
{
    public ReplacementTexture? Texture;
    public ReplacementClut? Clut;
    public TileRect Rect;
    public bool Hit;
}

public static class TextureResolver
{
    // Game-owned material binding. Data-only manifests cannot provide this delegate or guest pointers.
    public static Func<TileRect, ResolvedTexture>? ActorMaterials { get; set; }
    sealed class Entry
    {
        public int Generation = -1;
        public ulong IndexHash;
        public ulong ClutHash;
        public TextureAsset? Texture;
        public ClutAsset? Clut;
        public TextureAsset? PageTexture;
        public TileRect Rect;
        public TileRect PageRect;
        public bool Valid;
    }

    sealed class PageEntry
    {
        public int Generation = -1;
        public TextureAsset? Texture;
        public TileRect Rect;
    }

    static readonly Dictionary<long, PageEntry> _pages = [];

    static void CheckAspect(TextureAsset asset, ReplacementTexture tex, in TileRect rect, string kind)
    {
        if (asset.AspectChecked || rect.W <= 0 || rect.H <= 0 || tex.Height <= 0) return;
        asset.AspectChecked = true;

        tex.ScaleX = tex.Width / (float)rect.W;
        tex.ScaleY = tex.Height / (float)rect.H;

        double original = rect.W / (double)rect.H;
        double replacement = tex.Width / (double)tex.Height;
        bool distorted = Math.Abs(replacement - original) / original > 0.02;

        Console.WriteLine($"[assets] {kind} {asset.IndexHash:x16}: {rect.W}x{rect.H} -> {tex.Width}x{tex.Height} " +
                          $"({tex.ScaleX:0.##}x, {tex.ScaleY:0.##}x)" +
                          (distorted ? "  WARNING: aspect differs from the original, the image will be stretched" : ""));
    }

    /// <summary>
    /// How wide a whole texture page is, in texels. Always 256, whatever the depth.
    ///
    /// A texpage is 64 VRAM words wide, which is 256 texels at 4bpp but only 128 at 8bpp
    /// and 64 at 16bpp -- yet UVs are 8-bit at every depth, so a texture can address 256
    /// texels and simply runs on into the neighbouring texpage columns. Sizing the page
    /// by the hardware's 64 words left the rest of that UV range off the end of the
    /// replacement, and the shader normalises tile UVs across the page rect, so
    /// everything past the edge clamped and smeared into horizontal streaks.
    /// </summary>
    public static int PageWidthTexels(int bpp) => 256;

    // PS1 texture-window sampling is (uv & andMask) | offset. The maximum
    // remaining coordinate is andMask, not its complement: ~63 + 1 made a
    // 64-texel actor window look 193 texels wide, defeating HD replacements.
    public static int TextureWindowExtent(int andMask) => (andMask & 0xFF) + 1;

    static int TexelsPerWord(int bpp) => bpp switch { 4 => 4, 8 => 2, _ => 1 };

    /// <summary>Why a region lookup ended the way it did, counted per depth.</summary>
    public enum RegionOutcome { Upload, Ok, Outside, Empty, Dirty, Size }

    static readonly int[] _regionStats = new int[3 * 6];

    static int DepthSlot(int bpp) => bpp == 4 ? 0 : bpp == 8 ? 1 : 2;

    static bool NoteRegion(int bpp, RegionOutcome why)
    {
        Interlocked.Increment(ref _regionStats[DepthSlot(bpp) * 6 + (int)why]);
        return why is RegionOutcome.Ok or RegionOutcome.Upload;
    }

    /// <summary>
    /// The uploaded texture a tile belongs to, as a VRAM rectangle.
    ///
    /// A fixed 256x256 page is the wrong unit when a game keeps textures in the same
    /// VRAM rows as its framebuffers: the window always catches blocks the GPU is
    /// drawing into, the whole thing reads as dynamic, and the tile gets no replacement
    /// however complete the pack is. That is the case here for every 16bpp texture,
    /// which is most of the character art.
    ///
    /// The dirty tracker already distinguishes blocks the CPU uploaded from blocks the
    /// GPU rendered, so the uploaded extent can be recovered from it: take the aligned
    /// page-sized cell the tile sits in and trim whole block rows and columns off the
    /// edges until nothing GPU-written is left inside. Trimming stops at the tile, so a
    /// texture wedged against live framebuffer gives up rather than hashing pixels that
    /// change every frame.
    ///
    /// Both the dumper and the resolver call this, so they agree on the rectangle by
    /// construction, and it is derived from VRAM state alone -- no side channel.
    /// </summary>
    public static bool TryDescribeRegion(in TileRect tile, out TileRect region)
    {
        region = default;

        const int B = VramTracker.BlockW;
        int perWord = TexelsPerWord(tile.Bpp);
        int maxWords = PageWidthTexels(tile.Bpp) / perWord;

        // Anchor on the tile's own texpage, not an absolute grid. UVs are relative to the
        // texpage base and 8-bit, so [PageX, PageX + 256 texels) x [PageY, PageY + 256)
        // contains every tile that page can address -- and every tile of one texture
        // starts from the same rectangle, which is what keeps the hash stable. An
        // absolute grid instead cuts across texpage bases, and any 16bpp tile reaching
        // past its cell was thrown out.
        int x0 = tile.PageX;
        int x1 = Math.Min(x0 + maxWords, 1024);
        int y0 = tile.PageY;
        int y1 = Math.Min(y0 + 256, 512);

        int tx0 = tile.VramX, tx1 = tile.VramX + tile.VramW;
        int ty0 = tile.VramY, ty1 = tile.VramY + tile.H;

        // The image the game uploaded, when there is one covering this tile. That is the
        // texture's real extent, so the hash covers the texture and nothing else --
        // which is what makes a replacement built from the disc's own TIMs addressable,
        // and what stops a dump from being a slab of unrelated neighbours.
        if (VramTracker.TryFindUpload(tx0, ty0, tx1 - tx0, ty1 - ty0, out var up)
            && !VramTracker.IsGpuDirty(up.X, up.Y, up.W, up.H)
            && Describe(tile, up.X, up.Y, up.W, up.H, perWord, out region))
            return NoteRegion(tile.Bpp, RegionOutcome.Upload);

        if (tx0 < x0 || ty0 < y0 || tx1 > x1 || ty1 > y1) return NoteRegion(tile.Bpp, RegionOutcome.Outside);

        while (y0 < ty0 && VramTracker.IsGpuDirty(x0, y0, x1 - x0, B)) y0 += B;
        while (y1 > ty1 && VramTracker.IsGpuDirty(x0, y1 - B, x1 - x0, B)) y1 -= B;
        while (x0 < tx0 && VramTracker.IsGpuDirty(x0, y0, B, y1 - y0)) x0 += B;
        while (x1 > tx1 && VramTracker.IsGpuDirty(x1 - B, y0, B, y1 - y0)) x1 -= B;

        if (x1 <= x0 || y1 <= y0) return NoteRegion(tile.Bpp, RegionOutcome.Empty);
        if (VramTracker.IsGpuDirty(x0, y0, x1 - x0, y1 - y0)) return NoteRegion(tile.Bpp, RegionOutcome.Dirty);

        if (!Describe(tile, x0, y0, x1 - x0, y1 - y0, perWord, out region))
            return NoteRegion(tile.Bpp, RegionOutcome.Size);
        return NoteRegion(tile.Bpp, RegionOutcome.Ok);
    }

    /// <summary>Turn a VRAM rectangle into a tile rect in the sampling tile's UV space.</summary>
    static bool Describe(in TileRect tile, int x0, int y0, int words, int rows, int perWord,
        out TileRect region)
    {
        region = default;
        int w = words * perWord, h = rows;
        if (w <= 0 || h <= 0 || w * h > TextureTile.MaxTexels) return false;

        region = new TileRect
        {
            // Anchored on the tile's own texpage so U0/V0 stay in the UV space the
            // shader normalises against, even when the region starts before the page.
            PageX = tile.PageX,
            PageY = tile.PageY,
            U0 = (x0 - tile.PageX) * perWord,
            V0 = y0 - tile.PageY,
            W = w,
            H = h,
            Bpp = tile.Bpp,
            ClutX = tile.ClutX,
            ClutY = tile.ClutY,
            ClutCount = tile.ClutCount,
        };
        return true;
    }

    static TextureAsset? ResolvePage(ushort[] vram, int tpage, int clut, in TileRect tile, bool dirty, out TileRect pageRect)
    {
        if (!TryDescribeRegion(tile, out pageRect)) return null;

        long key = ((long)(pageRect.VramX & 0x3FF) << 42) ^ ((long)(pageRect.VramY & 0x1FF) << 33)
                   ^ ((long)(pageRect.W & 0x1FF) << 24) ^ ((long)(pageRect.H & 0x1FF) << 15)
                   ^ (clut & 0x7FFF);
        int generation = VramTracker.Generation(pageRect.VramX, pageRect.VramY, pageRect.VramW, pageRect.H)
                         ^ VramTracker.Generation(pageRect.ClutX, pageRect.ClutY, pageRect.ClutCount, 1);

        PageEntry page;
        lock (_pages)
        {
            if (!_pages.TryGetValue(key, out page!))
            {
                page = new PageEntry();
                _pages[key] = page;
            }
        }

        if (VramTracker.IsGpuDirty(pageRect.VramX, pageRect.VramY, pageRect.VramW, pageRect.H))
        {
            page.Generation = -1;
            page.Texture = null;
            return null;
        }

        if (page.Generation != generation)
        {
            page.Generation = generation;
            page.Rect = pageRect;
            page.Texture = null;

            if (TextureTile.Hash(vram, pageRect, out ulong pageIndex, out ulong pageClut))
            {
                if (!dirty) page.Texture = AssetReplacerManager.Instance.ResolveTexture(pageIndex, pageClut);
                TextureRegistry.Note(vram, pageRect, pageIndex, pageClut, tpage, clut,
                    page.Texture != null, isPage: true, dynamic: dirty);
            }
        }

        pageRect = page.Rect;
        return page.Texture;
    }

    static readonly Dictionary<long, Entry> _memo = [];
    static int _version;

    static int _statCalls, _statNoTexture, _statRejectSize, _statRejectDirty, _statHashed, _statMemo;

    public static bool Enabled { get; set; } = true;

    public static void ResetStats()
    {
        Volatile.Write(ref _statCalls, 0);
        Volatile.Write(ref _statNoTexture, 0);
        Volatile.Write(ref _statRejectSize, 0);
        Volatile.Write(ref _statRejectDirty, 0);
        Volatile.Write(ref _statHashed, 0);
        Volatile.Write(ref _statMemo, 0);
        Array.Clear(_regionStats);
    }

    public static string StatsLine() =>
        $"calls={Volatile.Read(ref _statCalls)} untextured={Volatile.Read(ref _statNoTexture)} " +
        $"rejected-size={Volatile.Read(ref _statRejectSize)} rejected-gpudirty={Volatile.Read(ref _statRejectDirty)} " +
        $"hashed={Volatile.Read(ref _statHashed)} memo-hits={Volatile.Read(ref _statMemo)} tiles={CachedTiles}";

    /// <summary>
    /// Why whole-texture regions are being refused, split by depth.
    ///
    /// A tile with no replacement of its own falls back to the region it came from, so
    /// when a depth shows no accepted regions, nothing at that depth can ever be
    /// replaced -- and the reason it is being refused is the thing worth knowing. The
    /// 16bpp row is the one to read: those are the character skins.
    /// </summary>
    public static string RegionStatsLine()
    {
        var sb = new System.Text.StringBuilder("regions");
        for (int slot = 0; slot < 3; slot++)
        {
            int bpp = slot == 0 ? 4 : slot == 1 ? 8 : 16;
            sb.Append($" {bpp}bpp[");
            for (int why = 0; why < 6; why++)
                sb.Append(why == 0 ? "" : " ")
                  .Append(((RegionOutcome)why).ToString().ToLowerInvariant())
                  .Append('=')
                  .Append(Volatile.Read(ref _regionStats[slot * 6 + why]));
            sb.Append(']');
        }
        return sb.ToString();
    }

    public static void Invalidate()
    {
        lock (_memo)
        {
            _memo.Clear();
            _version++;
        }
        lock (_pages) _pages.Clear();
    }

    public static int CachedTiles
    {
        get { lock (_memo) return _memo.Count; }
    }

    public static bool Resolve(int tpage, int clut, int uMin, int vMin, int uMax, int vMax,
        int twAndX, int twAndY, int twOrX, int twOrY, out ResolvedTexture result)
    {
        result = default;
        if (!Enabled) return false;

        var mgr = AssetReplacerManager.Instance;
        bool dumping = TextureDumper.Enabled;
        bool observing = dumping || TextureRegistry.Enabled;
        if (!observing && !mgr.HasTextures && ActorMaterials == null) return false;

        var gpu = Runtime.Gpu;
        if (gpu == null) return false;

        Interlocked.Increment(ref _statCalls);

        int u0, v0, w, h;
        if (twAndX != 0xFF || twOrX != 0)
        {
            u0 = twOrX;
            w = TextureWindowExtent(twAndX);
        }
        else
        {
            u0 = uMin;
            w = uMax - uMin + 1;
        }

        if (twAndY != 0xFF || twOrY != 0)
        {
            v0 = twOrY;
            h = TextureWindowExtent(twAndY);
        }
        else
        {
            v0 = vMin;
            h = vMax - vMin + 1;
        }

        if (w <= 0 || h <= 0 || w > 256 || h > 256)
        {
            Interlocked.Increment(ref _statRejectSize);
            return false;
        }

        var rect = TextureTile.Describe(tpage, clut, u0, v0, w, h);

        if (ActorMaterials?.Invoke(rect) is { Hit: true } actor)
        {
            result = actor;
            return true;
        }

        if (mgr.HasRules && mgr.MatchRule(tpage, rect.Bpp, w, h) is { } ruled)
        {
            var ruledTex = mgr.LoadTexture(ruled);
            if (ruledTex != null)
            {
                result.Rect = rect;
                result.Texture = ruledTex;
                result.Clut = null;
                result.Hit = true;
                return true;
            }
        }

        bool dirty = VramTracker.IsGpuDirty(rect.VramX, rect.VramY, rect.VramW, rect.H);
        if (dirty)
        {
            Interlocked.Increment(ref _statRejectDirty);
            if (!observing) return false;
        }

        long key = (long)(tpage & 0x1FF)
                   | ((long)(clut & 0x7FFF) << 9)
                   | ((long)(u0 & 0xFF) << 24)
                   | ((long)(v0 & 0xFF) << 32)
                   | ((long)(w & 0x1FF) << 40)
                   | ((long)(h & 0x1FF) << 49);

        int generation = VramTracker.Generation(rect.VramX, rect.VramY, rect.VramW, rect.H)
                         ^ VramTracker.Generation(rect.ClutX, rect.ClutY, rect.ClutCount, 1);

        Entry entry;
        lock (_memo)
        {
            if (!_memo.TryGetValue(key, out entry!))
            {
                entry = new Entry();
                _memo[key] = entry;
            }
        }

        if (entry.Generation == generation) Interlocked.Increment(ref _statMemo);
        else
        {
            Interlocked.Increment(ref _statHashed);
            entry.Generation = generation;
            entry.Rect = rect;
            entry.Valid = TextureTile.Hash(gpu.Vram, rect, out entry.IndexHash, out entry.ClutHash);

            if (entry.Valid)
            {
                if (dumping) TextureDumper.Offer(gpu.Vram, rect, entry.IndexHash, entry.ClutHash, tpage, clut);

                entry.Texture = null;
                entry.Clut = null;
                entry.PageTexture = null;

                if (!dirty)
                {
                    entry.Texture = mgr.ResolveTexture(entry.IndexHash, entry.ClutHash);
                    entry.Clut = mgr.ResolveClut(entry.ClutHash);
                }

                if (entry.Texture == null)
                    entry.PageTexture = ResolvePage(gpu.Vram, tpage, clut, rect, dirty, out entry.PageRect);

                if (entry.Texture != null || entry.Clut != null || entry.PageTexture != null) mgr.Stats.TextureHits++;
                else mgr.Stats.TextureMisses++;

                TextureRegistry.Note(gpu.Vram, rect, entry.IndexHash, entry.ClutHash, tpage, clut,
                    entry.Texture != null || entry.Clut != null || entry.PageTexture != null, isPage: false, dynamic: dirty);
            }
        }

        if (!entry.Valid || (entry.Texture == null && entry.Clut == null && entry.PageTexture == null)) return false;

        if (entry.Texture == null && entry.PageTexture != null)
        {
            result.Rect = entry.PageRect;
            result.Texture = mgr.LoadTexture(entry.PageTexture);
            result.Clut = null;
            result.Hit = result.Texture != null;
            if (result.Hit)
            {
                CheckAspect(entry.PageTexture, result.Texture!, entry.PageRect, "page");
                return true;
            }
        }

        result.Rect = entry.Rect;
        result.Texture = entry.Texture != null ? mgr.LoadTexture(entry.Texture) : null;
        if (result.Texture != null) CheckAspect(entry.Texture!, result.Texture, entry.Rect, "tile");
        result.Clut = entry.Clut != null ? mgr.LoadClut(entry.Clut) : null;
        result.Hit = result.Texture != null || result.Clut != null;
        return result.Hit;
    }
}
