using System.Runtime.InteropServices;

namespace RecompOne.Runtime.Host;

/// <summary>Resolve native dependencies from our payload even on machines with an older CRT installed.</summary>
public static class BundledNativeRuntime
{
    static readonly List<nint> Handles = [];
    public static void Initialize()
    {
        if (!OperatingSystem.IsWindows()) return;
        lock (Handles)
        {
            if (Handles.Count != 0) return;
            foreach (string name in new[] { "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll" })
                Handles.Add(NativeLibrary.Load(Path.Combine(AppContext.BaseDirectory, name)));
        }
    }
}
