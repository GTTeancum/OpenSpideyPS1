using System;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>Runtime compatibility for topology-changing Dreamcast costumes.</summary>
public static class DcModelCompatibility
{
    const int BagmanHeadFaceCount = 179;
    const int BagmanInnerFaceCount = 86;
    const ushort BagmanInnerDepthMarker = 0x6000;
    const uint BagmanDepthAddress = 0x1F800344u;
    const short BagmanDepthBias = 128;

    static readonly bool Trace =
        !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("RECOMP_TRACE_MODEL_STITCHES"));
    static bool _bagmanDepthActive;
    static bool _bagmanDepthReported;
    static ushort _savedBagmanDepth;

    /// <summary>
    /// Dreamcast resolves Peter's inner head behind the paper shell with a depth
    /// buffer.  The converted v4 actor marks that complete inner shell with SM1/SM2's
    /// native per-face ordering-table offset channel.  Require the exact audited
    /// topology before supplying the bias; every unrelated face batch is untouched.
    /// </summary>
    public static void ApplyBagmanNestedShellDepth(CpuContext c, IMemory m)
    {
        _bagmanDepthActive = false;
        if (c.A2 != BagmanHeadFaceCount) return;

        uint face = c.A0;
        int inner = 0;
        int outer = 0;
        for (int index = 0; index < BagmanHeadFaceCount; index++)
        {
            ushort flags = m.ReadU16(face);
            ushort length = m.ReadU16(face + 2u);
            if (length < 20 || length > 64) return;

            if ((flags & BagmanInnerDepthMarker) == BagmanInnerDepthMarker) inner++;
            else outer++;
            face += length;
        }
        if (inner != BagmanInnerFaceCount || outer != BagmanHeadFaceCount - BagmanInnerFaceCount)
            return;

        _savedBagmanDepth = m.ReadU16(BagmanDepthAddress);
        m.WriteU16(BagmanDepthAddress, unchecked((ushort)BagmanDepthBias));
        _bagmanDepthActive = true;
        if (Trace && !_bagmanDepthReported)
        {
            _bagmanDepthReported = true;
            Console.WriteLine(
                $"[dc-model] Bag-Man nested shell: inner={inner} outer={outer} " +
                $"ot-bias={BagmanDepthBias}");
        }
    }

    public static void RestoreBagmanNestedShellDepth(CpuContext c, IMemory m)
    {
        if (!_bagmanDepthActive) return;
        m.WriteU16(BagmanDepthAddress, _savedBagmanDepth);
        _bagmanDepthActive = false;
    }
}
