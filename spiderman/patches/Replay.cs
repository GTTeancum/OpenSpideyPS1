using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Hardware;

namespace Recompiled;

/// <summary>
/// Recording a play session's controller input, and replaying it.
///
/// A rendering fault that only shows up while moving is very hard to work on from a
/// description. Screenshot scripts reach a place and stop; the faults worth chasing --
/// geometry clipping at the frame edges, primitives dropped on a particular camera
/// angle -- happen in transit, on a path a fixed button script cannot fly. So the path
/// gets recorded once by a person and then flown as often as needed.
///
///   SPIDEY_REC=paths/rooftop.rec    record this session's pad input
///   SPIDEY_PLAY=paths/rooftop.rec   drive the pad from a recording instead
///   SPIDEY_PLAY_EXIT=1              quit when the recording runs out
///   SPIDEY_PLAY_LOOP=1              ...or start it again
///   SPIDEY_PLAY_AT=l1a1.vab+60      hold the replay until this archive loads
///
/// A recording anchors itself, and it begins at the first button actually pressed.
/// Sitting through the logos is not part of anyone's route, and it is the part that
/// drifts -- boot takes a different number of frames every run -- so the leading idle is
/// dropped and what gets written down instead is which archive had most recently loaded
/// when the player first touched the pad, and how long after. A replay waits for that
/// same load and then counts the same interval, which puts the route back where it was
/// recorded rather than a few hundred frames off it. SPIDEY_PLAY_AT overrides.
///
/// Replay pairs with the capture switches, so the usual way to look at a fault is
/// SPIDEY_PLAY with SPIDEY_SHOT_EVERY.
///
/// The format is text, run-length coded, one line per run of identical pad state:
///
///   &lt;frames&gt; &lt;state&gt; &lt;lx&gt; &lt;ly&gt; &lt;rx&gt; &lt;ry&gt;
///
/// State is the PlayStation button word as the host reports it -- active low, so FFFF
/// is nothing pressed. Axes are 00..FF with 80 centred. Text because these files are
/// worth reading and editing: trimming a recording to the ten seconds that matter, or
/// hand-writing a slow pan, is the point of having them.
///
/// **Replay is not deterministic.** The game paces itself off the wall clock, so the
/// same input does not land on the same game state twice -- see the note in
/// spiderman/README.md. A replay reproduces a route, not a frame.
/// </summary>
public static class Replay
{
    struct Frame
    {
        public ushort State;
        public byte Lx, Ly, Rx, Ry;
    }

    const string Magic = "# spidey input recording v1";

    // A run is flushed at least this often even while nothing changes, so a session
    // that ends by closing the window still leaves a file good to within a few seconds.
    const int MaxRun = 90;

    static readonly List<Frame> _play = new();
    static StreamWriter _rec;
    static string _recPath;
    static bool _loop, _exitAtEnd;
    static long _playAt;

    // Anchor, as in SPIDEY_SCRIPT: the archive whose load releases the replay, and how
    // many frames after it. Boot takes a different number of frames every run -- the
    // game paces off the wall clock -- so a replay that starts counting at frame zero
    // arrives somewhere different each time, which is no use for revisiting a fault.
    static string _anchorName;
    static long _anchorOffset;
    static long _startAt = -1;
    static bool _anchorFromEnv;

    // The most recent archive load, which is what a new recording anchors itself to.
    static string _lastWad;
    static long _lastWadFrame;

    static Frame _pending;
    static int _pendingRun;
    static long _recFrames;
    static bool _stamped;

