using System.Text;
using System.Text.Json;
using RecompOne.Runtime.Cdrom;

var sm1 = new DiscInstallProfile("Spider-Man", "Spider-Man (USA)", "SLUS-00875", "SLUS_008.75", "unused");
var sm2 = new DiscInstallProfile("Spider-Man 2", "Spider-Man 2 (USA)", "SLUS-01378", "SLUS_013.78", "unused");
int checks = 0;
void Check(bool condition, string name) { if (!condition) throw new Exception(name); checks++; Console.WriteLine("PASS " + name); }
string root = Path.Combine(Path.GetTempPath(), "OpenSpidey-DiscInstallRegression-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
// Small, retained fixtures only; never touch retail media or existing installations.
foreach (var profile in new[] { sm1, sm2 })
{
    string dir = Path.Combine(root, profile.DiscId); Directory.CreateDirectory(dir);
    File.WriteAllText(Path.Combine(dir, profile.BootFile), "different USA boot bytes; intentionally no known hash or size");
    File.WriteAllText(Path.Combine(dir, "SYSTEM.CNF"), $"BOOT = cdrom:\\{profile.BootFile};1\r\nTCB = 4\r\n");
    var manifest = new LooseDiscImage.Manifest { Files = [new() { Path = profile.BootFile, Size = 61 }, new() { Path = "SYSTEM.CNF", Lba = 2, Size = 60 }] };
    File.WriteAllText(Path.Combine(dir, LooseDiscImage.ManifestName), JsonSerializer.Serialize(manifest));
    Check(DiscRevisionValidator.Validate(dir, profile) == null, profile.DiscId + " accepts USA without hash/size/leadout");
    Check(DiscRevisionValidator.Validate(dir, profile == sm1 ? sm2 : sm1) != null, "rejects wrong game");
    File.WriteAllText(Path.Combine(dir, "SYSTEM.CNF"), "BOOT = cdrom:\\SLES_028.86;1\r\n");
    Check(DiscRevisionValidator.Validate(dir, profile) != null, "rejects other region despite USA filename present");
    File.WriteAllText(Path.Combine(dir, "SYSTEM.CNF"), $" boot\t= cdrom:/{profile.BootFile.ToLowerInvariant()};1\n");
    Check(DiscRevisionValidator.Validate(dir, profile) == null, "accepts config case/spacing changes");
}
foreach (var (sectorSize, offset) in new[] { (2048, 0), (2352, 24), (2352, 16), (2336, 8) })
{
    byte[] bytes = new byte[sectorSize * 24];
    new byte[] { 1, 67, 68, 48, 48, 49, 1 }.CopyTo(bytes, 16 * sectorSize + offset);
    for (int i = 0; i < 2048; i++) bytes[20 * sectorSize + offset + i] = (byte)(i % 251);
    string path = Path.Combine(root, $"layout-{sectorSize}-{offset}.iso"); File.WriteAllBytes(path, bytes);
    using var image = DiscImage.Open(path);
    Check(image.ReadSectorData(20, 2048).SequenceEqual(Enumerable.Range(0, 2048).Select(i => (byte)(i % 251))), $"ISO sector layout {sectorSize}/{offset}");
    if (sectorSize == 2352 && offset == 24)
        Check(image.ReadSectorData(20, 2336).SequenceEqual(bytes.AsSpan(20 * sectorSize + 16, 2336).ToArray()), "XA subheader and full payload retained");
    Check(image.ReadSectorData(24, 2048).All(b => b == 0), "out of range never crosses track");
}
foreach (string path in args)
{
    var profile = Path.GetFileName(path).Contains("2") ? sm2 : sm1;
    Check(DiscRevisionValidator.Validate(path, profile) == null, "real disc " + Path.GetFileName(path));
}
Console.WriteLine($"{checks} checks passed. Tiny fixtures: {root}");

