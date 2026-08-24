namespace RecompOne.Runtime.Host.Window;

public sealed class MenuBuilder
{
    public const int OrderStep = 10;

    readonly MenuNode _node;
    readonly MenuBuilder? _parent;

    MenuEntry? _last;
    MenuItemEntry? _lastItem;
    MenuNode? _lastNode;

    internal MenuBuilder(MenuNode node, MenuBuilder? parent)
    {
        _node = node;
        _parent = parent;
        if (parent != null)
        {
            _last = node;
            _lastNode = node;
        }
    }

    public MenuBuilder Item(string labelKey, Action onClick, string? shortcut = null)
    {
        _lastItem = new MenuItemEntry(labelKey, onClick) { Shortcut = shortcut };
        _lastNode = null;
        _last = _lastItem;
        Add(_lastItem);
        return this;
    }

    public MenuBuilder Check(string labelKey, Func<bool> get, Action<bool> set, string? shortcut = null)
    {
        Item(labelKey, () => set(!get()), shortcut);
        _lastItem!.Selected = get;
        return this;
    }

    public MenuBuilder Panel<T>(string labelKey) where T : class, IPanel
    {
        return Check(labelKey,
            () => PanelManager.Get<T>()?.IsOpen == true,
            open => { if (PanelManager.Get<T>() is { } panel) panel.IsOpen = open; });
    }

    public MenuBuilder Popup<T>(string labelKey) where T : Popup
    {
        return Item(labelKey, PopupManager.Open<T>);
    }

    public MenuBuilder Label(string labelKey) => Text(() => Localization.T(labelKey));

    public MenuBuilder Text(Func<string> text)
    {
        Track(new MenuTextEntry(text));
        return this;
    }

    public MenuBuilder Separator()
    {
        Track(new MenuSeparatorEntry());
        return this;
    }

    public MenuBuilder Custom(Action draw)
    {
        Track(new MenuCustomEntry(draw));
        return this;
    }

    public MenuBuilder Submenu(string labelKey) => new(_node.Submenu(labelKey), this);

    void Track(MenuEntry entry)
    {
        _lastItem = null;
        _lastNode = null;
        _last = entry;
        Add(entry);
    }

    public MenuBuilder End() => _parent ?? this;

    public MenuBuilder Order(int order)
    {
        if (_last == null) return this;
        if (_last == _node) _parent?.ReorderChild(_node, order);
        else _node.Reorder(_last, order);
        return this;
    }

    internal void ReorderChild(MenuNode child, int order) => _node.Reorder(child, order);

    public MenuBuilder Enabled(Func<bool> predicate)
    {
        if (_lastItem != null) _lastItem.Enabled = predicate;
        else if (_lastNode != null) _lastNode.Enabled = predicate;
        return this;
    }

    public MenuBuilder Disabled() => Enabled(static () => false);

    public MenuBuilder Tooltip(string tooltipKey)
    {
        if (_lastItem != null) _lastItem.TooltipKey = tooltipKey;
        else if (_lastNode != null) _lastNode.TooltipKey = tooltipKey;
        return this;
    }

    void Add(MenuEntry entry)
    {
        entry.Order = _node.NextOrder();
        _node.Add(entry);
    }
}
