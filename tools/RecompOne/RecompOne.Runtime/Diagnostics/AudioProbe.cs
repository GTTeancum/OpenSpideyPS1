using System;

namespace RecompOne.Runtime.Diagnostics;

/// <summary>
/// Measures what actually comes out of the mixer.
///
/// Audio is the one subsystem you cannot check by looking at a screenshot, and "the
/// SPU registers are being written" says nothing about whether a sound was produced.
/// Peak and RMS of the mixed buffer, the number of voices in a non-off ADSR phase, and
/// whether the XA ring delivered anything, together distinguish silence from output
/// and voice output from streamed output.
/// </summary>
public static class AudioProbe
{
    static long _samples;
    static double _sumSq;
    static int _peak;
    static long _xaSamples;
    static int _voicePeak;

    public static void Note(short[] buf, int frames, long xaSamples, int activeVoices)
    {
        for (int i = 0; i < frames * 2; i++)
        {
            int v = buf[i];
            if (v < 0) v = -v;
            if (v > _peak) _peak = v;
            _sumSq += (double)buf[i] * buf[i];
        }
        _samples += frames * 2;
        _xaSamples += xaSamples;
        if (activeVoices > _voicePeak) _voicePeak = activeVoices;
    }

    public static string Summary()
    {
        if (_samples == 0) return "audio: mixer never ran";
        double rms = Math.Sqrt(_sumSq / _samples);
        string s = $"audio: peak {_peak} ({_peak * 100.0 / 32767:F1}%), rms {rms:F0}, " +
                   $"voices<={_voicePeak}, xa {_xaSamples} samples";
        _samples = 0; _sumSq = 0; _peak = 0; _xaSamples = 0; _voicePeak = 0;
        return s;
    }
}
