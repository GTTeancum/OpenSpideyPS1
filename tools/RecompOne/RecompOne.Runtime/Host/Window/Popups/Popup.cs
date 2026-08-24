using System.Numerics;
using ImGuiNET;

namespace RecompOne.Runtime.Host.Window;

public abstract class Popup
{
    protected virtual Vector2 Size => new(520f, 0f);

    protected abstract string TitleKey { get; }

    protected virtual bool Closable => true;

    protected abstract void DrawContent();

    protected virtual void OnOpened() { }

    protected virtual void OnClosed() { }

    protected internal virtual void Update() { }

    public bool IsOpen { get; private set; }

    public void Open()
    {
        if (IsOpen) return;
        IsOpen = true;
        _pendingOpen = true;
        _pendingClose = false;
        PopupManager.Push(this);
        OnOpened();
    }

    public void Close()
    {
        if (!IsOpen) return;
        IsOpen = false;
        _pendingClose = true;
        PopupManager.CloseAbove(this);
        OnClosed();
    }

    public void Toggle()
    {
        if (IsOpen) Close();
        else Open();
    }

    string Id => _id ??= $"##popup-{GetType().FullName}";
    string? _id;

    bool _pendingOpen;
    bool _pendingClose;

    internal bool Finished => !IsOpen && !_pendingClose;

    internal void Render(int stackIndex)
    {
        if (_pendingOpen)
        {
            ImGui.OpenPopup(Id);
            _pendingOpen = false;
        }

        var viewport = ImGui.GetMainViewport();
        var style = ImGui.GetStyle();

        ImGui.SetNextWindowPos(viewport.GetCenter(), ImGuiCond.Always, new Vector2(0.5f, 0.5f));
        ImGui.SetNextWindowSize(Size * Theme.Scale, ImGuiCond.Always);

        const ImGuiWindowFlags flags =
            ImGuiWindowFlags.NoTitleBar | ImGuiWindowFlags.NoResize | ImGuiWindowFlags.NoMove |
            ImGuiWindowFlags.NoDocking | ImGuiWindowFlags.NoSavedSettings | ImGuiWindowFlags.NoScrollbar |
            ImGuiWindowFlags.NoScrollWithMouse;

        ImGui.PushStyleVar(ImGuiStyleVar.WindowPadding, Vector2.Zero);
        bool visible = ImGui.BeginPopupModal(Id, flags);
        ImGui.PopStyleVar();

        if (!visible)
        {
            _pendingClose = false;
            if (IsOpen) Close();
            _pendingClose = false;
            return;
        }

        DrawTitleBar();

        var padding = style.WindowPadding;
        var body = new Vector2(0f, Size.Y > 0f ? -padding.Y : 0f);
        var childFlags = ImGuiChildFlags.AlwaysUseWindowPadding |
                         (Size.Y > 0f ? ImGuiChildFlags.None : ImGuiChildFlags.AutoResizeY);

        ImGui.PushStyleVar(ImGuiStyleVar.WindowPadding, padding);
        ImGui.PushStyleVar(ImGuiStyleVar.ChildBorderSize, 0f);
        ImGui.PushStyleColor(ImGuiCol.ChildBg, Vector4.Zero);
        bool bodyVisible = ImGui.BeginChild("##body", body, childFlags, ImGuiWindowFlags.NoSavedSettings);
        ImGui.PopStyleColor();
        ImGui.PopStyleVar(2);

        if (bodyVisible) DrawContent();
        ImGui.EndChild();

        if (Closable && stackIndex == PopupManager.TopIndex && ImGui.IsKeyPressed(ImGuiKey.Escape))
            Close();

        PopupManager.DrawNested(stackIndex + 1);

        if (_pendingClose)
        {
            ImGui.CloseCurrentPopup();
            _pendingClose = false;
        }

        ImGui.EndPopup();
    }

    void DrawTitleBar()
    {
        var style = ImGui.GetStyle();
        var draw = ImGui.GetWindowDrawList();

        float height = Theme.TitleBarHeight;
        var origin = ImGui.GetCursorScreenPos();
        var end = new Vector2(origin.X + ImGui.GetWindowWidth(), origin.Y + height);

        draw.AddRectFilled(origin, end, ImGui.ColorConvertFloat4ToU32(Theme.TitleBar),
            style.WindowRounding, ImDrawFlags.RoundCornersTop);

        var title = Localization.T(TitleKey);
        draw.AddText(new Vector2(origin.X + style.WindowPadding.X, origin.Y + (height - ImGui.GetFontSize()) * 0.5f),
            ImGui.ColorConvertFloat4ToU32(Theme.TitleBarText), title);

        if (Closable) DrawCloseButton(origin, height);

        ImGui.SetCursorScreenPos(new Vector2(origin.X, end.Y));
        ImGui.Dummy(Vector2.Zero);
    }

    void DrawCloseButton(Vector2 origin, float height)
    {
        var style = ImGui.GetStyle();
        float margin = style.FramePadding.Y;
        float size = height - margin * 2f;
        var pos = new Vector2(origin.X + ImGui.GetWindowWidth() - size - style.WindowPadding.X * 0.5f, origin.Y + margin);

        ImGui.SetCursorScreenPos(pos);
        bool clicked = ImGui.InvisibleButton("##close", new Vector2(size, size));
        bool hovered = ImGui.IsItemHovered();

        var text = Theme.TitleBarText;
        var draw = ImGui.GetWindowDrawList();
        if (hovered)
            draw.AddRectFilled(pos, pos + new Vector2(size, size),
                ImGui.ColorConvertFloat4ToU32(text with { W = 0.18f }), style.FrameRounding);

        float inset = size * 0.32f;
        uint color = ImGui.ColorConvertFloat4ToU32(text with { W = hovered ? 1f : 0.8f });
        draw.AddLine(pos + new Vector2(inset, inset), pos + new Vector2(size - inset, size - inset), color, 1.6f * Theme.Scale);
        draw.AddLine(pos + new Vector2(size - inset, inset), pos + new Vector2(inset, size - inset), color, 1.6f * Theme.Scale);

        if (hovered) ImGui.SetTooltip(Localization.T("common.close"));
        if (clicked) Close();
    }
}
