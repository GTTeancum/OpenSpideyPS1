using System.Text;
using RecompOne.Runtime.Assets;
using RecompOne.Runtime.Config;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Dispatch;
using RecompOne.Runtime.Memory;

namespace RecompOne.Runtime.Host.Window;

/// <summary>Reuses each game's own OPTIONS implementation, including its controls and drawing.</summary>
public static class NativeVideoSetup
{
    public sealed record Bindings(uint Options, uint Strings, uint Pad, uint InputReturn, uint Sound,
        uint AspectOffset, uint ScreenOffset, uint TitleOffset, uint HelpOffset, uint AddRow);
    static Bindings? _active;
    static VideoSetupState? _state;
    static uint _text;
    static bool _requestSave;

    public static void RenameScreen(IMemory m, Bindings b)
    {
        uint p = m.ReadU32(b.Strings + b.ScreenOffset);
        // The English retail allocation already holds the longer "screen adjust".
        var bytes = Encoding.ASCII.GetBytes("screen adjust\0");
        if (bytes.Select((v, i) => m.ReadU8(p + (uint)i) == v).All(x => x)) Write(m, p, "video setup");
        p = m.ReadU32(b.Strings + b.HelpOffset + 16);
        bytes = Encoding.ASCII.GetBytes("adjust placement of screen image\0");
        if (bytes.Select((v, i) => m.ReadU8(p + (uint)i) == v).All(x => x))
            Write(m, p, "change resolution and aspect");
    }
    static void Write(IMemory m, uint p, string value)
    {
        byte[] bytes = Encoding.ASCII.GetBytes(value);
        if (bytes.Length >= 96) throw new InvalidOperationException("Video menu label exceeds its reserved slot");
        for (int i = 0; i < bytes.Length; i++) m.WriteU8(p + (uint)i, bytes[i]);
        m.WriteU8(p + (uint)bytes.Length, 0);
    }
    static void Labels(IMemory m)
    {
        Write(m, _text, $"aspect: {(_state!.Widescreen ? "16:9" : "4:3")}");
        Write(m, _text + 96, $"resolution: {_state.Selected}");
        Write(m, _text + 192, $"fullscreen: {(_state.Fullscreen ? "on" : "off")}");
        Write(m, _text + 864, _state.Applied ? "applied" : "apply");
    }
    public static void Run(CpuContext c, IMemory m, Bindings b)
    {
        if (_active != null) throw new InvalidOperationException("Nested Video Setup");
        RenameScreen(m, b);
        var saved = c.Snapshot();
        uint[] offsets = [b.AspectOffset,0x40,b.ScreenOffset,b.TitleOffset,
            b.HelpOffset,b.HelpOffset+4,b.HelpOffset+8,b.HelpOffset+12,b.HelpOffset+16];
        uint[] original = offsets.Select(o => m.ReadU32(b.Strings + o)).ToArray();
        _text = LooseWadOverrides.AllocateScratch(960, "native video menu labels");
        _active = b;
        _state = new(ConfigManager.Game.Widescreen ?? Hle.GpuHle.WidescreenDefault,
            ConfigManager.View.GetInt("VideoWidth", ConfigManager.View.WindowWidth),
            ConfigManager.View.GetInt("VideoHeight", ConfigManager.View.WindowHeight), ConfigManager.View.Fullscreen);
        try
        {
            for (int i = 0; i < offsets.Length; i++) m.WriteU32(b.Strings + offsets[i], _text + (uint)i * 96);
            Labels(m);
            string[] help = ["video setup","left or right changes aspect","triangle discards pending changes",
                "left or right changes resolution","windowed output size","left or right toggles fullscreen"];
            for (int i = 0; i < help.Length; i++) Write(m, _text + (uint)(i + 3) * 96, help[i]);
            Console.WriteLine($"[video-menu] opened {_state.Selected} wide={_state.Widescreen} fullscreen={_state.Fullscreen}");
            c.A0 = 14;
            Dispatcher.Call(c, m, b.Options);
        }
        finally
        {
            for (int i = 0; i < offsets.Length; i++) m.WriteU32(b.Strings + offsets[i], original[i]);
            LooseWadOverrides.TryFree(_text);
            _active = null; _state = null; _text = 0;
            c.Restore(saved);
            Console.WriteLine("[video-menu] closed; native OPTIONS restored");
        }
    }
    public static void Input(CpuContext c, IMemory m)
    {
        var b = _active;
        if (b == null || c.RA != b.InputReturn) return;
        if (m.ReadU8(c.A0 + 0x14) == 3)
        {
            // Retail lists reserve at least 40 rows. Four rows at 18-pixel spacing
            // fit the same native panel as the original three at 24 pixels.
            var context = c.Snapshot();
            m.WriteU32(c.A0 + 0x24, 18);
            c.A1 = _text + 864;
            Dispatcher.Call(c, m, b.AddRow);
            c.Restore(context);
        }
        int row = m.ReadU8(c.A0 + 0xE);
        bool left = m.ReadU8(b.Pad + 0x81) != 0, right = m.ReadU8(b.Pad + 0x91) != 0;
        bool select = m.ReadU8(b.Pad + 0x31) != 0 || m.ReadU8(b.Pad + 0xE1) != 0;
        if (!left && !right && !select) return;
        if (select) { m.WriteU8(b.Pad + 0x31, 0); m.WriteU8(b.Pad + 0xE1, 0); }
        m.WriteU8(b.Pad + 0x81, 0); m.WriteU8(b.Pad + 0x91, 0);
        if (row == 0) _state!.ChangeAspect();
        if (row == 1) _state!.ChangeResolution(left ? -1 : 1);
        if (row == 2) _state!.ChangeFullscreen();
        if (row == 3 && select)
        {
            var res = _state!.Selected;
            ConfigManager.Game.Widescreen = _state.Widescreen;
            ConfigManager.View.SetInt("VideoWidth", res.Width);
            ConfigManager.View.SetInt("VideoHeight", res.Height);
            ConfigManager.View.Fullscreen = _state.Fullscreen;
            HostWindow.SetFullscreen(_state.Fullscreen);
            if (!_state.Fullscreen) OutputPanel.RequestResolution(res.Width, res.Height);
            _requestSave = true;
            _state.Applied = true;
            Console.WriteLine($"[video-menu] apply {res} wide={_state.Widescreen} fullscreen={_state.Fullscreen}");
        }
        Labels(m);
        var saved = c.Snapshot();
        c.A0 = 0x1F; c.A1 = 0x2000; c.A2 = 0;
        Dispatcher.Call(c, m, b.Sound);
        c.Restore(saved);
        Console.WriteLine($"[video-menu] row={row} pending={_state!.Selected} wide={_state.Widescreen}");
    }
    internal static void SavePending()
    {
        if (!_requestSave) return;
        _requestSave = false;
        ConfigManager.SaveGame();
        ConfigManager.SaveView(PanelManager.Panels);
    }
}
