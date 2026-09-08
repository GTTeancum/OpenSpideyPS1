using System.IO.Compression;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using RecompOne.Runtime.Cdrom;

string root = Path.Combine(Path.GetTempPath(), "OpenSpidey-bundle-regression-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
int assertions = 0;
void Check(bool condition, string name)
{
    if (!condition) throw new Exception("FAIL: " + name);
    assertions++;
    Console.WriteLine("PASS: " + name);
}
byte[] Payload(Dictionary<string, string> files)
{
    using var buffer = new MemoryStream();
    using (var zip = new ZipArchive(buffer, ZipArchiveMode.Create, leaveOpen: true))
    {
        // Put metadata first deliberately; extraction must still install it last.
        using (var output = zip.CreateEntry("bundle.json").Open())
            JsonSerializer.Serialize(output, new { files = files.Select(f => new {
                path = f.Key, bytes = Encoding.UTF8.GetByteCount(f.Value),
                sha256 = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(f.Value))) }) });
        foreach (var file in files)
        {
            using var writer = new StreamWriter(zip.CreateEntry(file.Key).Open());
            writer.Write(file.Value);
        }
    }
    return buffer.ToArray();
}
void Install(byte[] bytes, string path, IProgress<LooseDiscImporter.Progress>? progress = null, CancellationToken token = default)
{
    using var stream = new MemoryStream(bytes);
    BundledAssets.Extract(stream, path, progress, token);
}
var v1 = Payload(new() { ["packs/old.png"] = "old pixels", ["packs/modified.png"] = "original", ["actor.psx"] = "actor-old" });
var v2 = Payload(new() { ["packs/new.png"] = "new pixels", ["actor.psx"] = "actor-new" });
string target = Path.Combine(root, "upgrade");
Install(v1, target);
File.WriteAllText(Path.Combine(target, "packs/modified.png"), "user modification");
File.WriteAllText(Path.Combine(target, "packs/unowned.png"), "user asset");
Install(v2, target);
Check(!File.Exists(Path.Combine(target, "packs/old.png")), "obsolete owned asset no longer active");
Check(Directory.GetFiles(Path.Combine(target, ".retired"), "old.png", SearchOption.AllDirectories)
    .Any(p => File.ReadAllText(p) == "old pixels"), "obsolete bytes recoverable outside packs");
Check(File.ReadAllText(Path.Combine(target, "packs/modified.png")) == "user modification", "modified obsolete file preserved");
Check(File.ReadAllText(Path.Combine(target, "packs/unowned.png")) == "user asset", "unowned file preserved");
Check(File.ReadAllText(Path.Combine(target, "actor.psx")) == "actor-new", "current actor updated");
int retiredCount = Directory.GetFiles(Path.Combine(target, ".retired"), "*", SearchOption.AllDirectories).Length;
Install(v2, target);
Check(Directory.GetFiles(Path.Combine(target, ".retired"), "*", SearchOption.AllDirectories).Length == retiredCount, "repeat install idempotent");
File.WriteAllText(Path.Combine(target, "actor.psx"), "xxxxxxxxx");
Install(v2, target);
Check(File.ReadAllText(Path.Combine(target, "actor.psx")) == "actor-new", "same-length corruption repaired");

string interrupted = Path.Combine(root, "interrupted");
Install(v1, interrupted);
string oldManifest = File.ReadAllText(Path.Combine(interrupted, "bundle.json"));
using (var cancel = new CancellationTokenSource())
{
    try { Install(v2, interrupted, new CallbackProgress(_ => cancel.Cancel()), cancel.Token); }
    catch (OperationCanceledException) { }
}
Check(File.ReadAllText(Path.Combine(interrupted, "bundle.json")) == oldManifest, "interruption retains previous ownership");
Install(v2, interrupted);
Check(!File.Exists(Path.Combine(interrupted, "packs/old.png")), "retry retires previous owned asset");

string outside = Path.Combine(root, "sentinel.txt");
File.WriteAllText(outside, "do not touch");
bool rejected = false;
try { Install(Payload(new() { ["../sentinel.txt"] = "bad" }), Path.Combine(root, "traversal")); }
catch (InvalidDataException) { rejected = true; }
Check(rejected && File.ReadAllText(outside) == "do not touch", "archive traversal rejected before writes");
bool duplicateRejected = false;
string duplicateTarget = Path.Combine(root, "duplicate");
try { Install(Payload(new() { ["actor.psx"] = "first", ["ACTOR.psx"] = "second" }), duplicateTarget); }
catch (InvalidDataException) { duplicateRejected = true; }
Check(duplicateRejected && Directory.GetFiles(duplicateTarget).Length == 0, "case-colliding destinations rejected before writes");
string malformed = Path.Combine(root, "malformed-ownership");
Directory.CreateDirectory(malformed);
File.WriteAllText(Path.Combine(malformed, "bundle.json"), JsonSerializer.Serialize(new { files = new[] {
    new { path = "../sentinel.txt", sha256 = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("do not touch"))) } } }));
Install(v2, malformed);
Check(File.ReadAllText(outside) == "do not touch", "unsafe prior ownership cannot retire outside file");
if (args is ["--real-bundles", var repository])
{
    foreach (string game in new[] { "spiderman", "spiderman2" })
    {
        string bundlePath = $"{game}/port/bundled/runtime-assets.zip";
        var info = new ProcessStartInfo("git") { WorkingDirectory = repository,
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true };
        info.ArgumentList.Add("show");
        info.ArgumentList.Add("HEAD:" + bundlePath);
        using var process = Process.Start(info)!;
        using var oldBytes = new MemoryStream();
        process.StandardOutput.BaseStream.CopyTo(oldBytes);
        process.WaitForExit();
        if (process.ExitCode != 0) throw new Exception("Cannot read prior committed bundle");
        string realTarget = Path.Combine(root, game);
        Install(oldBytes.ToArray(), realTarget);
        byte[] nextBytes = File.ReadAllBytes(Path.Combine(repository, bundlePath));
        Install(nextBytes, realTarget);
        using var nextZip = new ZipArchive(new MemoryStream(nextBytes));
        Check(nextZip.Entries.Where(e => !e.FullName.EndsWith('/')).All(e => {
            using var source = e.Open();
            using var installed = File.OpenRead(Path.Combine(realTarget, e.FullName));
            return SHA256.HashData(source).AsSpan().SequenceEqual(SHA256.HashData(installed));
        }), game + " real upgrade bytes match every new ZIP entry");
        int expectedTextures = nextZip.Entries.Count(e => e.FullName.StartsWith("packs/") && e.FullName.EndsWith(".png"));
        int activeTextures = Directory.GetFiles(Path.Combine(realTarget, "packs"), "*.png", SearchOption.AllDirectories).Length;
        Check(activeTextures == expectedTextures, game + $" has exactly {expectedTextures} current active texture files");
    }
}
Console.WriteLine($"SUCCESS: {assertions} assertions; retained test artifacts: {root}");

sealed class CallbackProgress(Action<LooseDiscImporter.Progress> callback) : IProgress<LooseDiscImporter.Progress>
{
    public void Report(LooseDiscImporter.Progress value) => callback(value);
}

namespace RecompOne.Runtime.Cdrom
{
    // Only the extractor's progress type is needed; no game or graphics code loads.
    public static class LooseDiscImporter
    {
        public sealed record Progress(string Stage, string File, int Files, int TotalFiles, long Bytes, long TotalBytes);
    }
}
