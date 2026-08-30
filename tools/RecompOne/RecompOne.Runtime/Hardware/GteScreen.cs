using System.Collections.Generic;

namespace RecompOne.Runtime.Hardware;

/// <summary>
/// The screen coordinates the GTE produced during the current frame.
///
/// This exists to answer one question exactly: is a primitive part of the world, or part
/// of the HUD? A widescreen hack has to know, because the world is squeezed at the
/// projection and the HUD has to be squeezed to match by hand -- and squeezing the wrong
/// thing drags scenery out of place.
///
/// Every proxy for that question leaks. Shape leaks: a HUD panel projects to an
/// axis-aligned rectangle, and so does a building sign, and so does a strip of ground.
/// Screen position leaks: the HUD lives in the corners, and so does whatever the camera
/// happens to point at. Draw order leaks: it is an ordering table, not a sequence.
///
/// The real difference is upstream of all of them. World geometry reaches the GPU by way
/// of the GTE; the HUD is laid out on the CPU and never goes near it. So the coordinates
/// the GTE emitted are recorded as they are produced, and a primitive whose every vertex
/// is one of them came from the world. That is the distinction itself rather than a
/// symptom of it.
///
/// It relies on the game handing GTE output to the GPU unaltered, which this one does --
/// vertices arrive pinned at exactly 1023, the GTE's own saturation limit, which is only
/// possible if nothing clipped or subdivided them on the way.
/// </summary>
public static class GteScreen
{
    /// <summary>Off unless something is asking, since it costs a hash insert per vertex.</summary>
    public static bool Tracking;

    // Two generations. The game builds one ordering table while walking the other, so
    // the primitives drawn between two vblanks were projected in the window before them
    // -- clearing on a single frame boundary left the set empty at exactly the moment it
    // was consulted, and everything read as HUD. Keeping the previous window as well
    // costs only a wider net, and a HUD vertex has to collide with a projected one on
    // every vertex of a primitive before that matters.
    static HashSet<int> _cur = new(8192);
    static HashSet<int> _prev = new(8192);

    static int Key(int x, int y) => ((x & 0xFFFF) << 16) | (y & 0xFFFF);

    public static void Note(int x, int y)
    {
        if (Tracking) _cur.Add(Key(x, y));
    }

    public static bool Has(int x, int y)
    {
        int k = Key(x, y);
        return _cur.Contains(k) || _prev.Contains(k);
    }

    public static int Count => _cur.Count + _prev.Count;

    /// <summary>A few of the recorded points, for checking the coordinate convention.</summary>
    public static string Sample(int n = 6)
    {
        var sb = new System.Text.StringBuilder();
        int i = 0;
        foreach (int k in _cur)
        {
            if (i++ >= n) break;
            sb.Append($"({(short)(k >> 16)},{(short)k}) ");
        }
        return sb.ToString();
    }

    /// <summary>
    /// Called once a frame: the current window becomes the previous one and a fresh
    /// window starts.
    /// </summary>
    public static void Roll()
    {
        (_cur, _prev) = (_prev, _cur);
        _cur.Clear();
    }
}
