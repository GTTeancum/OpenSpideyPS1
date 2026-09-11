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
Check(Costume.ViewerCount == 20 && SuitMods.MaxCount - SuitMods.StockCount == 41, "nineteen original costumes plus forty-one mod slots");
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
// Custom actor lifecycle: exercise the real binding/selection code while isolating
// native resource allocation behind deterministic dispatcher callbacks.
if (args.Length > 1)
{
    var custom = Directory.GetDirectories(args[1]).Where(d => File.Exists(Path.Combine(d, "suit.json")))
        .Select(d => SuitManifest.Read(Path.Combine(d, "suit.json"), SuitRules.Profiles, SuitRules.PowerText,
            SuitRules.Models, SuitManifest.Sm2SpiderMan)).Where(s => s.CustomModel != null).Take(2).ToArray();
    Check(custom.Length == 2, "two real custom actor manifests");
    SuitMods.Catalogue.Clear();
    for (int i = 0; i < 41; i++) SuitMods.Catalogue.Add(custom[i == 40 ? 1 : 0]);
    const uint table = 0x800ACED8, shared = table + 64;
    memory.WriteU8(0x800C236D, 1);
    for (uint i=0xC;i<=0x38;i+=4) memory.WriteU32(shared+i, 0x80300000+i);
    var bindings = Enumerable.Range(0,12).Select(i => memory.ReadU32(shared+0xC+(uint)i*4)).ToArray();
    var map = (Dictionary<uint, Action<CpuContext, IMemory>>)typeof(RecompOne.Runtime.Dispatch.Dispatcher)
        .GetField("_funcMap", System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.NonPublic)!.GetValue(null)!;
    int loads=0, frees=0, resident=0;
    map[0x80074C38] = (c,m) => {
        Check(resident++ == 0, "previous custom allocation released before new load");
        loads++;
        for(uint i=0xC;i<=0x38;i+=4) m.WriteU32(table+3*64+i,0x80400000+(uint)loads*0x10000+i);
        c.V0=3;
    };
    map[0x80074754] = (c,m) => {
        Check(c.A0==3 && c.A1==1, "correct native resource destructor arguments");
        Check(bindings.SequenceEqual(Enumerable.Range(0,12).Select(i=>m.ReadU32(shared+0xC+(uint)i*4))), "shared stock binding restored before release");
        frees++;resident--;
    };
    map[0x8004EB74] = (c,m) => { c.V0=0; };
    for(int round=0;round<3;round++)
    {
        foreach(int index in new[]{19,59,0})
        {
            Costume.WriteSelected(memory,index);
            Costume.SelectTextureLibrary(new CpuContext { A1=1 },memory);
            Check(resident==(index==0?0:1), "single custom resident across switch");
        }
    }
    Check(loads==6 && frees==6, "all six custom actor loads released");
}
// The denser actor path needs larger native command pools, with the original
// ordering-table allocations and the retail safety reserve left intact.
RecompOne.Runtime.Assets.LooseWadOverrides.Initialize(Path.Combine(root,"spiderman2/extracted"));
var alloc = new CpuContext { A0=0x17000, RA=0x8006BDE0 };
Check(FramePackets.TryAllocate(alloc), "first exact frame pool allocation redirected");
uint poolA=alloc.V0;
alloc.RA=0x8006BDF8;
Check(FramePackets.TryAllocate(alloc), "second exact frame pool allocation redirected");
uint poolB=alloc.V0;
Check(poolB-poolA==FramePackets.Capacity, "two disjoint bounded frame pools");
alloc.RA=0x8006BDAC;alloc.A0=0x4000;
Check(!FramePackets.TryAllocate(alloc), "ordering table allocation unchanged");
alloc.RA=0;alloc.A0=0x17000;
Check(!FramePackets.TryAllocate(alloc), "unrelated same-size allocation unchanged");
memory.WriteU32(0x800C247C,0x800A707C);
memory.WriteU32(0x800A70F0,poolB);
var packetContext=new CpuContext { GP=0x800C1764 };
FramePackets.SetLimit(packetContext,memory);
Check(memory.ReadU32(0x800C2034)==(poolB&0x7FFFFFFF)+FramePackets.Capacity-0x100, "packet limit uses selected pool with safety slack");
Check(RecompOne.Runtime.Assets.LooseWadOverrides.TryFree(poolA) && RecompOne.Runtime.Assets.LooseWadOverrides.TryFree(poolB), "both frame pools release through tracked allocator");
Console.WriteLine($"PASS: {tests} total assertions including frame pools");