    public static void Install()
    {
        var recPath = Environment.GetEnvironmentVariable("SPIDEY_REC");
        var playPath = Environment.GetEnvironmentVariable("SPIDEY_PLAY");
        _loop = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("SPIDEY_PLAY_LOOP"));
        var at = Environment.GetEnvironmentVariable("SPIDEY_PLAY_AT");
        _anchorFromEnv = !string.IsNullOrWhiteSpace(at);
        ParseAnchor(at);
        _exitAtEnd = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("SPIDEY_PLAY_EXIT"));

        if (!string.IsNullOrWhiteSpace(playPath)) LoadPlayback(playPath);
        if (!string.IsNullOrWhiteSpace(recPath)) StartRecording(recPath);
        if (_rec == null && _play.Count == 0) return;

        Event.AddListener<VSyncEvent>(OnFrame);
        AppDomain.CurrentDomain.ProcessExit += (_, _) => Close();
    }

    static void ParseAnchor(string spec)
    {
        if (string.IsNullOrWhiteSpace(spec)) { _startAt = 0; return; }

        spec = spec.Trim();
        if (long.TryParse(spec, NumberStyles.Integer, CultureInfo.InvariantCulture, out long abs))
        {
            _startAt = abs;
            return;
        }

        int plus = spec.LastIndexOf('+');
        if (plus > 0 && long.TryParse(spec[(plus + 1)..], out long off))
        {
            _anchorName = spec[..plus];
            _anchorOffset = off;
        }
        else _anchorName = spec;
    }

    /// <summary>Called for every archive lookup; releases a replay anchored to it.</summary>
    public static void NoteWadLoad(string name, long frame)
    {
        _lastWad = name;
        _lastWadFrame = frame;
        if (_startAt >= 0 || _anchorName == null) return;
        if (!string.Equals(_anchorName, name, StringComparison.OrdinalIgnoreCase)) return;
        _startAt = frame + _anchorOffset;
        Console.WriteLine($"[replay] '{name}' at frame {frame}: replay starts at frame {_startAt}");
    }

    static void StartRecording(string path)
    {
        // Recording while replaying would capture the replay, which is never what is
        // wanted and quietly overwrites the source when the paths match.
        if (_play.Count > 0)
        {
            Console.WriteLine("[replay] SPIDEY_REC ignored: already replaying");
            return;
        }

        var dir = Path.GetDirectoryName(Path.GetFullPath(path));
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
        _recPath = Path.GetFullPath(path);
        _rec = new StreamWriter(_recPath) { AutoFlush = true };
        _rec.WriteLine(Magic);
        _rec.WriteLine("# frames state lx ly rx ry -- state is active low, FFFF is idle");
        _pendingRun = 0;
        Console.WriteLine($"[replay] recording to {_recPath}");
    }

    static void LoadPlayback(string path)
    {
        var full = Path.GetFullPath(path);
        if (!File.Exists(full))
        {
            Console.WriteLine($"[replay] no such recording: {full}");
            return;
        }

        int bad = 0;
        foreach (var raw in File.ReadLines(full))
        {
            var line = raw.Trim();
            if (line.Length == 0) continue;
            if (line[0] == '#')
            {
                const string tag = "# anchor ";
                if (!_anchorFromEnv && line.StartsWith(tag, StringComparison.OrdinalIgnoreCase))
                {
                    _startAt = -1;
                    ParseAnchor(line[tag.Length..]);
                    Console.WriteLine($"[replay] anchored to {line[tag.Length..].Trim()}");
                }
                continue;
            }

            var f = line.Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            if (f.Length < 6) { bad++; continue; }
            if (!int.TryParse(f[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out int run) ||
                run <= 0 ||
                !ushort.TryParse(f[1], NumberStyles.HexNumber, CultureInfo.InvariantCulture, out ushort st) ||
                !byte.TryParse(f[2], NumberStyles.HexNumber, CultureInfo.InvariantCulture, out byte lx) ||
                !byte.TryParse(f[3], NumberStyles.HexNumber, CultureInfo.InvariantCulture, out byte ly) ||
                !byte.TryParse(f[4], NumberStyles.HexNumber, CultureInfo.InvariantCulture, out byte rx) ||
                !byte.TryParse(f[5], NumberStyles.HexNumber, CultureInfo.InvariantCulture, out byte ry))
            { bad++; continue; }

            var fr = new Frame { State = st, Lx = lx, Ly = ly, Rx = rx, Ry = ry };
            for (int i = 0; i < run; i++) _play.Add(fr);
        }

        if (_play.Count == 0)
        {
            Console.WriteLine($"[replay] {full} held no usable frames");
            return;
        }

        Console.WriteLine($"[replay] playing {_play.Count} frames ({_play.Count / 30.0:F1}s) " +
                          $"from {full}" + (bad > 0 ? $" ({bad} lines skipped)" : ""));
    }

    static void OnFrame(VSyncEvent e)
    {
        if (_rec != null) Record();
        if (_play.Count > 0) Drive(e.Frame);
    }

    static void Record()
    {
        var now = new Frame
        {
            State = Controller.State,
            Lx = Controller.LeftX,
            Ly = Controller.LeftY,
            Rx = Controller.RightX,
            Ry = Controller.RightY,
        };

        // Nothing is written until the pad is first touched; see the class note.
        if (!_stamped)
        {
            if (Idle(now)) return;
            _stamped = true;
            if (_lastWad != null)
            {
                long delta = System.Threading.Interlocked.Read(ref Diag.Frame) - _lastWadFrame;
                _rec.WriteLine($"# anchor {_lastWad}+{(delta < 0 ? 0 : delta)}");
                Console.WriteLine($"[replay] anchored to {_lastWad}+{(delta < 0 ? 0 : delta)}");
            }
        }

        if (_pendingRun > 0 && Same(now, _pending) && _pendingRun < MaxRun)
        {
            _pendingRun++;
            _recFrames++;
            return;
        }

        FlushRun();
        _pending = now;
        _pendingRun = 1;
        _recFrames++;
    }

    // Sticks rest wherever the hardware says they rest, which is rarely dead centre, so
    // "untouched" has to be a neighbourhood rather than an equality.
    const int Slack = 0x18;

    static bool Idle(Frame f) =>
        f.State == 0xFFFF &&
        Math.Abs(f.Lx - 0x80) <= Slack && Math.Abs(f.Ly - 0x80) <= Slack &&
        Math.Abs(f.Rx - 0x80) <= Slack && Math.Abs(f.Ry - 0x80) <= Slack;

    static bool Same(Frame a, Frame b) =>
        a.State == b.State && a.Lx == b.Lx && a.Ly == b.Ly && a.Rx == b.Rx && a.Ry == b.Ry;

    static void FlushRun()
    {
        if (_rec == null || _pendingRun == 0) return;
        _rec.WriteLine($"{_pendingRun} {_pending.State:X4} {_pending.Lx:X2} {_pending.Ly:X2} " +
                       $"{_pending.Rx:X2} {_pending.Ry:X2}");
        _pendingRun = 0;
    }

    static void Drive(long frame)
    {
        // Still waiting on the anchor: leave the host pad alone so the game is playable
        // while the replay is pending.
        if (_startAt < 0 || frame < _startAt)
        {
            Controller.ReplayActive = false;
            return;
        }

        if (_playAt >= _play.Count)
        {
            if (_loop) { _playAt = 0; }
            else
            {
                Controller.ReplayActive = false;
                if (_exitAtEnd)
                {
                    Console.WriteLine("[replay] recording finished");
                    Console.Out.Flush();
                    RecompOne.Runtime.Runtime.Shutdown();
                    Environment.Exit(0);
                }
                return;
            }
        }

        var f = _play[(int)_playAt++];
        Controller.ReplayActive = true;
        Controller.ReplayState = f.State;
        Controller.ReplayLeftX = f.Lx;
        Controller.ReplayLeftY = f.Ly;
        Controller.ReplayRightX = f.Rx;
        Controller.ReplayRightY = f.Ry;
    }

    static void Close()
    {
        if (_rec == null) return;
        FlushRun();
        _rec.Flush();
        _rec.Dispose();
        _rec = null;
        Console.WriteLine($"[replay] wrote {_recFrames} frames ({_recFrames / 30.0:F1}s) to {_recPath}");
    }
}
