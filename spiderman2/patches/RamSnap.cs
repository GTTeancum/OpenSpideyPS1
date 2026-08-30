using System;
using System.Collections.Generic;
using System.IO;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Writes the game's 2 MB of RAM to a file on named frames.
///
/// This exists to find variables by differencing rather than by reading disassembly.
/// Driving the menus from a timed button script does not work -- the frame a screen
/// appears on moves by hundreds between runs -- so the port needs to read the menu's
/// own selection instead of guessing when to press. Snapshot with one item highlighted,
/// press, snapshot again, and the selection is whichever small integer moved by one.
///
///     SPIDEY_SNAP=2560,2680     write ram_02560.bin and ram_02680.bin
///
/// 3 MB: the 2 MB the game allocates from, plus the fixed overlay region above it --
/// the menu lives in the shell overlay, so its variables are up there.
/// </summary>
public static class RamSnap
{
    const uint Base = 0x80000000, Size = 0x00300000;   // includes the overlay region at 0x80200000

    static readonly HashSet<long> _frames = new();
    static string _dir = "snaps";
    static bool _onCrash;
    static IMemory _mem;
    static long _lastFrame;

    public static void Install()
    {
        var spec = Environment.GetEnvironmentVariable("SPIDEY_SNAP");
        if (string.IsNullOrWhiteSpace(spec)) return;

        foreach (var raw in spec.Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            var t = raw.Trim();
            // A frame number is only reachable if the run gets that far, and a run that
            // dies gets there at a different frame every time. "crash" catches it where
            // it actually matters.
            if (t.Equals("crash", StringComparison.OrdinalIgnoreCase)) _onCrash = true;
            else if (long.TryParse(t, out var f)) _frames.Add(f);
        }
        if (_frames.Count == 0 && !_onCrash) return;

        _dir = Environment.GetEnvironmentVariable("SPIDEY_SNAP_DIR") ?? "snaps";
        Directory.CreateDirectory(_dir);
        Event.AddListener<VSyncEvent>(OnFrame);
        Console.WriteLine($"[snap] armed for {_frames.Count} frame(s)" +
                          (_onCrash ? " and on crash" : "") + $" -> {_dir}");
    }

    /// <summary>Write a snapshot now, named for why. Safe to call from a crash handler.</summary>
    public static void DumpNow(string tag)
    {
        if (!_onCrash || _mem == null) return;
        try { Write(_mem, $"ram_{tag}.bin"); }
        catch (Exception e) { Console.Error.WriteLine($"[snap] {tag} failed: {e.Message}"); }
    }

    static void OnFrame(VSyncEvent e)
    {
        _mem = e.Memory;
        _lastFrame = e.Frame;
        if (!_frames.Remove(e.Frame)) return;

        Write(e.Memory, $"ram_{e.Frame:D5}.bin");
    }

    static void Write(IMemory m, string name)
    {
        Directory.CreateDirectory(_dir);
        var buf = new byte[Size];
        for (uint o = 0; o < Size; o += 4)
        {
            uint w = m.ReadU32(Base + o);
            buf[o] = (byte)w; buf[o + 1] = (byte)(w >> 8);
            buf[o + 2] = (byte)(w >> 16); buf[o + 3] = (byte)(w >> 24);
        }

        string path = Path.Combine(_dir, name);
        File.WriteAllBytes(path, buf);
        Console.WriteLine($"[snap] {path} (frame {_lastFrame})");
    }
}
