using ImGuiNET;
using RecompOne.Runtime.Config;

namespace RecompOne.Runtime.Host.Window;

internal sealed class DisplaySettingsSection : ISettingsSection
{
    public string Id => "display";
    public string TitleKey => "settings.display";
    public int Order => 5;

    public void Draw()
    {
        if (Hle.GpuHle.WidescreenSupported)
        {
            bool wide = ConfigManager.Game.Widescreen ?? Hle.GpuHle.WidescreenDefault;
            string preview = Localization.T(wide
                ? "settings.display.aspect_wide"
                : "settings.display.aspect_standard");

            ImGui.TextUnformatted(Localization.T("settings.display.aspect"));
            ImGui.SetNextItemWidth(-1f);
            if (ImGui.BeginCombo("##display-aspect", preview))
            {
                if (ImGui.Selectable(Localization.T("settings.display.aspect_standard"), !wide))
                {
                    ConfigManager.Game.Widescreen = false;
                    ConfigManager.SaveGame();
                    OutputPanel.RequestWindowAspect(Hle.GpuHle.BaseAspect);
                }
                if (ImGui.Selectable(Localization.T("settings.display.aspect_wide"), wide))
                {
                    ConfigManager.Game.Widescreen = true;
                    ConfigManager.SaveGame();
                    OutputPanel.RequestWindowAspect(16f / 9f);
                }
                ImGui.EndCombo();
            }
            if (ImGui.IsItemHovered())
                ImGui.SetTooltip(Localization.T("settings.display.aspect_hint"));
            ImGui.Spacing();
        }

        bool fullscreen = ConfigManager.View.Fullscreen;
        if (ImGui.Checkbox(Localization.T("settings.display.fullscreen"), ref fullscreen))
        {
            ConfigManager.View.Fullscreen = fullscreen;
            HostWindow.SetFullscreen(fullscreen);
            ConfigManager.SaveView(PanelManager.Panels);
        }

        bool vsync = ConfigManager.View.VSync;
        if (ImGui.Checkbox(Localization.T("settings.display.vsync"), ref vsync))
        {
            ConfigManager.View.VSync = vsync;
            HostWindow.SetVSync(vsync);
            ConfigManager.SaveView(PanelManager.Panels);
        }
        if (ImGui.IsItemHovered()) ImGui.SetTooltip(Localization.T("settings.display.vsync_hint"));

        bool fxaa = ConfigManager.View.Fxaa;
        if (ImGui.Checkbox(Localization.T("settings.display.fxaa"), ref fxaa))
        {
            ConfigManager.View.Fxaa = fxaa;
            Hle.GpuHle.FxaaEnabled = fxaa;
            ConfigManager.SaveView(PanelManager.Panels);
        }
        if (ImGui.IsItemHovered()) ImGui.SetTooltip(Localization.T("settings.display.fxaa_hint"));

        int scale = ConfigManager.View.RenderScale;
        if (ImGui.SliderInt(Localization.T("settings.display.render_scale"), ref scale, 1, 8, "%dx"))
        {
            ConfigManager.View.RenderScale = scale;
            ConfigManager.SaveView(PanelManager.Panels);
            NoticePopup.Show(Localization.T("common.restart_required"));
        }
        if (ImGui.IsItemHovered()) ImGui.SetTooltip(Localization.T("settings.display.render_scale_hint"));

        int lines = Hle.GpuHle.LastDisplayH;
        int width = Hle.GpuHle.LastDisplayW;
        if (lines > 0)
            ImGui.TextDisabled(Localization.T("settings.display.render_scale_lines",
                width, lines, width * scale, lines * scale, scale));

        if (scale != Hle.GlVram.Scale)
            ImGui.TextDisabled(Localization.T("settings.display.restart_pending"));

        ImGui.Separator();
        ImGui.TextDisabled(Localization.T("settings.display.backend_running", Hle.GpuBackendFactory.Selected));
    }
}
