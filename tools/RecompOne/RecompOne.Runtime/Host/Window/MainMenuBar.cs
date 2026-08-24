using RecompOne.Runtime.Config;

namespace RecompOne.Runtime.Host.Window;

public static class MainMenuBar
{
    public const int SystemSettings = 10;
    public const int SystemViewSeparator = 20;
    public const int SystemShowMenuBar = 30;
    public const int SystemAutoHide = 40;
    public const int SystemFullscreen = 50;
    public const int SystemResetSeparator = 60;
    public const int SystemSoftReset = 70;
    public const int SystemHardReset = 80;
    public const int SystemQuitSeparator = 90;
    public const int SystemQuit = 100;

    static bool _registered;

    public static void RegisterBuiltins()
    {
        if (_registered) return;
        _registered = true;

        MenuRegistry.Menu("menu.system", MenuRegistry.OrderSystem)
            .Popup<SettingsPopup>("menu.system.settings").Order(SystemSettings)
            .Separator().Order(SystemViewSeparator)
            .Check("menu.system.show_menu_bar", () => !ConfigManager.View.HideTopBar, ShowMenuBar, "F1").Order(SystemShowMenuBar)
            .Check("menu.system.autohide_menu_bar", () => ConfigManager.View.AutoHideMenuBar, AutoHideMenuBar).Order(SystemAutoHide).Disabled()
            .Check("menu.system.fullscreen", () => ConfigManager.View.Fullscreen, Fullscreen, "F11").Order(SystemFullscreen)
            .Separator().Order(SystemResetSeparator)
            .Item("menu.system.hard_reset", Runtime.HardReset).Order(SystemHardReset)
            .Separator().Order(SystemQuitSeparator)
            .Item("menu.system.quit", static () => Environment.Exit(0)).Order(SystemQuit);

        MenuRegistry.Menu("menu.mods", MenuRegistry.OrderMods)
            .Popup<ModsPopup>("menu.mods.manage")
            .Item("menu.mods.hub", static () => { }).Disabled();

        MenuRegistry.Menu("menu.debug", MenuRegistry.OrderDebug)
            .Submenu("menu.debug.gpu")
                .Panel<OutputPanel>("panel.output")
                .Panel<VramViewerPanel>("panel.vram_viewer")
                .Panel<TextureInspectorPanel>("panel.texture_inspector")
                .Separator()
                .Check("menu.debug.dump_textures",
                    static () => Assets.Textures.TextureDumper.Tiles,
                    static on => Assets.Textures.TextureDumper.SetTiles(on))
                    .Tooltip("menu.debug.dump_textures.tooltip")
                .Check("menu.debug.dump_pages",
                    static () => Assets.Textures.TextureDumper.Pages,
                    static on => Assets.Textures.TextureDumper.SetPages(on))
                    .Tooltip("menu.debug.dump_pages.tooltip")
                .End()
            .Submenu("menu.debug.cpu")
                .Panel<CpuStatePanel>("panel.cpu_state")
                .End()
            .Submenu("menu.debug.memory")
                .Panel<RamMapPanel>("panel.ram_map")
                .Panel<MemoryEditorPanel>("panel.memory_editor")
                .End()
            .Submenu("menu.debug.audio")
                .Panel<SpuViewerPanel>("panel.spu_viewer")
                .End()
            .Submenu("menu.debug.cd")
                .Panel<CdDebugPanel>("panel.cd_debug")
                .End()
            .Submenu("menu.debug.system")
                .Panel<OverlayEventsPanel>("panel.overlay_events")
                .Panel<ConsolePanel>("panel.console")
                .End()
            .Separator()
            .Item("menu.debug.reset_view", ResetView);
    }

    public static void Draw() => MenuRegistry.Draw();

    static void ResetView()
    {
        ConfigManager.ResetView(PanelManager.Panels);
        HostWindow.RequestLayout();
    }

    static void ShowMenuBar(bool show)
    {
        ConfigManager.View.HideTopBar = !show;
        ConfigManager.SaveView(PanelManager.Panels);
    }

    static void AutoHideMenuBar(bool autoHide)
    {
        ConfigManager.View.AutoHideMenuBar = autoHide;
        ConfigManager.SaveView(PanelManager.Panels);
    }

    static void Fullscreen(bool fullscreen)
    {
        ConfigManager.View.Fullscreen = fullscreen;
        HostWindow.SetFullscreen(fullscreen);
        ConfigManager.SaveView(PanelManager.Panels);
    }
}
