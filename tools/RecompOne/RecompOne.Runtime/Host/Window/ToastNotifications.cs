using System.Numerics;
using ImGuiNET;

namespace RecompOne.Runtime.Host.Window;

public static class ToastNotifications
{
    const float SlideIn = 0.28f;
    const float SlideOut = 0.22f;
    const float DefaultDuration = 5f;
    const float Width = 330f;
    const float Margin = 12f;
    const float Spacing = 8f;
    const float IconSize = 34f;
    const float AccentBar = 3f;

    sealed class Toast
    {
        public int Id;
        public string Title = "";
        public string Message = "";
        public Func<uint>? Icon;
        public uint Texture;
        public bool TextureResolved;
        public float Duration;
        public float Enter;
        public float Age;
        public float Fade;
        public float Y;
        public bool Placed;
        public bool Hovered;
        public bool Closing;
    }

    static readonly List<Toast> _toasts = [];
    static readonly object _gate = new();
    static int _nextId;

    public static void Show(string titleKey, string messageKey, Func<uint>? icon = null, float duration = DefaultDuration)
        => ShowText(Localization.T(titleKey), Localization.T(messageKey), icon, duration);

    public static void ShowText(string title, string message, Func<uint>? icon = null, float duration = DefaultDuration)
    {
        lock (_gate)
            _toasts.Add(new Toast
            {
                Id = ++_nextId,
                Title = title ?? "",
                Message = message ?? "",
                Icon = icon,
                Duration = duration <= 0f ? DefaultDuration : duration,
            });
    }

    public static void Clear()
    {
        lock (_gate) _toasts.Clear();
    }

    public static void Draw() //draw in panel not outside
    {
        Toast[] toasts;
        lock (_gate)
        {
            if (_toasts.Count == 0) return;
            toasts = _toasts.ToArray();
        }

        var origin = ImGui.GetWindowPos();
        var areaMin = origin + ImGui.GetWindowContentRegionMin();
        var areaMax = origin + ImGui.GetWindowContentRegionMax();
        if (areaMax.X - areaMin.X < 1f || areaMax.Y - areaMin.Y < 1f) return;

        var style = ImGui.GetStyle();
        float dt = ImGui.GetIO().DeltaTime;
        float scale = Theme.Scale;
        float margin = Margin * scale;
        float spacing = Spacing * scale;
        float width = MathF.Min(Width * scale, areaMax.X - areaMin.X - margin * 2f);

        bool windowHovered = ImGui.IsWindowHovered(ImGuiHoveredFlags.ChildWindows);
        float right = areaMax.X - margin;
        float stackY = areaMin.Y + margin;

        var draw = ImGui.GetWindowDrawList();
        draw.PushClipRect(areaMin, areaMax, true);

        foreach (var toast in toasts)
        {
            toast.Enter += dt;
            if (!toast.Closing && !toast.Hovered) toast.Age += dt;
            if (!toast.Closing && toast.Age >= toast.Duration) toast.Closing = true;
            if (toast.Closing) toast.Fade += dt;

            float progress = toast.Closing
                ? 1f - Ease(Math.Clamp(toast.Fade / SlideOut, 0f, 1f))
                : Ease(Math.Clamp(toast.Enter / SlideIn, 0f, 1f));

            float height = Measure(toast, width, scale, style, out float rowHeight, out float textHeight, out float textWidth);

            if (!toast.Placed)
            {
                toast.Y = stackY;
                toast.Placed = true;
            }
            else
            {
                toast.Y += (stackY - toast.Y) * Math.Min(1f, dt * 14f);
            }

            float slide = (1f - progress) * (width + margin * 2f);
            var min = new Vector2(right - width + slide, toast.Y);
            var max = min + new Vector2(width, height);

            Paint(draw, toast, min, max, progress, rowHeight, textHeight, textWidth, scale, style);

            toast.Hovered = windowHovered && ImGui.IsMouseHoveringRect(min, max);
            if (toast.Hovered && ImGui.IsMouseClicked(ImGuiMouseButton.Left)) toast.Closing = true;

            stackY += height + spacing;
        }

        draw.PopClipRect();

        lock (_gate)
            _toasts.RemoveAll(t => t.Closing && t.Fade >= SlideOut);
    }

