namespace RecompOne.Runtime.Config;

/// <summary>Pending in-game video choices; nothing is persisted until Apply.</summary>
public sealed class VideoSetupState
{
    public readonly record struct Resolution(int Width, int Height)
    {
        public override string ToString() => $"{Width}x{Height}";
    }
    public static readonly Resolution[] Standard = [new(640, 480), new(800, 600), new(1024, 768), new(1280, 960), new(1600, 1200), new(1920, 1440)];
    public static readonly Resolution[] Wide = [new(960, 540), new(1280, 720), new(1600, 900), new(1920, 1080), new(2560, 1440), new(3840, 2160)];
    public bool Widescreen { get; private set; }
    public bool Fullscreen { get; private set; }
    public int Index { get; private set; }
    public bool Applied { get; set; }
    public Resolution[] Choices => Widescreen ? Wide : Standard;
    public Resolution Selected => Choices[Index];
    public VideoSetupState(bool wide, int width, int height, bool fullscreen = false)
    {
        Fullscreen = fullscreen;
        Widescreen = wide;
        Index = Array.FindIndex(Choices, r => r.Width == width && r.Height == height);
        if (Index < 0) Index = Array.IndexOf(Choices, Choices.MinBy(r => Math.Abs(r.Height - height)));
    }
    public void ChangeAspect()
    {
        int height = Selected.Height;
        Widescreen = !Widescreen;
        Index = Array.IndexOf(Choices, Choices.MinBy(r => Math.Abs(r.Height - height)));
        Applied = false;
    }
    public void ChangeFullscreen()
    {
        Fullscreen = !Fullscreen;
        Applied = false;
    }
    public void ChangeResolution(int direction)
    {
        Index = (Index + direction + Choices.Length) % Choices.Length;
        Applied = false;
    }
}
