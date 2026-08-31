using System.Collections.Concurrent;
using System.Text;

namespace RecompOne.Runtime.Assets.Textures;

public static class TextureDumper
{
    sealed class Job
    {
        public ulong Id;
        public ushort[] Window = [];
        public ushort[] Clut = [];
        public TileRect Rect;
        public ulong IndexHash, ClutHash;
        public int TPage, ClutId;
        public bool IsPage;
    }

    const int QueueCapacity = 8192;

    static readonly HashSet<ulong> _seen = [];
    static readonly HashSet<ulong> _idxWritten = [];
    static readonly HashSet<ulong> _clutWritten = [];
    static readonly object _gate = new();
    static BlockingCollection<Job> _queue = NewQueue();
    static Thread? _worker;
    static string _root = "";
    static string _clutRoot = "";
    static string _pageRoot = "";
    static int _written, _dropped, _failed, _offered;

    public static bool Tiles { get; private set; }
    public static bool Pages { get; private set; }
    public static bool Enabled => Tiles || Pages;
    public static int UniqueSeen { get { lock (_gate) return _seen.Count; } }
    public static int Offered => Volatile.Read(ref _offered);
    public static int Written => Volatile.Read(ref _written);
    public static int Dropped => Volatile.Read(ref _dropped);
    public static int Failed => Volatile.Read(ref _failed);
    public static int Pending => _queue.Count;
    public static string Root => _root;

    static BlockingCollection<Job> NewQueue() => new(new ConcurrentQueue<Job>(), QueueCapacity);

    public static void SetTiles(bool on)
    {
        if (on == Tiles) return;
        bool was = Enabled;
        Tiles = on;
        Apply(was);
    }

    public static void SetPages(bool on)
    {
        if (on == Pages) return;
        bool was = Enabled;
        Pages = on;
        Apply(was);
    }

    public static void SetEnabled(bool on)
    {
        bool was = Enabled;
        Tiles = Pages = on;
        Apply(was);
    }

    static void Apply(bool was)
    {
        if (Enabled == was) return;
        if (Enabled) Start();
        else Stop();
    }

    static void Start()
    {
        {
            string? explicitRoot = Environment.GetEnvironmentVariable("RECOMP_TEXTURE_DUMP_DIR");
            string dumpRoot;
            if (string.IsNullOrWhiteSpace(explicitRoot))
            {
                string game = Sanitize(AssetReplacerManager.Instance.GameId);
                dumpRoot = Path.GetFullPath(Path.Combine("dump", game));
            }
            else dumpRoot = Path.GetFullPath(explicitRoot);
            _root = Path.Combine(dumpRoot, "textures");
            _clutRoot = Path.Combine(dumpRoot, "cluts");
            _pageRoot = Path.Combine(dumpRoot, "pages");
            try
            {
                Directory.CreateDirectory(_root);
                Directory.CreateDirectory(_clutRoot);
                Directory.CreateDirectory(_pageRoot);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[assets] texture dump: cannot create '{_root}': {ex.Message}");
                return;
            }

            lock (_gate)
            {
                _seen.Clear();
                _idxWritten.Clear();
                _clutWritten.Clear();
            }
            Volatile.Write(ref _written, 0);
            Volatile.Write(ref _dropped, 0);
            Volatile.Write(ref _failed, 0);
            Volatile.Write(ref _offered, 0);

            if (_queue.IsAddingCompleted) _queue = NewQueue();
            EnsureWorker();
            TextureResolver.ResetStats();
           // Console.WriteLine($"[assets] texture dump ON (tiles={Tiles} pages={Pages}) -> {_root}");
        }
    }

    static void Stop()
    {
       // Console.WriteLine($"[assets] texture dump OFF: seen={UniqueSeen} written={Written} " + $"pending={Pending} dropped={Dropped} failed={Failed}");
       // Console.WriteLine($"[assets] resolver: {TextureResolver.StatsLine()}");
    }

    static string Sanitize(string s)
    {
        var sb = new StringBuilder(s.Length);
        foreach (char c in s) sb.Append(char.IsLetterOrDigit(c) || c is '-' or '_' ? c : '_');
        return sb.Length == 0 ? "UNKNOWN" : sb.ToString();
    }

    static void EnsureWorker()
    {
        if (_worker is { IsAlive: true }) return;
        _worker = new Thread(WorkerLoop) { IsBackground = true, Name = "tex-dump" };
        _worker.Start();
    }

    public static void Offer(ushort[] vram, in TileRect rect, ulong indexHash, ulong clutHash, int tpage, int clut)
    {
        if (!Enabled) return;
        if (!Tiles)
        {
            OfferPage(vram, rect, clutHash, tpage, clut);
            return;
        }

        ulong id = indexHash ^ (clutHash * 1099511628211UL);
        lock (_gate)
        {
            if (!_seen.Add(id)) return;
        }

        Interlocked.Increment(ref _offered);

        var job = new Job
        {
            Id = id,
            Rect = rect,
            IndexHash = indexHash,
            ClutHash = clutHash,
            TPage = tpage,
            ClutId = clut,
            Window = TextureTile.CopyWindow(vram, rect),
            Clut = TextureTile.CopyClut(vram, rect),
        };

        if (!_queue.TryAdd(job))
        {
            lock (_gate) _seen.Remove(id);
            Interlocked.Increment(ref _dropped);
            return;
        }

        OfferPage(vram, rect, clutHash, tpage, clut);
    }

