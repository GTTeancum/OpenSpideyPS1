using System;
using System.IO;
using System.Reflection;
using RecompOne.Runtime.Memory;
using Recompiled;
using Capture = Recompiled.Capture;

namespace SpiderMan2;

public static class Program
{
    const string Title = "Spider-Man 2: Enter Electro";
    const string BootFile = "SLUS_013.78";
    static readonly RecompOne.Runtime.Cdrom.DiscInstallProfile InstallProfile = new(
        Title,
        "Spider-Man 2: Enter Electro (USA) (Rev 1)",
        "SLUS-01378",
        BootFile,
        786432,
        "C121FD42DBA9DC0694A83033DD17683149072C086C671DB3B9139CCD38F232EC",
        "324BF4A37F78AE931AD3BD1F4930DCFCFEF39C0E8DEAB28F089B3315D9BB4D93",
        305023,
        "OpenSpidey.BundledAssets.zip");

    /// <summary>
    /// 8 MB rather than the retail 2 MB. The extra space is not for the game -- its own
    /// allocator never looks past 2 MB -- it is where the 28 code overlays are pinned so
    /// a static recompile can emit them at fixed addresses. They occupy 0x80200000 to
    /// 0x8027D000; see patches/OverlayPatches.cs.
    /// </summary>
    const uint RamSize = 0x00800000;
    static System.Threading.Mutex RuntimeMutex;

