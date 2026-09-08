using System.Text.Json;
using RecompOne.Runtime.Events;

namespace RecompOne.Runtime.Hle;

/// <summary>Opt-in submitted geometry evidence for native frame captures.</summary>
public static class GeometryTrace
{
    static readonly string? Path = Environment.GetEnvironmentVariable("RECOMP_GEOMETRY_DUMP");
    static readonly long Start = long.TryParse(Environment.GetEnvironmentVariable("RECOMP_GEOMETRY_START"), out var start) ? start : 0;
    static readonly long End = long.TryParse(Environment.GetEnvironmentVariable("RECOMP_GEOMETRY_END"), out var end) ? end : Start;
    static long _frame;
    static StreamWriter? _writer;

    static GeometryTrace()
    {
        if (string.IsNullOrWhiteSpace(Path)) return;
        Event.AddListener<VSyncEvent>(e =>
        {
            _frame = e.Frame;
            if (_frame > End) { _writer?.Dispose(); _writer = null; }
        });
    }

    public static void Triangle(HleVertex a, HleVertex b, HleVertex c, HleDrawEnv env, PrimFlags flags)
    {
        if (string.IsNullOrWhiteSpace(Path) || _frame < Start || _frame > End) return;
        _writer ??= new StreamWriter(Path) { AutoFlush = true };
        object Vertex(HleVertex v) => new { v.X, v.Y, v.Z, v.U, v.V, v.HasGteZ };
        _writer.WriteLine(JsonSerializer.Serialize(new
        {
            frame = _frame, vertices = new[] { Vertex(a), Vertex(b), Vertex(c) },
            env.ClipX0, env.ClipY0, env.ClipX1, env.ClipY1,
            flags.World, flags.Textured, flags.TPage, flags.Clut, flags.SemiTrans,
        }));
    }
}
