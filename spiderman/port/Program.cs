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

        // SPIDEY_GUARD=8009c5d4 -- report whatever writes rubbish into this address.
        var guard = Environment.GetEnvironmentVariable("SPIDEY_GUARD");
        if (!string.IsNullOrEmpty(guard))
            RecompOne.Runtime.Diagnostics.MemGuard.Address =
                Convert.ToUInt32(guard.Replace("0x", ""), 16) & 0x1FFFFFFFu;

        // SPIDEY_GUARD_VALUE=00a402c7 -- report wherever this exact word gets stored.
        var gv = Environment.GetEnvironmentVariable("SPIDEY_GUARD_VALUE");
        if (!string.IsNullOrEmpty(gv))
        {
            RecompOne.Runtime.Diagnostics.MemGuard.Value = Convert.ToUInt32(gv.Replace("0x", ""), 16);
            RecompOne.Runtime.Diagnostics.MemGuard.WatchValue = true;
        }

        RecompOne.Runtime.Diagnostics.MemGuard.Lenient =
            !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("SPIDEY_LENIENT"));

        // Spider-Man is a 30 fps game. Gameplay never touches VSync -- it spins on
        // DrawSync until the GPU has finished the last ordering table -- so the pacing
        // gate is a GPU that stays busy for a frame's worth of time. The simulation then
        // advances once per vblank tick, which is why the tick rate is left at one per
        // presented frame: together they give 30 frames and 30 ticks a second.
        int hz = TargetHz();
        RecompOne.Runtime.GpuBusy.FrameBudgetMs = 1000.0 / hz;

        // How many vblanks the counter advances per presented frame, separately from the
        // frame budget above. SPIDEY_VBLANK overrides it: the game steps its simulation
        // per vblank tick, so this decides the speed of everything that moves, while the
        // budget only decides how often a frame is drawn.
        // One, measured. The game steps its simulation once per vblank tick, so this is
        // the speed of everything that moves; the budget above only sets how often a
        // frame is drawn. Setting it to 2 -- on the reasoning that a 30 fps game sees
        // two vblanks per frame and that vblank-based timers should measure real
        // seconds -- ran the whole game at double speed while rendering at 30.
        RecompOne.Runtime.Runtime.VBlanksPerFrame = Math.Max(1, (int)Math.Round(60.0 / hz));

        // Default 2, which keeps the vblank counter at the console's real 60 Hz while
        // frames are presented at 30. SPIDEY_VBLANK=1 halves it -- everything the game
        // times in vblanks then runs at half rate, which is the knob to reach for if the
        // game looks like it is running fast.
        var vb = Environment.GetEnvironmentVariable("SPIDEY_VBLANK");
        RecompOne.Runtime.Runtime.VBlankStep =
            int.TryParse(vb, out int n) && n >= 1 && n <= 4
                ? n
                : Math.Max(1, (int)Math.Round(60.0 / hz));

        Diag.Install();
        RecompOne.Runtime.Runtime.DiscValidator = ValidateDisc;
        EnableLogs(Environment.GetEnvironmentVariable("SPIDEY_LOG"));
        Capture.Install();
        Cheats.Install();
        RamSnap.Install();
        LevelSwitch.Install();
        ModelAlias.Install();
        ModelGuard.Install();
        Costume.Install();
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
    /// SPIDEY_HZ -- the rate the game is meant to run at. 30 is correct for this title;
    /// SPIDEY_HZ=0 removes the pacing entirely and lets it free-run.
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