    public static int Main(string[] args)
    {
        if (!AcquireRuntimeLease()) return 4;

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

        string installRoot = ExeDirectory() ?? AppContext.BaseDirectory;
        string installOutput = InstallOutput(installRoot);
        string gameData;
        try
        {
            gameData = RecompOne.Runtime.Cdrom.FirstRunDiscInstaller.EnsureInstalled(
                InstallProfile,
                installOutput,
                ResolveExistingGameData(args),
                RequestedImage(args),
                Assembly.GetExecutingAssembly());
        }
        catch (Exception e)
        {
            Console.Error.WriteLine("[SpiderMan2] setup failed: " + e.Message);
            RecompOne.Runtime.Runtime.Shutdown();
            return 2;
        }
        SeedSettings(gameData);
        RecompOne.Runtime.Config.ConfigManager.Game.CdPath = gameData;
        if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("SPIDEY_ASSET_DIR")))
            Environment.SetEnvironmentVariable(
                "SPIDEY_ASSET_DIR",
                Path.Combine(Path.GetDirectoryName(installOutput)!, "assets", "builtin"));
        RecompOne.Runtime.Assets.LooseWadOverrides.Initialize(gameData);
        if (string.Equals(
            Environment.GetEnvironmentVariable("RECOMP_INSTALL_ONLY"), "1",
            StringComparison.Ordinal))
        {
            RecompOne.Runtime.Runtime.Shutdown();
            return 0;
        }

        // A generated Dreamcast actor batch can carry original-resolution host
        // textures beside its compact PS1-VRAM compatibility pages. Keep that
        // batch self-contained unless the caller selected another pack root.
        if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("RECOMP_ASSET_PACK_DIR")))
        {
            string actorRoot = Environment.GetEnvironmentVariable("SPIDEY_ASSET_DIR");
            string actorPacks = string.IsNullOrWhiteSpace(actorRoot)
                ? null
                : Path.Combine(Path.GetFullPath(actorRoot), "packs");
            if (actorPacks != null && Directory.Exists(actorPacks))
                Environment.SetEnvironmentVariable("RECOMP_ASSET_PACK_DIR", actorPacks);
        }

        // Non-interactive texture-pack authoring. This observes only the emulated
        // game's own texture uploads and never drives the host desktop or game input.
        var dumpTextures = Environment.GetEnvironmentVariable("SPIDEY_DUMP_TEXTURES");
        if (string.Equals(dumpTextures, "pages", StringComparison.OrdinalIgnoreCase))
            RecompOne.Runtime.Assets.Textures.TextureDumper.SetPages(true);
        else if (string.Equals(dumpTextures, "tiles", StringComparison.OrdinalIgnoreCase))
            RecompOne.Runtime.Assets.Textures.TextureDumper.SetTiles(true);
        else if (string.Equals(dumpTextures, "all", StringComparison.OrdinalIgnoreCase))
            RecompOne.Runtime.Assets.Textures.TextureDumper.SetEnabled(true);

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
        // The game loop is frame-rate dependent, but a host present is not necessarily a
        // game update. At the default budget the measured steady-state relationship is
        // 15 gameplay updates, 30 host presents and 60 vblanks per second.
        //
        // SPIDEY_VBLANK controls both the console vblank counter and IRQ 0 deliveries.
        // At 30 presented frames per second, two of each preserve the console's 60 Hz
        // signal for the game's registered VSyncCallback timers.
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
        Costume.Install();
        Cheats.Install();
        Rates.Install();
        Wide.Install(0x80031EA0u, completeBackdrop: true, defaultEnabled: true);
        Harness.Install();

        AppDomain.CurrentDomain.UnhandledException += (_, e) => Diag.Fatal(e.ExceptionObject as Exception);

        try
        {
            RecompOne.Runtime.Runtime.Run(() =>
            {
                var mem = new PSMemory(RamSize);
                Entry.Run(mem, gameData, Title);
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

    static bool AcquireRuntimeLease()
    {
        RuntimeMutex = new System.Threading.Mutex(
            false, @"Local\OpenSpideyPS1.GameRuntime");
        try
        {
            if (RuntimeMutex.WaitOne(0)) return true;
        }
        catch (System.Threading.AbandonedMutexException)
        {
            return true;
        }

        Console.Error.WriteLine(
            "[SpiderMan2] another OpenSpidey game process is already running; refusing a second instance");
        RuntimeMutex.Dispose();
        RuntimeMutex = null;
        return false;
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

    static string ResolveExistingGameData(string[] args)
    {
        if (args.Length > 0)
        {
            string requested = Path.GetFullPath(args[0]);
            if (RecompOne.Runtime.Cdrom.LooseDiscImage.IsLooseDirectory(requested)) return requested;
            return null;
        }

        foreach (var dir in CandidateDirs())
        {
            foreach (var candidate in new[]
            {
                Path.Combine(dir, "spiderman2", "extracted"),
                Path.Combine(dir, "extracted"),
                Path.Combine(dir, "game"),
                dir,
            })
                if (RecompOne.Runtime.Cdrom.LooseDiscImage.IsLooseDirectory(candidate))
                    return Path.GetFullPath(candidate);
        }

        return null;
    }

    static string RequestedImage(string[] args)
    {
        if (args.Length == 0) return null;
        string path = Path.GetFullPath(args[0]);
        return File.Exists(path) ? path : null;
    }

    static string InstallOutput(string installRoot)
    {
        string output = Environment.GetEnvironmentVariable("SPIDEY_DATA");
        return string.IsNullOrWhiteSpace(output)
            ? Path.Combine(installRoot, "game")
            : Path.GetFullPath(output);
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

    // Store the loose directory, never the import image, as the persistent runtime path.
    static void SeedSettings(string gameData)
    {
        try
        {
            const string path = "settings.json";
            var options = new System.Text.Json.JsonSerializerOptions
            {
                WriteIndented = true,
                PropertyNameCaseInsensitive = true,
            };
            var config = File.Exists(path)
                ? System.Text.Json.JsonSerializer.Deserialize<RecompOne.Runtime.Config.GameConfig>(File.ReadAllText(path), options)
                : null;
            config ??= new RecompOne.Runtime.Config.GameConfig();
            config.CdPath = gameData;
            var json = System.Text.Json.JsonSerializer.Serialize(config, options);
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
        return RecompOne.Runtime.Cdrom.DiscRevisionValidator.Validate(path, InstallProfile);
    }
}
