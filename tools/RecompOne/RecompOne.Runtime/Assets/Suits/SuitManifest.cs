using System.Buffers.Binary;
using System.Text.Json;

namespace RecompOne.Runtime.Assets.Suits;

/// <summary>Data-only reskins. No guest addresses, model binaries, scripts or assemblies.</summary>
public sealed record SuitManifest(string Id, string Name, string Comments, string Model, int AbilityProfile,
    IReadOnlyDictionary<uint, string> Textures)
{
    public const string Sm1SpiderMan = "spiderman";
    public const string ScarletSpider = "scarlet-spider";
    public const string Symbiote = "symbiote";
    public const string QuickChange = "quick-change";
    public const string PeterParker = "peter-parker";
    public const string Sm2SpiderMan = "sm2-spiderman";
    public static readonly string[] Profiles =
        ["spiderman", "2099", "symbiote", "captain-universe", "unlimited",
         "bagman", "scarlet", "ben-reilly", "quick-change", "peter-parker"];
    public const long PixelBudget = 64L * 1024 * 1024;
    // Verbatim GAME POWERS lines from SM1 charbio.dat, in Profiles order.
    public static readonly string[][] PowerText =
    [
        ["SUPER STRENGTH", "SUPER AGILITY", "STICK TO WALLS", "SPIDER SENSE"],
        ["ENHANCED STRENGTH"], ["UNLIMITED WEBBING"],
        ["INVULNERABLE", "ENHANCED STRENGTH", "UNLIMITED WEBBING"],
        ["STEALTH MODE"], ["NO SPIDEY BELT"], ["NONE"], ["NONE"],
        ["NO SPIDEY BELT"], ["NO SPIDEY BELT"]
    ];

    public static string[] WrapComments(string value)
    {
        var lines = new List<string>();
        string line = "";
        foreach (string word in value.ToUpperInvariant().Split(' ', StringSplitOptions.RemoveEmptyEntries))
        {
            string remaining = word;
            if (line.Length > 0 && line.Length + remaining.Length + 1 > 18)
            { lines.Add(line); line = ""; }
            while (remaining.Length > 18)
            { lines.Add(remaining[..18]); remaining = remaining[18..]; }
            line = line.Length == 0 ? remaining : line + " " + remaining;
        }
        if (line.Length > 0) lines.Add(line);
        return lines.ToArray();
    }
    // Fixed, executable-owned model and material rules. JSON selects one name; it
    // cannot supply an asset path, hash allowlist, guest address or model binary.
    // The SM1 default's invisible-wing cutout is deliberately not paintable.
    public static readonly IReadOnlyDictionary<string, IReadOnlySet<uint>> PlayerModels =
        new Dictionary<string, IReadOnlySet<uint>>(StringComparer.Ordinal)
        {
            [Sm1SpiderMan] = new HashSet<uint>
                { 0x9D39C02B, 0xD8425644, 0x29AF154F, 0xFBC5A5A0, 0x154B7D71, 0xF82D1471, 0x42991273, 0xD7669388 },
            [ScarletSpider] = new HashSet<uint>
                { 0x1778DB9A, 0x5F0D20A8, 0xC5EE3A18, 0x36A50094, 0x11EA6D65, 0x8C50A625, 0x7A72B1C7, 0x2CFFB514, 0x3BACB315, 0x496BA159 },
            [Symbiote] = new HashSet<uint>
                { 0xF4D27622, 0x9CDEB9B5, 0x05D5A779, 0x71BEC0C6, 0xB673BFC9, 0x1CDD4E95, 0x773F88DF, 0x8F41CBF0 },
            [QuickChange] = new HashSet<uint>
                { 0x578DEAB3, 0x0F90CC4B, 0xAA7AD3C0, 0xBC7032AA, 0x69D50075, 0x1CDDE71B, 0x86DC7A99, 0x5EDAA6D9, 0x8F403460 },
            [PeterParker] = new HashSet<uint>
                { 0x578DF3D3, 0x0F9094E3, 0xAA7AB050, 0xBC7032AA, 0x69D50075, 0xB5ABA1F5, 0x00AB3AFD, 0x38EDDC02,
                  0xCC2C8B5B, 0xCAD400D7, 0x5ED98A8F, 0x99D83224 },
            [Sm2SpiderMan] = new HashSet<uint>
                { 0xE9587C6D, 0x197BC27A, 0x21AFE1A6, 0x4E1E5E1A, 0x3BC194AE, 0x1527743E, 0x08BD6474, 0xDC38D248,
                  0xCEB60740, 0x3ED5F30B, 0x1A501534, 0x933EF22C, 0x42985F7A, 0x7FFB7AAD },
        };

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

    public static SuitManifest Read(string path) => Read(path, Profiles, PowerText, PlayerModels, Sm1SpiderMan);

    // Game-owned allowlists only; a manifest cannot supply model paths, memory
    // addresses, or a new power implementation. Keep SM1 as the default policy.
    public static SuitManifest Read(string path, string[] profiles, string[][] powerText,
        IReadOnlyDictionary<string, IReadOnlySet<uint>> playerModels, string defaultModel)
    {
        if (new FileInfo(path).Length > 32 * 1024) throw new InvalidDataException("manifest exceeds 32 KiB");
        string root = Path.GetDirectoryName(Path.GetFullPath(path))!;
        ContainedFile(root, Path.GetFileName(path));
        using var doc = JsonDocument.Parse(File.ReadAllBytes(path), new JsonDocumentOptions
            { CommentHandling = JsonCommentHandling.Skip, MaxDepth = 8 });
        var o = doc.RootElement;
        Fields(o, "version", "id", "name", "comments", "model", "abilities", "textures");
        if (o.GetProperty("version").GetInt32() != 1) throw new InvalidDataException("unsupported suit version");
        string id = Label(o, "id", 48);
        if (id.Any(c => !(c is >= 'a' and <= 'z' or >= '0' and <= '9' or '-')))
            throw new InvalidDataException("id must use lowercase letters, digits and hyphens");
        string model = o.TryGetProperty("model", out var modelProperty)
            ? modelProperty.GetString() ?? ""
            : defaultModel;
        if (!playerModels.TryGetValue(model, out var donorMaterials))
            throw new InvalidDataException(
                "unknown player model; expected " + string.Join(", ", playerModels.Keys));
        var abilities = o.GetProperty("abilities");
        Fields(abilities, "profile");
        int profile = Array.IndexOf(profiles, abilities.GetProperty("profile").GetString());
        if (profile < 0) throw new InvalidDataException("unknown ability profile for this game");
        string comments = o.GetProperty("comments").GetString() ?? "";
        if (comments.Length > 72 || comments.Any(c => c < 32 || c > 126))
            throw new InvalidDataException("comments must be at most 72 printable ASCII characters");
        int availableLines = 11 - 4 - powerText[profile].Length;
        if (WrapComments(comments).Length > availableLines)
            throw new InvalidDataException($"comments do not fit beneath this donor's powers; shorten to {availableLines} lines of 18 characters");
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
            if (!donorMaterials.Contains(material)) throw new InvalidDataException("unknown paintable DC donor material");
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
        return new(id, Label(o, "name", 18), comments, model, profile, textures);
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
