using System.Buffers.Binary;
using System.Text.Json;
using System.Text.Json.Nodes;
using Recompiled;
using RecompOne.Runtime.Assets.Suits;
using RecompOne.Runtime.Assets.Textures;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

string root = Path.GetFullPath(args[0]);
string sample = Path.Combine(root, "mods/samples/magenta-man");
string work = Path.Combine(root, "proof_render/magenta-man/regression-" + DateTime.UtcNow.ToString("yyyyMMddHHmmssfff"));
string dir = Path.Combine(work, "test-suit");
Directory.CreateDirectory(dir);
File.Copy(Path.Combine(sample, "textures/FBC5A5A0.png"), Path.Combine(dir, "small.png"));
var document = JsonNode.Parse(File.ReadAllText(Path.Combine(sample, "suit.json")), documentOptions:
    new JsonDocumentOptions { CommentHandling = JsonCommentHandling.Skip })!;
document["textures"] = new JsonObject { ["FBC5A5A0"] = "small.png" };
string clean = document.ToJsonString();
string manifest = Path.Combine(dir, "suit.json");
File.WriteAllText(manifest, clean);
int tests = 0;
void Check(bool condition, string label)
{
    if (!condition) throw new Exception("FAIL: " + label);
    tests++;
    Console.WriteLine("PASS: " + label);
}
void Reject(Action<JsonNode> mutate, string label)
{
    var doc = JsonNode.Parse(clean)!;
    mutate(doc);
    File.WriteAllText(manifest, doc.ToJsonString());
    bool rejected = false;
    try { SuitManifest.Read(manifest); } catch { rejected = true; }
    Check(rejected, label);
    File.WriteAllText(manifest, clean);
}
Check(SuitManifest.Read(Path.Combine(sample, "suit.json")).Decode().Values.Any(t => t.Width == 2048 && t.Height == 2048), "real 2048 PNG decoded at full dimensions");
Check(document["donor"] == null, "DC default Spider-Man is implicit; sample has no donor field");
var noModel = JsonNode.Parse(clean)!;
noModel.AsObject().Remove("model");
File.WriteAllText(manifest, noModel.ToJsonString());
Check(SuitManifest.Read(manifest).Model == SuitManifest.Sm1SpiderMan,
    "missing model remains backward-compatible with SM1/DC Spider-Man");
