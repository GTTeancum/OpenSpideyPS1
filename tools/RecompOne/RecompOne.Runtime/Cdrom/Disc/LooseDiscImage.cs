using System.Text.Json;

namespace RecompOne.Runtime.Cdrom;

/// <summary>
/// Directory-backed PlayStation media. Regular ISO files are stored normally;
/// sectorized XA/STR files retain their 2336-byte Mode 2 sectors so their subheaders,
/// channels, and ADPCM payload survive extraction.
/// </summary>
public sealed class LooseDiscImage : IDiscImage
{
    public const string ManifestName = "recompone-disc.json";

    public sealed class Manifest
    {
        public int Version { get; set; } = 1;
        public string GameId { get; set; } = "";
        public int LeadoutLba { get; set; }
        public int DataSectors { get; set; }
        public List<ManifestTrack> Tracks { get; set; } = [];
        public List<ManifestFile> Files { get; set; } = [];
    }

    public sealed class ManifestTrack
    {
        public int Number { get; set; }
        public DiscTrackKind Kind { get; set; }
        public int StartLba { get; set; }
        public int SectorSize { get; set; }
    }

    public sealed class ManifestFile
    {
        public string Path { get; set; } = "";
        public int Lba { get; set; }
        public uint Size { get; set; }
        public bool Raw2336 { get; set; }
    }

