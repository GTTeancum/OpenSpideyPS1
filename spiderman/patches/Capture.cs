using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using RecompOne.Runtime;
using RecompOne.Runtime.Assets;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Hardware;
using RecompOne.Runtime.Hle;

namespace Recompiled;

/// <summary>
/// Headless verification harness. Off unless the environment asks for it, so a normal
/// launch is unaffected.
///
///   SPIDEY_SHOTS=60,300,600   frames to write a PNG on
///   SPIDEY_SHOT_EVERY=120     ...or write one every N frames
///   SPIDEY_SHOT_DIR=shots     where they go (default "shots")
///   SPIDEY_EXIT=900           quit after this frame
///   SPIDEY_SCRIPT=120:start;300:cross:8
///                              press a button at a frame, optionally for N frames
///   SPIDEY_SCRIPT=title.bmr+200:start:10
///                              ...or a number of frames after an archive file loads,
///                              which is reproducible when the frame number is not
///
/// Frames are read back from the GPU backend rather than off the desktop, so the
/// capture is what the emulated console actually drew.
/// </summary>
public static class Capture
{
    sealed class Press
    {
        public long Frame;          // -1 until an anchor resolves it
        public ushort Mask;
        public int Hold;
        public string Anchor;       // archive file whose load starts the countdown
        public long Offset;
    }

    static readonly HashSet<long> _shotFrames = new();
    static readonly List<Press> _script = new();
    static string _dir = "shots";
    static long _every;
    static long _exit = -1;
    static bool _active;

    static readonly Dictionary<string, ushort> Buttons = new(StringComparer.OrdinalIgnoreCase)
    {
        ["select"] = Controller.Select,
        ["l3"] = Controller.L3,
        ["r3"] = Controller.R3,
        ["start"] = Controller.Start,
        ["up"] = Controller.Up,
        ["right"] = Controller.Right,
        ["down"] = Controller.Down,
        ["left"] = Controller.Left,
        ["l2"] = Controller.L2,
        ["r2"] = Controller.R2,
        ["l1"] = Controller.L1,
        ["r1"] = Controller.R1,
        ["triangle"] = Controller.Triangle,
        ["circle"] = Controller.Circle,
        ["cross"] = Controller.Cross,
        ["square"] = Controller.Square,
    };

    public static void Install()
    {
        foreach (var f in Split("SPIDEY_SHOTS"))
            if (long.TryParse(f, out var n)) { _shotFrames.Add(n); _active = true; }

        var every = Environment.GetEnvironmentVariable("SPIDEY_SHOT_EVERY");
        if (long.TryParse(every, out var e) && e > 0) { _every = e; _active = true; }

        var dir = Environment.GetEnvironmentVariable("SPIDEY_SHOT_DIR");
        if (!string.IsNullOrWhiteSpace(dir)) _dir = dir;

        var mark = Environment.GetEnvironmentVariable("SPIDEY_MARK");
        if (long.TryParse(mark, out var mk) && mk > 0) { _markEvery = mk; _active = true; }

        var exit = Environment.GetEnvironmentVariable("SPIDEY_EXIT");
        if (long.TryParse(exit, out var x) && x > 0) { _exit = x; _active = true; }

        foreach (var step in Split("SPIDEY_SCRIPT", ';'))
        {
            var parts = step.Split(':');
            if (parts.Length < 2) continue;
            string rawFrame = parts[0].Trim();
            ushort mask = 0;
            foreach (var name in parts[1].Split('+'))
                if (Buttons.TryGetValue(name.Trim(), out var b)) mask |= b;
            if (mask == 0) continue;
            int hold = 4;
            if (parts.Length > 2 && int.TryParse(parts[2], out var h) && h > 0) hold = h;
            _script.Add(MakePress(rawFrame, mask, hold));
            _active = true;
        }

        // The frame counter feeds the watchdog, so listen even with nothing to capture.
        if (_active) Directory.CreateDirectory(_dir);
        Event.AddListener<VSyncEvent>(OnFrame);
        if (!_active) return;
        Console.WriteLine($"[capture] armed: shots={_shotFrames.Count} every={_every} exit={_exit} script={_script.Count}");
    }

    static IEnumerable<string> Split(string name, char sep = ',')
    {
        var v = Environment.GetEnvironmentVariable(name);
        if (string.IsNullOrWhiteSpace(v)) yield break;
        foreach (var part in v.Split(sep))
            if (part.Trim().Length > 0)
                yield return part.Trim();
    }

    static long _markEvery;

    static void OnFrame(VSyncEvent e)
    {
        System.Threading.Interlocked.Exchange(ref Diag.Frame, e.Frame);
        DriveInput(e);

        if (_markEvery > 0 && e.Frame % _markEvery == 0)
            Console.WriteLine($"[frame {e.Frame}]");

        if (_shotFrames.Contains(e.Frame) || (_every > 0 && e.Frame % _every == 0))
            Save(e.Frame);

        if (_exit > 0 && e.Frame >= _exit)
        {
            Console.WriteLine($"[capture] exit at frame {e.Frame}");
            Console.Out.Flush();
            Runtime.Shutdown();
            Environment.Exit(0);
        }
    }

    // Fed into the runtime's controller state rather than written over the pad buffers.
    // The buffers get refreshed from that state on the runtime's own schedule, so a
    // press written directly into them only lasted until the next refresh -- which,
    // once the service tick started running between frames, was almost immediately.
    static void DriveInput(VSyncEvent e)
    {
        if (_script.Count == 0) return;

        ushort held = 0;
        foreach (var p in _script)
            if (e.Frame >= p.Frame && e.Frame < p.Frame + p.Hold)
                held |= p.Mask;

        RecompOne.Runtime.Hardware.Controller.ScriptHeld = held;
    }

