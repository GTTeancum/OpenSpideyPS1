using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace RecompOne.Runtime.Sdk;

public static class LibApi
{
    public static void PatchBios(CpuContext c, IMemory m)
    {
       // Log.Sdk("PatchBios()");
    }

    public static void PatchedBiosCall(CpuContext c, IMemory m)
    {
       // Log.Sdk("PatchedBiosCall()");
        c.V0 = 1u;
    }
}
