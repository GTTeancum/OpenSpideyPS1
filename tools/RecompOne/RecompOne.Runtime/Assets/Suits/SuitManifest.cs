using System.Buffers.Binary;
using System.Text.Json;

namespace RecompOne.Runtime.Assets.Suits;

/// <summary>Data-only reskins. No guest addresses, model binaries, scripts or assemblies.</summary>
public sealed record SuitManifest(string Id, string Name, string Description, int AbilityProfile,
    IReadOnlyDictionary<uint, string> Textures)
{
    public static readonly string[] Profiles =
        ["spiderman", "2099", "symbiote", "captain-universe", "unlimited",
         "bagman", "scarlet", "ben-reilly", "quick-change", "peter-parker"];
    public const long PixelBudget = 64L * 1024 * 1024;
    // Public paintable materials of the approved wingless DC Spider-Man donor.
    // The invisible-wing cutout is deliberately not a paintable body material.
    static readonly HashSet<uint> DonorMaterials =
        [0x9D39C02B, 0xD8425644, 0x29AF154F, 0xFBC5A5A0, 0x154B7D71, 0xF82D1471, 0x42991273, 0xD7669388];

    static void Fields(JsonElement element, params string[] allowed)
    {
        if (element.ValueKind != JsonValueKind.Object) throw new InvalidDataException("expected JSON object");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var p in element.EnumerateObject())
            if (!allowed.Contains(p.Name) || !seen.Add(p.Name))
                throw new InvalidDataException($"unknown or duplicate field '{p.Name}'");
    }

    static string Label(JsonElement element, string field, int max)
    {
        string s = element.GetProperty(field).GetString() ?? "";
        if (s.Length == 0 || s.Length > max || s.Any(c => c < 32 || c > 126))
            throw new InvalidDataException($"'{field}' must be 1..{max} printable ASCII characters");
        return s;
    }

    // Reject symlinks/junctions as well as traversal: the final file stays in this mod.
    public static string ContainedFile(string root, string relative)
    {
        if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.Contains(':'))
            throw new InvalidDataException("texture path must be relative");
        string[] parts = relative.Replace('\\', '/').Split('/');
        if (parts.Any(p => p is "" or "." or "..")) throw new InvalidDataException("unsafe texture path");
        string current = Path.GetFullPath(root);
        if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("mod directory cannot be a link");
        foreach (string part in parts)
        {
            current = Path.Combine(current, part);
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("mod paths cannot contain links");
        }
        return current;
    }

    public static (int Width, int Height) PngSize(ReadOnlySpan<byte> data)
    {
        if (data.Length < 33 || !data[..8].SequenceEqual(new byte[] {137,80,78,71,13,10,26,10}) ||
            BinaryPrimitives.ReadUInt32BigEndian(data[8..]) != 13 || !data.Slice(12,4).SequenceEqual("IHDR"u8))
            throw new InvalidDataException("expected PNG with IHDR");
        uint w = BinaryPrimitives.ReadUInt32BigEndian(data[16..]);
        uint h = BinaryPrimitives.ReadUInt32BigEndian(data[20..]);
        if (w == 0 || h == 0 || w > 4096 || h > 4096)
            throw new InvalidDataException("PNG dimensions must be 1..4096 (HD is host-side)");
        return ((int)w, (int)h);
    }

    public static SuitManifest Read(string path)
    {
        if (new FileInfo(path).Length > 32 * 1024) throw new InvalidDataException("manifest exceeds 32 KiB");
        string root = Path.GetDirectoryName(Path.GetFullPath(path))!;
        ContainedFile(root, Path.GetFileName(path));
        using var doc = JsonDocument.Parse(File.ReadAllBytes(path), new JsonDocumentOptions
            { CommentHandling = JsonCommentHandling.Skip, MaxDepth = 8 });
        var o = doc.RootElement;
        Fields(o, "version", "id", "name", "description", "donor", "abilities", "textures");
        if (o.GetProperty("version").GetInt32() != 1) throw new InvalidDataException("unsupported suit version");
        string id = Label(o, "id", 48);
        if (id.Any(c => !(c is >= 'a' and <= 'z' or >= '0' and <= '9' or '-')))
            throw new InvalidDataException("id must use lowercase letters, digits and hyphens");
        if (o.GetProperty("donor").GetString() != "dc-spiderman")
            throw new InvalidDataException("supported donor: dc-spiderman (installed, wingless SM1 actor)");
        var abilities = o.GetProperty("abilities");
        Fields(abilities, "profile");
        int profile = Array.IndexOf(Profiles, abilities.GetProperty("profile").GetString());
        if (profile < 0) throw new InvalidDataException("unknown SM1 ability profile");
        var textures = new Dictionary<uint, string>();
        var tex = o.GetProperty("textures");
        if (tex.ValueKind != JsonValueKind.Object) throw new InvalidDataException("textures must be an object");
        long total = 0;
        Span<byte> header = stackalloc byte[33];
        foreach (var p in tex.EnumerateObject())
        {
            if (p.Name.Length != 8 || !uint.TryParse(p.Name, System.Globalization.NumberStyles.HexNumber,
                    System.Globalization.CultureInfo.InvariantCulture, out uint material) || textures.Count >= 32)
                throw new InvalidDataException("texture keys must be eight-digit donor material IDs; max 32");
            if (!DonorMaterials.Contains(material)) throw new InvalidDataException("unknown paintable DC donor material");
            string relative = p.Value.GetString() ?? "";
            if (!relative.EndsWith(".png", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("PNG textures only");
            string file = ContainedFile(root, relative);
            if (new FileInfo(file).Length > 32 * 1024 * 1024) throw new InvalidDataException("PNG file exceeds 32 MiB");
            using var stream = File.OpenRead(file);
            stream.ReadExactly(header);
            var size = PngSize(header);
            total += (long)size.Width * size.Height * 4;
            if (total > PixelBudget) throw new InvalidDataException("suit exceeds 64 MiB decoded texture budget");
            if (!textures.TryAdd(material, file)) throw new InvalidDataException("duplicate material ID");
        }
        if (textures.Count == 0) throw new InvalidDataException("at least one external texture is required");
        return new(id, Label(o, "name", 18), Label(o, "description", 72), profile, textures);
    }

    public Dictionary<uint, ReplacementTexture> Decode()
    {
        var result = new Dictionary<uint, ReplacementTexture>();
        long total = 0;
        foreach (var (id, file) in Textures)
        {
            // Read bounded bytes once, then validate and decode those same bytes (no size-check/decode race).
            using var stream = File.OpenRead(file);
            if (stream.Length > 32 * 1024 * 1024) throw new InvalidDataException("PNG file exceeds 32 MiB");
            byte[] bytes = new byte[checked((int)stream.Length)];
            stream.ReadExactly(bytes);
            var size = PngSize(bytes);
            total += (long)size.Width * size.Height * 4;
            if (total > PixelBudget) throw new InvalidDataException("suit exceeds 64 MiB decoded texture budget");
            var image = StbImageSharp.ImageResult.FromMemory(bytes, StbImageSharp.ColorComponents.RedGreenBlueAlpha);
            if (image.Width != size.Width || image.Height != size.Height || image.Data.Length != size.Width * size.Height * 4)
                throw new InvalidDataException("PNG decode dimensions changed");
            result.Add(id, new ReplacementTexture { Width = size.Width, Height = size.Height, Rgba = image.Data });
        }
        return result;
    }
}
