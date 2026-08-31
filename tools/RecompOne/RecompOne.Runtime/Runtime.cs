using RecompOne.Runtime.Context;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Host;
using RecompOne.Runtime.Memory;

namespace RecompOne.Runtime;

public enum RunMode { Retail, Devkit }

public sealed class HardResetSignal : Exception;

public static class Runtime
{
    public static CpuContext? Cpu { get; private set; }
    public static IMemory? Mem { get; private set; }
    public static Gpu? Gpu;
    public static Spu? Spu;
    public static Cdrom.CdController? Cd;

    public static RunMode Mode { get; private set; } = RunMode.Retail;
    public static void SetMode(RunMode mode) => Mode = mode; //devkit vs retail, devkits reads from sim and has more ram

    public static uint RamSize { get; internal set; } = MemoryMap.RetailRamSize;
    public static uint RamWordMask => (RamSize - 1) & ~3u;
    public static string CdPath => Config.ConfigManager.Game.CdPath;

    public static Func<string, string?>? DiscValidator;
    public static string? ValidateDisc(string path)
    {
        try { return DiscValidator?.Invoke(path); }
        catch (Exception e) { return e.Message; }
    }
    
    public static Config.ViewConfig View => Config.ConfigManager.View;
    public static void SaveView() => Config.ConfigManager.SaveView(Host.Window.PanelManager.Panels);
    
    public static Hardware.MemoryCard CardA = new("carda.sav") { Enabled = true };
    public static Hardware.MemoryCard CardB = new("cardb.sav") { Enabled = true };

    static void LoadMemoryCards()
    {
        var g = Config.ConfigManager.Game;
        CardA = new(Fallback(g.CardAPath, "carda.sav")) { Enabled = g.CardAEnabled };
        CardB = new(Fallback(g.CardBPath, "cardb.sav")) { Enabled = g.CardBEnabled };

        static string Fallback(string path, string def) => string.IsNullOrWhiteSpace(path) ? def : path;
    }
    public static readonly Memory.RamLogger RamLog = new();
    public static readonly Dispatch.OverlayEventLog OverlayLog = new();

    static bool _hostReady;

    public static void Initialize(string title)
    {
        if (!_hostReady)
        {
            _hostReady = true;
            Diagnostics.ConsoleMirror.Install();
            HostWindow.Initialize(title);
            Audio.Initialize();
        }

        LoadMemoryCards();
        Audio.SetMasterVolume(Config.ConfigManager.Game.Muted ? 0f : Config.ConfigManager.Game.MasterVolume);
        if (Event.HasAnyListeners<RuntimeReadyEvent>())
        {
            Event.Dispatch(new RuntimeReadyEvent());
        }
    }

    public static void WaitForValidDisc() => HostWindow.WaitForValidDisc();

    public static string Title
    {
        get => HostWindow.Title;
        set => HostWindow.Title = value;
    }

    public static void SetTitle(string title) => HostWindow.SetTitle(title);

    public static void SetIcon(byte[] data) => HostWindow.SetIcon(data);

    public static void SetIcon(byte[] rgba, int width, int height) => HostWindow.SetIcon(rgba, width, height);

    public static void ClearIcon() => HostWindow.ClearIcon();
    
    public static void ShowNotice(string message) => Host.Window.NoticePopup.Show(message);
    public static void SetStartupNotice(string message, string title = "common.notice", string ackKey = "StartupNoticeAck") => Host.Window.StartupNoticePopup.Set(message, title, ackKey);

    public static void AddLanguages(string json) => Host.Window.Localization.Merge(json);
    public static bool AddLanguages(System.Reflection.Assembly assembly, string resourceName)
        => Host.Window.Localization.MergeEmbedded(assembly, resourceName);

    public static void SetContext(CpuContext c, IMemory m)
    {
        Cpu = c;
        Mem = m;
    }

    static volatile bool _hardResetPending;

    public static bool HardResetPending => _hardResetPending;

    public static void HardReset() => _hardResetPending = true;

    public static void Run(Action boot)
    {
        while (true)
        {
            try
            {
                boot();
                return;
            }
            catch (HardResetSignal)
            {
                Console.WriteLine("[Runtime] hard reset,game booting again");
                ResetForBoot();
            }
        }
    }

    static void ResetForBoot()
    {
        Audio.Detach();

        Sdk.LibCd.Reset();
        Sdk.LibCdStream.Reset();
        Assets.Xa.XaRouter.Reset();
        Sdk.LibPad.Reset();
        Dispatch.Dispatcher.Reset();
        Bios.BiosB.Reset();
        OverlayLog.Clear();

        Cpu = null;
        Mem = null;
        Gpu = null;
        Spu = null;
        Cd = null;

        if (Hle.GpuHle.Backend is { Ready: true } backend)
        {
            backend.FillRect(0, 0, global::RecompOne.Runtime.Gpu.VramWidth, global::RecompOne.Runtime.Gpu.VramHeight, 0);
            backend.Flush();
        }
    }