    static float Measure(Toast toast, float width, float scale, ImGuiStylePtr style,out float rowHeight, out float textHeight, out float textWidth) //icon calc
    {
        float icon = Texture(toast) != 0 ? IconSize * scale : 0f;
        float inner = AccentBar * scale + style.WindowPadding.X;

        textWidth = width - inner - style.WindowPadding.X;
        if (icon > 0f) textWidth -= icon + style.ItemSpacing.X;
        if (textWidth < 1f) textWidth = 1f;

        float titleHeight = toast.Title.Length > 0 ? ImGui.CalcTextSize(toast.Title, false, textWidth).Y : 0f;
        float messageHeight = toast.Message.Length > 0 ? ImGui.CalcTextSize(toast.Message, false, textWidth).Y : 0f;

        textHeight = titleHeight + messageHeight;
        if (titleHeight > 0f && messageHeight > 0f) textHeight += style.ItemSpacing.Y;

        rowHeight = MathF.Max(icon, textHeight);
        return rowHeight + style.WindowPadding.Y * 2f;
    }

    static void Paint(ImDrawListPtr draw, Toast toast, Vector2 min, Vector2 max, float alpha,
        float rowHeight, float textHeight, float textWidth, float scale, ImGuiStylePtr style)
    {
        float rounding = style.WindowRounding;
        float bar = AccentBar * scale;

        draw.AddRectFilled(min, max, Fade(style.Colors[(int)ImGuiCol.PopupBg], alpha * 0.97f), rounding);

        draw.PushClipRect(min, new Vector2(min.X + bar, max.Y), true);
        draw.AddRectFilled(min, max, Fade(Theme.Accent, alpha), rounding, ImDrawFlags.RoundCornersLeft);
        draw.PopClipRect();

        draw.AddRect(min, max, Fade(style.Colors[(int)ImGuiCol.Border], alpha), rounding);

        float x = min.X + bar + style.WindowPadding.X;
        float top = min.Y + style.WindowPadding.Y;

        uint texture = Texture(toast);
        if (texture != 0)
        {
            float size = IconSize * scale;
            var at = new Vector2(x, top + (rowHeight - size) * 0.5f);
            draw.AddImage((nint)texture, at, at + new Vector2(size, size), Vector2.Zero, Vector2.One,
                Fade(Vector4.One, alpha));
            x += size + style.ItemSpacing.X;
        }

        var font = ImGui.GetFont();
        float fontSize = ImGui.GetFontSize();
        float y = top + (rowHeight - textHeight) * 0.5f;

        if (toast.Title.Length > 0)
        {
            draw.AddText(font, fontSize, new Vector2(x, y), Fade(Theme.AccentText, alpha), toast.Title, textWidth);
            y += ImGui.CalcTextSize(toast.Title, false, textWidth).Y + style.ItemSpacing.Y;
        }

        if (toast.Message.Length > 0)
            draw.AddText(font, fontSize, new Vector2(x, y), Fade(style.Colors[(int)ImGuiCol.Text], alpha),
                toast.Message, textWidth);
    }

    static uint Fade(Vector4 color, float alpha) => ImGui.ColorConvertFloat4ToU32(color with { W = color.W * alpha });

    static uint Texture(Toast toast)
    {
        if (toast.TextureResolved) return toast.Texture;
        toast.TextureResolved = true;
        if (toast.Icon == null) return 0;

        try { toast.Texture = toast.Icon(); }
        catch (Exception e) { Console.Error.WriteLine($"[Toast] icon failed: {e.Message}"); }
        return toast.Texture;
    }

    static float Ease(float t) => 1f - MathF.Pow(1f - t, 3f); //easy the position to make it smoooooooth
}