File.WriteAllText(manifest, clean);
foreach (var (modelId, materials) in SuitManifest.PlayerModels)
{
    var modelDoc = JsonNode.Parse(clean)!;
    modelDoc["model"] = modelId;
    modelDoc["textures"] = new JsonObject { [materials.First().ToString("X8")] = "small.png" };
    File.WriteAllText(manifest, modelDoc.ToJsonString());
    Check(SuitManifest.Read(manifest).Model == modelId, "fixed player model accepted: " + modelId);
}
File.WriteAllText(manifest, clean);
Check(TextureResolver.TextureWindowExtent(63) == 64 && TextureResolver.TextureWindowExtent(31) == 32 && TextureResolver.TextureWindowExtent(255) == 256, "PS1 texture window mask yields correct replacement extent (not 193/225)");
Reject(d => d["donor"] = "../../unsafe.psx", "arbitrary model files rejected");
Reject(d => d["model"] = "../../unsafe.psx", "model selector rejects paths and arbitrary identifiers");
Reject(d => d["address"] = "0x80010000", "raw address fields rejected");
Reject(d => d["abilities"]!["profile"] = "sm2-electric-web", "unknown ability profile rejected");
Reject(d => d["name"] = "BAD\u0002TEXT", "selector control bytes rejected");
Reject(d => d["comments"] = "BAD\u0002TEXT", "comment control bytes rejected");
Reject(d => d["comments"] = new string('W', 72), "comments that would overflow the default donor pane rejected");
var emptyComments = JsonNode.Parse(clean)!;
emptyComments["comments"] = "";
File.WriteAllText(manifest, emptyComments.ToJsonString());
Check(SuitManifest.Read(manifest).Comments == "", "author may leave comments empty");
File.WriteAllText(manifest, clean);
Reject(d => d["textures"]!["FBC5A5A0"] = "../outside.png", "path traversal rejected");
Reject(d => d["textures"]!["FBC5A5A0"] = "C:/outside.png", "absolute path rejected");
Reject(d => d["textures"]!["FBC5A5A0"] = "small.png:stream", "alternate file stream rejected");
Reject(d => d["textures"]!["12345678"] = "small.png", "unknown donor material rejected");
File.WriteAllText(manifest, clean.Replace("\"version\":1", "\"version\":1,\"version\":1"));
bool duplicate = false;
try { SuitManifest.Read(manifest); } catch { duplicate = true; }
Check(duplicate, "duplicate JSON fields rejected");
File.WriteAllText(manifest, clean);
byte[] huge = File.ReadAllBytes(Path.Combine(dir, "small.png"));
BinaryPrimitives.WriteUInt32BigEndian(huge.AsSpan(16), 0xffffffff);
File.WriteAllBytes(Path.Combine(dir, "huge.png"), huge);
Reject(d => d["textures"]!["FBC5A5A0"] = "huge.png", "oversized PNG rejected before decoding");
byte[] budgetHeader = (byte[])huge.Clone();
BinaryPrimitives.WriteUInt32BigEndian(budgetHeader.AsSpan(16), 4096);
BinaryPrimitives.WriteUInt32BigEndian(budgetHeader.AsSpan(20), 4096);
File.WriteAllBytes(Path.Combine(dir, "budget.png"), budgetHeader);
Reject(d => d["textures"] = new JsonObject { ["FBC5A5A0"] = "budget.png", ["9D39C02B"] = "budget.png" }, "aggregate decoded budget rejected before decoding");
var invalid = SuitManifest.Read(manifest);
File.WriteAllBytes(Path.Combine(dir, "small.png"), huge);
bool changed = false;
try { invalid.Decode(); } catch { changed = true; }
Check(changed, "PNG revalidated at activation after on-disk changes");
File.Copy(Path.Combine(sample, "textures/FBC5A5A0.png"), Path.Combine(dir, "small.png"), true);
Environment.SetEnvironmentVariable("SPIDEY_SUIT_MOD_DIR", work);
SuitMods.Install();
Check(Costume.ViewerCount == 21, "mod appended without replacing twenty stock suits");
var memory = new PSMemory(0x800000);
const uint selected = 0x800A5704, unlocks = 0x800A5708, player = 0x80100000;
memory.WriteU32(unlocks, 1);
Check(Costume.IsUnlocked(memory, 20) && !Costume.IsUnlocked(memory, 1), "mod unlocked with only default stock suit unlocked");
foreach (var (modelId, asset) in new[]
{
    (SuitManifest.Sm1SpiderMan, "spidey.psx"),
    (SuitManifest.ScarletSpider, "spscar.psx"),
    (SuitManifest.Symbiote, "spsymbi.psx"),
    (SuitManifest.QuickChange, "spquick.psx"),
    (SuitManifest.PeterParker, "sppark.psx"),
    (SuitManifest.Sm2SpiderMan, "sp2default.psx"),
})
{
    SuitMods.Catalogue[0] = SuitMods.Catalogue[0] with { Model = modelId };
    Costume.WriteSelected(memory, 20);
    Check(Costume.DreamcastAssetFor("spidey.psx", memory) == asset,
        "mod routes to fixed bundled actor: " + modelId);
}
uint[] configs = [0x00202040,0x00402020,0x00200000,0x00404040,0x00402020,0x00403030,0x00202040,0x00402020,0x00200000,0x00200000];
for (byte i = 0; i < 10; i++)
{
    Costume.WriteSelected(memory, 0);
    SuitMods.Catalogue[0] = SuitMods.Catalogue[0] with { AbilityProfile = i };
    byte[] before = memory.Ram.ToArray();
    Costume.WriteSelected(memory, 20);
    Costume.ApplyAbilityProfile(new CpuContext { V0 = player }, memory);
    Check(Costume.ReadSelected(memory) == 20 && memory.ReadU8(selected) == 0 && memory.ReadU8(selected + 1) == 0 && memory.ReadU32(player + 0x584) == configs[i], "profile copied without loading a retail costume overlay, safe uninstall fallback: " + SuitManifest.Profiles[i]);
    bool confined = true;
    for (int p = 0; p < before.Length; p++)
        if (before[p] != memory.Ram[p] && !(p >= 0xA5704 && p < 0xA5708) && !(p >= 0x100584 && p < 0x100588)) confined = false;
    Check(confined && memory.ReadU32(unlocks) == 1, "only fixed selection/config fields written; no texture bytes in guest RAM");
}
Check(File.ReadAllText(Path.Combine(work, "selected-suit.txt")) == "magenta-man", "host selection stored by stable ID");
Costume.PrepareViewer(new CpuContext(), memory);
Check(memory.ReadU32(Costume.ViewerTable + 20 * 12) >= Costume.ViewerTable + 0x800, "mod label stored in port-owned selector arena");
// Use retail data and functions as the UI oracle, not a hand-designed layout.
byte[] bio = File.ReadAllBytes(Path.Combine(root, "spiderman/extracted/wad/charbio.dat"));
string[] costumeSections = System.Text.Encoding.ASCII.GetString(bio).Split((char)1)
    .Where(s => s.Contains("Game Powers:\0")).ToArray();
