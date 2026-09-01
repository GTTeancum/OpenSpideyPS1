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

    // Four submitted-frame generations. These games build ordering tables ahead of the
    // buffer they display, and SM2 can service multiple vblanks before it swaps that
    // buffer. Rolling at every vblank discarded all projection points before their
    // primitives reached the GPU. Wide rolls this ring on actual PutDispEnv swaps; four
    // generations cover both double buffering and an ahead-built table without turning
    // this into an unbounded history. Every vertex must still match.
    const int Generations = 4;
    static readonly HashSet<int>[] _sets =
        [new(8192), new(8192), new(8192), new(8192)];
    static int _cur;

    static int Key(int x, int y) => ((x & 0xFFFF) << 16) | (y & 0xFFFF);

    public static void Note(int x, int y)
    {
        if (Tracking) _sets[_cur].Add(Key(x, y));
    }

    public static bool Has(int x, int y)
    {
        int k = Key(x, y);
        for (int i = 0; i < Generations; i++)
            if (_sets[i].Contains(k)) return true;
        return false;
    }

    public static int Count
    {
        get
        {
            int count = 0;
            for (int i = 0; i < Generations; i++) count += _sets[i].Count;
            return count;
        }
    }

    /// <summary>A few of the recorded points, for checking the coordinate convention.</summary>
    public static string Sample(int n = 6)
    {
        var sb = new System.Text.StringBuilder();
        int i = 0;
        foreach (int k in _sets[_cur])
        {
            if (i++ >= n) break;
            sb.Append($"({(short)(k >> 16)},{(short)k}) ");
        }
        return sb.ToString();
    }

    /// <summary>
    /// Called once per actual display-buffer swap.
    /// </summary>
    public static void Roll()
    {
        _cur = (_cur + 1) % Generations;
        _sets[_cur].Clear();
    }
}