    readonly string _root;
    readonly Manifest _manifest;
    readonly List<ManifestFile> _byLba;
    readonly Dictionary<string, ManifestFile> _byPath;
    readonly Dictionary<string, FileStream> _streams = new(StringComparer.OrdinalIgnoreCase);
    readonly object _ioGate = new();
    readonly bool _trace = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("SPIDEY_TRACE_LOOSE"));
    int _traceReads;

    LooseDiscImage(string root, Manifest manifest)
    {
        _root = root;
        _manifest = manifest;
        _byLba = manifest.Files.OrderBy(f => f.Lba).ToList();
        _byPath = manifest.Files.ToDictionary(f => CanonicalPath(f.Path), StringComparer.OrdinalIgnoreCase);
    }

    public static bool IsLooseDirectory(string path) =>
        Directory.Exists(path) && File.Exists(Path.Combine(path, ManifestName));

    public static LooseDiscImage Open(string path)
    {
        string root = Path.GetFullPath(path);
        string manifestPath = Path.Combine(root, ManifestName);
        var manifest = JsonSerializer.Deserialize<Manifest>(File.ReadAllText(manifestPath), JsonOptions())
            ?? throw new InvalidDataException($"invalid loose-disc manifest: {manifestPath}");
        if (manifest.Version != 1)
            throw new InvalidDataException($"unsupported loose-disc manifest version {manifest.Version}");
        return new LooseDiscImage(root, manifest);
    }

    public string Format => "loose files";
    public int FirstTrack => _manifest.Tracks.Count == 0 ? 1 : _manifest.Tracks.Min(t => t.Number);
    public int LastTrack => _manifest.Tracks.Count == 0 ? 1 : _manifest.Tracks.Max(t => t.Number);
    public bool HasTracks => _manifest.Tracks.Count > 0;
    public int LeadoutLba => _manifest.LeadoutLba;
    public int DataSectors => _manifest.DataSectors;
    public IReadOnlyList<DiscTrack> Tracks => _manifest.Tracks
        .Select(t => new DiscTrack(t.Number, t.Kind, t.StartLba, t.SectorSize)).ToList();

    public bool TrackStartLba(int track, out int lba)
    {
        var found = _manifest.Tracks.Find(t => t.Number == track);
        lba = found?.StartLba ?? 0;
        return found != null;
    }

    public byte[] ReadSectorData(int lba, int size)
    {
        var output = new byte[size];
        var file = FindByLba(lba);
        if (_trace && _traceReads++ < 200)
            Console.WriteLine($"[loose] read lba={lba} size={size} file={file?.Path ?? "<hole>"}");
        if (file == null || size <= 0) return output;

        int sector = lba - file.Lba;
        if (file.Raw2336)
        {
            // CueBinImage returns the 2336 bytes beginning at the Mode 2 subheader for
            // XA callers, and begins ordinary 2048-byte reads eight bytes later.
            int sourceOffset = size >= 2329 ? 0 : 8;
            ReadAt(file, (long)sector * 2336 + sourceOffset, output);
        }
        else if (size <= 2048)
        {
            ReadAt(file, (long)sector * 2048, output);
        }
        else
        {
            // A normal ISO file has no XA subheader. Synthesize the same data position
            // inside a zeroed Mode 2 sector for callers asking for a raw sector.
            var data = new byte[2048];
            ReadAt(file, (long)sector * 2048, data);
            int at = Math.Min(8, output.Length);
            data.AsSpan(0, Math.Min(data.Length, output.Length - at)).CopyTo(output.AsSpan(at));
        }
        return output;
    }

    internal byte[] ReadLooseFile(string path)
    {
        var file = FindPath(path) ?? throw new FileNotFoundException($"loose-disc file not found: {path}");
        var result = new byte[file.Size];
        int done = 0;
        for (int sector = 0; done < result.Length; sector++)
        {
            byte[] data = ReadSectorData(file.Lba + sector, 2048);
            int count = Math.Min(2048, result.Length - done);
            data.AsSpan(0, count).CopyTo(result.AsSpan(done));
            done += count;
        }
        return result;
    }

    internal bool LocateLooseFile(string path, out int lba, out uint size)
    {
        var file = FindPath(path);
        if (_trace)
            Console.WriteLine($"[loose] locate {path} -> {(file == null ? "not found" : file.Path)}");
        lba = file?.Lba ?? 0;
        size = file?.Size ?? 0;
        return file != null;
    }

    internal string? FindLooseFile(string name)
    {
        string target = Path.GetFileName(CanonicalPath(name));
        return _manifest.Files.FirstOrDefault(f =>
            Path.GetFileName(CanonicalPath(f.Path)).Equals(target, StringComparison.OrdinalIgnoreCase))?.Path;
    }

    ManifestFile? FindPath(string path)
    {
        path = CanonicalPath(path);
        if (_byPath.TryGetValue(path, out var exact)) return exact;
        string basename = Path.GetFileName(path);
        return _manifest.Files.FirstOrDefault(f =>
            Path.GetFileName(CanonicalPath(f.Path)).Equals(basename, StringComparison.OrdinalIgnoreCase));
    }

    ManifestFile? FindByLba(int lba)
    {
        // The manifest is small (tens of files), and this preserves holes between
        // extents without pretending they belong to the preceding file.
        foreach (var file in _byLba)
        {
            int sectors = checked((int)((file.Size + 2047) / 2048));
            if (lba >= file.Lba && lba < file.Lba + sectors) return file;
            if (file.Lba > lba) break;
        }
        return null;
    }

    void ReadAt(ManifestFile file, long offset, byte[] output)
    {
        lock (_ioGate)
        {
            string path = HostPath(file.Path);
            if (!_streams.TryGetValue(path, out var stream))
                _streams[path] = stream = File.OpenRead(path);
            if (offset >= stream.Length) return;
            stream.Position = offset;
            int count = (int)Math.Min(output.Length, stream.Length - offset);
            stream.ReadExactly(output, 0, count);
        }
    }

    string HostPath(string relative)
    {
        string path = Path.GetFullPath(Path.Combine(_root, Normalize(relative).Replace('/', Path.DirectorySeparatorChar)));
        string prefix = _root.EndsWith(Path.DirectorySeparatorChar) ? _root : _root + Path.DirectorySeparatorChar;
        if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"loose-disc path escapes its root: {relative}");
        return path;
    }

    static string Normalize(string path) => path.TrimStart('/', '\\').Replace('\\', '/');

    static string CanonicalPath(string path) => string.Join('/', Normalize(path).Split('/').Select(part =>
    {
        int semicolon = part.IndexOf(';');
        return semicolon >= 0 ? part[..semicolon] : part;
    }));

    internal static JsonSerializerOptions JsonOptions() => new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter(JsonNamingPolicy.CamelCase) },
    };

    public void Dispose()
    {
        lock (_ioGate)
        {
            foreach (var stream in _streams.Values) stream.Dispose();
            _streams.Clear();
        }
    }
}

