using ImGuiNET;

namespace RecompOne.Runtime.Host.Window;

public static class MenuRegistry
{
    public const int OrderSystem = 0;
    public const int OrderMods = 100;
    public const int OrderGame = 200;
    public const int OrderDebug = 400;
    public const int OrderDefault = 500;
    public const int OrderHelp = 600;

    static readonly List<MenuNode> _roots = [];
    static int _sequence;

    public static MenuBuilder Menu(string labelKey, int order = OrderDefault)
    {
        var node = Find(labelKey);
        if (node == null)
        {
            node = new MenuNode(labelKey) { Order = order, Sequence = _sequence++ };
            _roots.Add(node);
        }
        else if (order < node.Order)
        {
            node.Order = order;
        }

        return new MenuBuilder(node, null);
    }

    public static void BarItem(string labelKey, Action onClick, int order = OrderDefault)
    {
        var node = Find(labelKey) ?? new MenuNode(labelKey) { Order = order, Sequence = _sequence++ };
        node.OnClick = onClick;
        if (!_roots.Contains(node)) _roots.Add(node);
    }

    public static bool Remove(string labelKey) => _roots.RemoveAll(m => m.LabelKey == labelKey) > 0;

    internal static void Draw()
    {
        if (!ImGui.BeginMainMenuBar()) return;

        _roots.Sort((a, b) => a.Order != b.Order ? a.Order.CompareTo(b.Order) : a.Sequence.CompareTo(b.Sequence));
        foreach (var menu in _roots) menu.Draw();

        ImGui.EndMainMenuBar();
    }

    static MenuNode? Find(string labelKey)
    {
        foreach (var menu in _roots)
            if (menu.LabelKey == labelKey) return menu;
        return null;
    }
}
