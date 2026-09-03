namespace RecompOne.Runtime.Events;

/// <summary>fires for each primitive before it is drawns</summary>
public sealed class RenderPrimEvent : GameEvent
{
    public int Count;
    public readonly int[] X = new int[4];
    public readonly int[] Y = new int[4];
    public readonly int[] U = new int[4];
    public readonly int[] V = new int[4];
    public readonly float[] Depth = new float[4];
    public readonly bool[] HasDepth = new bool[4];
    public int DrawLeft, DrawRight, DrawTop, DrawBottom;
    public int DrawOffsetX, DrawOffsetY;
    public bool Textured, SemiTransparent, Gouraud, Raw;
    /// <summary>Set by a projection-aware listener when every vertex came from the GTE.</summary>
    public bool World;
    /// <summary>Screen-space HUD classified by the widescreen patch.</summary>
    public bool Hud;
    /// <summary>Color-only full-frame overlay that must not replace scene coverage.</summary>
    public bool IgnoreCoverage;
    /// <summary>The SDK draw-environment background rectangle, not scene geometry.</summary>
    public bool Background;
    public int Clut, TexPage;
    public bool Skip;
}
