using RecompOne.Runtime.Context;
using RecompOne.Runtime.Host.Window;
using RecompOne.Runtime.Memory;

namespace Recompiled;

public static class VideoSetup
{
    static readonly NativeVideoSetup.Bindings Menu=new(0x80243854,0x800A382C,0x800B29C8,
        0x80243AE8,0x8006E814,0x6C,0x78,0x300,0x1D4,0x80018380);
    public static void Options(CpuContext c,IMemory m)=>NativeVideoSetup.RenameScreen(m,Menu);
    public static void Run(CpuContext c,IMemory m)=>NativeVideoSetup.Run(c,m,Menu);
}
