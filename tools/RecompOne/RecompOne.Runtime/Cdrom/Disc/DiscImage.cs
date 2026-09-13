using RecompOne.Runtime.Cdrom.Chd;

namespace RecompOne.Runtime.Cdrom;

public static class DiscImage
{
    public static IDiscImage Open(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new ArgumentException("disc path i empty", nameof(path));
        if (!File.Exists(path) && !Directory.Exists(path))
            throw new FileNotFoundException($"disc image not found: {path}", path);

        if (Directory.Exists(path))
            return LooseDiscImage.Open(path);

        return Detect(path) switch
        {
            DiscFormat.Chd => ChdImage.Open(path),
            DiscFormat.CueBin => CueBinImage.Open(path),
            DiscFormat.Iso => SectorImage.Open(path),
            _ => throw new NotSupportedException($"unsupported disc format: {path}"),
        };
    }

    public static DiscFormat Detect(string path)
    {
        var ext = Path.GetExtension(path);
        if (ext.Equals(".chd", StringComparison.OrdinalIgnoreCase)) return DiscFormat.Chd;
        if (ext.Equals(".cue", StringComparison.OrdinalIgnoreCase)) return DiscFormat.CueBin;
        if (ext.Equals(".bin", StringComparison.OrdinalIgnoreCase) ||
            ext.Equals(".iso", StringComparison.OrdinalIgnoreCase)) return DiscFormat.Iso;
        if (Directory.Exists(path) && LooseDiscImage.IsLooseDirectory(path)) return DiscFormat.Loose;
        return HasChdMagic(path) ? DiscFormat.Chd : DiscFormat.Unknown;
    }

    private static bool HasChdMagic(string path)
    {
        try
        {
            using var s = File.OpenRead(path);
            Span<byte> magic = stackalloc byte[8];
            return s.Read(magic) == 8 && magic.SequenceEqual(ChdFile.Magic);
        }
        catch
        {
            return false;
        }
    }
}

public enum DiscFormat
{
    Unknown,
    CueBin,
    Chd,
    Loose,
    Iso,
}
