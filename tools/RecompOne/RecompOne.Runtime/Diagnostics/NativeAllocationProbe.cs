using System.Runtime.InteropServices;

namespace RecompOne.Runtime.Diagnostics;

/// <summary>Opt-in process-local allocation attribution; no shipping DLL dependency.</summary>
internal static unsafe class NativeAllocationProbe
{
    static delegate* unmanaged[Cdecl]<int, void> _phase;
    static delegate* unmanaged[Cdecl]<char*, int> _flush;
    static string? _path;
    static long _nextFlush;

    public static void Initialize()
    {
        var library = Environment.GetEnvironmentVariable("RECOMP_NATIVE_ALLOCATION_PROBE");
        if (string.IsNullOrWhiteSpace(library)) return;
        var directory = Environment.GetEnvironmentVariable("SPIDEY_LOG_DIR");
        if (string.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory))
            throw new InvalidOperationException("Native allocation probe requires an existing SPIDEY_LOG_DIR");
        // The explicit absolute path prevents normal DLL search-path substitution.
        if (!Path.IsPathFullyQualified(library))
            throw new InvalidOperationException("Native allocation probe DLL path must be absolute");
        nint handle = NativeLibrary.Load(library);
        var install = (delegate* unmanaged[Cdecl]<int>)NativeLibrary.GetExport(handle, "InstallProbe");
        int status = install();
        if (status != 0) throw new InvalidOperationException($"Native allocation hook install failed: {status}");
        _phase = (delegate* unmanaged[Cdecl]<int, void>)NativeLibrary.GetExport(handle, "SetProbePhase");
        _flush = (delegate* unmanaged[Cdecl]<char*, int>)NativeLibrary.GetExport(handle, "FlushProbe");
        _path = Path.Combine(directory, "native-allocations.log");
        Console.WriteLine("[native-allocation-probe] installed in this process only");
        // Keep the module resident until process exit: driver worker threads may
        // still enter an allocation callback after the render window closes.
    }

    public static void Phase(int phase) { if (_phase != null) _phase(phase); }

    public static void Flush(bool force = false)
    {
        if (_flush == null || (!force && Environment.TickCount64 < _nextFlush)) return;
        _nextFlush = Environment.TickCount64 + 5000;
        fixed (char* path = _path)
        {
            int count = _flush(path);
            if (count != 0) Console.WriteLine($"[native-allocation-probe] flushed {count} records");
        }
    }
}