// Full-capacity fixtures stay isolated from the user's installed catalogue.
Costume.WriteSelected(memory, 0);
SuitMods.Catalogue.Clear();
string capacityRoot = Path.Combine(work, "capacity");
Directory.CreateDirectory(capacityRoot);
for (int i = 0; i <= SuitMods.MaxCount - SuitMods.StockCount; i++)
{
    string folder = Path.Combine(capacityRoot, $"suit-{i:D2}");
    Directory.CreateDirectory(folder);
    File.Copy(Path.Combine(dir, "small.png"), Path.Combine(folder, "small.png"));
    var d = JsonNode.Parse(clean)!;
    d["id"] = $"capacity-{i:D2}";
    d["name"] = $"CAPACITY SUIT {i:D2} XX";
    d["comments"] = new string('X', 54);
    File.WriteAllText(Path.Combine(folder, "suit.json"), d.ToJsonString());
}
Environment.SetEnvironmentVariable("SPIDEY_SUIT_MOD_DIR", capacityRoot);
SuitMods.Install();
Check(Costume.ViewerCount == 60 && SuitMods.Catalogue.Count == 60 - SuitMods.StockCount,
    "exactly sixty total rows; overflow fixture rejected");
memory.WriteU32(Costume.ViewerTable + 0x5000, 0xAABBCCDD);
Costume.PrepareViewer(new CpuContext(), memory);
Check(memory.ReadU32(Costume.ViewerTable + 59 * 12) >= Costume.ViewerTable + 0x800 &&
    memory.ReadU32(Costume.ViewerTable + 0x5000) == 0xAABBCCDD, "last table record and text arena guard");
uint fullList = 0x80500000;
memory.WriteU32(fullList - 4, 0x11223344);
memory.WriteU32(fullList + Costume.ViewerListBytes, 0x55667788);
var fullUi = new CpuContext { SP = 0x80700000, A0 = fullList, A1 = 24, A2 = 75, A3 = 1 };
memory.WriteU32(fullUi.SP + 16, 192); memory.WriteU32(fullUi.SP + 20, 192); memory.WriteU32(fullUi.SP + 24, 10);
Recompiled.SpiderMan2.func_80017C6C(fullUi, memory);
Costume.ConfigureViewerList(memory, fullList);
memory.WriteU8(fullList + 0x14, 60);
for (uint row = 0; row < 60; row++)
{
    uint entry = fullList + 0x28 + row * 32;
    memory.WriteU32(entry, memory.ReadU32(Costume.ViewerTable + row * 12));
    memory.WriteU8(entry + 13, 1);
    Recompiled.SpiderMan2.func_80018278(new CpuContext { A0 = fullList, A1 = row }, memory);
    Check(memory.ReadU8(fullList + 14) == row && memory.ReadU16(entry + 4) == 192,
        "native selection reaches row " + row);
}
memory.WriteU8(fullList + 0x28 + 59 * 32 + 20, 123);
Recompiled.SpiderMan2.func_80018074(new CpuContext { A0 = fullList }, memory);
Check(memory.ReadU8(fullList + 0x28 + 59 * 32 + 26) == 123,
    "native color refresh reaches the final row");
Check(memory.ReadU32(fullList - 4) == 0x11223344 && memory.ReadU32(fullList + Costume.ViewerListBytes) == 0x55667788,
    "sixty-row initialization and selection preserve allocation guards");
uint savedUnlocks = memory.ReadU32(unlocks);
Costume.WriteSelected(memory, 59);
Check(Costume.ReadSelected(memory) == 59 && memory.ReadU32(unlocks) == savedUnlocks && Costume.IsUnlocked(memory, 59),
    "last mod selects without changing stock unlocks");
string savedId = SuitMods.At(59).Id;
Check(File.ReadAllText(Path.Combine(capacityRoot, "selected-suit.txt")) == savedId, "last slot persists stable identity");
SuitMods.Select(-1, false); SuitMods.Catalogue.Clear(); SuitMods.Install();
Check(Costume.ReadSelected(memory) == 59 && SuitMods.At(59).Id == savedId, "last slot restores after catalogue reload");
Costume.WriteSelected(memory, 0);
Console.WriteLine($"PASS: {tests} assertions including full sixty-slot capacity");
