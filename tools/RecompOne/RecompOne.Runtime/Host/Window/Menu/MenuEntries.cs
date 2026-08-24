using ImGuiNET;

namespace RecompOne.Runtime.Host.Window;

abstract class MenuEntry
{
    public int Order;
    public int Sequence;

    public abstract void Draw();
}

sealed class MenuItemEntry(string labelKey, Action onClick) : MenuEntry
{
    public string? Shortcut;
    public Func<bool>? Selected;
    public Func<bool>? Enabled;
    public string? TooltipKey;

    public override void Draw()
    {
        bool selected = Selected?.Invoke() ?? false;
        bool enabled = Enabled?.Invoke() ?? true;

        if (ImGui.MenuItem(Localization.T(labelKey), Shortcut, selected, enabled)) onClick();
        MenuTooltip.Draw(TooltipKey);
    }
}

sealed class MenuTextEntry(Func<string> text) : MenuEntry
{
    public override void Draw() => ImGui.TextDisabled(text());
}

sealed class MenuSeparatorEntry : MenuEntry
{
    public override void Draw() => ImGui.Separator();
}

sealed class MenuCustomEntry(Action draw) : MenuEntry
{
    public override void Draw() => draw();
}

sealed class MenuNode(string labelKey) : MenuEntry
{
    public readonly string LabelKey = labelKey;

    readonly List<MenuEntry> _entries = [];
    bool _sorted = true;
    int _nextOrder;

    public Action? OnClick;
    public Func<bool>? Enabled;
    public string? TooltipKey;

    public int NextOrder() => _nextOrder += MenuBuilder.OrderStep;

    public void Add(MenuEntry entry)
    {
        entry.Sequence = _entries.Count;
        _entries.Add(entry);
        _sorted = false;
        if (entry.Order > _nextOrder) _nextOrder = entry.Order;
    }

    public void Reorder(MenuEntry entry, int order)
    {
        entry.Order = order;
        if (order > _nextOrder) _nextOrder = order;
        _sorted = false;
    }

    public MenuNode Submenu(string key)
    {
        foreach (var entry in _entries)
            if (entry is MenuNode node && node.LabelKey == key) return node;

        var created = new MenuNode(key) { Order = NextOrder() };
        Add(created);
        return created;
    }

    public override void Draw()
    {
        var label = Localization.T(LabelKey);
        bool enabled = Enabled?.Invoke() ?? true;

        if (_entries.Count == 0)
        {
            if (ImGui.MenuItem(label, null, false, enabled)) OnClick?.Invoke();
            MenuTooltip.Draw(TooltipKey);
            return;
        }

        if (!ImGui.BeginMenu(label, enabled))
        {
            MenuTooltip.Draw(TooltipKey);
            return;
        }

        MenuTooltip.Draw(TooltipKey);
        Sort();
        foreach (var entry in _entries) entry.Draw();
        ImGui.EndMenu();
    }

    void Sort()
    {
        if (_sorted) return;
        _entries.Sort((a, b) => a.Order != b.Order ? a.Order.CompareTo(b.Order) : a.Sequence.CompareTo(b.Sequence));
        _sorted = true;
    }
}

static class MenuTooltip
{
    public static void Draw(string? tooltipKey)
    {
        if (tooltipKey == null || !ImGui.IsItemHovered(ImGuiHoveredFlags.AllowWhenDisabled)) return;
        ImGui.SetTooltip(Localization.T(tooltipKey));
    }
}