    /// <summary>
    /// A step is either an absolute frame, or an archive file name and an offset --
    /// "title.bmr+200". The game paces itself off the wall clock, so the frame a given
    /// screen appears on moves by hundreds between runs and an absolute schedule stops
    /// lining up with the menus. Anchoring to the load of a file that screen needs
    /// makes a script mean the same thing every time.
    /// </summary>
    static Press MakePress(string raw, ushort mask, int hold)
    {
        if (long.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var abs))
            return new Press { Frame = abs, Mask = mask, Hold = hold };

        long offset = 0;
        string anchor = raw;
        int plus = raw.LastIndexOf('+');
        if (plus > 0 && long.TryParse(raw.Substring(plus + 1), out var off))
        {
            anchor = raw.Substring(0, plus);
            offset = off;
        }
        return new Press { Frame = -1, Mask = mask, Hold = hold, Anchor = anchor, Offset = offset };
    }

    /// <summary>Called for every archive lookup; resolves any step anchored to it.</summary>
    public static void NoteWadLoad(string name, long frame)
    {
        foreach (var p in _script)
            if (p.Frame < 0 && p.Anchor != null &&
                string.Equals(p.Anchor, name, StringComparison.OrdinalIgnoreCase))
            {
                p.Frame = frame + p.Offset;
                Console.WriteLine($"[capture] '{name}' at frame {frame}: step resolved to frame {p.Frame}");
            }
    }

    static void WritePad(uint buf, ushort state)
    {
        var m = Runtime.Mem;
        if (m == null || buf == 0) return;
        m.WriteU8(buf + 0, 0x00);
        m.WriteU8(buf + 1, 0x41);
        m.WriteU8(buf + 2, (byte)(state & 0xFF));
        m.WriteU8(buf + 3, (byte)(state >> 8));
    }

    // VRAM row 0 sits at framebuffer y=0, so glReadPixels' bottom-first order already
    // comes out top-first here -- no flip. Alpha is the PS1 mask bit, not opacity.
    static void SaveScaled(long frame, byte[] rgba, int w, int h)
    {
        for (int i = 3; i < rgba.Length; i += 4) rgba[i] = 255;

        string path = Path.Combine(_dir, $"frame_{frame:D5}.png");
        PngWriter.WriteRgba(path, rgba, w, h);
        Console.WriteLine($"[capture] {path} {w}x{h} (internal resolution)");
    }

    static void Save(long frame)
    {
        var gpu = Runtime.Gpu;
        var backend = GpuHle.Backend;
        if (gpu == null || backend is not { Ready: true }) return;

        int w = gpu.DisplayWidth, h = gpu.DisplayHeight;
        if (w <= 0 || h <= 0) return;
        int x = gpu.DisplayX, y = gpu.DisplayY;

        // Prefer the full internal resolution: VRAM is stored at RenderScale, so this is
        // the image the rasteriser actually produced rather than a console-resolution
        // capture. Not available for 24bpp FMV, where VRAM holds packed byte triples
        // that only make sense read back at native width.
        if (!gpu.Display24Bit)
        {
            var scaled = backend.ReadScaled(x, y, w, h, out int sw, out int sh);
            if (scaled != null && sw > 0 && sh > 0)
            {
                SaveScaled(frame, scaled, sw, sh);
                return;
            }
        }

        // In 24-bit mode three bytes per pixel are packed across the 16-bit words.
        int srcW = gpu.Display24Bit ? (w * 3 + 1) / 2 : w;
        var px = new ushort[srcW * h];
        try { backend.ReadVram(x, y, srcW, h, px); }
        catch (Exception ex) { Console.WriteLine($"[capture] readback failed: {ex.Message}"); return; }

        var rgba = new byte[w * h * 4];
        for (int row = 0; row < h; row++)
        {
            for (int col = 0; col < w; col++)
            {
                int o = (row * w + col) * 4;
                byte r, g, b;
                if (gpu.Display24Bit)
                {
                    int byteIndex = col * 3;
                    int wi = row * srcW + (byteIndex >> 1);
                    ushort w0 = px[wi];
                    ushort w1 = (wi + 1) < (row + 1) * srcW ? px[wi + 1] : (ushort)0;
                    if ((byteIndex & 1) == 0)
                    {
                        r = (byte)(w0 & 0xFF);
                        g = (byte)(w0 >> 8);
                        b = (byte)(w1 & 0xFF);
                    }
                    else
                    {
                        r = (byte)(w0 >> 8);
                        g = (byte)(w1 & 0xFF);
                        b = (byte)(w1 >> 8);
                    }
                }
                else
                {
                    ushort p = px[row * srcW + col];
                    r = (byte)((p & 0x1F) << 3);
                    g = (byte)(((p >> 5) & 0x1F) << 3);
                    b = (byte)(((p >> 10) & 0x1F) << 3);
                    r |= (byte)(r >> 5); g |= (byte)(g >> 5); b |= (byte)(b >> 5);
                }
                rgba[o] = r; rgba[o + 1] = g; rgba[o + 2] = b; rgba[o + 3] = 255;
            }
        }

        string path = Path.Combine(_dir, $"frame_{frame:D5}.png");
        PngWriter.WriteRgba(path, rgba, w, h);
        Console.WriteLine($"[capture] {path} {w}x{h}{(gpu.Display24Bit ? " (24bpp)" : "")}");
    }
}
