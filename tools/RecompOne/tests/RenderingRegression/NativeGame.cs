using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

// Run the same geometry invariants through each game's real recompiled routines.
static class NativeGame
{
#if SM2
    public const uint ModelTable = 0x800BCEE8, Camera = 0x800C2A74;
    public static readonly Action<CpuContext, IMemory> EdgeNative = Recompiled.SpiderMan2.func_80089B74_Impl;
    public static readonly Action<CpuContext, IMemory> Edge = Recompiled.SpiderMan2.func_80089B74;
    public static readonly Action<CpuContext, IMemory> SubdivisionNative = Recompiled.SpiderMan2.func_8008997C_Impl;
    public static readonly Action<CpuContext, IMemory> Subdivision = Recompiled.SpiderMan2.func_8008997C;
    public static readonly Action<CpuContext, IMemory> CornersNative = Recompiled.SpiderMan2.func_80089918_Impl;
    public static readonly Action<CpuContext, IMemory> Corners = Recompiled.SpiderMan2.func_80089918;
    public static readonly Action<CpuContext, IMemory> Frustum = Recompiled.SpiderMan2.func_800877F4;
#else
    public const uint ModelTable = 0x800A0914, Camera = 0x800B591C;
    public static readonly Action<CpuContext, IMemory> EdgeNative = Recompiled.SpiderMan.func_8007D534_Impl;
    public static readonly Action<CpuContext, IMemory> Edge = Recompiled.SpiderMan.func_8007D534;
    public static readonly Action<CpuContext, IMemory> SubdivisionNative = Recompiled.SpiderMan.func_8007D33C_Impl;
    public static readonly Action<CpuContext, IMemory> Subdivision = Recompiled.SpiderMan.func_8007D33C;
    public static readonly Action<CpuContext, IMemory> CornersNative = Recompiled.SpiderMan.func_8007D2D8_Impl;
    public static readonly Action<CpuContext, IMemory> Corners = Recompiled.SpiderMan.func_8007D2D8;
    public static readonly Action<CpuContext, IMemory> Frustum = Recompiled.SpiderMan.func_8007B1B4;
#endif
}
