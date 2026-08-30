using System;
using System.IO;
using System.Linq;
using RecompOne.Runtime.Memory;
using Recompiled;
using Capture = Recompiled.Capture;

namespace SpiderMan2;

public static class Program
{
    const string Title = "Spider-Man 2: Enter Electro";
    const string BootFile = "SLUS_013.78";

    /// <summary>
    /// 8 MB rather than the retail 2 MB. The extra space is not for the game -- its own
    /// allocator never looks past 2 MB -- it is where the 28 code overlays are pinned so
    /// a static recompile can emit them at fixed addresses. They occupy 0x80200000 to
    /// 0x8027D000; see patches/OverlayPatches.cs.
    /// </summary>
    const uint RamSize = 0x00800000;

    public static int Main(string[] args)
    {
        // Everything the game writes -- logs, saves, shots -- is resolved against the
        // working directory, so anchor that to the executable. Environment.ProcessPath,
        // not AppContext.BaseDirectory: for a single-file build the latter is the
        // extraction folder.
        try
        {
            string home = ExeDirectory();
            if (home != null) Directory.SetCurrentDirectory(home);
        }
        catch { }

        string cue = ResolveCue(args);
        if (cue != null) SeedSettings(cue);

        var guard = Environment.GetEnvironmentVariable("SPIDEY_GUARD");
        if (!string.IsNullOrEmpty(guard))
            RecompOne.Runtime.Diagnostics.MemGuard.Address =
                Convert.ToUInt32(guard.Replace("0x", ""), 16) & 0x1FFFFFFFu;

        var gv = Environment.GetEnvironmentVariable("SPIDEY_GUARD_VALUE");
        if (!string.IsNullOrEmpty(gv))
        {
            RecompOne.Runtime.Diagnostics.MemGuard.Value = Convert.ToUInt32(gv.Replace("0x", ""), 16);
            RecompOne.Runtime.Diagnostics.MemGuard.WatchValue = true;
        }

        RecompOne.Runtime.Diagnostics.MemGuard.Lenient =
            !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("SPIDEY_LENIENT"));

        // The rate to pace at. Spider-Man runs its gameplay loop off DrawSync rather
        // than VSync, so the pacing gate there is a GPU that stays busy for a frame's
        // worth of time; whether this game does the same is a measurement, not an
        // assumption, so SPIDEY_HZ is the knob and patches/Rates.cs is the measurement.
        int hz = TargetHz();
        RecompOne.Runtime.GpuBusy.FrameBudgetMs = 1000.0 / hz;
        RecompOne.Runtime.Runtime.VBlanksPerFrame = Math.Max(1, (int)Math.Round(60.0 / hz));

        var vb = Environment.GetEnvironmentVariable("SPIDEY_VBLANK");
        RecompOne.Runtime.Runtime.VBlankStep =
            int.TryParse(vb, out int n) && n >= 1 && n <= 4
                ? n
                : Math.Max(1, (int)Math.Round(60.0 / hz));

        Diag.Install();
        RecompOne.Runtime.Runtime.DiscValidator = ValidateDisc;
        EnableLogs(Environment.GetEnvironmentVariable("SPIDEY_LOG"));
        Capture.Install();
        RamSnap.Install();
        LevelSwitch.Install();
        Cheats.Install();
        Rates.Install();
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

    /// <summary>
    /// SPIDEY_HZ -- the rate the game is meant to run at. Pass 60 to let it run as fast
    /// as the host will present.
    /// </summary>
    static int TargetHz()
    {
        var hz = Environment.GetEnvironmentVariable("SPIDEY_HZ");
        if (int.TryParse(hz, out int want) && want >= 10 && want <= 60) return want;
        return 30;
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
        Console.WriteLine("[SpiderMan2] logging: " + spec);
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
            // Two games share this repository, and their cue sheets sit side by side in
            // the same folder. Match this game's and never the other's: "Spider-Man 2".
            var hit = Directory.GetFiles(dir, "*.cue")
                               .FirstOrDefault(f => Path.GetFileName(f).StartsWith("Spider-Man 2", StringComparison.OrdinalIgnoreCase));
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
            Console.Error.WriteLine("[SpiderMan2] could not seed settings.json: " + e.Message);
        }
    }

    /// <summary>
    /// Recognise the disc by its boot executable. This also keeps the two games apart:
    /// Spider-Man's disc does not carry SLUS_013.78, so pointing this build at the wrong
    /// cue sheet is refused rather than half-loaded.
    /// </summary>
    static string ValidateDisc(string path)
    {
        try
        {
            using var fs = RecompOne.Runtime.Cdrom.DiscFs.Open(path);
            if (!fs.Locate(BootFile, out _, out _))
                return "expected " + BootFile + " (Spider-Man 2: Enter Electro, USA) on the disc; not found";
            return null;
        }
        catch (Exception e)
        {
            return e.Message;
        }
    }
}
