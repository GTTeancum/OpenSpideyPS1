using System;
using System.IO;
using System.Linq;
using RecompOne.Runtime.Memory;
using Recompiled;
using Capture = Recompiled.Capture;

namespace SpiderMan;

public static class Program
{
    const string Title = "Spider-Man";
    const string BootFile = "SLUS_008.75";

    /// <summary>
    /// 8 MB rather than the retail 2 MB. The extra space is not for the game -- its own
    /// allocator never looks past 2 MB -- it is where the code overlays are pinned so a
    /// static recompile can emit them at fixed addresses. See patches/OverlayPatches.cs.
    /// </summary>
    const uint RamSize = 0x00800000;

    public static int Main(string[] args)
    {
        // Everything the game writes -- logs, saves, shots -- is resolved against the
        // working directory, so anchor that to the executable. Otherwise a launch from
        // elsewhere scatters them wherever the shell happened to be. Environment
        // .ProcessPath, not AppContext.BaseDirectory: for a single-file build the
        // latter is the extraction folder.
        try
        {
            string home = ExeDirectory();
            if (home != null) Directory.SetCurrentDirectory(home);
        }
        catch { }

        string cue = ResolveCue(args);
        if (cue != null) SeedSettings(cue);

        Diag.Install();
        RecompOne.Runtime.Runtime.DiscValidator = ValidateDisc;
        EnableLogs(Environment.GetEnvironmentVariable("SPIDEY_LOG"));
        Capture.Install();
        Harness.Install();

        AppDomain.CurrentDomain.UnhandledException += (_, e) => Diag.Fatal(e.ExceptionObject as Exception);

        try
        {
            RecompOne.Runtime.Runtime.Run(() =>
            {
                var mem = new PSMemory(RamSize);
                Entry.Run(mem, cue, Title);
            });
        }
        catch (Exception ex)
        {
            Diag.Fatal(ex);
            RecompOne.Runtime.Runtime.Shutdown();
            return 3;
        }

        RecompOne.Runtime.Runtime.Shutdown();
        return 0;
    }

    // SPIDEY_LOG=bios,sdk,cd,gpu,dma,spu,mdec
    static void EnableLogs(string spec)
    {
        if (string.IsNullOrWhiteSpace(spec)) return;
        foreach (var raw in spec.Split(','))
        {
            switch (raw.Trim().ToLowerInvariant())
            {
                case "bios": RecompOne.Runtime.Log.BiosOn = true; break;
                case "sdk": RecompOne.Runtime.Log.SdkOn = true; break;
                case "cd": RecompOne.Runtime.Log.CdOn = true; break;
                case "gpu": RecompOne.Runtime.Log.GpuOn = true; break;
                case "dma": RecompOne.Runtime.Log.DmaOn = true; break;
                case "spu": RecompOne.Runtime.Log.SpuOn = true; break;
                case "mdec": RecompOne.Runtime.Log.MdecOn = true; break;
                case "all":
                    RecompOne.Runtime.Log.BiosOn = RecompOne.Runtime.Log.SdkOn =
                    RecompOne.Runtime.Log.CdOn = RecompOne.Runtime.Log.GpuOn =
                    RecompOne.Runtime.Log.DmaOn = RecompOne.Runtime.Log.SpuOn =
                    RecompOne.Runtime.Log.MdecOn = true;
                    break;
            }
        }
        Console.WriteLine($"[SpiderMan] logging: {spec}");
    }

    static string ExeDirectory()
    {
        string exe = Environment.ProcessPath;
        return string.IsNullOrEmpty(exe) ? AppContext.BaseDirectory : Path.GetDirectoryName(exe);
    }

    // The disc lives in the repository root; the build output sits a few levels below.
    static string ResolveCue(string[] args)
    {
        if (args.Length > 0 && File.Exists(args[0])) return Path.GetFullPath(args[0]);

        foreach (var dir in CandidateDirs())
        {
            if (!Directory.Exists(dir)) continue;
            // Two games share this repository; take the one this port is built for.
            var hit = Directory.GetFiles(dir, "*.cue")
                               .FirstOrDefault(f => Path.GetFileName(f).StartsWith("Spider-Man (", StringComparison.OrdinalIgnoreCase));
            if (hit != null) return Path.GetFullPath(hit);
        }
        return null;
    }

    static System.Collections.Generic.IEnumerable<string> CandidateDirs()
    {
        var here = ExeDirectory() ?? AppContext.BaseDirectory;
        yield return here;
        var d = new DirectoryInfo(here);
        for (int i = 0; i < 8 && d != null; i++)
        {
            yield return d.FullName;
            d = d.Parent;
        }
        yield return Directory.GetCurrentDirectory();
    }

    // Written once so the runtime's "pick a disc" gate passes without user interaction.
    static void SeedSettings(string cue)
    {
        try
        {
            const string path = "settings.json";
            if (File.Exists(path))
            {
                var text = File.ReadAllText(path);
                if (text.Contains("\"CdPath\"") && !text.Contains("\"CdPath\": \"\"")) return;
            }
            var json = System.Text.Json.JsonSerializer.Serialize(
                new RecompOne.Runtime.Config.GameConfig { CdPath = cue },
                new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(path, json);
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"[SpiderMan] could not seed settings.json: {e.Message}");
        }
    }

    /// <summary>
    /// Spider-Man's primary volume descriptor carries a blank volume identifier, so
    /// the disc is recognised by its boot executable instead.
    /// </summary>
    static string ValidateDisc(string path)
    {
        try
        {
            using var fs = RecompOne.Runtime.Cdrom.DiscFs.Open(path);
            if (!fs.Locate(BootFile, out _, out _))
                return $"expected {BootFile} (Spider-Man, USA) on the disc; not found";
            return null;
        }
        catch (Exception e)
        {
            return e.Message;
        }
    }
}
