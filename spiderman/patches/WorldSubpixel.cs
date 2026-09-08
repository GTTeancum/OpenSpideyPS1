#nullable enable
using System;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Hardware;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>Carry fractional projection through SM1's explicit subdivision edge offsets.</summary>
public static class WorldSubpixel
{
    readonly record struct Saved(uint Address, uint Word, GteScreen.VertexTag Tag);
    static readonly Saved[] _saved = new Saved[64];
    static int _count;
    public static long PreservedEdges;
    public static long CertifiedClamps;
    static readonly GteScreen.VertexTag[] _corners = new GteScreen.VertexTag[3];
    static bool _haveCorners;

    // The native routine builds a temporary GTE matrix from three rounded camera
    // vertices. Keep the original projections so its subdivision points remain on
    // the same projective edges as an adjacent, unsubdivided face.
    public static void SetSubdivisionCorners(CpuContext c, IMemory m)
    {
        _haveCorners = false;
        if (m is not PSMemory ps) return;
        uint[] addresses = { c.T1, c.T2, c.T3 };
        for (int i = 0; i < 3; i++)
            if (!ps.TryGetGteVertex(addresses[i], m.ReadU32(addresses[i]), out _corners[i]) ||
                !_corners[i].HasSubpixel || _corners[i].Depth <= 0) return;
        _haveCorners = true;
    }

    static readonly System.Collections.Generic.Stack<Func<uint, uint, GteScreen.VertexTag, GteScreen.VertexTag>?> _clampScopes = new();

    public static void SubdivisionEnter(CpuContext c, IMemory m)
    {
        _clampScopes.Push(GteScreen.RamVertexTransform);
        GteScreen.RamVertexTransform = CertifyClamp;
    }

    public static void SubdivisionExit(CpuContext c, IMemory m)
    {
        GteScreen.RamVertexTransform = _clampScopes.Pop();
        _haveCorners = false;
    }

    static GteScreen.VertexTag CertifyClamp(uint address, uint word, GteScreen.VertexTag tag)
    {
        // func_8007D33C writes its 16-byte subdivision grid in scratch RAM.
        // It caps native X to [-510,1022] and Y to510 after RTPS. Certify that
        // exact transformation, retaining the original projection for GPU clipping.
        if (address < 0x1F800000u || address >= 0x1F800400u || (address & 15u) != 0 ||
            !tag.HasSubpixel) return tag;
        int nativeX = tag.NativeScreen == 0 ? (int)MathF.Floor(tag.ScreenX) : Coord(tag.NativeScreen, 0);
        int nativeY = tag.NativeScreen == 0 ? (int)MathF.Floor(tag.ScreenY) : Coord(tag.NativeScreen, 16);
        int x = Math.Clamp(nativeX, -510, 1022);
        int y = Math.Clamp(nativeY, -1024, 510);
        uint expected = (ushort)(short)x | (uint)(ushort)(short)y << 16;
        if ((word & 0x07FF07FFu) != (expected & 0x07FF07FFu)) return tag;
        if (_haveCorners)
        {
            uint xy = RecompOne.Runtime.Gte.Read(0);
            int a = (short)xy, b = (short)(xy >> 16), d = (short)RecompOne.Runtime.Gte.Read(1);
            if (a >= 0 && b >= 0 && d >= 0 && a + b + d == 4096)
            {
                double za = a * (double)_corners[0].Depth, zb = b * (double)_corners[1].Depth, zd = d * (double)_corners[2].Depth;
                double z = za + zb + zd;
                tag = new GteScreen.VertexTag((float)(z / 4096),
                    (float)((za * _corners[0].ScreenX + zb * _corners[1].ScreenX + zd * _corners[2].ScreenX) / z),
                    (float)((za * _corners[0].ScreenY + zb * _corners[1].ScreenY + zd * _corners[2].ScreenY) / z), true);
                return tag with { NativeScreen = 0x80000000u | (word & 0x07FF07FFu) };
            }
        }
        if (tag.ScreenX >= -510 && tag.ScreenX < 1023 && tag.ScreenY < 511) return tag;
        CertifiedClamps++;
        return tag with { NativeScreen = 0x80000000u | (word & 0x07FF07FFu) };
    }

    public static void EdgeEnter(CpuContext c, IMemory m)
    {
        _count = 0;
        if (m is not PSMemory ps) return;
        // func_8007D534 advances A0 by T6, then offsets max(A2-1, 1) points.
        int count = Math.Max(unchecked((int)c.A2) - 1, 1);
        if (count > _saved.Length) return;
        uint address = c.A0;
        for (int i = 0; i < count; i++)
        {
            address = unchecked(address + c.T6);
            uint word = m.ReadU32(address);
            if (!ps.TryGetGteVertex(address, word, out var tag) || !tag.HasSubpixel) continue;
            if (!GteScreen.ValidatePacketVertex(word, tag).HasSubpixel) continue;
            _saved[_count++] = new Saved(address, word, tag);
        }
    }

    static int Coord(uint word, int shift) => (int)(word << (21 - shift)) >> 21;

    public static void EdgeExit(CpuContext c, IMemory m)
    {
        if (m is not PSMemory ps) return;
        for (int i = 0; i < _count; i++)
        {
            var saved = _saved[i];
            uint word = m.ReadU32(saved.Address);
            int dx = Coord(word, 0) - Coord(saved.Word, 0);
            int dy = Coord(word, 16) - Coord(saved.Word, 16);
            // Packed 32-bit addition can carry/borrow across the X halfword.
            // Crossing X=0/-1 therefore changes Y by zero or two, even though
            // the nominal edge offset is +/-1. Verify the actual native write.
            bool crossedHalfword = (Coord(saved.Word, 0) == 0 && dx == -1) ||
                (Coord(saved.Word, 0) == -1 && dx == 1);
            if (Math.Abs(dx) > 1 || Math.Abs(dy) > (crossedHalfword ? 2 : 1)) continue;
            ps.TagGteVertex(saved.Address, word, saved.Tag with
            {
                // These offsets cover integer-raster cracks. Applying them to
                // precise geometry changes the surface/UV mapping and separates
                // shared projected edges. Keep the original host projection.
                NativeScreen = 0x80000000u | (word & 0x07FF07FFu),
            });
            PreservedEdges++;
        }
        _count = 0;
    }
}