    static void OfferPage(ushort[] vram, in TileRect tile, ulong clutHash, int tpage, int clut)
    {
        if (!Pages) return;

        // The same derivation the resolver uses, so the hash written here is the hash
        // looked up later. See TextureResolver.TryDescribeRegion.
        if (!TextureResolver.TryDescribeRegion(tile, out var pageRect)) return;
        if (!TextureTile.Hash(vram, pageRect, out ulong pageIndexHash, out ulong pageClutHash)) return;

        ulong pageId = 0x9E3779B97F4A7C15UL ^ pageIndexHash ^ (pageClutHash * 1099511628211UL);
        lock (_gate)
        {
            if (!_seen.Add(pageId)) return;
        }

        var job = new Job
        {
            Id = pageId,
            Rect = pageRect,
            IndexHash = pageIndexHash,
            ClutHash = pageClutHash,
            TPage = tpage,
            ClutId = clut,
            IsPage = true,
            Window = TextureTile.CopyWindow(vram, pageRect),
            Clut = TextureTile.CopyClut(vram, pageRect),
        };

        if (_queue.TryAdd(job)) return;
        lock (_gate) _seen.Remove(pageId);
        Interlocked.Increment(ref _dropped);
    }

    static void WorkerLoop()
    {
        foreach (var job in _queue.GetConsumingEnumerable())
        {
            try
            {
                WriteJob(job);
                Interlocked.Increment(ref _written);
            }
            catch (Exception ex)
            {
                Interlocked.Increment(ref _failed);
                Console.Error.WriteLine($"[assets] texture dump failed for {job.IndexHash:x16} " +
                                        $"({job.Rect.W}x{job.Rect.H} {job.Rect.Bpp}bpp u0={job.Rect.U0}): {ex.Message}");
            }
        }
    }

    static void WriteJob(Job job)
    {
        var r = job.Rect;

        if (job.IsPage)
        {
            string page = Path.Combine(_pageRoot, $"{job.IndexHash:x16}_{job.ClutHash:x16}");
            PngWriter.WriteRgba(page + ".png", TextureTile.DecodeFrom(job.Window, job.Clut, r), r.W, r.H);
            // The raw VRAM words as well as the picture. A PNG says what a texture looks
            // like; only the words say what it *is*, which is what a search of the game's
            // own archive can be run against when a texture turns out not to come from
            // anywhere obvious.
            File.WriteAllBytes(page + ".bin", TextureTile.RawBytes(job.Window));
            File.WriteAllBytes(page + ".clut.bin", TextureTile.RawBytes(job.Clut));
            File.WriteAllText(page + ".json", $$"""
            {
              "kind": "page",
              "indexHash": "{{job.IndexHash:x16}}",
              "clutHash": "{{job.ClutHash:x16}}",
              "bpp": {{r.Bpp}},
              "width": {{r.W}},
              "height": {{r.H}},
              "texpage": {{job.TPage}},
              "clut": {{job.ClutId}}
            }
            """);
            return;
        }

        string baseName = Path.Combine(_root, $"{job.IndexHash:x16}_{job.ClutHash:x16}");

        PngWriter.WriteRgba(baseName + ".png", TextureTile.DecodeFrom(job.Window, job.Clut, r), r.W, r.H);
        File.WriteAllBytes(baseName + ".idx.bin", TextureTile.RawBytes(job.Window));

        if (r.Bpp != 16)
        {
            bool writeIdx, writeClut;
            lock (_gate)
            {
                writeIdx = _idxWritten.Add(job.IndexHash);
                writeClut = _clutWritten.Add(job.ClutHash);
            }

            if (writeIdx)
            {
                var indices = TextureTile.DecodeIndicesFrom(job.Window, r);
                int max = r.Bpp == 4 ? 15 : 255;
                var scaled = new byte[indices.Length];
                for (int i = 0; i < indices.Length; i++) scaled[i] = (byte)(indices[i] * 255 / max);
                PngWriter.WriteGray(Path.Combine(_root, $"{job.IndexHash:x16}.idx.png"), scaled, r.W, r.H);
            }

            if (writeClut)
            {
                string clutBase = Path.Combine(_clutRoot, $"{job.ClutHash:x16}");
                PngWriter.WriteRgba(clutBase + ".clut.png", TextureTile.DecodeClutFrom(job.Clut), job.Clut.Length, 1);
                File.WriteAllBytes(clutBase + ".clut.bin", TextureTile.RawBytes(job.Clut));
            }
        }

        string json = $$"""
        {
          "indexHash": "{{job.IndexHash:x16}}",
          "clutHash": "{{job.ClutHash:x16}}",
          "bpp": {{r.Bpp}},
          "width": {{r.W}},
          "height": {{r.H}},
          "texpage": {{job.TPage}},
          "clut": {{job.ClutId}},
          "u0": {{r.U0}},
          "v0": {{r.V0}}
        }
        """;
        File.WriteAllText(baseName + ".json", json);
    }
}
