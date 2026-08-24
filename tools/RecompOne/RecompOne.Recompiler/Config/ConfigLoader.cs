using System.Text.Json;
using System.Text.Json.Serialization;

namespace RecompOne.Recompiler.Config;

public sealed class RecompOneConfig
{
    [JsonPropertyName("game")] public GameConfig Game { get; set; } = new();
    [JsonPropertyName("cue")] public string Cue { get; set; } = "";
    [JsonPropertyName("elf")] public string? Elf { get; set; }
    [JsonPropertyName("map")] public string? Map { get; set; }
    [JsonPropertyName("funcMap")] public string? FuncMap { get; set; }
    [JsonPropertyName("main")] public string? Main { get; set; }
    [JsonPropertyName("functions")] public FunctionEntry[] Functions { get; set; } = [];
    [JsonPropertyName("linearSweep")] public bool LinearSweep { get; set; } //linear sweep is to find functions when the elf doesnt ptovide then properly (fuck you sh) this can and WILL get some data as code, use it by your own risk
    [JsonPropertyName("debug")] public bool Debug { get; set; }
    [JsonPropertyName("callRing")] public bool CallRing { get; set; }
    [JsonPropertyName("addressComments")] public bool AddressComments { get; set; }
    [JsonPropertyName("disasmComments")] public bool DisasmComments { get; set; }
    [JsonPropertyName("overlays")] public OverlayConfig[] Overlays { get; set; } = [];
    [JsonPropertyName("stubs")] public string[] Stubs { get; set; } = [];
    [JsonPropertyName("ignored")] public string[] Ignored { get; set; } = [];
    [JsonPropertyName("patches")] public PatchEntry[] Patches { get; set; } = [];
}

public sealed class PatchEntry
{
    [JsonPropertyName("overlay")]
    [JsonConverter(typeof(StringOrArrayConverter))]
    public string[] Overlay { get; set; } = []; //list or single one, * for wildcard so can have the same patch being applied in all overlays containing this function

    [JsonPropertyName("function")] public string Function { get; set; } = "";
    [JsonPropertyName("address")] public string Address { get; set; } = "";
    [JsonPropertyName("target")] public string Target { get; set; } = "";
    [JsonPropertyName("mode")] public string Mode { get; set; } = "replace";

    public bool MatchesOverlay(string overlayName)
    {
        if (Overlay.Length == 0) return true;
        foreach (var o in Overlay)
        {
            if (o == "*") return true;
            if (string.Equals(o, overlayName, StringComparison.OrdinalIgnoreCase)) return true;
        }
        return false;
    }

    public string OverlayLabel => Overlay.Length == 0 ? "" : string.Join(",", Overlay);
}

public sealed class StringOrArrayConverter : JsonConverter<string[]>
{
    public override string[] Read(ref Utf8JsonReader reader, Type type, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.String)
        {
            var s = reader.GetString();
            return string.IsNullOrEmpty(s) ? [] : [s];
        }

        if (reader.TokenType == JsonTokenType.StartArray)
        {
            var list = new List<string>();
            while (reader.Read() && reader.TokenType != JsonTokenType.EndArray)
                if (reader.TokenType == JsonTokenType.String)
                {
                    var s = reader.GetString();
                    if (!string.IsNullOrEmpty(s)) list.Add(s);
                }
            return list.ToArray();
        }

        return [];
    }

    
    public override void Write(Utf8JsonWriter writer, string[] value, JsonSerializerOptions options)
    {
        if (value.Length == 1) { writer.WriteStringValue(value[0]); return; }
        writer.WriteStartArray();
        foreach (var v in value) writer.WriteStringValue(v);
        writer.WriteEndArray();
    }
}

public sealed class GameConfig
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("output")] public string Output { get; set; } = "./Recompiled";
}

public sealed class OverlayConfig
{
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("elf")] public string? Elf { get; set; }
    [JsonPropertyName("map")] public string? Map { get; set; }
    [JsonPropertyName("funcMap")] public string? FuncMap { get; set; }
    [JsonPropertyName("base")] public string? Base { get; set; }
    [JsonPropertyName("file")] public string? File { get; set; }
    // A local file holding the overlay image already in the form it has in RAM.
    // Games that relocate an overlay while loading it have no byte range on the disc
    // that matches what actually executes, so the bytes have to be prepared outside.
    [JsonPropertyName("path")] public string? Path { get; set; }
    [JsonPropertyName("offset")] public int Offset { get; set; } = 0;
    [JsonPropertyName("skip")] public int Skip { get; set; } = 0;
    [JsonPropertyName("lba")] public int Lba { get; set; } = -1;
    [JsonPropertyName("size")] public int? Size { get; set; }
    [JsonPropertyName("decrypt")] public bool Decrypt { get; set; }
    [JsonPropertyName("rebase")] public int Rebase { get; set; } = 0;
    [JsonPropertyName("functions")] public FunctionEntry[] Functions { get; set; } = [];
    [JsonPropertyName("linearSweep")] public bool? LinearSweep { get; set; }
    [JsonPropertyName("debug")] public bool? Debug { get; set; }
    [JsonPropertyName("stubs")] public string[] Stubs { get; set; } = [];
    [JsonPropertyName("ignored")] public string[] Ignored { get; set; } = [];
}

public sealed class FunctionEntry
{
    [JsonPropertyName("address")] public string Address { get; set; } = "";
    [JsonPropertyName("name")] public string? Name { get; set; }
}

public static class ConfigLoader
{
    private static readonly JsonSerializerOptions Options = new()
    {
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
        PropertyNameCaseInsensitive = true,
    };

    public static RecompOneConfig Load(string path)
    {
        using var stream = File.OpenRead(path);
        return JsonSerializer.Deserialize<RecompOneConfig>(stream, Options)
            ?? throw new InvalidDataException($"failed to parse config {path}");
    }
}
