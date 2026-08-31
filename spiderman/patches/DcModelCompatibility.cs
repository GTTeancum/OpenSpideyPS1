using System;
using System.Collections.Generic;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Runtime compatibility fixes for higher-detail Dreamcast character meshes.
/// </summary>
public static class DcModelCompatibility
{
    const uint ModelTable = 0x800A0904u;
    const uint ActiveModelSlot = 0x800B53CDu;
    const int RetailHeadVertexCount = 38;
    const int HeadMeshIndex = 7;
    const int BagmanHeadFaceCount = 179;
    const int BagmanInnerFaceCount = 86;
    const ushort BagmanInnerDepthMarker = 0x6000;
    const uint BagmanDepthAddress = 0x1F800344u;
    const short DefaultBagmanDepthBias = 128;

    static readonly bool Trace =
        !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("RECOMP_TRACE_MODEL_STITCHES"));
    static readonly short BagmanDepthBias = ReadBagmanDepthBias();
    static readonly HashSet<uint> _reportedHeads = [];
    static bool _bagmanDepthActive;
    static ushort _savedBagmanDepth;

    static short ReadBagmanDepthBias()
    {
        string? configured = Environment.GetEnvironmentVariable("RECOMP_BAGMAN_DEPTH_BIAS");
        if (string.IsNullOrWhiteSpace(configured))
            return DefaultBagmanDepthBias;
        if (!short.TryParse(configured, out short value) || value <= 0)
            throw new InvalidOperationException(
                "RECOMP_BAGMAN_DEPTH_BIAS must be a positive signed 16-bit integer");
        return value;
    }

    /// <summary>
    /// SM1's menu expression routine writes two hard-coded 38-vertex PS1 head
    /// targets directly into mesh 7.  Dreamcast heads have different topology and
    /// vertex counts, so the loop walks beyond both target tables and turns code/data
    /// bytes into head coordinates.  The game already keeps an exact backup of the
    /// active head for this effect; restore that geometry for non-retail topology.
    /// </summary>
    public static void RestoreHeadAfterPs1Morph(CpuContext c, IMemory m)
    {
        uint slot = m.ReadU8(ActiveModelSlot);
        uint modelEntry = ModelTable + (slot << 6);
        uint pointerTable = m.ReadU32(modelEntry + 0x10u);
        if (pointerTable < 4u || m.ReadU32(pointerTable - 4u) <= HeadMeshIndex)
            return;

        uint head = m.ReadU32(pointerTable + HeadMeshIndex * 4u);
        int vertexCount = m.ReadU16(head + 2u);
        if (vertexCount == RetailHeadVertexCount)
            return;

        uint backup = m.ReadU32(c.GP + 0xAB4u);
        if (backup == 0u)
            return;

        uint vertices = head + 0x1Cu;
        for (uint index = 0; index < vertexCount; index++)
        {
            uint source = backup + index * 8u;
            uint target = vertices + index * 8u;
            m.WriteU16(target, m.ReadU16(source));
            m.WriteU16(target + 2u, m.ReadU16(source + 2u));
            m.WriteU16(target + 4u, m.ReadU16(source + 4u));
        }

        if (Trace && _reportedHeads.Add(head))
        {
            Console.WriteLine(
                $"[dc-model] bypassed retail {RetailHeadVertexCount}-vertex head morph " +
                $"for mesh with {vertexCount} vertices at 0x{head:X8}");
        }
    }

    /// <summary>
    /// Translate Bag-Man's Dreamcast nested-shell depth relationship into SM1's
    /// native per-face ordering-table offset. The converter marks all 86 original
    /// inner head/neck faces with 0x6000; this hook recognizes the complete,
    /// topology-checked 179-face batch before supplying the selected offset.
    /// </summary>
    public static void ApplyBagmanNestedShellDepth(CpuContext c, IMemory m)
    {
        _bagmanDepthActive = false;
        if (c.A2 != BagmanHeadFaceCount)
            return;

        uint face = c.A0;
        int inner = 0;
        int outer = 0;
        for (int index = 0; index < BagmanHeadFaceCount; index++)
        {
            ushort flags = m.ReadU16(face);
            ushort length = m.ReadU16(face + 2u);
            if (length < 20 || length > 64)
                return;

            if ((flags & BagmanInnerDepthMarker) == BagmanInnerDepthMarker)
                inner++;
            else
                outer++;
            face += length;
        }
        if (inner != BagmanInnerFaceCount || outer != BagmanHeadFaceCount - BagmanInnerFaceCount)
            return;

        _savedBagmanDepth = m.ReadU16(BagmanDepthAddress);
        m.WriteU16(BagmanDepthAddress, unchecked((ushort)BagmanDepthBias));
        _bagmanDepthActive = true;
        if (Trace)
            Console.WriteLine(
                $"[dc-model] Bag-Man nested shell: inner={inner} outer={outer} " +
                $"ot-bias={BagmanDepthBias}");
    }

    public static void RestoreBagmanNestedShellDepth(CpuContext c, IMemory m)
    {
        if (!_bagmanDepthActive)
            return;
        m.WriteU16(BagmanDepthAddress, _savedBagmanDepth);
        _bagmanDepthActive = false;
    }
}
