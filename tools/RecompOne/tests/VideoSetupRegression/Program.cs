using RecompOne.Runtime.Config;

static void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
}

foreach (bool wide in new[] { false, true })
{
    var options = wide ? VideoSetupState.Wide : VideoSetupState.Standard;
    foreach (var size in options)
    {
        Check(size.Width * (wide ? 9 : 3) == size.Height * (wide ? 16 : 4), "Incorrect aspect ratio");
        Check(size.Width >= 640 && size.Height >= 480, "Below minimum resolution");
        var state = new VideoSetupState(wide, size.Width, size.Height);
        Check(state.Selected == size, "Saved resolution failed to reopen exactly");
        state.Applied = true;
        state.ChangeResolution(-1);
        state.ChangeResolution(1);
        Check(state.Selected == size && !state.Applied, "Cycling or dirty state failed");
        for (int i = 0; i < options.Length; i++) state.ChangeResolution(1);
        Check(state.Selected == size, "Forward wrap failed");
        for (int i = 0; i < options.Length; i++) state.ChangeResolution(-1);
        Check(state.Selected == size, "Backward wrap failed");
    }
}
var pending = new VideoSetupState(false, 640, 480);
pending.ChangeAspect();
Check(pending.Widescreen && pending.Selected == new VideoSetupState.Resolution(960, 540), "Aspect should preserve nearest height");
pending.ChangeResolution(1);
var reopened = new VideoSetupState(false, 640, 480);
Check(!reopened.Widescreen && reopened.Selected.Width == 640, "Discarded pending choices leaked into new menu");
Console.WriteLine("PASS: all presets, exact saved selections, aspect ratios, minimum size, bidirectional wrap, and independent pending state");
