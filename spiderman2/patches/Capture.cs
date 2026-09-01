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
///   SPIDEY_SHOTS=60,title.bmr+450
///                              absolute or archive-anchored frames to write a PNG on
///   SPIDEY_SHOT_EVERY=120     ...or write one every N frames
///   SPIDEY_SHOT_DIR=shots     where they go (default "shots")
///   SPIDEY_CAPTURE_PRESENTED=1 capture the final presented frame, including FXAA
///   SPIDEY_CAPTURE_FXAA_PAIR=1 write pre/post-FXAA images from the exact same frame
///   SPIDEY_EXIT=900           quit after this frame
///   SPIDEY_EXIT=e1m0_t.trg+3400
///                              ...or relative to an archive load
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
        public int Occurrence = 1;  // which load of that file, 1-based
        public int Seen;
        public bool Started;
        public int Remaining;
    }

    sealed class Shot
    {
        public long Frame;          // -1 until an anchor resolves it
        public string Anchor;
        public long Offset;
        public int Occurrence = 1;
        public int Seen;
        public bool Fired;
    }

    static readonly List<Shot> _shots = new();

    /// <summary>
    /// SPIDEY_HOT=8000,9000 -- print the functions dominating the call ring on these
    /// frames. A game that presents frames at full rate while its state machine has
    /// stopped moving never trips the watchdog, and the picture alone cannot say which
    /// loop it is stuck in; this names it.
    /// </summary>
    static readonly List<long> _hotFrames = new();
    static bool[] _hotFired = System.Array.Empty<bool>();
    static readonly List<Press> _script = new();
    static string _dir = "shots";
    static long _every;
    static long _exit = -1;
    static Shot _exitShot;
    static bool _active;
    static bool _presented;
    static bool _fxaaPair;
    static string _bootSkipAnchor;
    static bool _bootSkipActive;

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
        var runToken = Environment.GetEnvironmentVariable("SPIDEY_RUN_TOKEN");
        if (!string.IsNullOrWhiteSpace(runToken))
            Console.WriteLine($"[capture] run-token {runToken}");

        _bootSkipAnchor = Environment.GetEnvironmentVariable("SPIDEY_BOOT_SKIP_UNTIL");
        if (!string.IsNullOrWhiteSpace(_bootSkipAnchor))
        {
            _bootSkipActive = true;
            _active = true;
            Console.WriteLine($"[capture] boot-skip armed until '{_bootSkipAnchor}'");
        }

        foreach (var f in Split("SPIDEY_SHOTS"))
        {
            _shots.Add(MakeShot(f));
            _active = true;
        }

        foreach (var f in Split("SPIDEY_HOT"))
            if (long.TryParse(f, out var hf)) { _hotFrames.Add(hf); _active = true; }
        _hotFrames.Sort();
        _hotFired = new bool[_hotFrames.Count];

        var every = Environment.GetEnvironmentVariable("SPIDEY_SHOT_EVERY");
        if (long.TryParse(every, out var e) && e > 0) { _every = e; _active = true; }

        var dir = Environment.GetEnvironmentVariable("SPIDEY_SHOT_DIR");
        if (!string.IsNullOrWhiteSpace(dir)) _dir = dir;

        _presented = Environment.GetEnvironmentVariable("SPIDEY_CAPTURE_PRESENTED") == "1";
        _fxaaPair = Environment.GetEnvironmentVariable("SPIDEY_CAPTURE_FXAA_PAIR") == "1";

        var mark = Environment.GetEnvironmentVariable("SPIDEY_MARK");
        if (long.TryParse(mark, out var mk) && mk > 0) { _markEvery = mk; _active = true; }

        var exit = Environment.GetEnvironmentVariable("SPIDEY_EXIT");
        if (!string.IsNullOrWhiteSpace(exit))
        {
            var stop = MakeShot(exit.Trim());
            if (stop.Frame > 0) _exit = stop.Frame;
            else _exitShot = stop;
            _active = true;
        }

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
        string sourceStatus = _fxaaPair ? " source=fxaa-pair" : _presented ? " source=presented" : " source=raster";
        Console.WriteLine($"[capture] armed: shots={_shots.Count} every={_every} exit={_exit} script={_script.Count}{sourceStatus}");
    }

    /// <summary>
    /// Which SPU voices are still sounding, and their envelope level.
    ///
    /// The game's own SpuGetVoiceEnvelope reads a voice's ENVX and waits for it to reach
    /// zero, so a voice whose envelope never decays is a game that waits forever. This
    /// says whether that is what is happening, rather than leaving it inferred from a
    /// frozen picture.
    /// </summary>
    static string SpuVoices()
    {
        var spu = RecompOne.Runtime.Runtime.Spu;
        if (spu == null) return "spu: (none)";
        var vs = new RecompOne.Runtime.Spu.VoiceDebug[24];
        spu.CaptureDebug(vs, out var st);
        var sb = new System.Text.StringBuilder("spu: ");
        int live = 0;
        for (int i = 0; i < vs.Length; i++)
        {
            if (vs[i].Phase == RecompOne.Runtime.Spu.AdsrPhase.Off && vs[i].AdsrVol == 0) continue;
            live++;
            sb.Append($"v{i}={vs[i].Phase}/{vs[i].AdsrVol}{(vs[i].EndX ? "/end" : "")} ");
        }
        return sb.Append($"| live={live} endx=0x{st.Endx:X6}").ToString();
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

        // "at or after", not "equal to": during an FMV the counter steps by more than
        // one, so an exact match can be stepped straight over and never fire.
        for (int i = 0; i < _hotFrames.Count; i++)
            if (!_hotFired[i] && e.Frame >= _hotFrames[i])
            {
                _hotFired[i] = true;
                Console.WriteLine($"[hot f{e.Frame}] {RecompOne.Runtime.Sdk.LibCdStream.RingState}");
                Console.WriteLine($"[hot f{e.Frame}] {SpuVoices()}");
                Console.WriteLine($"[hot f{e.Frame}] {Diag.Hot(14)}");
            }

        bool explicitShot = false;
        foreach (var shot in _shots)
        {
            if (shot.Fired || shot.Frame < 0 || e.Frame < shot.Frame) continue;
            shot.Fired = true;
            explicitShot = true;
        }
        if (explicitShot || (_every > 0 && e.Frame % _every == 0)) Save(e.Frame);

        if (_exit > 0 && e.Frame >= _exit)
        {
            Console.WriteLine(
                $"[capture] span audit: wide accepted {RecompOne.Runtime.Gpu.WideSpanAccepted}, " +
                $"rejected x/y {RecompOne.Runtime.Gpu.SpanXRejected}/{RecompOne.Runtime.Gpu.SpanYRejected}");
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
        if (_script.Count == 0 && !_bootSkipActive) return;

        ushort held = 0;
        // Movies do not all sample the pad on the same delivered VSync. Pulse START
        // inside the emulated process until the first archive belonging to the target
        // screen loads, then release it immediately. This cannot leak host input and
        // cannot keep advancing menus after the named boundary.
        if (_bootSkipActive && (e.Frame % 24) < 12)
            held |= Controller.Start;

        foreach (var p in _script)
        {
            // An anchored step sits at -1 until its archive loads. Without this guard
            // the window "frame >= -1 && frame < -1 + hold" is open on frames 0..hold-2,
            // so every anchored press also fires at boot: a script that meant to press
            // START at the title screen pressed it on frame 0 as well, which skipped the
            // intro movies. The symptom was that arming any script changed where the
            // game got to, which made scripted runs and measurement runs disagree.
            if (p.Frame < 0) continue;
            // Movie presentation can jump across exact emulated frame numbers. Fire
            // on the first delivered VSync at or after the target, then hold for the
            // requested number of delivered VSyncs so a skip cannot strand the run.
            if (!p.Started && e.Frame >= p.Frame)
            {
                p.Started = true;
                p.Remaining = p.Hold;
                Console.WriteLine(
                    $"[capture] input fired at frame {e.Frame} (target {p.Frame}, hold {p.Hold})");
            }
            if (p.Remaining > 0)
            {
                held |= p.Mask;
                p.Remaining--;
            }
        }

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

        // "e1m0_g.psx#2" -- the second time that file is read, not the first. The
        // attract demo plays the same level the game starts on, so a step anchored to
        // the level's geometry fires during the demo unless it can say which load it
        // means.
        int occurrence = 1;
        int hash = anchor.LastIndexOf('#');
        if (hash > 0 && int.TryParse(anchor.Substring(hash + 1), out var occ) && occ > 0)
        {
            occurrence = occ;
            anchor = anchor.Substring(0, hash);
        }
        return new Press { Frame = -1, Mask = mask, Hold = hold, Anchor = anchor,
                           Offset = offset, Occurrence = occurrence };
    }

    static Shot MakeShot(string raw)
    {
        if (long.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var abs))
            return new Shot { Frame = abs };

        long offset = 0;
        string anchor = raw;
        int plus = raw.LastIndexOf('+');
        if (plus > 0 && long.TryParse(raw.Substring(plus + 1), out var off))
        {
            anchor = raw.Substring(0, plus);
            offset = off;
        }

        int occurrence = 1;
        int hash = anchor.LastIndexOf('#');
        if (hash > 0 && int.TryParse(anchor.Substring(hash + 1), out var occ) && occ > 0)
        {
            occurrence = occ;
            anchor = anchor.Substring(0, hash);
        }
        return new Shot { Frame = -1, Anchor = anchor, Offset = offset, Occurrence = occurrence };
    }

    /// <summary>Called for every archive lookup; resolves any step anchored to it.</summary>
    public static void NoteWadLoad(string name, long frame)
    {
        if (_bootSkipActive &&
            string.Equals(_bootSkipAnchor, name, StringComparison.OrdinalIgnoreCase))
        {
            _bootSkipActive = false;
            Controller.ScriptHeld = 0;
            Console.WriteLine(
                $"[capture] boot-skip completed at '{name}' load frame {frame}");
        }
        foreach (var p in _script)
            if (p.Frame < 0 && p.Anchor != null &&
                string.Equals(p.Anchor, name, StringComparison.OrdinalIgnoreCase))
            {
                if (++p.Seen < p.Occurrence) continue;
                p.Frame = frame + p.Offset;
                Console.WriteLine($"[capture] '{name}' load #{p.Seen} at frame {frame}: step resolved to frame {p.Frame}");
            }
        foreach (var shot in _shots)
            if (shot.Frame < 0 && shot.Anchor != null &&
                string.Equals(shot.Anchor, name, StringComparison.OrdinalIgnoreCase))
            {
                if (++shot.Seen < shot.Occurrence) continue;
                shot.Frame = frame + shot.Offset;
                Console.WriteLine($"[capture] '{name}' load #{shot.Seen} at frame {frame}: shot resolved to frame {shot.Frame}");
            }
        if (_exitShot is { Frame: < 0 } && _exitShot.Anchor != null &&
            string.Equals(_exitShot.Anchor, name, StringComparison.OrdinalIgnoreCase))
        {
            if (++_exitShot.Seen >= _exitShot.Occurrence)
            {
                _exit = frame + _exitShot.Offset;
                _exitShot.Frame = _exit;
                Console.WriteLine($"[capture] '{name}' load #{_exitShot.Seen} at frame {frame}: exit resolved to frame {_exit}");
            }
        }
    }


    // VRAM row 0 sits at framebuffer y=0, so glReadPixels' bottom-first order already
    // comes out top-first here -- no flip. Alpha is the PS1 mask bit, not opacity.
    static void SaveScaled(long frame, byte[] rgba, int w, int h, string suffix = "")
    {
        for (int i = 3; i < rgba.Length; i += 4) rgba[i] = 255;
        (rgba, w) = ToDisplayAspect(rgba, w, h);

        string path = Path.Combine(_dir, $"frame_{frame:D5}{suffix}.png");
        PngWriter.WriteRgba(path, rgba, w, h);
        Console.WriteLine($"[capture] {path} {w}x{h} (live-3d 16bpp display aspect)");
    }

    /// <summary>
    /// Resample to the aspect the console actually outputs.
    ///
    /// PlayStation pixels are not square: a 512x240 frame is meant to fill a 4:3
    /// screen, so a capture written at its stored width is stretched sideways by 1.6x
    /// and every judgement made from it -- does that model look right, is the HUD the
    /// right shape -- is being made about the wrong picture. The window already
    /// presents at Display.OutputAspect; a screenshot should agree with it.
    /// </summary>
    static (byte[] rgba, int w) ToDisplayAspect(byte[] src, int w, int h)
    {
        // Match whatever the window is presenting. SourceAspect carries the widescreen
        // stretch, since the framebuffer itself keeps the console's dimensions.
        float aspect = GpuHle.SourceAspect > 0f ? GpuHle.SourceAspect : 4f / 3f;
        int dstW = (int)MathF.Round(h * aspect);
        if (dstW <= 0 || dstW == w) return (src, w);

        var dst = new byte[dstW * h * 4];
        // Box filter horizontally when shrinking, linear when growing: shrinking 2048
        // to 1280 by point sampling throws away two pixels in five and the HUD text
        // comes out ragged.
        float ratio = (float)w / dstW;
        for (int y = 0; y < h; y++)
        {
            int srcRow = y * w * 4, dstRow = y * dstW * 4;
            for (int x = 0; x < dstW; x++)
            {
                float x0 = x * ratio, x1 = x0 + ratio;
                int i0 = (int)x0, i1 = Math.Min(w - 1, (int)MathF.Ceiling(x1) - 1);
                int r = 0, g = 0, b = 0, n = 0;
                for (int i = i0; i <= i1; i++)
                {
                    int o = srcRow + i * 4;
                    r += src[o]; g += src[o + 1]; b += src[o + 2]; n++;
                }
                if (n == 0) n = 1;
                int d = dstRow + x * 4;
                dst[d] = (byte)(r / n); dst[d + 1] = (byte)(g / n);
                dst[d + 2] = (byte)(b / n); dst[d + 3] = 255;
            }
        }
        return (dst, dstW);
    }

    static void Save(long frame)
    {
        var gpu = Runtime.Gpu;
        var backend = GpuHle.Backend;
        if (gpu == null || backend is not { Ready: true }) return;

        int w = gpu.DisplayWidth, h = gpu.DisplayHeight;
        if (w <= 0 || h <= 0) return;
        int x = gpu.DisplayX, y = gpu.DisplayY;

        if (_fxaaPair)
        {
            var source = backend.ReadPreFxaa(out int sw, out int sh);
            var shown = backend.ReadPresented(out int pw, out int ph);
            if (source != null && shown != null && sw == pw && sh == ph && sw > 0 && sh > 0)
            {
                SaveScaled(frame, source, sw, sh, "_fxaa_source");
                SaveScaled(frame, shown, pw, ph, "_fxaa_result");
                return;
            }
            Console.WriteLine("[capture] exact FXAA pair is not ready; falling back to normal capture");
        }

        if (_presented)
        {
            var shown = backend.ReadPresented(out int pw, out int ph);
            if (shown != null && pw > 0 && ph > 0)
            {
                SaveScaled(frame, shown, pw, ph);
                return;
            }
            Console.WriteLine("[capture] final presented frame is not ready; falling back to raster readback");
        }

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

        (rgba, w) = ToDisplayAspect(rgba, w, h);
        string path = Path.Combine(_dir, $"frame_{frame:D5}.png");
        PngWriter.WriteRgba(path, rgba, w, h);
        Console.WriteLine($"[capture] {path} {w}x{h}{(gpu.Display24Bit ? " (24bpp)" : "")}");
    }
}