Check(costumeSections.Length == 10, "ten original ability-donor descriptions found");
for (int profile = 0; profile < 10; profile++)
{
    string[] originalPowers = costumeSections[profile].Split("Game Powers:\0\u0002DDd")[1]
        .Split("\u0002ii\0Comments:")[0].TrimEnd('\0').ToUpperInvariant().Split('\0');
    Check(SuitManifest.PowerText[profile].SequenceEqual(originalPowers), "donor power wording matches retail: " + SuitManifest.Profiles[profile]);
    SuitMods.Catalogue[0] = SuitMods.Catalogue[0] with { AbilityProfile = profile, Comments = "Made by Jane. Enjoy!" };
    Costume.PrepareViewer(new CpuContext(), memory);
    uint p = memory.ReadU32(Costume.ViewerTable + 20 * 12 + 4);
    var lines = new List<string>();
    while (memory.ReadU8(p) != 255)
    {
        if (memory.ReadU8(p) == 2) { p += 4; continue; }
        string line = "";
        while (memory.ReadU8(p) != 0) line += (char)memory.ReadU8(p++);
        p++;
        lines.Add(line);
    }
    string[] expected = ["COSTUME:", "MAGENTA MAN", "GAME POWERS:", ..originalPowers,
        "COMMENTS:", ..SuitManifest.WrapComments("Made by Jane. Enjoy!")];
    Check(lines.SequenceEqual(expected) && lines.Count <= 11,
        "stock-style sections, automatic donor powers and author's comments: " + SuitManifest.Profiles[profile]);
}
Check(bio.AsSpan().IndexOf(new byte[] { 2, 105, 105, 0 }) >= 0 &&
      bio.AsSpan().IndexOf(new byte[] { 2, 68, 68, 100 }) >= 0, "stock description palette read from charbio.dat");
for (uint suit = 10; suit < Costume.ViewerCount; suit++)
{
    uint p = memory.ReadU32(Costume.ViewerTable + suit * 12 + 4);
    bool paletteMatches = true;
    while (memory.ReadU8(p) != 255)
    {
        if (memory.ReadU8(p) == 2)
        {
            uint rgb = (uint)(memory.ReadU8(p + 1) | memory.ReadU8(p + 2) << 8 | memory.ReadU8(p + 3) << 16);
            paletteMatches &= rgb is 0x006969 or 0x644444;
            p += 4;
        }
        else { while (memory.ReadU8(p++) != 0) { } }
    }
    Check(paletteMatches, "stock right-column RGB tokens: suit " + suit);
}
uint retailList = 0x80400000, extendedList = 0x80401000;
foreach (uint list in new[] { retailList, extendedList })
{
    var ui = new CpuContext { SP = 0x80700000, A0 = list, A1 = 24, A2 = 75, A3 = 1 };
    memory.WriteU32(ui.SP + 16, 192); memory.WriteU32(ui.SP + 20, 192); memory.WriteU32(ui.SP + 24, 10);
    Recompiled.SpiderMan.func_80016424(ui, memory);
    byte count = list == retailList ? (byte)10 : (byte)21;
    memory.WriteU8(list + 0x14, count);
    for (uint row = 0; row < count; row++) memory.WriteU8(list + 0x35 + row * 28, 1);
}
Costume.ConfigureViewerList(memory, extendedList);
var retailUi = new CpuContext { A0 = retailList };
var extendedUi = new CpuContext { A0 = extendedList };
Recompiled.SpiderMan.func_800168C4(retailUi, memory); Recompiled.SpiderMan.func_800168C4(extendedUi, memory);
Check(retailUi.V0 == 90 && extendedUi.V0 == 100 && memory.ReadU8(extendedList + 0x15) == 11,
      "eleven visible rows retain stock ten-pixel pitch");
