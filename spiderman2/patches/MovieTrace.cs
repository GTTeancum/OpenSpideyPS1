using System;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// What the game's movie player is waiting for.
///
/// `MovieNextFrame` (0x80030D08) is the whole of it. It calls StGetNext, and on a frame
/// it reads the STR header's frame number, stores it at gp+1944, and compares it with a
/// target at gp+1952. Only when the number reaches the target does it set the "movie
/// finished" flag at gp+1912 -- so a movie that stops delivering frames before the
/// target leaves that flag clear and the game waits for an end that cannot arrive. The
/// screen holds the last decoded frame, which looks like a freeze and is really a
/// player still politely waiting.
///
/// This prints the three words on each transition, so "the stream stopped early" and
/// "the game asked for more frames than the movie has" can be told apart. Off unless
/// SPIDEY_TRACE_MOVIE=1.
/// </summary>
public static class MovieTrace
{
    static readonly bool On =
        Environment.GetEnvironmentVariable("SPIDEY_TRACE_MOVIE") == "1";

    const uint OffFlag = 1912, OffCurrent = 1944, OffTarget = 1952;

    static uint _lastCurrent = uint.MaxValue, _lastFlag = uint.MaxValue;
    static long _calls;

    /// <summary>post-hook on MovieNextFrame</summary>
    public static void NextFrameExit(CpuContext c, IMemory m)
    {
        _calls++;
        if (!On) return;

        uint flag = m.ReadU32(c.GP + OffFlag);
        uint cur = m.ReadU32(c.GP + OffCurrent);
        uint tgt = m.ReadU32(c.GP + OffTarget);

        if (cur == _lastCurrent && flag == _lastFlag) return;
        _lastCurrent = cur;
        _lastFlag = flag;

        Console.WriteLine(
            $"[movie] f{System.Threading.Interlocked.Read(ref Diag.Frame)} " +
            $"gp=0x{c.GP:X8} frame={(int)cur} target={(int)tgt} done={flag} " +
            $"polls={_calls} | {RecompOne.Runtime.Sdk.LibCdStream.RingState}");
    }
}