/// <summary>One-time importer from BIN/CUE or CHD to the loose runtime layout.</summary>
public static class LooseDiscImporter
{
    public static string Import(string imagePath, string outputDirectory, string gameId)
    {
        string output = Path.GetFullPath(outputDirectory);
        Directory.CreateDirectory(output);
        string manifestPath = Path.Combine(output, LooseDiscImage.ManifestName);
        if (File.Exists(manifestPath))
        {
            EnsureWad(output);
            return output;
        }

        Console.WriteLine($"[import] extracting {gameId} to loose files: {output}");
        using var fs = DiscFs.Open(imagePath);
        var files = fs.EnumerateFiles().ToList();
        var manifest = new LooseDiscImage.Manifest
        {
            GameId = gameId,
            LeadoutLba = fs.LeadoutLba,
            DataSectors = fs.DataSectors,
            Tracks = fs.Tracks.Select(t => new LooseDiscImage.ManifestTrack
            {
                Number = t.Number,
                Kind = t.Kind,
                StartLba = t.StartLba,
                SectorSize = t.SectorSize,
            }).ToList(),
        };

        foreach (var file in files)
        {
            string relative = file.Path.Replace('\\', '/');
            bool raw2336 = relative.EndsWith(".XA", StringComparison.OrdinalIgnoreCase) ||
                           relative.EndsWith(".STR", StringComparison.OrdinalIgnoreCase);
            string destination = Path.Combine(output, relative.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            long expected = raw2336 ? ((file.Size + 2047L) / 2048L) * 2336L : file.Size;

            if (!File.Exists(destination) || new FileInfo(destination).Length != expected)
            {
                Console.WriteLine($"[import] {relative}");
                if (raw2336)
                {
                    using var stream = File.Create(destination);
                    int sectors = checked((int)((file.Size + 2047) / 2048));
                    for (int i = 0; i < sectors; i++)
                        stream.Write(fs.ReadSectorData(file.Lba + i, 2336));
                }
                else
                {
                    File.WriteAllBytes(destination, fs.ReadFile(relative));
                }
            }

            manifest.Files.Add(new LooseDiscImage.ManifestFile
            {
                Path = relative,
                Lba = file.Lba,
                Size = file.Size,
                Raw2336 = raw2336,
            });
        }

        string temporary = manifestPath + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(manifest, LooseDiscImage.JsonOptions()));
        EnsureWad(output);
        File.Move(temporary, manifestPath, true);
        Console.WriteLine("[import] complete; the original image is no longer needed");
        return output;
    }

    public static void EnsureWad(string root)
    {
        string hedPath = Path.Combine(root, "CD.HED");
        string wadPath = Path.Combine(root, "CD.WAD");
        if (!File.Exists(hedPath) || !File.Exists(wadPath)) return;

        byte[] hed = File.ReadAllBytes(hedPath);
        using var wad = File.OpenRead(wadPath);
        string output = Path.Combine(root, "wad");
        Directory.CreateDirectory(output);
        int cursor = 0;
        int extracted = 0;
        // Retail HED tables use either a zero byte or 0xFF as the end marker.
        // SM1's final record is followed immediately by 0xFF at EOF.
        while (cursor < hed.Length && hed[cursor] != 0 && hed[cursor] != 0xFF)
        {
            int end = Array.IndexOf(hed, (byte)0, cursor);
            if (end < 0) throw new InvalidDataException("unterminated CD.HED name");
            string name = System.Text.Encoding.ASCII.GetString(hed, cursor, end - cursor);
            cursor = (end + 1 + 3) & ~3;
            if (cursor + 8 > hed.Length) throw new InvalidDataException("truncated CD.HED entry");
            uint offset = BitConverter.ToUInt32(hed, cursor);
            uint size = BitConverter.ToUInt32(hed, cursor + 4);
            cursor += 8;
            if ((ulong)offset + size > (ulong)wad.Length)
                throw new InvalidDataException($"CD.HED entry outside CD.WAD: {name}");
            if (!Path.GetFileName(name).Equals(name, StringComparison.Ordinal))
                throw new InvalidDataException($"unsafe CD.HED name: {name}");

            string destination = Path.Combine(output, name);
            if (!File.Exists(destination) || new FileInfo(destination).Length != size)
            {
                byte[] data = new byte[size];
                wad.Position = offset;
                wad.ReadExactly(data);
                File.WriteAllBytes(destination, data);
            }
            extracted++;
        }
        Console.WriteLine($"[import] {extracted} CD.WAD entries available as loose files");
    }
}
