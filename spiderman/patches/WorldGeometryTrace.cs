#nullable enable
using System;
using System.IO;
using System.Text.Json;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

public static class WorldGeometryTrace
{
    static readonly string? Dump = Environment.GetEnvironmentVariable("RECOMP_GEOMETRY_DUMP");
    static readonly long Start = long.TryParse(Environment.GetEnvironmentVariable("RECOMP_GEOMETRY_START"), out var start) ? start : 0;
    static readonly long End = long.TryParse(Environment.GetEnvironmentVariable("RECOMP_GEOMETRY_END"), out var end) ? end : Start;
    static StreamWriter? _writer;
    public static void Record(CpuContext c, IMemory m)
    {
        if (string.IsNullOrWhiteSpace(Dump) || Diag.Frame < Start || Diag.Frame > End || c.A2 > 4096 || m is not PSMemory ps) return;
        _writer ??= new StreamWriter(Dump + ".sources") { AutoFlush = true };
        uint pointer = c.A0, vertexBase = m.ReadU32(0x800B58F0u);
        for (int i = 0; i < c.A2; i++)
        {
            uint header = m.ReadU32(pointer), indices = m.ReadU32(pointer + 4);
            uint size = header >> 16;
            if (size < 8 || size > 256) break;
            object[] vertices = new object[4];
            for (int j = 0; j < 4; j++)
            {
                uint address = vertexBase + ((indices >> (j * 8)) & 255) * 8;
                uint packed = m.ReadU32(address);
                ps.TryGetGteVertex(address, packed, out var tag);
                vertices[j] = new { address, packed, tag.ScreenX, tag.ScreenY, tag.Depth,
                    flags = m.ReadU32(address + 4), cameraXY = m.ReadU32(address + 0x1F40) };
            }
            uint[] words = new uint[size / 4];
            for (int j = 0; j < words.Length; j++) words[j] = m.ReadU32(pointer + (uint)j * 4);
            _writer.WriteLine(JsonSerializer.Serialize(new { frame = Diag.Frame, caller = c.RA, pointer, header, vertices, words }));
            pointer += size;
        }
    }
    static uint _input, _count;
    public static void TransformEnter(CpuContext c, IMemory m)
    {
        _input=c.A0; _count=c.A1;
    }
    public static void TransformExit(CpuContext c, IMemory m)
    {
        if (string.IsNullOrWhiteSpace(Dump) || Diag.Frame<Start || Diag.Frame>End || _count>256 || m is not PSMemory ps) return;
        // Restrict this detail to the two adjacent rooftop chunks under investigation.
        if (_input is not (0x8013CA9Cu or 0x8013D238u)) return;
        _writer ??= new StreamWriter(Dump+".sources") { AutoFlush=true };
        uint output=m.ReadU32(0x800B58F0u);
        for(uint i=0;i<_count;i++)
        {
            uint address=output+i*8, word=m.ReadU32(address);
            ps.TryGetGteVertex(address,word,out var tag);
            _writer.WriteLine(JsonSerializer.Serialize(new {kind="transform", frame=Diag.Frame, input=_input, index=i,
                sourceXY=m.ReadU32(_input+i*8),sourceZF=m.ReadU32(_input+i*8+4),word,
                tag.ScreenX,tag.ScreenY,tag.Depth, flags=m.ReadU32(address+4)}));
        }
    }
}
