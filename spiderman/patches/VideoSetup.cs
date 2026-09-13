using RecompOne.Runtime.Context;
using RecompOne.Runtime.Host.Window;
using RecompOne.Runtime.Memory;

namespace Recompiled;

public static class VideoSetup
{
    static readonly NativeVideoSetup.Bindings Menu=new(0x8025AA84,0x80097760,0x800A4DF4,
        0x8025AD18,0x80063770,0x68,0x74,0x430,0x1CC,0x80016B30);
    public static void Options(CpuContext c,IMemory m)=>NativeVideoSetup.RenameScreen(m,Menu);
    public static void Run(CpuContext c,IMemory m)=>NativeVideoSetup.Run(c,m,Menu);
}
