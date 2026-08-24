using NVorbis;

namespace RecompOne.Runtime.Assets.Decoders;

public sealed class VorbisDecoder : IPcmDecoder
{
    readonly VorbisReader _r;
    float[] _scratch = [];

    public int SampleRate { get; }
    public int Channels { get; }
    public long TotalFrames { get; }

    public VorbisDecoder(Stream s)
    {
        _r = new VorbisReader(s, true);
        SampleRate = _r.SampleRate;
        Channels = _r.Channels;
        TotalFrames = _r.TotalSamples;
    }

    public int ReadFrames(short[] dst, int frames)
    {
        int need = frames * Channels;
        if (_scratch.Length < need) _scratch = new float[need];

        int got = _r.ReadSamples(_scratch, 0, need);
        for (int i = 0; i < got; i++)
        {
            int v = (int)(_scratch[i] * 32767f);
            dst[i] = (short)(v < -32768 ? -32768 : v > 32767 ? 32767 : v);
        }
        return got / Channels;
    }

    public void SeekFrames(long frame)
    {
        if (frame < 0) frame = 0;
        if (frame > TotalFrames) frame = TotalFrames;
        try { _r.SeekTo(frame); }
        catch (ArgumentOutOfRangeException) { }
    }

    public void Dispose() => _r.Dispose();
}
