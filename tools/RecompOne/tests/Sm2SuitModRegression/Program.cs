using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Recompiled;
using RecompOne.Runtime.Assets.Suits;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

string root = Path.GetFullPath(args[0]);
string work = Path.Combine(root, "proof_render/magenta-man/sm2-regression-" + DateTime.UtcNow.ToString("yyyyMMddHHmmssfff"));
string dir = Path.Combine(work, "example");
Directory.CreateDirectory(dir);
string sample = Path.Combine(root, "mods/samples/magenta-man-sm2/suit.json");
var fixture = SuitManifest.Read(sample, SuitRules.Profiles, SuitRules.PowerText,
    SuitRules.Models, SuitManifest.Sm2SpiderMan);
int tests = 0;
void Check(bool condition, string label)
{
    if (!condition) throw new Exception("FAIL: " + label);
    tests++;
    Console.WriteLine("PASS: " + label);
}
Check(fixture.Textures.Count == 14 && fixture.Decode().Values.Any(t => t.Width == 2048), "fourteen external materials, real 2048 decode");
File.Copy(fixture.Textures.First().Value, Path.Combine(dir, "small.png"));
var json = JsonNode.Parse(File.ReadAllText(sample), documentOptions: new JsonDocumentOptions { CommentHandling = JsonCommentHandling.Skip })!;
json["textures"] = new JsonObject { [fixture.Textures.First().Key.ToString("X8")] = "small.png" };
string clean = json.ToJsonString(), path = Path.Combine(dir, "suit.json");
File.WriteAllText(path, clean);
var noModel = JsonNode.Parse(clean)!;
noModel.AsObject().Remove("model");
File.WriteAllText(path, noModel.ToJsonString());
Check(SuitManifest.Read(path, SuitRules.Profiles, SuitRules.PowerText,
    SuitRules.Models, SuitManifest.Sm2SpiderMan).Model == SuitManifest.Sm2SpiderMan,
    "missing model remains backward-compatible with SM2 Spider-Man");
File.WriteAllText(path, clean);
foreach (var (modelId, materials) in SuitRules.Models)
{
    var modelDoc = JsonNode.Parse(clean)!;
    modelDoc["model"] = modelId;
    modelDoc["textures"] = new JsonObject { [materials.First().ToString("X8")] = "small.png" };
    File.WriteAllText(path, modelDoc.ToJsonString());
    Check(SuitManifest.Read(path, SuitRules.Profiles, SuitRules.PowerText,
        SuitRules.Models, SuitManifest.Sm2SpiderMan).Model == modelId,
        "fixed player model accepted: " + modelId);
}
File.WriteAllText(path, clean);
Environment.SetEnvironmentVariable("SPIDEY_SUIT_MOD_DIR", work);
SuitMods.Install();
Check(Costume.ViewerCount == 20 && SuitMods.MaxCount - SuitMods.StockCount == 12, "nineteen original costumes plus twelve mod slots");
var memory = new PSMemory(0x800000);
const uint selected = 0x800B31F2, unlocks = 0x800B31F8;
memory.WriteU32(unlocks, 1);
byte[] shell = File.ReadAllBytes(Path.Combine(root, "spiderman2/config/overlays/shell.bin"));
for (uint i = 0; i < shell.Length; i++) memory.WriteU8(0x8023D000 + i, shell[i]);
Check(Costume.IsUnlocked(memory, 19) && !Costume.IsUnlocked(memory, 1), "mod unlocked without changing retail unlock bits");
string[] sections = Encoding.ASCII.GetString(File.ReadAllBytes(Path.Combine(root, "spiderman2/extracted/wad/charbio.dat")))
    .Split((char)1).Where(s => s.Contains("Game Powers:\0")).ToArray();
Check(sections.Length == 19, "nineteen original power descriptions");
for (int profile = 0; profile < 19; profile++)
{
    Costume.WriteSelected(memory, 0);
    SuitMods.Catalogue[0] = fixture with { AbilityProfile = profile };
    byte[] before = memory.Ram.ToArray();
    Costume.WriteSelected(memory, 19);
    Check(Costume.ReadSelected(memory) == 19 && memory.ReadU8(selected) == profile, "safe native proxy: " + SuitRules.Profiles[profile]);
    bool confined = true;
    for (int p = 0; p < before.Length; p++)
        if (before[p] != memory.Ram[p] && !(p >= 0xB31F2 && p < 0xB31F6) && !(p >= 0xC2210 && p < 0xC222C)) confined = false;
    Check(confined && memory.ReadU32(unlocks) == 1, "writes confined to known selection/power fields");
    // Execute the ORIGINAL game's power-ID decoder as the behavioral oracle.
    uint[] flags = Enumerable.Range(0, 7).Select(i => memory.ReadU32(0x800C2210 + (uint)i * 4)).ToArray();
    Recompiled.SpiderMan2.func_80249168(new CpuContext(), memory);
    Check(flags.SequenceEqual(Enumerable.Range(0,7).Select(i => memory.ReadU32(0x800C2210 + (uint)i*4))), "native power decoder parity");
    Costume.TextureLibraryLoaded(new CpuContext { GP = 0x80090000 }, memory);
    Check(Costume.LoadedCostume == 19 && memory.ReadU32(0x80090AA8) == profile + 1,
        "appearance completion preserves native one-based electrical-resistance identity");
    // charbio storage order differs from the viewer: Ross red/white and
    // Symbiote/2099 are swapped. Resolve by the original entry key, not position.
    string[] keys = ["spider-man", "phoenix", "prodigy", "dusk", "insulated", "ross-red", "ross-white",
        "venom2", "inverse", "Symbiote spider-man", "Spider-man 2099", "Captain Universe", "Spidey unlimited",
        "Amazing bag man", "Scarlet Spidey", "Ben Riley", "Quick Change Spidey", "Peter Parker", "Battle Damaged"];
    string section = sections.Single(s => s.StartsWith(keys[profile] + '\0'));
    string[] powers = section.Split("Game Powers:\0\u0002DDd")[1]
        .Split("\u0002ii\0Comments:")[0].TrimEnd('\0').ToUpperInvariant().Split('\0');
    Check(SuitRules.PowerText[profile].SequenceEqual(powers), "original GAME POWERS wording: " + SuitRules.Profiles[profile]);
    Costume.PrepareViewer(new CpuContext(), memory);
    Check(memory.ReadU32(Costume.ViewerTable + 19*12) >= Costume.ViewerTable + 0x800, "mod text stays in dedicated arena");
}
for (int i = 0; i < 19; i++)
{
    Costume.WriteSelected(memory, i);
    Check(SuitMods.Active == -1 && memory.ReadU8(selected) == i && memory.ReadU32(unlocks) == 1, "stock selection restored: " + i);
}
foreach (var mutation in new Action<JsonNode>[] {
    d => d["donor"] = "other-model", d => d["address"] = "0x80010000",
    d => d["abilities"]!["profile"] = "arbitrary", d => d["textures"] = new JsonObject { ["9D39C02B"] = "small.png" },
    d => d["textures"] = new JsonObject { ["E9587C6D"] = "../small.png" }
})
{
    var doc = JsonNode.Parse(clean)!;
    mutation(doc); File.WriteAllText(path, doc.ToJsonString());
    bool rejected = false;
    try { SuitManifest.Read(path, SuitRules.Profiles, SuitRules.PowerText,
        SuitRules.Models, SuitManifest.Sm2SpiderMan); } catch { rejected = true; }
    Check(rejected, "unsafe or wrong-game manifest rejected");
}
Console.WriteLine($"PASS: {tests} assertions; {work}");
