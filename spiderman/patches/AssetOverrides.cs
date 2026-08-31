using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Game-side hook target for the shared loose-WAD loader. Kept as a named patch so
/// generated SM1 configs remain self-describing.
/// </summary>
public static class AssetOverrides
{
    public static void Find(string name, IMemory memory) =>
        RecompOne.Runtime.Assets.LooseWadOverrides.Find(
            name,
            Costume.DreamcastModelFor(name, memory));
    public static void FindExit(CpuContext c) => RecompOne.Runtime.Assets.LooseWadOverrides.FindExit(c);
    public static bool CdWadRead(CpuContext c, IMemory m) =>
        RecompOne.Runtime.Assets.LooseWadOverrides.Read(c, m);
}
