using System.Buffers.Binary;
using System.IO.Compression;

namespace RecompOne.Runtime.Assets;

//got some parts from stack overflow
public static class PngWriter
{
    static readonly byte[] Signature = [0x89, (byte)'P', (byte)'N', (byte)'G', 0x0D, 0x0A, 0x1A, 0x0A];

    public static void WriteRgba(string path, ReadOnlySpan<byte> rgba, int width, int height) => Write(path, rgba, width, height, 4, 6);

    public static void WriteGray(string path, ReadOnlySpan<byte> gray, int width, int height) => Write(path, gray, width, height, 1, 0);

    static void Write(string path, ReadOnlySpan<byte> pixels, int width, int height, int channels, byte colorType)
    {
        if (width <= 0 || height <= 0) return;

        var raw = new byte[(width * channels + 1) * height];
        for (int y = 0; y < height; y++)
        {
            int src = y * width * channels;
            int dst = y * (width * channels + 1);
            raw[dst] = 0;
            pixels.Slice(src, width * channels).CopyTo(raw.AsSpan(dst + 1));
        }

        byte[] compressed;
        using (var ms = new MemoryStream())
        {
            using (var z = new ZLibStream(ms, CompressionLevel.Optimal, true))
                z.Write(raw, 0, raw.Length);
            compressed = ms.ToArray();
        }

        var dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

        using var file = File.Create(path);
        file.Write(Signature);

        var ihdr = new byte[13];
        BinaryPrimitives.WriteInt32BigEndian(ihdr.AsSpan(0), width);
        BinaryPrimitives.WriteInt32BigEndian(ihdr.AsSpan(4), height);
        ihdr[8] = 8;
        ihdr[9] = colorType;
        
        
        Chunk(file, "IHDR", ihdr);
        Chunk(file, "IDAT", compressed);
        Chunk(file, "IEND", []);
    }

    
    static void Chunk(Stream s, string type, ReadOnlySpan<byte> data)
    {
        Span<byte> len = stackalloc byte[4];
        BinaryPrimitives.WriteInt32BigEndian(len, data.Length);
        s.Write(len);

        Span<byte> tag = stackalloc byte[4];
        for (int i = 0; i < 4; i++) tag[i] = (byte)type[i];
        s.Write(tag);
        s.Write(data);

        uint crc = Crc32(tag, data);
        Span<byte> c = stackalloc byte[4];
        BinaryPrimitives.WriteUInt32BigEndian(c, crc);
        s.Write(c);
    }

    static readonly uint[] CrcTable = BuildCrcTable();

    static uint[] BuildCrcTable()
    {
        var table = new uint[256];
        for (uint n = 0; n < 256; n++)
        {
            uint c = n;
            for (int k = 0; k < 8; k++)
                c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            table[n] = c;
        }
        return table;
    }

    static uint Crc32(ReadOnlySpan<byte> a, ReadOnlySpan<byte> b)
    {
        uint c = 0xFFFFFFFFu;
        foreach (byte x in a) c = CrcTable[(c ^ x) & 0xFF] ^ (c >> 8);
        foreach (byte x in b) c = CrcTable[(c ^ x) & 0xFF] ^ (c >> 8);
        return c ^ 0xFFFFFFFFu;
    }
}