    /// <summary>
    /// Console vblanks per game frame -- see Host.FrameClock.VBlanksPerFrame. Set 2 for
    /// a game that ran at 30 fps on hardware.
    /// </summary>
    public static int VBlanksPerFrame
    {
        get => Host.FrameClock.VBlanksPerFrame;
        set => Host.FrameClock.VBlanksPerFrame = value < 1 ? 1 : value;
    }

    /// <summary>
    /// How much the vblank counter advances, and how many vblank IRQs are delivered,
    /// per presented frame. Separate from VBlanksPerFrame, which sets how long a frame
    /// lasts. At a 30 Hz presentation cadence this must be 2 to preserve the console's
    /// 60 Hz vblank signal for both polling code and VSyncCallback handlers.
    /// </summary>
    public static int VBlankStep { get; set; } = 1;

    /// <summary>Rate instrumentation -- throttled presents vs bare service passes.</summary>
    public static long Presents, ServicePasses;

    public static void PresentFrame()
    {
        Presents++;
        if (_hardResetPending)
        {
            _hardResetPending = false;
            throw new HardResetSignal();
        }

        Diagnostics.CallRing.NoteFrame();
        long __t0 = System.Diagnostics.Stopwatch.GetTimestamp();
        HostWindow.Present(Gpu);
        Audio.Attach(Spu);
        long __t1 = System.Diagnostics.Stopwatch.GetTimestamp();
        FrameClock.Throttle();
        long __t2 = System.Diagnostics.Stopwatch.GetTimestamp();
        Diagnostics.FrameProfile.Note(__t0, __t1, __t2);
        Sdk.LibCd.Tick();
        if (Mem != null) { Bios.BiosB.RefreshPad(Mem); Sdk.LibPad.Refresh(Mem); } //is this correct?
        if (Cpu != null && Mem != null) Bios.BiosB.PumpCard(Cpu, Mem, _pumping);
        // IRQ 0 is the console's vblank interrupt. A 30 Hz game frame spans two
        // 60 Hz vblanks, so deliver the same number that the counter advances. Keep
        // this coupled to VBlankStep: code registered through VSyncCallback observes
        // the interrupt, while VSync(-1) observes the counter, and hardware advances
        // both from the same signal.
        for (int i = 0; i < VBlankStep; i++) DispatchIrq(0);
    }

    static bool _pumping;

    /// <summary>
    /// Games wait for an interrupt by spinning on a variable their IRQ handler writes.
    /// Nothing advances that variable in a static recompile, because interrupts are
    /// only delivered while presenting a frame -- so a wait loop that does not call
    /// VSync itself never exits. The memory layer notices a long run of reads with no
    /// intervening write and calls this, which presents a frame and delivers the
    /// vblank exactly as the hardware would have done asynchronously.
    /// </summary>
    public static void IdleTick()
    {
        if (_pumping || Cpu == null || Mem == null) return;
        _pumping = true;
        try { Sdk.LibEtc.Service(Cpu, Mem); }
        finally { _pumping = false; }
    }

    /// <summary>
    /// Everything a frame does *except* declaring that a frame happened: service the
    /// CD and keep the host window alive.
    ///
    /// A game that spins without ever calling VSync still needs all of that -- its wait
    /// loop is usually waiting on exactly the CD or pad state this refreshes, and the
    /// window stops responding without it. What it must not do is advance the vblank
    /// counter, because every timed wait in the game is measured against that, and
    /// inventing vblanks faster than real time makes them all finish early.
    /// </summary>
    public static void ServiceOnly()
    {
        ServicePasses++;
        HostWindow.Present(Gpu);
        Audio.Attach(Spu);
        Sdk.LibCd.Tick();
        // Deliberately no pad refresh. The pads are sampled once per vblank on
        // hardware, and PresentFrame already does that; repeating it here at service
        // rate overwrites the pad buffers hundreds of times between frames, which
        // stomps on anything else that writes them -- a scripted press from the
        // capture harness lasted microseconds instead of a frame.
        // Deliberately no vblank IRQ. This path can run hundreds of times per second
        // while DrawSync is polling a busy GPU. Delivering IRQ 0 here made the games'
        // VSyncCallback handlers advance on every service pass (and once more through
        // nested pending delivery), so animations and timers ran far ahead of the
        // presented frame rate. Real vblanks are delivered only by PresentFrame.
    }

    public static void DispatchIrq(int irq)
    {
        if (Cpu != null && Mem != null)
            Interrupts.Deliver(irq, Cpu, Mem);
    }

    public static void Shutdown()
    {
        Audio.Shutdown();
        HostWindow.Shutdown();
    }
}
