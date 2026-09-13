namespace RecompOne.Runtime.Cdrom;

/// <summary>Single data-track BIN/ISO. Detect layout from the ISO9660 volume descriptor.</summary>
public sealed class SectorImage : IDiscImage
{
    readonly FileStream _stream;
    readonly int _sectorSize, _dataOffset;
    readonly object _gate = new();

    SectorImage(FileStream stream, int sectorSize, int dataOffset)
        => (_stream, _sectorSize, _dataOffset) = (stream, sectorSize, dataOffset);

    public static SectorImage Open(string path)
    {
        var stream = File.OpenRead(path);
        try
        {
            foreach (var (size, offset) in new[] { (2352, 24), (2352, 16), (2336, 8), (2048, 0) })
            {
                long position = 16L * size + offset;
                if (stream.Length < position + 7 || stream.Length % size != 0) continue;
                stream.Position = position;
                Span<byte> header = stackalloc byte[7];
                stream.ReadExactly(header);
                if (header.SequenceEqual(new byte[] { 1, 67, 68, 48, 48, 49, 1 }))
                    return new SectorImage(stream, size, offset);
            }
            throw new InvalidDataException("No readable ISO9660 data track was found in this BIN/ISO");
        }
        catch { stream.Dispose(); throw; }
    }

    public string Format => $"BIN/ISO ({_sectorSize}-byte sectors)";
    public int FirstTrack => 1;
    public int LastTrack => 1;
    public bool HasTracks => true;
    public int LeadoutLba => checked((int)(_stream.Length / _sectorSize));
    public int DataSectors => LeadoutLba;
    public IReadOnlyList<DiscTrack> Tracks => [new(1, DiscTrackKind.Data, 0, _sectorSize)];
    public bool TrackStartLba(int track, out int lba) { lba = 0; return track == 1; }

    public byte[] ReadSectorData(int lba, int size)
    {
        var result = new byte[size];
        if (lba < 0 || lba >= DataSectors) return result;
        int offset = _dataOffset, destination = 0;
        if (size > 2048)
        {
            if (_sectorSize == 2352) offset = size >= 2340 ? 12 : 16;
            else if (_sectorSize == 2336) offset = 0;
            else destination = size >= 2340 ? 12 : 8;
        }
        int count = Math.Min(size - destination, _sectorSize - offset);
        lock (_gate)
        {
            _stream.Position = (long)lba * _sectorSize + offset;
            _stream.ReadExactly(result.AsSpan(destination, count));
        }
        return result;
    }

    public void Dispose() => _stream.Dispose();
}
