using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace RecompOne.Runtime.Cdrom;

public static class BundledAssets
{
    const string MarkerName = ".payload-sha256";
    const string ManifestName = "bundle.json";
    sealed record OwnedAsset(string Path, string Sha256);

    static string ResolveAsset(string target, string relative)
    {
        string normalized = relative.Replace('/', Path.DirectorySeparatorChar);
        string destination = Path.GetFullPath(Path.Combine(target, normalized));
        string prefix = target.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (Path.IsPathRooted(normalized) || !destination.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"bundled asset escapes its root: {relative}");
        return destination;
    }

    static List<OwnedAsset> ReadOwnership(string target)
    {
        string manifest = Path.Combine(target, ManifestName);
        if (!File.Exists(manifest)) return [];
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(manifest));
            var result = new List<OwnedAsset>();
            if (!doc.RootElement.TryGetProperty("files", out var files)) return result;
            foreach (var file in files.EnumerateArray())
            {
                string? path = file.GetProperty("path").GetString();
                string? hash = file.GetProperty("sha256").GetString();
                if (path is null || hash is null) continue;
                ResolveAsset(target, path);
                result.Add(new(path, hash));
            }
            return result;
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or KeyNotFoundException or InvalidDataException)
        {
            // Invalid ownership metadata never authorizes moving arbitrary files.
            Console.WriteLine($"[assets] previous ownership unavailable; preserving existing files: {ex.Message}");
            return [];
        }
    }

    static bool Matches(ZipArchiveEntry entry, string installed)
    {
        if (!File.Exists(installed) || new FileInfo(installed).Length != entry.Length) return false;
        using var source = entry.Open();
        using var current = File.OpenRead(installed);
        return SHA256.HashData(source).AsSpan().SequenceEqual(SHA256.HashData(current));
    }

    public static void Extract(Stream payload, string targetDirectory,
        IProgress<LooseDiscImporter.Progress>? progress, CancellationToken cancellationToken)
    {
        using var memory = new MemoryStream();
        payload.CopyTo(memory);
        byte[] bytes = memory.ToArray();
        string hash = Convert.ToHexString(SHA256.HashData(bytes));
        string target = Path.GetFullPath(targetDirectory);
        string marker = Path.Combine(target, MarkerName);
        Directory.CreateDirectory(target);
        using var archive = new ZipArchive(new MemoryStream(bytes, writable: false), ZipArchiveMode.Read);
        var entries = archive.Entries.Where(e => !e.FullName.EndsWith('/'))
            .Select(e => (Entry: e, Destination: ResolveAsset(target, e.FullName))).ToArray();
        var destinations = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in entries)
            if (!destinations.Add(entry.Destination))
                throw new InvalidDataException($"duplicate bundled asset: {entry.Entry.FullName}");
        cancellationToken.ThrowIfCancellationRequested();
        if (File.Exists(marker) && File.ReadAllText(marker).Trim().Equals(hash, StringComparison.OrdinalIgnoreCase)
            && entries.All(e => Matches(e.Entry, e.Destination))) return;

        var previous = ReadOwnership(target);
        long total = entries.Sum(e => e.Entry.Length), completed = 0;
        int files = 0;
        void ExtractEntry((ZipArchiveEntry Entry, string Destination) item)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Directory.CreateDirectory(Path.GetDirectoryName(item.Destination)!);
            string temporary = item.Destination + ".partial";
            using (Stream source = item.Entry.Open())
            using (var output = File.Create(temporary))
            {
                byte[] buffer = new byte[128 * 1024];
                int count;
                while ((count = source.Read(buffer, 0, buffer.Length)) > 0)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    output.Write(buffer, 0, count);
                    completed += count;
                    progress?.Report(new("Installing bundled upgrades", item.Entry.FullName,
                        files, entries.Length, completed, total));
                }
            }
            File.Move(temporary, item.Destination, true);
            files++;
        }

        // Keep the old ownership manifest until all obsolete files have been handled.
        // Cancellation/retry therefore retains the information needed for retirement.
        foreach (var item in entries.Where(e => !e.Entry.FullName.Equals(ManifestName, StringComparison.OrdinalIgnoreCase)))
            ExtractEntry(item);
        string retiredRoot = Path.Combine(target, ".retired", Guid.NewGuid().ToString("N"));
        foreach (var old in previous)
        {
            cancellationToken.ThrowIfCancellationRequested();
            string installed = ResolveAsset(target, old.Path);
            if (destinations.Contains(installed) || !File.Exists(installed)) continue;
            string installedHash;
            using (var current = File.OpenRead(installed))
                installedHash = Convert.ToHexString(SHA256.HashData(current));
            if (!installedHash.Equals(old.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                Console.WriteLine($"[assets] preserving modified obsolete file: {old.Path}");
                continue;
            }
            string retired = ResolveAsset(retiredRoot, old.Path);
            Directory.CreateDirectory(Path.GetDirectoryName(retired)!);
            File.Move(installed, retired);
            Console.WriteLine($"[assets] retired obsolete bundled file: {old.Path}");
        }
        foreach (var item in entries.Where(e => e.Entry.FullName.Equals(ManifestName, StringComparison.OrdinalIgnoreCase)))
            ExtractEntry(item);
        string temporaryMarker = marker + ".tmp";
        File.WriteAllText(temporaryMarker, hash);
        File.Move(temporaryMarker, marker, true);
    }
}
