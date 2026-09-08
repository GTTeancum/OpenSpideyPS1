using System.Numerics;
using ImGuiNET;

namespace RecompOne.Runtime.Host.Window;

internal sealed class OutputPanel : IPanel
{
    public string Name => "Output";
    public string TitleKey => "panel.output";
    
    public bool IsOpen { get => true; set { } }
    static uint _texId;
    static int _texW, _texH;
    static float _aspect = 4f / 3f;

    public static bool IsDocked { get; private set; }

    public static void SetTexture(uint id, int w, int h, float aspect = 0f)
        => (_texId, _texW, _texH, _aspect) = (id, w, h, aspect > 0f ? aspect : 4f / 3f);

    //idea: in the future make this be able to draw images so you can have ornamented backgrounds
    public void Draw()
    {
        ImGui.SetNextWindowSize(new Vector2(640, 480), ImGuiCond.FirstUseEver);
        ImGui.PushStyleColor(ImGuiCol.WindowBg, new Vector4(0f, 0f, 0f, 1f));

        bool visible = ImGui.Begin(this.Title());
        IsDocked = ImGui.IsWindowDocked();

        if (!visible)
        {
            ImGui.End();
            ImGui.PopStyleColor();
            return;
        }

        if (_texId != 0 && _texW > 0 && _texH > 0)
        {
            var avail = ImGui.GetContentRegionAvail();
            FitWindowOnce(avail);
            FitRequestedWindow(avail);
            var imageSize = FitAspect(new Vector2(_aspect, 1f), avail);
            var offset = (avail - imageSize) * 0.5f;
            ImGui.SetCursorPos(ImGui.GetCursorPos() + offset);
            ImGui.Image((nint)_texId, imageSize);
        }

        ToastNotifications.Draw();

        ImGui.End();
        ImGui.PopStyleColor();
    }

    static bool _fitted;
    static float _requestedWindowAspect;

    /// <summary>
    /// Resize a windowed host when the player explicitly changes the gameplay aspect.
    /// This is separate from the presented texture because game menus remain authored
    /// at 4:3 even when gameplay is configured for 16:9.
    /// </summary>
    public static void RequestWindowAspect(float aspect)
        => _requestedWindowAspect = aspect > 0f ? aspect : Hle.GpuHle.BaseAspect;

    /// <summary>
    /// Shape the window to the aspect being presented, once, on the first widescreen
    /// gameplay frame with a real panel area. Menus arrive first at 4:3; treating that
    /// first texture as the one chance to fit permanently stranded later 16:9 gameplay
    /// inside the original 4:3 host window.
    /// </summary>
    static void FitWindowOnce(Vector2 avail)
    {
        if (_fitted || avail.X < 16f || avail.Y < 16f) return;
        float want = _aspect;
        if (want <= Hle.GpuHle.BaseAspect + 0.01f) return;

        _fitted = true;
        int dx = (int)MathF.Round(avail.Y * want - avail.X);
        Console.WriteLine(
            $"[Host] fitting window to {want:F3} output from {avail.X:F0}x{avail.Y:F0} panel");
        if (dx != 0) HostWindow.GrowWindow(dx, 0);
    }

    static void FitRequestedWindow(Vector2 avail)
    {
        float want = _requestedWindowAspect;
        if (want <= 0f || avail.X < 16f || avail.Y < 16f) return;
        _requestedWindowAspect = 0f;
        _fitted = true;

        // A fullscreen viewport belongs to the monitor. Letter/pillarboxing it is the
        // correct response; changing the monitor mode behind a settings choice is not.
        if (Config.ConfigManager.View.Fullscreen) return;

        int dx = (int)MathF.Round(avail.Y * want - avail.X);
        Console.WriteLine(
            $"[Host] fitting window to selected {want:F3} gameplay aspect from " +
            $"{avail.X:F0}x{avail.Y:F0} panel");
        if (dx != 0) HostWindow.GrowWindow(dx, 0);
    }

    static Vector2 FitAspect(Vector2 src, Vector2 dst)
    {
        float scale = MathF.Min(dst.X / src.X, dst.Y / src.Y);
        return src * scale;
    }
}
