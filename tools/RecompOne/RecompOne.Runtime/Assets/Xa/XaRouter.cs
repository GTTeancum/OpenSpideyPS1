namespace RecompOne.Runtime.Assets.Xa;

public static class XaRouter
{
    const int MaxGap = 512;
    const int NewRunLbaSlack = 64;
    const int ResumeWindowMs = 2000;

    static readonly object _gate = new();
    static readonly int[] _frames = new int[4032];

    static XaEntry? _entry;
    static ReplacementStream? _stream;
    static byte _file, _channel;
    static int _lastLba = int.MinValue;
    static int _startLba;
    static int _accepted;
    static int _outRate = 37800;
    static bool _outStereo = true;
    static bool _exhausted;
    static long _tailDeadline;
    static long _lastSectorTick;

    public static bool Active
    {
        get { lock (_gate) return _stream != null; }
    }

    public static string? ActiveName
    {
        get { lock (_gate) return _stream?.Name; }
    }

    public static string? ActiveEntry
    {
        get { lock (_gate) return _entry?.ToString(); }
    }

    public static void Reset()
    {
        lock (_gate)
        {
            _stream?.Dispose();
            _stream = null;
            _entry = null;
            _lastLba = int.MinValue;
            _accepted = 0;
            _exhausted = false;
            _tailDeadline = 0;
        }
    }

    public static void Sector(int lba, byte[] sec, bool fromStr)
    {
        byte file = sec[0];
        byte channel = sec[1];
        byte coding = sec[3];

        lock (_gate)
        {
            bool newRun = _lastLba == int.MinValue || file != _file || channel != _channel ||
                          lba < _lastLba || lba > _lastLba + MaxGap;

            if (newRun) BeginRun(lba, file, channel, sec, fromStr);

            _lastLba = lba;
            _lastSectorTick = Environment.TickCount64;
            _accepted++;

            if (_entry != null && _accepted > 8 && lba > _startLba)
                _entry.Interleave = (lba - _startLba) / (double)(_accepted - 1);

            bool stereo = (coding & 0x01) != 0;
            int rate = (coding & 0x04) != 0 ? 18900 : 37800;
            int want = stereo ? 2016 : 4032;
            _outRate = rate;
            _outStereo = stereo;

            if (_stream == null || _exhausted)
            {
                XaAudio.DecodeSector(sec, 8, coding);
                AssetReplacerManager.Instance.Stats.XaPassthrough++;
                return;
            }

            int got = _stream.ReadPacked(_frames, want, rate);
            if (got < want)
            {
                switch (_stream.Options.OnShorter)
                {
                    case ShortPolicy.Loop:
                        _stream.SeekSeconds(_stream.Options.LoopStart);
                        got += _stream.ReadPacked(_frames, got, want - got, rate);
                        if (got < want) Array.Clear(_frames, got, want - got);
                        break;
                    case ShortPolicy.EndStream:
                        Array.Clear(_frames, got, want - got);
                        _exhausted = true;
                        break;
                    default:
                        Array.Clear(_frames, got, want - got);
                        break;
                }
            }

            XaAudio.PushFrames(_frames, want, rate);
            AssetReplacerManager.Instance.Stats.XaReplaced++;

            if (_stream.Options.TailMs > 0)
                _tailDeadline = Environment.TickCount64 + _stream.Options.TailMs;
        }
    }

    static void BeginRun(int lba, byte file, byte channel, byte[] sec, bool fromStr)
    {
        var mgr = AssetReplacerManager.Instance;
        mgr.Stats.XaRuns++;

        var entry = mgr.ResolveXa(file, channel, lba);
        if (entry == null)
        {
            ulong probe = AssetHash.XaPayload(sec.AsSpan(8, Math.Min(2304, Math.Max(0, sec.Length - 8))));
            entry = mgr.ResolveXaByPayload(probe);
        }

        if (_stream != null && !_exhausted && ReferenceEquals(entry, _entry) && !_stream.Ended &&
            Environment.TickCount64 - _lastSectorTick <= ResumeWindowMs)
        {
            _accepted = 0;
            _startLba = lba;
            _file = file;
            _channel = channel;
            return;
        }

        _stream?.Dispose();
        _stream = null;
        _entry = null;
        _exhausted = false;
        _accepted = 0;
        _startLba = lba;
        _file = file;
        _channel = channel;

        if (entry == null) return;

        if (fromStr && !entry.Options.AllowStr)
        {
            Log.Sdk($"[assets] xa: '{entry.AudioName}' skip in STR context (allowStr is false)");
            return;
        }

        var stream = mgr.OpenStream(entry);
        if (stream == null) return;

        double seek = 0;
        int delta = lba - entry.StartLba;
        if (delta > NewRunLbaSlack)
        {
            double framesPerSector = 2016;
            double interleave = entry.Interleave <= 0 ? 1 : entry.Interleave;
            seek = delta / interleave * framesPerSector / 37800.0;
        }
        if (seek > 0) stream.SeekSeconds(seek);

        _entry = entry;
        _stream = stream;
        entry.TimesPlayed++;

        //Console.WriteLine($"[assets] xa: f{file} c{channel} lba={lba} -> '{entry.AudioName}' ({entry.PackId})" +(seek > 0 ? $" seek={seek:0.00}s" : ""));
    }

    public static bool WantsCarrier(out int rewindLba)
    {
        rewindLba = 0;
        lock (_gate)
        {
            if (_stream == null || _exhausted) return false;
            if (!_stream.Options.Extend) return false;
            if (_stream.Ended) return false;
            if (_stream.PositionSeconds * 1000 > _stream.Options.ExtendMaxMs) return false;
            rewindLba = _startLba;
            return true;
        }
    }

    public static bool PumpTail()
    {
        lock (_gate)
        {
            if (_stream == null || _exhausted) return false;
            if (_tailDeadline == 0 || Environment.TickCount64 > _tailDeadline) return false;
            if (XaAudio.BufferedSamples > 4096) return true;

            int want = _outStereo ? 2016 : 4032;
            int got = _stream.ReadPacked(_frames, want, _outRate);
            if (got <= 0)
            {
                _tailDeadline = 0;
                return false;
            }
            if (got < want) Array.Clear(_frames, got, want - got);
            XaAudio.PushFrames(_frames, want, _outRate);
            return true;
        }
    }
}