Check(memory.ReadU32(extendedList + 0x1C) == 24 && memory.ReadU32(extendedList + 0x20) == 70 &&
      memory.ReadU32(extendedList + 0x24) == 10 && memory.ReadU8(extendedList + 12) == 1,
      "first text line aligns with right column; stock X, row pitch and font preserved");
uint frame = 0x80402000;
memory.WriteU32(extendedList + 4, frame);
memory.WriteU32(frame + 0x1C, 19); memory.WriteU32(frame + 0xC, 150);
memory.WriteU32(frame + 0x20, 65); memory.WriteU32(frame + 0x10, 104);
Costume.AlignViewerFrame(memory, extendedList);
Check(memory.ReadU32(frame + 0x20) == 58 && memory.ReadU32(frame + 0x10) == 117,
      "left frame top and bottom match original right-panel bounds");
Check(memory.ReadU32(frame + 0x1C) == 19 && memory.ReadU32(frame + 0xC) == 150 &&
      memory.ReadU32(extendedList + 0x20) == 70 && memory.ReadU32(extendedList + 0x24) == 10,
      "frame alignment preserves width, X, text anchor and spacing");
string shell = File.ReadAllText(Path.Combine(root, "spiderman/generated/shell.cs"));
string viewer = shell.Split("public static void func_80261C70(CpuContext")[1].Split("public static void func_80262774(CpuContext")[0];
Check(viewer.Contains("c.V1 = 0x0000000Au;") && !viewer.Contains("c.V1 = Recompiled.Costume.ViewerCount;"),
      "generated viewer passes stock row pitch, not costume count");
// Synthetic trusted player descriptor proves binding scope independently of pixel appearance.
SuitMods.Observe(memory);
Costume.DreamcastAssetFor("spidey.psx", memory);
uint entry = 0x800A0904, model = 0x80300000, meta = 0x80301000, descriptor = 0x80302000;
memory.WriteU32(entry, 0x64697073); memory.WriteU16(entry + 4, 0x7965);
memory.WriteU32(entry + 0x14, model); memory.WriteU32(entry + 12, meta);
memory.WriteU32(model + 8, 0); memory.WriteU32(model + 12, 0);
memory.WriteU32(meta, 1); memory.WriteU32(meta + 4, descriptor);
memory.WriteU8(descriptor, 32); memory.WriteU8(descriptor + 1, 32);
memory.WriteU8(descriptor + 4, 47); memory.WriteU8(descriptor + 9, 47);
memory.WriteU16(descriptor + 6, 3); memory.WriteU16(descriptor + 2, 64);
memory.WriteU32(descriptor + 20, 0xFBC5A5A0);
var hit = TextureResolver.ActorMaterials!(TextureTile.Describe(3,64,32,32,16,16));
Check(hit.Hit && hit.Texture!.Width == 64, "trusted player material resolves external PNG");
Check(TextureResolver.ActorMaterials!(TextureTile.Describe(3,64,32,32,17,17)).Hit, "inclusive outer UV edge remains bound");
Check(!TextureResolver.ActorMaterials!(TextureTile.Describe(3,64,48,32,4,4)).Hit, "adjacent texture region untouched");
Check(!TextureResolver.ActorMaterials!(TextureTile.Describe(4,64,32,32,16,16)).Hit, "other texture page untouched");
Check(!TextureResolver.ActorMaterials!(TextureTile.Describe(3,65,32,32,16,16)).Hit, "other palette untouched");
Costume.WriteSelected(memory, 0);
Check(hit.Texture!.Retired && !TextureResolver.ActorMaterials!(TextureTile.Describe(3,64,32,32,16,16)).Hit, "stock selection retires external materials");
File.WriteAllBytes(Path.Combine(dir, "small.png"), huge[..33]);
Costume.WriteSelected(memory, 20);
Check(SuitMods.Active == -1 && Costume.ReadSelected(memory) == 0, "failed PNG activation falls back atomically to stock");
File.Copy(Path.Combine(sample, "textures/FBC5A5A0.png"), Path.Combine(dir, "small.png"), true);
for (byte i = 0; i < 20; i++)
{
    uint bits = memory.ReadU32(unlocks);
    Costume.WriteSelected(memory, i);
    Check(Costume.ReadSelected(memory) == i && memory.ReadU32(unlocks) == bits, "stock selection/unlock preservation " + i);
}
Console.WriteLine($"PASS: {tests} assertions; evidence {work}");
